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
from app.services.export import (
    serial_harvest_conflicts_csv,
    serial_harvest_csv,
    serial_harvest_review_csv,
    serial_harvest_rows,
    serial_harvest_txt,
)


def latest_session_id(repo: Repository) -> str | None:
    row = repo.conn.execute(
        """
        SELECT id
        FROM import_sessions
        WHERE imported_count > 0
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row["id"]) if row else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a simple deduplicated serial list plus photo traceability files."
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output folder. Defaults to data/exports/serial_harvest_latest.",
    )
    parser.add_argument(
        "--session",
        default="latest",
        help="latest, all, or a specific import session id. Default: latest.",
    )
    parser.add_argument("--from-date", default=None, help="Optional start date YYYY-MM-DD.")
    parser.add_argument("--to-date", default=None, help="Optional end date YYYY-MM-DD.")
    parser.add_argument("--gap", default="10", help="Start a new group when serial photos are more than this many photos apart.")
    args = parser.parse_args()

    settings = load_settings()
    output_dir = Path(args.output_dir) if args.output_dir else settings.export_root / "serial_harvest_latest"
    output_dir.mkdir(parents=True, exist_ok=True)

    database = Database(settings.database_url)
    with database.session() as conn:
        run_migrations(conn)
        repo = Repository(conn)
        session_arg = str(args.session or "latest").strip()
        if session_arg.lower() == "latest":
            session_id = latest_session_id(repo)
        elif session_arg.lower() == "all":
            session_id = None
        else:
            session_id = session_arg
        rows = serial_harvest_rows(
            repo,
            session_id=session_id,
            date_from=args.from_date,
            date_to=args.to_date,
            gap_threshold=int(str(args.gap or "10")),
        )
        conflicts_csv = serial_harvest_conflicts_csv(repo, session_id=session_id)

    serials_path = output_dir / "serials_only.txt"
    csv_path = output_dir / "serials_with_photos.csv"
    review_path = output_dir / "review_needed_serials.csv"
    conflicts_path = output_dir / "serial_conflicts_by_photo.csv"
    serials_path.write_text(serial_harvest_txt(rows), encoding="utf-8")
    csv_path.write_text(serial_harvest_csv(rows), encoding="utf-8-sig", newline="")
    review_path.write_text(serial_harvest_review_csv(rows), encoding="utf-8-sig", newline="")
    conflicts_path.write_text(conflicts_csv, encoding="utf-8-sig", newline="")

    review_count = sum(1 for row in rows if row.get("confidence") == "review")
    duplicate_hits = sum(max(0, int(row.get("duplicate_count") or 0) - 1) for row in rows)
    print(f"Unique serials: {len(rows)}")
    print(f"Review-needed: {review_count}")
    print(f"Duplicate detections removed: {duplicate_hits}")
    print(f"Wrote: {serials_path}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {review_path}")
    print(f"Wrote: {conflicts_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
