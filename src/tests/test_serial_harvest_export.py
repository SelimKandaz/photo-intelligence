from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from app.db.connection import Database
from app.db.migrations import run_migrations
from app.db.repository import Repository
from app.models.types import ExtractedEntity
from app.services.export import serial_harvest_conflicts_csv, serial_harvest_csv, serial_harvest_review_csv, serial_harvest_rows, serial_harvest_txt


def add_photo(repo: Repository, session_id: str, name: str, seq: int, serial: str, entity_type: str) -> str:
    photo_id = repo.upsert_photo(
        {
            "import_session_id": session_id,
            "path": f"C:/photos/{name}",
            "original_path": f"C:/photos/{name}",
            "file_name": name,
            "file_ext": ".jpg",
            "file_hash": f"hash-{name}",
            "file_size": 10,
            "modified_time": float(seq),
            "detected_type": "jpeg",
            "sequence_index": seq,
            "status": "indexed",
        }
    )
    run_id = repo.create_extraction_run(photo_id, "test", "1", "audit")
    repo.insert_entity(photo_id, run_id, ExtractedEntity(entity_type, serial, 0.95, "test"), "test", "1")
    repo.complete_extraction_run(run_id, "completed")
    return photo_id


class SerialHarvestExportTests(unittest.TestCase):
    def test_harvest_deduplicates_serial_values_but_keeps_photos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                add_photo(repo, session_id, "a.jpg", 1, "MT2331FT15720", "printed_serial_number")
                add_photo(repo, session_id, "b.jpg", 2, "mt2331ft15720", "barcode_serial_number")
                add_photo(repo, session_id, "c.jpg", 3, "99Y0A1234567", "barcode_serial_number")

                rows = serial_harvest_rows(repo, session_id=session_id)
                self.assertEqual([row["serial_number"] for row in rows], ["MT2331FT15720", "99Y0A1234567"])
                self.assertEqual(rows[0]["duplicate_count"], 2)
                self.assertIn("a.jpg", rows[0]["photo_names"])
                self.assertIn("b.jpg", rows[0]["photo_names"])

                txt = serial_harvest_txt(rows)
                self.assertEqual(txt.count("MT2331FT15720"), 1)

                csv_rows = list(csv.DictReader(io.StringIO(serial_harvest_csv(rows))))
                self.assertEqual(len(csv_rows), 2)
                self.assertEqual(csv_rows[0]["serial_number"], "MT2331FT15720")

    def test_review_csv_only_contains_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                photo_id = repo.upsert_photo(
                    {
                        "import_session_id": session_id,
                        "path": "C:/photos/mismatch.jpg",
                        "original_path": "C:/photos/mismatch.jpg",
                        "file_name": "mismatch.jpg",
                        "file_ext": ".jpg",
                        "file_hash": "hash-mismatch",
                        "file_size": 10,
                        "modified_time": 1.0,
                        "detected_type": "jpeg",
                        "sequence_index": 1,
                        "status": "indexed",
                    }
                )
                run_id = repo.create_extraction_run(photo_id, "test", "1", "audit")
                repo.insert_entity(photo_id, run_id, ExtractedEntity("printed_serial_number", "PRINTED123", 0.90, "test"), "test", "1")
                repo.insert_entity(photo_id, run_id, ExtractedEntity("barcode_serial_number", "BARCODE456", 1.0, "test"), "test", "1")
                repo.complete_extraction_run(run_id, "completed")

                rows = serial_harvest_rows(repo, session_id=session_id)
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(row["confidence"] == "review" for row in rows))
                review_csv_rows = list(csv.DictReader(io.StringIO(serial_harvest_review_csv(rows))))
                self.assertEqual(len(review_csv_rows), 2)

    def test_grouped_txt_inserts_blank_line_when_photo_gap_is_large(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                add_photo(repo, session_id, "a.jpg", 1, "MT2331FT15720", "barcode_serial_number")
                add_photo(repo, session_id, "b.jpg", 2, "MT2331FT15721", "barcode_serial_number")
                add_photo(repo, session_id, "z.jpg", 20, "MT2331FT15722", "barcode_serial_number")

                rows = serial_harvest_rows(repo, session_id=session_id, gap_threshold=10)
                txt = serial_harvest_txt(rows)
                self.assertIn("MT2331FT15721\n\nMT2331FT15722", txt)
                self.assertEqual([row["group_id"] for row in rows], ["1", "1", "2"])

    def test_conflicts_csv_outputs_printed_and_barcode_side_by_side(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                session_id = repo.create_import_session("C:/photos")
                photo_id = repo.upsert_photo(
                    {
                        "import_session_id": session_id,
                        "path": "C:/photos/mismatch.jpg",
                        "original_path": "C:/photos/mismatch.jpg",
                        "file_name": "mismatch.jpg",
                        "file_ext": ".jpg",
                        "file_hash": "hash-mismatch-conflicts",
                        "file_size": 10,
                        "modified_time": 1.0,
                        "detected_type": "jpeg",
                        "sequence_index": 1,
                        "status": "indexed",
                    }
                )
                run_id = repo.create_extraction_run(photo_id, "test", "1", "audit")
                repo.insert_entity(photo_id, run_id, ExtractedEntity("printed_serial_number", "PRINTED123", 0.90, "test"), "test", "1")
                repo.insert_entity(photo_id, run_id, ExtractedEntity("barcode_serial_number", "BARCODE456", 1.0, "test"), "test", "1")
                repo.complete_extraction_run(run_id, "completed")

                csv_text = serial_harvest_conflicts_csv(repo, session_id=session_id)
                rows = list(csv.DictReader(io.StringIO(csv_text)))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["printed_serials"], "PRINTED123")
                self.assertEqual(rows[0]["barcode_or_qr_serials"], "BARCODE456")


if __name__ == "__main__":
    unittest.main()
