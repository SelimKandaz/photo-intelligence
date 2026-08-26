from __future__ import annotations

import importlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path


class SemanticBackendSmokeTests(unittest.TestCase):
    def test_package_imports_without_connecting_to_services(self) -> None:
        module = importlib.import_module("app.semantic_backend.main")
        self.assertIsNotNone(module.app)

    def test_settings_can_load_secret_free_environment(self) -> None:
        from app.semantic_backend.config import Settings

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shutil.copy2(Path(__file__).resolve().parents[1] / ".env.example", root / ".env")
            previous = os.environ.get("OLLAMA_BASE_URL")
            try:
                os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
                settings = Settings.from_env(root)
            finally:
                if previous is None:
                    os.environ.pop("OLLAMA_BASE_URL", None)
                else:
                    os.environ["OLLAMA_BASE_URL"] = previous
            self.assertEqual(settings.ollama_base_url, "http://127.0.0.1:11434")
            self.assertEqual(settings.qdrant_collection, "photo_intelligence_docs")

    def test_empty_entities_are_stable_json(self) -> None:
        from app.semantic_backend.entity_extract import entities_to_json, normalize_entities

        normalized = normalize_entities(None)
        self.assertEqual(normalized["po_numbers"], [])
        self.assertNotEqual(entities_to_json(None), "null")


if __name__ == "__main__":
    unittest.main()
