from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db.connection import Database
from app.db.migrations import run_migrations
from app.db.repository import Repository
from app.models.types import ExtractedEntity
from app.search.engine import SearchEngine
from app.services.export import serial_rows_csv


class DatabaseSearchExportTests(unittest.TestCase):
    def test_search_and_export_use_structured_entities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            database = Database(f"sqlite:///{db_path}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                photo_id = repo.upsert_photo(
                    {
                        "import_session_id": session_id,
                        "path": "C:/photos/a.jpg",
                        "original_path": "C:/photos/a.jpg",
                        "file_name": "a.jpg",
                        "file_ext": ".jpg",
                        "file_hash": "hash1",
                        "file_size": 10,
                        "modified_time": 1.0,
                        "detected_type": "jpeg",
                        "sequence_index": 1,
                        "status": "indexed",
                    }
                )
                run_id = repo.create_extraction_run(photo_id, "test", "1", "audit")
                repo.insert_entity(
                    photo_id,
                    run_id,
                    ExtractedEntity("printed_serial_number", "MT2331FT15720", 0.96, "printed_ocr"),
                    "test",
                    "1",
                )
                repo.insert_entity(
                    photo_id,
                    run_id,
                    ExtractedEntity("purchase_order", "11234", 0.80, "regex_guess"),
                    "test",
                    "1",
                )
                repo.complete_extraction_run(run_id, "completed")

                search_result = SearchEngine(repo).search("PO 11234 SN MT2331FT15720")
                self.assertEqual(len(search_result["results"]), 1)
                self.assertEqual(search_result["results"][0]["photo_id"], photo_id)

                csv_text = serial_rows_csv(repo)
                self.assertIn("MT2331FT15720", csv_text)
                self.assertIn("printed-s/n", csv_text)


if __name__ == "__main__":
    unittest.main()

