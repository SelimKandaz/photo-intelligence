from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.db.connection import Database
from app.db.migrations import run_migrations
from app.db.repository import Repository
from app.services.export import serial_rows_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Export one row per serial with printed-vs-barcode audit.")
    parser.add_argument(
        "--output",
        default=None,
        help="CSV output path. Defaults to data/exports/serial_rows_printed_vs_barcode_audit.csv.",
    )
    args = parser.parse_args()

    settings = load_settings()
    output = Path(args.output) if args.output else settings.export_root / "serial_rows_printed_vs_barcode_audit.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_url)
    with database.session() as conn:
        run_migrations(conn)
        csv_text = serial_rows_csv(Repository(conn))
    output.write_text(csv_text, encoding="utf-8-sig", newline="")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

