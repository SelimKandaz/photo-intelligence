from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.context.engine import ContextEngine
from app.db.connection import Database
from app.db.migrations import current_schema_version, run_migrations
from app.db.repository import Repository
from app.ingestion.importer import ImportService
from app.ingestion.storage import prepare_storage_path
from app.models.types import ExtractedEntity
from app.search.engine import SearchEngine
from app.services.export import serial_rows_csv


def make_settings(root: Path, *, database_url: str | None = None, storage_mode: str = "reference") -> Settings:
    settings = Settings(
        app_mode="desktop",
        database_url=database_url or f"sqlite:///{root / 'test.db'}",
        host="127.0.0.1",
        port=8001,
        photo_storage_root=root / "storage",
        thumbnail_root=root / "thumbs",
        import_folder=root / "imports",
        export_root=root / "exports",
        log_root=root / "logs",
        storage_mode=storage_mode,
        extractor_name="test_extractor",
        extractor_version="1",
        ocr_backend="barcode",
        tesseract_cmd="",
        worker_mode="local-thread",
    )
    settings.ensure_directories()
    return settings


def insert_photo(repo: Repository, session_id: str, name: str, index: int = 1) -> str:
    return repo.upsert_photo(
        {
            "import_session_id": session_id,
            "path": f"C:/photos/{name}",
            "original_path": f"C:/photos/{name}",
            "file_name": name,
            "file_ext": Path(name).suffix,
            "file_hash": f"hash-{name}",
            "file_size": 10,
            "modified_time": float(index),
            "detected_type": "jpeg",
            "sequence_index": index,
            "status": "indexed",
        }
    )


class HardeningTests(unittest.TestCase):
    def test_migration_idempotence_preserves_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                photo_id = insert_photo(repo, session_id, "a.jpg")
                version = current_schema_version(conn)
                run_migrations(conn)
                self.assertEqual(current_schema_version(conn), version)
                self.assertIsNotNone(repo.get_photo(photo_id))

    def test_storage_reference_and_copy_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "photo.jpg"
            source.write_bytes(b"fake-photo")

            ref_settings = make_settings(root / "ref", storage_mode="reference")
            active, stored = prepare_storage_path(ref_settings, source, "abcdef")
            self.assertEqual(active, source)
            self.assertEqual(stored, "")

            copy_settings = make_settings(root / "copy", storage_mode="copy")
            active, stored = prepare_storage_path(copy_settings, source, "abcdef")
            self.assertTrue(active.exists())
            self.assertEqual(active, copy_settings.photo_storage_root / "ab" / "abcdef.jpg")
            self.assertEqual(stored, str(active))

    def test_duplicate_file_handling_records_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            imports = root / "imports"
            imports.mkdir()
            (imports / "a.jpg").write_bytes(b"same")
            (imports / "b.jpg").write_bytes(b"same")
            settings = make_settings(root, storage_mode="reference")
            database = Database(settings.database_url)
            result = ImportService(database, settings).import_folder(imports, backend="barcode")
            self.assertEqual(result["imported_count"], 1)
            self.assertEqual(result["skipped_count"], 1)
            with database.session() as conn:
                rows = conn.execute("SELECT * FROM duplicate_files").fetchall()
                self.assertEqual(len(rows), 1)
                self.assertTrue(str(rows[0]["duplicate_path"]).endswith("b.jpg"))

    def test_po_context_carry_forward(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                first = insert_photo(repo, session_id, "po.jpg", index=1)
                second = insert_photo(repo, session_id, "serial.jpg", index=2)
                run_id = repo.create_extraction_run(first, "test", "1", "audit")
                repo.insert_entity(first, run_id, ExtractedEntity("purchase_order", "11234", 0.9, "regex_guess"))
                ContextEngine(repo).apply_import_session_context(session_id)
                context = repo.list_context_assignments(second)
                self.assertEqual(context[0]["entity_type"], "purchase_order")
                self.assertEqual(context[0]["value"], "11234")

    def test_query_id_rank_feedback_storage_and_learning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                photo_id = insert_photo(repo, session_id, "a.jpg")
                run_id = repo.create_extraction_run(photo_id, "test", "1", "audit")
                repo.insert_entity(photo_id, run_id, ExtractedEntity("printed_serial_number", "MT2331FT15720", 0.96, "printed_ocr"))
                repo.update_searchable_text(photo_id)

                search_result = SearchEngine(repo).search("MT2331FT15720")
                result = search_result["results"][0]
                click_id = repo.record_search_click(
                    photo_id,
                    query_id=result["query_id"],
                    result_rank=result["rank"],
                    query_fingerprint=result["query_fingerprint"],
                )
                repo.add_feedback(
                    photo_id,
                    "correct",
                    query_id=result["query_id"],
                    query_fingerprint=result["query_fingerprint"],
                    result_rank=result["rank"],
                )
                click = conn.execute("SELECT * FROM search_clicks WHERE id = ?", (click_id,)).fetchone()
                feedback = conn.execute("SELECT * FROM feedback WHERE photo_id = ?", (photo_id,)).fetchone()
                self.assertEqual(click["result_rank"], 1)
                self.assertEqual(feedback["result_rank"], 1)
                self.assertGreater(repo.learning_signal_score(result["query_fingerprint"], photo_id), 0)

    def test_printed_only_and_barcode_only_serial_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                printed_photo = insert_photo(repo, session_id, "printed.jpg", 1)
                barcode_photo = insert_photo(repo, session_id, "barcode.jpg", 2)
                run_a = repo.create_extraction_run(printed_photo, "test", "1", "audit")
                run_b = repo.create_extraction_run(barcode_photo, "test", "1", "audit")
                repo.insert_entity(printed_photo, run_a, ExtractedEntity("printed_serial_number", "MT2331FT15720", 0.96, "printed_ocr"))
                repo.insert_entity(barcode_photo, run_b, ExtractedEntity("barcode_serial_number", "MT2610FT11954", 0.99, "barcode_qr"))
                repo.insert_entity(barcode_photo, run_b, ExtractedEntity("unknown_possible_identifier", "7290110123456", 0.85, "barcode_qr", metadata={"kind": "ean"}))
                csv_text = serial_rows_csv(repo)
                self.assertIn("printed-s/n", csv_text)
                self.assertIn("barcode-only-no-printed-s/n-read", csv_text)
                self.assertIn("7290110123456", csv_text)

    def test_search_exact_po_serial_and_fuzzy_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                photo_id = insert_photo(repo, session_id, "label.jpg")
                run_id = repo.create_extraction_run(photo_id, "test", "1", "audit")
                repo.insert_entity(photo_id, run_id, ExtractedEntity("printed_serial_number", "MT2331FT15720", 0.96, "printed_ocr"))
                repo.insert_entity(photo_id, run_id, ExtractedEntity("purchase_order", "11234", 0.8, "regex_guess"))
                conn.execute(
                    "INSERT INTO raw_ocr_results(id, extraction_run_id, photo_id, source, text) VALUES (?, ?, ?, ?, ?)",
                    ("ocr1", run_id, photo_id, "test", "blue capacitor evidence label"),
                )
                repo.update_searchable_text(photo_id)

                by_serial = SearchEngine(repo).search("MT2331FT15720")
                by_po_sn = SearchEngine(repo).search("PO 11234 SN MT2331FT15720")
                fast_fuzzy = SearchEngine(repo).search("capacitro", mode="fast")
                by_fuzzy = SearchEngine(repo).search("capacitro", mode="deep")
                self.assertEqual(by_serial["results"][0]["photo_id"], photo_id)
                self.assertEqual(by_po_sn["results"][0]["photo_id"], photo_id)
                self.assertEqual(fast_fuzzy["search_mode"], "fast")
                self.assertIn("Deep Search", fast_fuzzy["warning"])
                self.assertEqual(by_fuzzy["search_mode"], "deep")
                self.assertTrue(by_fuzzy["used_deep_scan"])
                self.assertGreaterEqual(by_fuzzy["total_photo_count"], 1)
                self.assertEqual(by_fuzzy["results"][0]["photo_id"], photo_id)
                self.assertIn("raw_ocr", by_fuzzy["results"][0]["match_sources"])


if __name__ == "__main__":
    unittest.main()
