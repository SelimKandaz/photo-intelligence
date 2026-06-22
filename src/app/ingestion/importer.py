from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable

from app.config import Settings
from app.context.engine import ContextEngine
from app.db.connection import Database
from app.db.migrations import run_migrations
from app.db.repository import Repository
from app.extraction.pipeline import PhotoExtractor
from app.ingestion.storage import prepare_storage_path
from app.ocr.image_io import ImageLoader
from app.services.file_types import IGNORED_EXTENSIONS, detect_file_type, is_supported_file
from app.services.hashing import file_fingerprint
from app.services.thumbnails import create_thumbnail


ProgressCallback = Callable[[str], None]


class ImportService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def import_folder(
        self,
        source_path: Path,
        *,
        force: bool = False,
        backend: str | None = None,
        job_id: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict:
        source_path = source_path.expanduser().resolve()
        backend = (backend or self.settings.ocr_backend).lower().strip()
        extractor = PhotoExtractor(
            extractor_name=self.settings.extractor_name,
            extractor_version=self.settings.extractor_version,
            backend=backend,
        )
        image_loader = ImageLoader()

        with self.database.session() as conn:
            run_migrations(conn)
            repo = Repository(conn)
            session_id = repo.create_import_session(str(source_path))
            if job_id:
                repo.attach_job_session(job_id, session_id)
            conn.commit()

            all_files = sorted(
                [p for p in source_path.rglob("*") if p.is_file()],
                key=lambda p: (p.stat().st_mtime, str(p).lower()),
            )
            total = len(all_files)
            imported = 0
            skipped = 0
            failed = 0

            for sequence_index, path in enumerate(all_files, start=1):
                try:
                    if progress_callback:
                        progress_callback(f"{sequence_index}/{total}: {path.name}")

                    suffix = path.suffix.lower()
                    if suffix in IGNORED_EXTENSIONS:
                        repo.record_skipped_file(session_id, str(path), f"ignored extension {suffix}")
                        skipped += 1
                        conn.commit()
                        continue
                    if not is_supported_file(path):
                        repo.record_skipped_file(session_id, str(path), "unsupported file type")
                        skipped += 1
                        conn.commit()
                        continue

                    file_hash, file_size, modified_time = file_fingerprint(path)
                    existing_by_hash = repo.find_photo_by_hash(file_hash)
                    if (
                        existing_by_hash
                        and existing_by_hash["original_path"] != str(path)
                        and not force
                    ):
                        repo.record_duplicate_file(
                            import_session_id=session_id,
                            canonical_photo_id=existing_by_hash["id"],
                            original_path=existing_by_hash["original_path"],
                            duplicate_path=str(path),
                            file_hash=file_hash,
                            file_size=file_size,
                        )
                        repo.record_skipped_file(
                            session_id,
                            str(path),
                            f"duplicate file hash already indexed at {existing_by_hash['path']}",
                        )
                        skipped += 1
                        conn.commit()
                        continue

                    detected_type = detect_file_type(path)
                    active_path, storage_path = prepare_storage_path(self.settings, path, file_hash)
                    metadata = image_loader.image_metadata(active_path)
                    captured_at = metadata.get("exif", {}).get("36867") or metadata.get("exif", {}).get("306")
                    photo_id = repo.upsert_photo(
                        {
                            "import_session_id": session_id,
                            "path": str(active_path),
                            "original_path": str(path),
                            "file_name": path.name,
                            "file_ext": suffix,
                            "file_hash": file_hash,
                            "file_size": file_size,
                            "modified_time": modified_time,
                            "detected_type": detected_type,
                            "storage_path": storage_path,
                            "storage_mode": self.settings.storage_mode,
                            "captured_at": captured_at,
                            "sequence_index": sequence_index,
                            "status": "pending",
                        }
                    )

                    if metadata:
                        repo.upsert_image_metadata(photo_id, metadata)
                    if path.suffix.lower() not in {".pdf"} and detected_type != "pdf":
                        thumb_path = self.settings.thumbnail_root / f"{photo_id}.jpg"
                        thumb_size = create_thumbnail(active_path, thumb_path)
                        if thumb_size:
                            repo.insert_thumbnail(photo_id, str(thumb_path), thumb_size[0], thumb_size[1])

                    if (
                        not force
                        and repo.has_extraction(
                            photo_id,
                            self.settings.extractor_name,
                            self.settings.extractor_version,
                            backend,
                        )
                    ):
                        repo.update_photo_status(photo_id, "indexed")
                        repo.record_skipped_file(session_id, str(path), "already extracted by this version")
                        skipped += 1
                        conn.commit()
                        continue

                    run_id = repo.create_extraction_run(
                        photo_id,
                        self.settings.extractor_name,
                        self.settings.extractor_version,
                        backend,
                    )
                    output = extractor.extract(
                        active_path,
                        progress_callback=lambda msg, file_name=path.name: progress_callback(
                            f"{file_name}: {msg}"
                        )
                        if progress_callback
                        else None,
                    )
                    repo.store_extraction_output(photo_id, run_id, output)
                    repo.complete_extraction_run(
                        run_id,
                        "completed",
                        error=" | ".join(output.errors),
                        raw_text=output.raw_ocr_text,
                    )
                    if output.errors:
                        repo.add_review_item(photo_id, run_id, "Extraction completed with warnings: " + " | ".join(output.errors), priority=40)
                        repo.update_photo_status(photo_id, "indexed_with_warnings", " | ".join(output.errors))
                    else:
                        repo.update_photo_status(photo_id, "indexed")
                    imported += 1
                    conn.commit()
                except Exception as exc:
                    failed += 1
                    repo.record_failed_file(session_id, str(path), str(exc), traceback.format_exc())
                    existing = repo.find_photo_by_path(str(path))
                    if existing:
                        repo.update_photo_status(existing["id"], "failed", str(exc))
                    conn.commit()

                repo.update_import_totals(
                    session_id,
                    total_files=total,
                    imported_count=imported,
                    skipped_count=skipped,
                    failed_count=failed,
                    status="running",
                )
                conn.commit()

            ContextEngine(repo).apply_import_session_context(session_id)
            status = "completed" if failed == 0 else "failed"
            repo.update_import_totals(
                session_id,
                total_files=total,
                imported_count=imported,
                skipped_count=skipped,
                failed_count=failed,
                status=status,
            )
            conn.commit()

            return {
                "session_id": session_id,
                "source_path": str(source_path),
                "total_files": total,
                "imported_count": imported,
                "skipped_count": skipped,
                "failed_count": failed,
                "status": status,
            }
