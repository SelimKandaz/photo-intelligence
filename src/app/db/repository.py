from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import defaultdict
from typing import Any

from app.models.types import ExtractedEntity, ExtractionOutput, normalize_entity_value


def new_id() -> str:
    return uuid.uuid4().hex


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_import_session(self, source_path: str) -> str:
        session_id = new_id()
        self.conn.execute(
            """
            INSERT INTO import_sessions(id, source_path, status)
            VALUES (?, ?, 'running')
            """,
            (session_id, source_path),
        )
        return session_id

    def create_import_job(
        self,
        job_id: str,
        source_path: str,
        *,
        backend: str,
        force: bool,
        storage_mode: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO import_jobs(
                id, kind, source_path, status, backend, force, storage_mode, started_at
            )
            VALUES (?, 'import', ?, 'queued', ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (job_id, source_path, backend, int(force), storage_mode),
        )

    def attach_job_session(self, job_id: str, session_id: str) -> None:
        self.conn.execute(
            """
            UPDATE import_jobs
            SET import_session_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (session_id, job_id),
        )

    def update_import_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress_text: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        current = self.conn.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
        if not current:
            return
        self.conn.execute(
            """
            UPDATE import_jobs
            SET status = COALESCE(?, status),
                progress_text = COALESCE(?, progress_text),
                result_json = COALESCE(?, result_json),
                error = COALESCE(?, error),
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CASE
                    WHEN ? IN ('completed', 'failed', 'interrupted') THEN CURRENT_TIMESTAMP
                    ELSE completed_at
                END
            WHERE id = ?
            """,
            (
                status,
                progress_text,
                json.dumps(result, sort_keys=True) if result is not None else None,
                error,
                status,
                job_id,
            ),
        )

    def mark_interrupted_import_jobs(self) -> None:
        self.conn.execute(
            """
            UPDATE import_jobs
            SET status = 'interrupted',
                error = CASE WHEN error = '' THEN 'App restarted before this job completed.' ELSE error END,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CURRENT_TIMESTAMP
            WHERE status IN ('queued', 'running')
            """
        )

    def list_import_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM import_jobs
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [row_to_dict(row) or {} for row in rows]

    def get_import_job(self, job_id: str) -> dict[str, Any] | None:
        return row_to_dict(self.conn.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone())

    def update_import_totals(
        self,
        session_id: str,
        *,
        total_files: int,
        imported_count: int,
        skipped_count: int,
        failed_count: int,
        status: str,
        notes: str = "",
    ) -> None:
        self.conn.execute(
            """
            UPDATE import_sessions
            SET total_files = ?, imported_count = ?, skipped_count = ?,
                failed_count = ?, status = ?, notes = ?,
                finished_at = CASE WHEN ? IN ('completed', 'failed') THEN CURRENT_TIMESTAMP ELSE finished_at END
            WHERE id = ?
            """,
            (
                total_files,
                imported_count,
                skipped_count,
                failed_count,
                status,
                notes,
                status,
                session_id,
            ),
        )

    def record_skipped_file(self, session_id: str, path: str, reason: str) -> None:
        self.conn.execute(
            """
            INSERT INTO skipped_files(id, import_session_id, path, reason)
            VALUES (?, ?, ?, ?)
            """,
            (new_id(), session_id, path, reason),
        )

    def record_failed_file(self, session_id: str, path: str, error: str, tb: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO failed_files(id, import_session_id, path, error, traceback)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_id(), session_id, path, error, tb),
        )

    def list_failed_files(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM failed_files
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [row_to_dict(row) or {} for row in rows]

    def find_photo_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM photos WHERE file_hash = ? ORDER BY created_at LIMIT 1",
            (file_hash,),
        ).fetchone()
        return row_to_dict(row)

    def record_duplicate_file(
        self,
        *,
        import_session_id: str,
        canonical_photo_id: str | None,
        original_path: str,
        duplicate_path: str,
        file_hash: str,
        file_size: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO duplicate_files(
                id, import_session_id, canonical_photo_id, original_path,
                duplicate_path, file_hash, file_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                import_session_id,
                canonical_photo_id,
                original_path,
                duplicate_path,
                file_hash,
                file_size,
            ),
        )

    def find_photo_by_path(self, path: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM photos WHERE path = ?", (path,)).fetchone()
        return row_to_dict(row)

    def has_extraction(
        self,
        photo_id: str,
        extractor_name: str,
        extractor_version: str,
        backend: str,
    ) -> bool:
        row = self.conn.execute(
            """
            SELECT 1
            FROM extraction_runs
            WHERE photo_id = ? AND extractor_name = ? AND extractor_version = ?
              AND backend = ? AND status = 'completed'
            LIMIT 1
            """,
            (photo_id, extractor_name, extractor_version, backend),
        ).fetchone()
        return row is not None

    def upsert_photo(self, data: dict[str, Any]) -> str:
        photo_id = data.get("id") or new_id()
        self.conn.execute(
            """
            INSERT INTO photos (
                id, import_session_id, path, original_path, file_name, file_ext,
                file_hash, file_size, modified_time, detected_type,
                storage_path, captured_at, sequence_index, status, last_error, storage_mode
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                import_session_id = excluded.import_session_id,
                original_path = excluded.original_path,
                file_name = excluded.file_name,
                file_ext = excluded.file_ext,
                file_hash = excluded.file_hash,
                file_size = excluded.file_size,
                modified_time = excluded.modified_time,
                detected_type = excluded.detected_type,
                storage_path = excluded.storage_path,
                captured_at = excluded.captured_at,
                sequence_index = excluded.sequence_index,
                status = excluded.status,
                last_error = excluded.last_error,
                storage_mode = excluded.storage_mode,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                photo_id,
                data.get("import_session_id"),
                data["path"],
                data["original_path"],
                data["file_name"],
                data["file_ext"],
                data["file_hash"],
                data["file_size"],
                data["modified_time"],
                data["detected_type"],
                data.get("storage_path", ""),
                data.get("captured_at"),
                data.get("sequence_index"),
                data.get("status", "pending"),
                data.get("last_error", ""),
                data.get("storage_mode", "reference"),
            ),
        )
        row = self.conn.execute("SELECT id FROM photos WHERE path = ?", (data["path"],)).fetchone()
        return str(row["id"])

    def update_photo_status(self, photo_id: str, status: str, last_error: str = "") -> None:
        self.conn.execute(
            """
            UPDATE photos
            SET status = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, last_error, photo_id),
        )

    def update_photo_thumbnail(self, photo_id: str, thumbnail_path: str) -> None:
        self.conn.execute(
            """
            UPDATE photos
            SET thumbnail_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (thumbnail_path, photo_id),
        )

    def upsert_image_metadata(self, photo_id: str, metadata: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO image_metadata (
                photo_id, width, height, format, camera_make, camera_model, taken_at, exif_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(photo_id) DO UPDATE SET
                width = excluded.width,
                height = excluded.height,
                format = excluded.format,
                camera_make = excluded.camera_make,
                camera_model = excluded.camera_model,
                taken_at = excluded.taken_at,
                exif_json = excluded.exif_json
            """,
            (
                photo_id,
                metadata.get("width"),
                metadata.get("height"),
                metadata.get("format", ""),
                metadata.get("camera_make", ""),
                metadata.get("camera_model", ""),
                metadata.get("taken_at"),
                json.dumps(metadata.get("exif", {}), sort_keys=True),
            ),
        )

    def insert_thumbnail(self, photo_id: str, path: str, width: int, height: int) -> None:
        self.conn.execute(
            """
            INSERT INTO thumbnails(id, photo_id, path, width, height)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_id(), photo_id, path, width, height),
        )
        self.update_photo_thumbnail(photo_id, path)

    def create_extraction_run(
        self,
        photo_id: str,
        extractor_name: str,
        extractor_version: str,
        backend: str,
    ) -> str:
        run_id = new_id()
        self.conn.execute(
            """
            INSERT INTO extraction_runs(
                id, photo_id, extractor_name, extractor_version, backend, status
            )
            VALUES (?, ?, ?, ?, ?, 'running')
            """,
            (run_id, photo_id, extractor_name, extractor_version, backend),
        )
        return run_id

    def complete_extraction_run(
        self,
        run_id: str,
        status: str,
        *,
        duration_ms: int | None = None,
        error: str = "",
        raw_text: str = "",
    ) -> None:
        raw_hash = hashlib.sha256(raw_text.encode("utf-8", errors="ignore")).hexdigest() if raw_text else ""
        self.conn.execute(
            """
            UPDATE extraction_runs
            SET status = ?, completed_at = CURRENT_TIMESTAMP, duration_ms = ?,
                error = ?, raw_text_hash = ?
            WHERE id = ?
            """,
            (status, duration_ms, error, raw_hash, run_id),
        )

    def store_extraction_output(
        self,
        photo_id: str,
        run_id: str,
        output: ExtractionOutput,
    ) -> None:
        if output.raw_ocr_text:
            self.conn.execute(
                """
                INSERT INTO raw_ocr_results(id, extraction_run_id, photo_id, source, text, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (new_id(), run_id, photo_id, output.backend, output.raw_ocr_text, None),
            )

        for value in output.raw_barcode_values:
            self.conn.execute(
                """
                INSERT INTO raw_barcode_results(
                    id, extraction_run_id, photo_id, value, source, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (new_id(), run_id, photo_id, value, "barcode_scan", 1.0),
            )

        self.conn.execute(
            """
            UPDATE entities
            SET is_current = 0
            WHERE photo_id = ? AND extractor_name = ? AND extractor_version != ''
            """,
            (photo_id, output.extractor_name),
        )
        for entity in output.entities:
            self.insert_entity(photo_id, run_id, entity, output.extractor_name, output.extractor_version)

        if output.serial_mismatch and output.serial_mismatch != "MATCH":
            priority = 90 if output.serial_mismatch.startswith("MISMATCH") else 60
            self.add_review_item(photo_id, run_id, output.serial_mismatch, priority=priority)
        self.update_searchable_text(photo_id)

    def insert_entity(
        self,
        photo_id: str,
        extraction_run_id: str | None,
        entity: ExtractedEntity,
        extractor_name: str = "",
        extractor_version: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO entities(
                id, photo_id, extraction_run_id, entity_type, value, normalized_value,
                confidence, source_type, evidence_text, evidence_bbox_json,
                metadata_json, extractor_name, extractor_version, is_current
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                new_id(),
                photo_id,
                extraction_run_id,
                entity.entity_type,
                entity.value,
                entity.normalized_value,
                entity.confidence,
                entity.source_type,
                entity.evidence_text,
                json.dumps(entity.evidence_bbox or {}, sort_keys=True),
                json.dumps(entity.metadata, sort_keys=True),
                extractor_name,
                extractor_version,
            ),
        )

    def add_review_item(
        self,
        photo_id: str,
        extraction_run_id: str | None,
        reason: str,
        priority: int = 50,
    ) -> None:
        existing = self.conn.execute(
            """
            SELECT 1 FROM review_queue
            WHERE photo_id = ? AND reason = ? AND status = 'open'
            LIMIT 1
            """,
            (photo_id, reason),
        ).fetchone()
        if existing:
            return
        self.conn.execute(
            """
            INSERT INTO review_queue(id, photo_id, extraction_run_id, reason, priority)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_id(), photo_id, extraction_run_id, reason, priority),
        )

    def list_photos(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM photos
            ORDER BY COALESCE(sequence_index, 999999), modified_time, path
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = row_to_dict(row) or {}
            item["entities"] = self.list_current_entities(item["id"])
            item["context"] = self.list_context_assignments(item["id"])
            items.append(item)
        return items

    def get_photo(self, photo_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        item = row_to_dict(row)
        if not item:
            return None
        item["metadata"] = row_to_dict(
            self.conn.execute("SELECT * FROM image_metadata WHERE photo_id = ?", (photo_id,)).fetchone()
        )
        item["entities"] = self.list_current_entities(photo_id)
        item["context"] = self.list_context_assignments(photo_id)
        item["raw_ocr"] = [
            row_to_dict(row)
            for row in self.conn.execute(
                "SELECT * FROM raw_ocr_results WHERE photo_id = ? ORDER BY created_at DESC",
                (photo_id,),
            ).fetchall()
        ]
        item["raw_barcodes"] = [
            row_to_dict(row)
            for row in self.conn.execute(
                "SELECT * FROM raw_barcode_results WHERE photo_id = ? ORDER BY created_at DESC",
                (photo_id,),
            ).fetchall()
        ]
        item["corrections"] = [
            row_to_dict(row)
            for row in self.conn.execute(
                "SELECT * FROM user_corrections WHERE photo_id = ? ORDER BY created_at DESC",
                (photo_id,),
            ).fetchall()
        ]
        item["navigation"] = self.previous_next_photos(photo_id)
        return item

    def get_failed_file(self, failed_file_id: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute("SELECT * FROM failed_files WHERE id = ?", (failed_file_id,)).fetchone()
        )

    def mark_failed_file_retry(self, failed_file_id: str) -> None:
        self.conn.execute(
            """
            UPDATE failed_files
            SET retry_count = retry_count + 1
            WHERE id = ?
            """,
            (failed_file_id,),
        )

    def list_current_entities(self, photo_id: str) -> list[dict[str, Any]]:
        return [
            row_to_dict(row) or {}
            for row in self.conn.execute(
                """
                SELECT *
                FROM entities
                WHERE photo_id = ? AND is_current = 1
                ORDER BY entity_type, confidence DESC, value
                """,
                (photo_id,),
            ).fetchall()
        ]

    def list_context_assignments(self, photo_id: str) -> list[dict[str, Any]]:
        return [
            row_to_dict(row) or {}
            for row in self.conn.execute(
                """
                SELECT *
                FROM context_assignments
                WHERE photo_id = ? AND is_current = 1
                ORDER BY confidence DESC, entity_type
                """,
                (photo_id,),
            ).fetchall()
        ]

    def photos_for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM photos
            WHERE import_session_id = ?
            ORDER BY COALESCE(sequence_index, 999999), modified_time, path
            """,
            (session_id,),
        ).fetchall()
        return [row_to_dict(row) or {} for row in rows]

    def clear_context_for_session(self, session_id: str) -> None:
        self.conn.execute(
            """
            UPDATE context_assignments
            SET is_current = 0
            WHERE batch_id = ?
            """,
            (session_id,),
        )

    def add_context_assignment(
        self,
        photo_id: str,
        entity_type: str,
        value: str,
        confidence: float,
        reason: str,
        source_photo_id: str | None,
        batch_id: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO context_assignments(
                id, photo_id, entity_type, value, confidence, reason, source_photo_id, batch_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id(), photo_id, entity_type, value, confidence, reason, source_photo_id, batch_id),
        )

    def record_search_query(self, query_text: str, parsed_entities: dict[str, Any]) -> str:
        query_id = new_id()
        self.conn.execute(
            """
            INSERT INTO search_queries(id, query_text, parsed_entities_json)
            VALUES (?, ?, ?)
            """,
            (query_id, query_text, json.dumps(parsed_entities, sort_keys=True)),
        )
        return query_id

    def record_search_click(
        self,
        photo_id: str,
        query_id: str | None = None,
        result_rank: int | None = None,
        action: str = "open",
        query_fingerprint: str = "",
    ) -> str:
        click_id = new_id()
        self.conn.execute(
            """
            INSERT INTO search_clicks(id, query_id, photo_id, result_rank, action, query_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (click_id, query_id, photo_id, result_rank, action, query_fingerprint),
        )
        return click_id

    def add_feedback(
        self,
        photo_id: str,
        rating: str,
        note: str = "",
        query_id: str | None = None,
        query_fingerprint: str = "",
        result_rank: int | None = None,
    ) -> str:
        feedback_id = new_id()
        self.conn.execute(
            """
            INSERT INTO feedback(id, photo_id, query_id, rating, note, query_fingerprint, result_rank)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (feedback_id, photo_id, query_id, rating, note, query_fingerprint, result_rank),
        )
        if query_fingerprint:
            weight = 0.0
            normalized_rating = rating.lower().strip()
            if normalized_rating in {"correct", "confirmed", "yes"}:
                weight = 12.0
            elif normalized_rating in {"wrong", "incorrect", "false_positive"}:
                weight = -18.0
            elif normalized_rating == "needs_review":
                weight = -3.0
            if weight:
                self.conn.execute(
                    """
                    INSERT INTO search_learning_signals(
                        id, query_id, photo_id, query_fingerprint, rating, weight
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (new_id(), query_id, photo_id, query_fingerprint, rating, weight),
                )
        return feedback_id

    def add_correction(
        self,
        photo_id: str,
        entity_type: str,
        corrected_value: str,
        *,
        old_value: str = "",
        note: str = "",
        corrected_by: str = "",
    ) -> str:
        correction_id = new_id()
        self.conn.execute(
            """
            INSERT INTO user_corrections(
                id, photo_id, entity_type, old_value, corrected_value, note, corrected_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (correction_id, photo_id, entity_type, old_value, corrected_value, note, corrected_by),
        )
        entity = ExtractedEntity(
            entity_type=entity_type,
            value=corrected_value,
            confidence=1.0,
            source_type="user_corrected",
            evidence_text=note,
            metadata={"correction_id": correction_id},
        )
        self.insert_entity(photo_id, None, entity, "user_correction", "manual")
        self.update_searchable_text(photo_id)
        return correction_id

    def list_review_queue(self, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT rq.*, p.path, p.thumbnail_path
            FROM review_queue rq
            JOIN photos p ON p.id = rq.photo_id
            WHERE rq.status = ?
            ORDER BY rq.priority DESC, rq.created_at
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()
        return [row_to_dict(row) or {} for row in rows]

    def resolve_review_item(self, review_item_id: str, action: str, note: str = "") -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM review_queue WHERE id = ?", (review_item_id,)).fetchone()
        item = row_to_dict(row)
        if not item:
            return None
        status_map = {
            "resolved": "resolved",
            "confirmed_mismatch": "confirmed_mismatch",
            "false_positive": "false_positive",
        }
        new_status = status_map.get(action)
        if not new_status:
            raise ValueError("Review action must be resolved, confirmed_mismatch, or false_positive")
        self.conn.execute(
            """
            UPDATE review_queue
            SET status = ?, resolved_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_status, review_item_id),
        )
        self.conn.execute(
            """
            INSERT INTO review_resolution_history(
                id, review_item_id, photo_id, old_status, new_status, action, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id(), review_item_id, item["photo_id"], item["status"], new_status, action, note),
        )
        item["status"] = new_status
        return item

    def search_corpus(self, photo_ids: set[str] | None = None) -> list[dict[str, Any]]:
        if photo_ids is None:
            photos = self.conn.execute(
                "SELECT * FROM photos WHERE status != 'skipped' ORDER BY modified_time, path"
            ).fetchall()
        elif not photo_ids:
            photos = []
        else:
            placeholders = ",".join("?" for _ in photo_ids)
            photos = self.conn.execute(
                f"SELECT * FROM photos WHERE id IN ({placeholders}) ORDER BY modified_time, path",
                tuple(photo_ids),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for photo_row in photos:
            photo = row_to_dict(photo_row) or {}
            photo_id = photo["id"]
            photo["entities"] = self.list_current_entities(photo_id)
            photo["context"] = self.list_context_assignments(photo_id)
            ocr_rows = self.conn.execute(
                """
                SELECT text
                FROM raw_ocr_results
                WHERE photo_id = ?
                ORDER BY created_at DESC
                LIMIT 3
                """,
                (photo_id,),
            ).fetchall()
            barcode_rows = self.conn.execute(
                """
                SELECT value
                FROM raw_barcode_results
                WHERE photo_id = ?
                ORDER BY created_at DESC
                """,
                (photo_id,),
            ).fetchall()
            photo["raw_ocr_text"] = "\n".join(str(row["text"]) for row in ocr_rows)
            photo["raw_barcode_values"] = [str(row["value"]) for row in barcode_rows]
            result.append(photo)
        return result

    def photo_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS count FROM photos WHERE status != 'skipped'").fetchone()
        return int(row["count"] if row else 0)

    def exact_candidate_photo_ids(self, query_entities: list[dict[str, Any]], compatibility: dict[str, set[str]]) -> set[str]:
        ids: set[str] = set()
        for query_entity in query_entities:
            q_type = query_entity["entity_type"]
            q_value = query_entity["normalized_value"]
            compatible = compatibility.get(q_type, {q_type})
            placeholders = ",".join("?" for _ in compatible)
            rows = self.conn.execute(
                f"""
                SELECT DISTINCT photo_id
                FROM entities
                WHERE entity_type IN ({placeholders})
                  AND normalized_value = ?
                  AND is_current = 1
                """,
                tuple(compatible) + (q_value,),
            ).fetchall()
            ids.update(str(row["photo_id"]) for row in rows)

            ctx_rows = self.conn.execute(
                """
                SELECT DISTINCT photo_id
                FROM context_assignments
                WHERE entity_type = ? AND value = ? AND is_current = 1
                """,
                (q_type, query_entity["value"]),
            ).fetchall()
            ids.update(str(row["photo_id"]) for row in ctx_rows)
        return ids

    def fts_candidate_photo_ids(self, terms: list[str], limit: int = 500) -> set[str]:
        clean_terms = []
        for term in terms:
            safe = "".join(ch for ch in term.upper() if ch.isalnum())
            if len(safe) >= 3:
                clean_terms.append(safe)
        if not clean_terms:
            return set()
        query = " OR ".join(f"{term}*" for term in clean_terms[:8])
        try:
            rows = self.conn.execute(
                """
                SELECT DISTINCT photo_id
                FROM searchable_text_fts
                WHERE searchable_text_fts MATCH ?
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        except sqlite3.Error:
            return set()
        return {str(row["photo_id"]) for row in rows}

    def learning_signal_score(self, query_fingerprint: str, photo_id: str) -> float:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(weight), 0) AS score
            FROM search_learning_signals
            WHERE query_fingerprint = ? AND photo_id = ?
            """,
            (query_fingerprint, photo_id),
        ).fetchone()
        return float(row["score"] if row and row["score"] is not None else 0.0)

    def update_searchable_text(self, photo_id: str) -> None:
        photo = row_to_dict(self.conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone())
        if not photo:
            return
        entities = self.list_current_entities(photo_id)
        context = self.list_context_assignments(photo_id)
        ocr_rows = self.conn.execute(
            "SELECT text FROM raw_ocr_results WHERE photo_id = ? ORDER BY created_at DESC LIMIT 5",
            (photo_id,),
        ).fetchall()
        barcode_rows = self.conn.execute(
            "SELECT value FROM raw_barcode_results WHERE photo_id = ? ORDER BY created_at DESC",
            (photo_id,),
        ).fetchall()
        parts = [
            photo.get("path", ""),
            photo.get("original_path", ""),
            photo.get("file_name", ""),
            " ".join(entity["value"] for entity in entities),
            " ".join(ctx["value"] for ctx in context),
            " ".join(row["text"] for row in ocr_rows),
            " ".join(row["value"] for row in barcode_rows),
        ]
        content = "\n".join(part for part in parts if part)
        self.conn.execute("DELETE FROM searchable_text_fts WHERE photo_id = ?", (photo_id,))
        self.conn.execute(
            "INSERT INTO searchable_text_fts(photo_id, content) VALUES (?, ?)",
            (photo_id, content),
        )

    def nearby_photos(self, photo_id: str, radius: int = 2) -> list[dict[str, Any]]:
        current = self.conn.execute(
            "SELECT import_session_id, sequence_index, modified_time FROM photos WHERE id = ?",
            (photo_id,),
        ).fetchone()
        if not current:
            return []
        session_id = current["import_session_id"]
        sequence_index = current["sequence_index"]
        if session_id and sequence_index is not None:
            rows = self.conn.execute(
                """
                SELECT *
                FROM photos
                WHERE import_session_id = ?
                  AND sequence_index BETWEEN ? AND ?
                  AND id != ?
                ORDER BY sequence_index
                """,
                (session_id, int(sequence_index) - radius, int(sequence_index) + radius, photo_id),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT *
                FROM photos
                WHERE id != ?
                ORDER BY ABS(modified_time - ?)
                LIMIT ?
                """,
                (photo_id, current["modified_time"], radius * 2),
            ).fetchall()
        return [row_to_dict(row) or {} for row in rows]

    def previous_next_photos(self, photo_id: str) -> dict[str, dict[str, Any] | None]:
        current = self.conn.execute(
            "SELECT import_session_id, sequence_index, modified_time FROM photos WHERE id = ?",
            (photo_id,),
        ).fetchone()
        if not current:
            return {"previous": None, "next": None}
        session_id = current["import_session_id"]
        sequence_index = current["sequence_index"]
        previous = None
        next_item = None
        if session_id and sequence_index is not None:
            previous = row_to_dict(
                self.conn.execute(
                    """
                    SELECT * FROM photos
                    WHERE import_session_id = ? AND sequence_index < ?
                    ORDER BY sequence_index DESC
                    LIMIT 1
                    """,
                    (session_id, sequence_index),
                ).fetchone()
            )
            next_item = row_to_dict(
                self.conn.execute(
                    """
                    SELECT * FROM photos
                    WHERE import_session_id = ? AND sequence_index > ?
                    ORDER BY sequence_index ASC
                    LIMIT 1
                    """,
                    (session_id, sequence_index),
                ).fetchone()
            )
        return {"previous": previous, "next": next_item}

    def serial_export_source_rows(self) -> list[dict[str, Any]]:
        photos = self.search_corpus()
        rows: list[dict[str, Any]] = []
        for photo in photos:
            grouped: dict[str, list[str]] = defaultdict(list)
            eans: list[str] = []
            for entity in photo["entities"]:
                grouped[entity["entity_type"]].append(entity["value"])
                if entity["entity_type"] == "unknown_possible_identifier":
                    try:
                        metadata = json.loads(entity.get("metadata_json") or "{}")
                    except Exception:
                        metadata = {}
                    if metadata.get("kind") in {"ean", "upc"}:
                        eans.append(entity["value"])
            printed = sorted(set(grouped.get("printed_serial_number", [])))
            barcode = sorted(set(grouped.get("barcode_serial_number", [])))
            mismatch = ""
            if printed and barcode:
                if set(printed) == set(barcode):
                    mismatch = "MATCH"
                else:
                    parts = []
                    missing = sorted(set(printed) - set(barcode))
                    extra = sorted(set(barcode) - set(printed))
                    if missing:
                        parts.append("printed_not_in_barcode=" + ";".join(missing))
                    if extra:
                        parts.append("barcode_not_printed=" + ";".join(extra))
                    mismatch = "MISMATCH: " + " | ".join(parts)
            elif printed:
                mismatch = "PRINTED_ONLY"
            elif barcode:
                mismatch = "BARCODE_ONLY"
            context_grouped: dict[str, list[str]] = defaultdict(list)
            for ctx in photo.get("context", []):
                context_grouped[str(ctx.get("entity_type") or "")].append(str(ctx.get("value") or ""))

            purchase_orders = sorted(
                set(grouped.get("purchase_order", []))
                | {value for value in context_grouped.get("purchase_order", []) if value}
            )
            sales_orders = sorted(
                set(grouped.get("sales_order", []))
                | {value for value in context_grouped.get("sales_order", []) if value}
            )

            rows.append(
                {
                    "photo_id": photo["id"],
                    "path": photo["path"],
                    "file_name": photo["file_name"],
                    "captured_at": photo.get("captured_at") or "",
                    "modified_time": photo.get("modified_time") or "",
                    "created_at": photo.get("created_at") or "",
                    "sequence_index": photo.get("sequence_index"),
                    "import_session_id": photo.get("import_session_id") or "",
                    "review_status": self.photo_review_status(photo["id"]),
                    "model_numbers": sorted(set(grouped.get("model_number", []))),
                    "part_numbers": sorted(set(grouped.get("part_number", []))),
                    "ean_numbers": sorted(set(eans)),
                    "purchase_orders": purchase_orders,
                    "sales_orders": sales_orders,
                    "printed_serial_numbers": printed,
                    "barcode_serial_numbers": barcode,
                    "serial_mismatch": mismatch,
                }
            )
        return rows

    def photo_review_status(self, photo_id: str) -> str:
        row = self.conn.execute(
            """
            SELECT status
            FROM review_queue
            WHERE photo_id = ?
            ORDER BY CASE WHEN status = 'open' THEN 0 ELSE 1 END, created_at DESC
            LIMIT 1
            """,
            (photo_id,),
        ).fetchone()
        return str(row["status"]) if row else ""

    def entity_exists(self, photo_id: str, entity_type: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM entities
            WHERE photo_id = ? AND entity_type = ? AND is_current = 1
            LIMIT 1
            """,
            (photo_id, entity_type),
        ).fetchone()
        return row is not None

    def normalized_entity_exists(self, photo_id: str, entity_type: str, value: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM entities
            WHERE photo_id = ? AND entity_type = ? AND normalized_value = ?
              AND is_current = 1
            LIMIT 1
            """,
            (photo_id, entity_type, normalize_entity_value(value)),
        ).fetchone()
        return row is not None
