from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.db.connection import Database
from app.db.migrations import run_migrations
from app.ocr.image_io import configure_tesseract_executable


ROOT = Path(__file__).resolve().parents[1]


class DesktopSmokeTests(unittest.TestCase):
    def test_desktop_module_imports_and_tesseract_check_does_not_crash(self) -> None:
        try:
            import app.desktop.main as desktop_main  # noqa: F401
        except ModuleNotFoundError as exc:
            if exc.name == "PySide6":
                self.skipTest("PySide6 is not installed in this environment.")
            raise

        result = configure_tesseract_executable()
        self.assertTrue(result is None or isinstance(result, str))

    def test_settings_env_example_migrations_and_desktop_smoke_startup(self) -> None:
        try:
            import PySide6  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("PySide6 is not installed in this environment.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copy2(ROOT / ".env.example", temp_root / ".env")
            database = Database(f"sqlite:///{temp_root / 'data' / 'photo_inventory.db'}")
            with database.session() as conn:
                run_migrations(conn)

            env = os.environ.copy()
            env["PHOTO_INTELLIGENCE_ROOT"] = str(temp_root)
            env["PYTHONPATH"] = str(ROOT)
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["PHOTO_INTELLIGENCE_SMOKE_EXIT_MS"] = "250"
            completed = subprocess.run(
                [sys.executable, "-m", "app.desktop.main"],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
            self.assertTrue((temp_root / "data" / "photo_inventory.db").exists())


if __name__ == "__main__":
    unittest.main()

