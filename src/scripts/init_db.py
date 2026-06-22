from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.db.connection import Database
from app.db.migrations import run_migrations


def main() -> int:
    settings = load_settings()
    database = Database(settings.database_url)
    with database.session() as conn:
        run_migrations(conn)
    print(f"Initialized database: {settings.database_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

