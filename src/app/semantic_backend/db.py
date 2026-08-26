from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .entity_extract import entities_to_json, normalize_entities


FILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    source_path TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL,
    source_category TEXT NOT NULL DEFAULT 'misc',
    source_type TEXT NOT NULL DEFAULT 'unknown',
    file_hash TEXT NOT NULL DEFAULT '',
    modified_time REAL NOT NULL DEFAULT 0,
    indexed_at TEXT NOT NULL DEFAULT '',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT NOT NULL DEFAULT '',
    last_run_id TEXT NOT NULL DEFAULT ''
);
"""

CHUNK_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    relative_path TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL,
    source_category TEXT NOT NULL DEFAULT 'misc',
    source_type TEXT NOT NULL DEFAULT 'unknown',
    chunk_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    chunk_label TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    detected_entities TEXT NOT NULL DEFAULT '{}',
    entities TEXT NOT NULL DEFAULT '{}',
    modified_time REAL NOT NULL DEFAULT 0,
    indexed_at TEXT NOT NULL DEFAULT '',
    file_hash TEXT NOT NULL DEFAULT ''
);
"""

INGESTION_RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    force_reindex INTEGER NOT NULL DEFAULT 0,
    files_seen INTEGER NOT NULL DEFAULT 0,
    imported_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    unsupported_count INTEGER NOT NULL DEFAULT 0,
    chunks_created INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    notes TEXT NOT NULL DEFAULT ''
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_chunks_source_path ON chunks(source_path);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_file_name ON chunks(file_name);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_relative_path ON chunks(relative_path);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_category ON chunks(source_category);",
    "CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);",
    "CREATE INDEX IF NOT EXISTS idx_files_category ON files(source_category);",
]


def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _add_column_if_missing(connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if column_name in _column_names(connection, table_name):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def ensure_schema(self) -> None:
        with self.connect() as connection:
            connection.execute(FILE_SCHEMA)
            connection.execute(CHUNK_SCHEMA)
            connection.execute(INGESTION_RUN_SCHEMA)
            for name, definition in (
                ("relative_path", "TEXT NOT NULL DEFAULT ''"),
                ("source_category", "TEXT NOT NULL DEFAULT 'misc'"),
                ("source_type", "TEXT NOT NULL DEFAULT 'unknown'"),
                ("last_run_id", "TEXT NOT NULL DEFAULT ''"),
            ):
                _add_column_if_missing(connection, "files", name, definition)
            for name, definition in (
                ("relative_path", "TEXT NOT NULL DEFAULT ''"),
                ("source_category", "TEXT NOT NULL DEFAULT 'misc'"),
                ("source_type", "TEXT NOT NULL DEFAULT 'unknown'"),
                ("chunk_index", "INTEGER NOT NULL DEFAULT 0"),
                ("chunk_label", "TEXT NOT NULL DEFAULT ''"),
                ("detected_entities", "TEXT NOT NULL DEFAULT '{}'"),
                ("entities", "TEXT NOT NULL DEFAULT '{}'"),
                ("file_hash", "TEXT NOT NULL DEFAULT ''"),
            ):
                _add_column_if_missing(connection, "chunks", name, definition)
            for statement in INDEXES:
                connection.execute(statement)
            connection.commit()

    def start_ingestion_run(self, *, force_reindex: bool, started_at: str) -> str:
        run_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_runs(
                    id, started_at, force_reindex, status
                )
                VALUES(?, ?, ?, 'running')
                """,
                (run_id, started_at, int(force_reindex)),
            )
            connection.commit()
        return run_id

    def finish_ingestion_run(
        self,
        run_id: str,
        *,
        finished_at: str,
        files_seen: int,
        imported_count: int,
        updated_count: int,
        skipped_count: int,
        failed_count: int,
        unsupported_count: int,
        chunks_created: int,
        status: str,
        notes: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_runs
                SET finished_at = ?, files_seen = ?, imported_count = ?, updated_count = ?,
                    skipped_count = ?, failed_count = ?, unsupported_count = ?, chunks_created = ?,
                    status = ?, notes = ?
                WHERE id = ?
                """,
                (
                    finished_at,
                    files_seen,
                    imported_count,
                    updated_count,
                    skipped_count,
                    failed_count,
                    unsupported_count,
                    chunks_created,
                    status,
                    notes,
                    run_id,
                ),
            )
            connection.commit()

    def get_latest_ingestion_run(self) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def get_file_record(self, source_path: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM files WHERE source_path = ?", (source_path,)).fetchone()
        return dict(row) if row else None

    def upsert_file_record(
        self,
        *,
        source_path: str,
        relative_path: str,
        file_name: str,
        source_category: str,
        source_type: str,
        file_hash: str,
        modified_time: float,
        indexed_at: str,
        chunk_count: int,
        status: str,
        error_message: str,
        last_run_id: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO files(
                    source_path, relative_path, file_name, source_category, source_type,
                    file_hash, modified_time, indexed_at, chunk_count, status, error_message, last_run_id
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    file_name = excluded.file_name,
                    source_category = excluded.source_category,
                    source_type = excluded.source_type,
                    file_hash = excluded.file_hash,
                    modified_time = excluded.modified_time,
                    indexed_at = excluded.indexed_at,
                    chunk_count = excluded.chunk_count,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    last_run_id = excluded.last_run_id
                """,
                (
                    source_path,
                    relative_path,
                    file_name,
                    source_category,
                    source_type,
                    file_hash,
                    modified_time,
                    indexed_at,
                    chunk_count,
                    status,
                    error_message,
                    last_run_id,
                ),
            )
            connection.commit()

    def clear_source(self, source_path: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM chunks WHERE source_path = ?", (source_path,))
            connection.commit()

    def replace_chunks(self, source_path: str, chunks: Iterable[dict[str, object]]) -> None:
        rows = list(chunks)
        records: list[tuple[object, ...]] = []
        for row in rows:
            normalized_entities = row.get("detected_entities", row.get("entities"))
            records.append(
                (
                    row["id"],
                    row["source_path"],
                    row["relative_path"],
                    row["file_name"],
                    row["source_category"],
                    row["source_type"],
                    row["chunk_id"],
                    row["chunk_index"],
                    row["chunk_label"],
                    row["text"],
                    entities_to_json(normalized_entities),
                    entities_to_json(normalized_entities),
                    row["modified_time"],
                    row["indexed_at"],
                    row["file_hash"],
                )
            )
        with self.connect() as connection:
            connection.execute("DELETE FROM chunks WHERE source_path = ?", (source_path,))
            connection.executemany(
                """
                INSERT INTO chunks(
                    id, source_path, relative_path, file_name, source_category, source_type,
                    chunk_id, chunk_index, chunk_label, text, detected_entities, entities,
                    modified_time, indexed_at, file_hash
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            connection.commit()

    def get_index_stats(self) -> dict[str, int]:
        with self.connect() as connection:
            indexed_files = connection.execute("SELECT COUNT(*) FROM files WHERE status = 'indexed'").fetchone()[0]
            indexed_chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            failed_files = connection.execute("SELECT COUNT(*) FROM files WHERE status = 'error'").fetchone()[0]
            unsupported_files = connection.execute("SELECT COUNT(*) FROM files WHERE status = 'unsupported'").fetchone()[0]
        return {
            "indexed_files": int(indexed_files),
            "indexed_chunks": int(indexed_chunks),
            "failed_files": int(failed_files),
            "unsupported_files": int(unsupported_files),
        }

    def get_stats(self) -> dict[str, object]:
        stats = self.get_index_stats()
        stats["last_ingestion_run"] = self.get_latest_ingestion_run()
        return stats

    def list_files(self, limit: int = 500) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM files ORDER BY relative_path LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_failed_files(self, limit: int = 200) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM files WHERE status IN ('error', 'unsupported') ORDER BY relative_path LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def iter_chunks(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM chunks ORDER BY file_name, chunk_index").fetchall()
        items: list[dict[str, object]] = []
        for row in rows:
            payload = dict(row)
            normalized_entities = normalize_entities(payload.get("detected_entities", payload.get("entities")))
            payload["detected_entities"] = normalized_entities
            payload["entities"] = normalized_entities
            items.append(payload)
        return items
