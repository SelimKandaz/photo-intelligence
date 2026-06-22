from __future__ import annotations

import shutil
from pathlib import Path

from app.config import Settings


def stored_photo_path(settings: Settings, source_path: Path, file_hash: str) -> Path:
    suffix = source_path.suffix.lower()
    return settings.photo_storage_root / file_hash[:2] / f"{file_hash}{suffix}"


def prepare_storage_path(settings: Settings, source_path: Path, file_hash: str) -> tuple[Path, str]:
    if settings.storage_mode == "reference":
        return source_path, ""
    if settings.storage_mode != "copy":
        raise ValueError("STORAGE_MODE must be 'reference' or 'copy'")

    destination = stored_photo_path(settings, source_path, file_hash)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source_path, destination)
    return destination, str(destination)

