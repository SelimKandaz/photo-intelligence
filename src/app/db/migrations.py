from __future__ import annotations

import sqlite3
from collections.abc import Callable


def migration_001_initial_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS import_sessions (
            id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            total_files INTEGER NOT NULL DEFAULT 0,
            imported_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS photos (
            id TEXT PRIMARY KEY,
            import_session_id TEXT,
            path TEXT NOT NULL UNIQUE,
            original_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_ext TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            modified_time REAL NOT NULL,
            detected_type TEXT NOT NULL,
            storage_path TEXT NOT NULL DEFAULT '',
            thumbnail_path TEXT NOT NULL DEFAULT '',
            captured_at TEXT,
            sequence_index INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(import_session_id) REFERENCES import_sessions(id)
        );

        CREATE TABLE IF NOT EXISTS image_metadata (
            photo_id TEXT PRIMARY KEY,
            width INTEGER,
            height INTEGER,
            format TEXT NOT NULL DEFAULT '',
            camera_make TEXT NOT NULL DEFAULT '',
            camera_model TEXT NOT NULL DEFAULT '',
            taken_at TEXT,
            exif_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS thumbnails (
            id TEXT PRIMARY KEY,
            photo_id TEXT NOT NULL,
            path TEXT NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS extraction_runs (
            id TEXT PRIMARY KEY,
            photo_id TEXT NOT NULL,
            extractor_name TEXT NOT NULL,
            extractor_version TEXT NOT NULL,
            backend TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            duration_ms INTEGER,
            error TEXT NOT NULL DEFAULT '',
            raw_text_hash TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS raw_ocr_results (
            id TEXT PRIMARY KEY,
            extraction_run_id TEXT NOT NULL,
            photo_id TEXT NOT NULL,
            source TEXT NOT NULL,
            text TEXT NOT NULL,
            confidence REAL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id) ON DELETE CASCADE,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS raw_barcode_results (
            id TEXT PRIMARY KEY,
            extraction_run_id TEXT NOT NULL,
            photo_id TEXT NOT NULL,
            value TEXT NOT NULL,
            symbology TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            confidence REAL,
            bbox_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id) ON DELETE CASCADE,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            photo_id TEXT NOT NULL,
            extraction_run_id TEXT,
            entity_type TEXT NOT NULL,
            value TEXT NOT NULL,
            normalized_value TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_type TEXT NOT NULL,
            evidence_text TEXT NOT NULL DEFAULT '',
            evidence_bbox_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            extractor_name TEXT NOT NULL DEFAULT '',
            extractor_version TEXT NOT NULL DEFAULT '',
            is_current INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE,
            FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS context_assignments (
            id TEXT PRIMARY KEY,
            photo_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL,
            source_photo_id TEXT,
            batch_id TEXT,
            is_current INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE,
            FOREIGN KEY(source_photo_id) REFERENCES photos(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS search_queries (
            id TEXT PRIMARY KEY,
            query_text TEXT NOT NULL,
            parsed_entities_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS search_clicks (
            id TEXT PRIMARY KEY,
            query_id TEXT,
            photo_id TEXT NOT NULL,
            result_rank INTEGER,
            action TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(query_id) REFERENCES search_queries(id) ON DELETE SET NULL,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            photo_id TEXT NOT NULL,
            query_id TEXT,
            rating TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE,
            FOREIGN KEY(query_id) REFERENCES search_queries(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS user_corrections (
            id TEXT PRIMARY KEY,
            photo_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            old_value TEXT NOT NULL DEFAULT '',
            corrected_value TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            note TEXT NOT NULL DEFAULT '',
            corrected_by TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS review_queue (
            id TEXT PRIMARY KEY,
            photo_id TEXT NOT NULL,
            extraction_run_id TEXT,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            priority INTEGER NOT NULL DEFAULT 50,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE,
            FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS skipped_files (
            id TEXT PRIMARY KEY,
            import_session_id TEXT,
            path TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(import_session_id) REFERENCES import_sessions(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS failed_files (
            id TEXT PRIMARY KEY,
            import_session_id TEXT,
            path TEXT NOT NULL,
            error TEXT NOT NULL,
            traceback TEXT NOT NULL DEFAULT '',
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(import_session_id) REFERENCES import_sessions(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_photos_hash ON photos(file_hash);
        CREATE INDEX IF NOT EXISTS idx_photos_session ON photos(import_session_id, sequence_index);
        CREATE INDEX IF NOT EXISTS idx_extraction_runs_photo ON extraction_runs(photo_id, extractor_name, extractor_version);
        CREATE INDEX IF NOT EXISTS idx_entities_lookup ON entities(entity_type, normalized_value, is_current);
        CREATE INDEX IF NOT EXISTS idx_entities_photo ON entities(photo_id, is_current);
        CREATE INDEX IF NOT EXISTS idx_context_photo ON context_assignments(photo_id, is_current);
        CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(status, priority);
        """
    )


def migration_002_hardening_foundation(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS duplicate_files (
            id TEXT PRIMARY KEY,
            import_session_id TEXT,
            canonical_photo_id TEXT,
            original_path TEXT NOT NULL,
            duplicate_path TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            file_size INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(import_session_id) REFERENCES import_sessions(id) ON DELETE SET NULL,
            FOREIGN KEY(canonical_photo_id) REFERENCES photos(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS import_jobs (
            id TEXT PRIMARY KEY,
            import_session_id TEXT,
            kind TEXT NOT NULL DEFAULT 'import',
            source_path TEXT NOT NULL,
            status TEXT NOT NULL,
            backend TEXT NOT NULL DEFAULT '',
            force INTEGER NOT NULL DEFAULT 0,
            storage_mode TEXT NOT NULL DEFAULT 'reference',
            progress_text TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            started_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY(import_session_id) REFERENCES import_sessions(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS review_resolution_history (
            id TEXT PRIMARY KEY,
            review_item_id TEXT NOT NULL,
            photo_id TEXT NOT NULL,
            old_status TEXT NOT NULL,
            new_status TEXT NOT NULL,
            action TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(review_item_id) REFERENCES review_queue(id) ON DELETE CASCADE,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS search_learning_signals (
            id TEXT PRIMARY KEY,
            query_id TEXT,
            photo_id TEXT NOT NULL,
            query_fingerprint TEXT NOT NULL,
            rating TEXT NOT NULL,
            weight REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(query_id) REFERENCES search_queries(id) ON DELETE SET NULL,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS searchable_text_fts
        USING fts5(
            photo_id UNINDEXED,
            content,
            tokenize='unicode61'
        );

        CREATE INDEX IF NOT EXISTS idx_duplicate_files_hash ON duplicate_files(file_hash);
        CREATE INDEX IF NOT EXISTS idx_import_jobs_status ON import_jobs(status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_search_learning_query ON search_learning_signals(query_fingerprint, photo_id);
        """
    )
    _add_column_if_missing(conn, "photos", "storage_mode", "TEXT NOT NULL DEFAULT 'reference'")
    _add_column_if_missing(conn, "feedback", "query_fingerprint", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "search_clicks", "query_fingerprint", "TEXT NOT NULL DEFAULT ''")


def migration_003_feedback_result_rank(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "feedback", "result_rank", "INTEGER")


MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "001_initial_schema", migration_001_initial_schema),
    (2, "002_hardening_foundation", migration_002_hardening_foundation),
    (3, "003_feedback_result_rank", migration_003_feedback_result_rank),
]

SCHEMA_VERSION = MIGRATIONS[-1][0]


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _add_column_if_missing(conn, "schema_migrations", "name", "TEXT NOT NULL DEFAULT ''")


def current_schema_version(conn: sqlite3.Connection) -> int:
    ensure_migration_table(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
    return int(row["version"] if row and row["version"] is not None else 0)


def applied_migrations(conn: sqlite3.Connection) -> list[dict]:
    ensure_migration_table(conn)
    rows = conn.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def run_migrations(conn: sqlite3.Connection) -> None:
    ensure_migration_table(conn)
    applied = {
        int(row["version"])
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, name, migration in MIGRATIONS:
        if version in applied:
            continue
        migration(conn)
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
            (version, name),
        )
        conn.commit()


def _add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")
