from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.db.connection import Database
from app.db.migrations import applied_migrations, current_schema_version, run_migrations


def main() -> int:
    settings = load_settings()
    database = Database(settings.database_url)
    with database.session() as conn:
        run_migrations(conn)
        payload = {
            "database_url": settings.database_url,
            "schema_version": current_schema_version(conn),
            "migrations": applied_migrations(conn),
        }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

