from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from .db import Database
from .entity_extract import extract_entities
from .parsers import ParsedDocument, ParsedSegment, detect_source_category, is_supported_file, parse_file


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_candidate_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def _split_large_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    units = [unit.strip() for unit in text.splitlines() if unit.strip()]
    if not units:
        return [text[:limit]]
    parts: list[str] = []
    current = ""
    for unit in units:
        candidate = unit if not current else f"{current}\n{unit}"
        if current and len(candidate) > limit:
            parts.append(current)
            current = unit
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _expand_segments(segments: list[ParsedSegment], max_chars: int) -> list[ParsedSegment]:
    expanded: list[ParsedSegment] = []
    for segment in segments:
        pieces = _split_large_text(segment.text.strip(), max_chars)
        if len(pieces) == 1:
            expanded.append(segment)
            continue
        for piece_index, piece in enumerate(pieces, start=1):
            expanded.append(
                ParsedSegment(
                    label=f"{segment.label} part {piece_index}",
                    text=piece,
                    metadata=dict(segment.metadata),
                )
            )
    return expanded


def _chunk_label(segments: list[ParsedSegment]) -> str:
    if not segments:
        return "chunk"
    if len(segments) == 1:
        return segments[0].label
    return f"{segments[0].label} -> {segments[-1].label}"


def chunk_document(
    document: ParsedDocument,
    *,
    source_path: str,
    relative_path: str,
    file_name: str,
    source_category: str,
    modified_time: float,
    file_hash: str,
    max_chars: int = 5200,
) -> list[dict[str, object]]:
    context_prefix = str(document.metadata.get("context_prefix", "")).strip()
    prefix_length = len(context_prefix) + 2 if context_prefix else 0
    segments = _expand_segments(document.segments, max_chars=max(900, max_chars - prefix_length))
    if not segments:
        return []
    structured_types = {"csv", "xlsx"}
    overlap_segments = 0 if document.source_type in structured_types else 1
    chunk_rows: list[dict[str, object]] = []
    current_segments: list[ParsedSegment] = []
    current_length = 0

    def flush() -> None:
        nonlocal current_segments, current_length
        if not current_segments:
            return
        chunk_index = len(chunk_rows) + 1
        chunk_id = f"chunk-{chunk_index:04d}"
        body = "\n\n".join(segment.text.strip() for segment in current_segments if segment.text.strip()).strip()
        text = f"{context_prefix}\n\n{body}".strip() if context_prefix else body
        detected_entities = extract_entities(text)
        chunk_rows.append(
            {
                "id": str(uuid5(NAMESPACE_URL, f"{source_path}::{chunk_id}")),
                "source_path": source_path,
                "relative_path": relative_path,
                "file_name": file_name,
                "source_category": source_category,
                "source_type": document.source_type,
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "chunk_label": _chunk_label(current_segments),
                "text": text,
                "entities": detected_entities,
                "detected_entities": detected_entities,
                "modified_time": modified_time,
                "indexed_at": utc_now(),
                "file_hash": file_hash,
            }
        )
        retained = current_segments[-overlap_segments:] if overlap_segments else []
        current_segments = [ParsedSegment(label=item.label, text=item.text, metadata=dict(item.metadata)) for item in retained]
        current_length = sum(len(item.text) + 2 for item in current_segments)

    for segment in segments:
        segment_length = len(segment.text) + 2
        if current_segments and current_length + segment_length + prefix_length > max_chars:
            flush()
        current_segments.append(segment)
        current_length += segment_length
    flush()
    return chunk_rows


class Ingestor:
    def __init__(self, settings, db: Database, ollama_client, qdrant_store) -> None:
        self.settings = settings
        self.db = db
        self.ollama_client = ollama_client
        self.qdrant_store = qdrant_store
        self.db.ensure_schema()

    def _parse(self, path: Path) -> ParsedDocument:
        return parse_file(path)

    def _record_unhandled_file(
        self,
        *,
        run_id: str,
        file_path: Path,
        source_path: str,
        relative_path: str,
        file_hash: str,
        modified_time: float,
        source_category: str,
        status: str,
        error_message: str,
    ) -> None:
        self.db.clear_source(source_path)
        try:
            self.qdrant_store.delete_source(source_path)
        except Exception:
            pass
        self.db.upsert_file_record(
            source_path=source_path,
            relative_path=relative_path,
            file_name=file_path.name,
            source_category=source_category,
            source_type=file_path.suffix.lower().lstrip(".") or "unknown",
            file_hash=file_hash,
            modified_time=modified_time,
            indexed_at=utc_now(),
            chunk_count=0,
            status=status,
            error_message=error_message,
            last_run_id=run_id,
        )

    def ingest(self, force: bool = False) -> dict[str, object]:
        started_at = utc_now()
        run_id = self.db.start_ingestion_run(force_reindex=force, started_at=started_at)
        summary = {
            "run_id": run_id,
            "started_at": started_at,
            "files_seen": 0,
            "imported": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "unsupported": 0,
            "chunks_created": 0,
            "failed_files": [],
        }
        for file_path in iter_candidate_files(self.settings.data_sources_path):
            summary["files_seen"] += 1
            source_path = str(file_path.resolve())
            relative_path = str(file_path.relative_to(self.settings.data_sources_path))
            file_hash = compute_file_hash(file_path)
            modified_time = file_path.stat().st_mtime
            existing = self.db.get_file_record(source_path)
            source_category = detect_source_category(file_path)
            if not is_supported_file(file_path):
                summary["unsupported"] += 1
                self._record_unhandled_file(
                    run_id=run_id,
                    file_path=file_path,
                    source_path=source_path,
                    relative_path=relative_path,
                    file_hash=file_hash,
                    modified_time=modified_time,
                    source_category=source_category,
                    status="unsupported",
                    error_message=f"Unsupported file type: {file_path.suffix or '[no extension]'}",
                )
                continue
            if existing and not force and existing["file_hash"] == file_hash and existing["status"] == "indexed":
                summary["skipped"] += 1
                self.db.upsert_file_record(
                    source_path=source_path,
                    relative_path=relative_path,
                    file_name=file_path.name,
                    source_category=existing.get("source_category", source_category),
                    source_type=existing.get("source_type", file_path.suffix.lower().lstrip(".")),
                    file_hash=file_hash,
                    modified_time=modified_time,
                    indexed_at=str(existing.get("indexed_at", "")),
                    chunk_count=int(existing.get("chunk_count", 0)),
                    status="indexed",
                    error_message="",
                    last_run_id=run_id,
                )
                continue
            try:
                parsed = self._parse(file_path)
                source_category = detect_source_category(file_path, parsed.text, parsed.source_type)
                chunks = chunk_document(
                    parsed,
                    source_path=source_path,
                    relative_path=relative_path,
                    file_name=file_path.name,
                    source_category=source_category,
                    modified_time=modified_time,
                    file_hash=file_hash,
                )
                if chunks:
                    vectors = self.ollama_client.embed([chunk["text"] for chunk in chunks])
                    self.qdrant_store.ensure_collection(len(vectors[0]))
                    self.qdrant_store.delete_source(source_path)
                    points = []
                    for chunk, vector in zip(chunks, vectors):
                        points.append(
                            {
                                "id": chunk["id"],
                                "vector": vector,
                                "payload": {
                                    "source_path": chunk["source_path"],
                                    "relative_path": chunk["relative_path"],
                                    "file_name": chunk["file_name"],
                                    "source_category": chunk["source_category"],
                                    "source_type": chunk["source_type"],
                                    "chunk_id": chunk["chunk_id"],
                                    "chunk_index": chunk["chunk_index"],
                                    "chunk_label": chunk["chunk_label"],
                                    "text": chunk["text"],
                                    "entities": chunk["entities"],
                                    "modified_time": chunk["modified_time"],
                                    "indexed_at": chunk["indexed_at"],
                                    "file_hash": chunk["file_hash"],
                                },
                            }
                        )
                    self.qdrant_store.upsert(points)
                else:
                    self.qdrant_store.delete_source(source_path)
                self.db.replace_chunks(source_path, chunks)
                self.db.upsert_file_record(
                    source_path=source_path,
                    relative_path=relative_path,
                    file_name=file_path.name,
                    source_category=source_category,
                    source_type=parsed.source_type,
                    file_hash=file_hash,
                    modified_time=modified_time,
                    indexed_at=utc_now(),
                    chunk_count=len(chunks),
                    status="indexed",
                    error_message="",
                    last_run_id=run_id,
                )
                if existing and existing.get("status") == "indexed":
                    summary["updated"] += 1
                else:
                    summary["imported"] += 1
                summary["chunks_created"] += len(chunks)
            except Exception as exc:
                summary["failed"] += 1
                message = str(exc)[:1200]
                summary["failed_files"].append(
                    {
                        "file_name": file_path.name,
                        "relative_path": relative_path,
                        "error_message": message,
                    }
                )
                self._record_unhandled_file(
                    run_id=run_id,
                    file_path=file_path,
                    source_path=source_path,
                    relative_path=relative_path,
                    file_hash=file_hash,
                    modified_time=modified_time,
                    source_category=source_category,
                    status="error",
                    error_message=message,
                )
        finished_at = utc_now()
        run_status = "completed_with_errors" if summary["failed"] else "completed"
        self.db.finish_ingestion_run(
            run_id,
            finished_at=finished_at,
            files_seen=summary["files_seen"],
            imported_count=summary["imported"],
            updated_count=summary["updated"],
            skipped_count=summary["skipped"],
            failed_count=summary["failed"],
            unsupported_count=summary["unsupported"],
            chunks_created=summary["chunks_created"],
            status=run_status,
        )
        summary["finished_at"] = finished_at
        summary.update(self.db.get_index_stats())
        summary["last_ingestion_run"] = self.db.get_latest_ingestion_run()
        return summary
