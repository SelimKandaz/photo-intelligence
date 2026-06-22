from __future__ import annotations

import unittest

from app.entity_parser.inventory import InventoryEntityParser


class InventoryParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = InventoryEntityParser()

    def test_printed_and_barcode_mismatch_is_flagged(self) -> None:
        result = self.parser.parse(
            "PO 11234\nP/N: MMA4Z00-NS400\nS/N: MT2331FT15720",
            ["MT2610FT11954", "7290110123456"],
        )
        self.assertEqual(result.fields["printed_serial_numbers"], "MT2331FT15720")
        self.assertEqual(result.fields["barcode_serial_numbers"], "MT2610FT11954")
        self.assertTrue(result.serial_mismatch.startswith("MISMATCH"))
        entity_pairs = {(entity.entity_type, entity.value) for entity in result.entities}
        self.assertIn(("purchase_order", "11234"), entity_pairs)
        self.assertIn(("printed_serial_number", "MT2331FT15720"), entity_pairs)
        self.assertIn(("barcode_serial_number", "MT2610FT11954"), entity_pairs)

    def test_matching_printed_and_barcode_is_match(self) -> None:
        result = self.parser.parse("Serial: MT2331FT15720", ["MT2331FT15720"])
        self.assertEqual(result.serial_mismatch, "MATCH")
        self.assertEqual(result.fields["serial_numbers"], "MT2331FT15720")

    def test_barcode_only_is_not_silently_printed(self) -> None:
        result = self.parser.parse("", ["MT2610FT11954"])
        self.assertEqual(result.serial_mismatch, "BARCODE_ONLY")
        self.assertEqual(result.fields["printed_serial_numbers"], "")
        self.assertEqual(result.fields["barcode_serial_numbers"], "MT2610FT11954")

    def test_ocr_only_mt26_candidate_needs_review(self) -> None:
        result = self.parser.parse("random read M26 106T 11837", [])
        self.assertEqual(result.fields["serial_numbers"], "")
        self.assertIn("MT2610FT11837", result.fields["serial_candidates_ocr"])
        candidates = [
            entity
            for entity in result.entities
            if entity.entity_type == "unknown_possible_identifier"
            and entity.metadata.get("kind") == "ocr_serial_candidate"
        ]
        self.assertTrue(candidates)


if __name__ == "__main__":
    unittest.main()

