from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.db.connection import Database
from app.ingestion.importer import ImportService


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a folder into the photo intelligence index.")
    parser.add_argument("folder", nargs="?", help="Folder to import. Defaults to IMPORT_FOLDER from .env.")
    parser.add_argument("--backend", default=None, help="audit, barcode, tesseract, or auto")
    parser.add_argument("--force", action="store_true", help="Re-run extraction even if this version already ran.")
    args = parser.parse_args()

    settings = load_settings()
    database = Database(settings.database_url)
    folder = Path(args.folder) if args.folder else settings.import_folder
    service = ImportService(database, settings)
    result = service.import_folder(
        folder,
        force=args.force,
        backend=args.backend,
        progress_callback=lambda msg: print(msg, flush=True),
    )
    print(json.dumps(result, indent=2))
    return 0 if result["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

