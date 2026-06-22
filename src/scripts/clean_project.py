from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def remove_file(path: Path, dry_run: bool) -> None:
    print(f"remove file {path}")
    if not dry_run:
        path.unlink(missing_ok=True)


def remove_dir(path: Path, dry_run: bool) -> None:
    print(f"remove dir  {path}")
    if not dry_run:
        shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean Python caches and local build artifacts.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed.")
    parser.add_argument(
        "--keep-dist",
        action="store_true",
        help="Keep dist/ while removing Python caches and temporary build files.",
    )
    args = parser.parse_args()

    for cache_dir in ROOT.rglob("__pycache__"):
        if ".venv" not in cache_dir.parts:
            remove_dir(cache_dir, args.dry_run)

    for pattern in ("*.pyc", "*.pyo"):
        for file_path in ROOT.rglob(pattern):
            if ".venv" not in file_path.parts:
                remove_file(file_path, args.dry_run)

    for relative in ("build", "work"):
        path = ROOT / relative
        if path.exists():
            remove_dir(path, args.dry_run)

    if not args.keep_dist and (ROOT / "dist").exists():
        remove_dir(ROOT / "dist", args.dry_run)

    for cache_name in (".pytest_cache", ".mypy_cache", ".ruff_cache"):
        path = ROOT / cache_name
        if path.exists():
            remove_dir(path, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

