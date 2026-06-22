from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(
    os.environ.get("PHOTO_INTELLIGENCE_ROOT")
    or os.environ.get("APP_ROOT")
    or CODE_ROOT
).resolve()


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _path_env(name: str, default: str) -> Path:
    value = os.environ.get(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


@dataclass(frozen=True)
class Settings:
    app_mode: str
    database_url: str
    host: str
    port: int
    photo_storage_root: Path
    thumbnail_root: Path
    import_folder: Path
    export_root: Path
    log_root: Path
    storage_mode: str
    extractor_name: str
    extractor_version: str
    ocr_backend: str
    tesseract_cmd: str
    worker_mode: str

    def ensure_directories(self) -> None:
        for path in (
            self.photo_storage_root,
            self.thumbnail_root,
            self.import_folder,
            self.export_root,
            self.log_root,
        ):
            path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    _load_dotenv(PROJECT_ROOT / ".env")
    if PROJECT_ROOT != CODE_ROOT:
        _load_dotenv(CODE_ROOT / ".env")
    storage_mode = os.environ.get("STORAGE_MODE", "reference").lower().strip()
    if storage_mode not in {"reference", "copy"}:
        raise ValueError("STORAGE_MODE must be 'reference' or 'copy'")
    settings = Settings(
        app_mode=os.environ.get("APP_MODE", "desktop"),
        database_url=os.environ.get("DATABASE_URL", "sqlite:///data/photo_inventory.db"),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8001")),
        photo_storage_root=_path_env("PHOTO_STORAGE_ROOT", "data/storage"),
        thumbnail_root=_path_env("THUMBNAIL_ROOT", "data/thumbnails"),
        import_folder=_path_env("IMPORT_FOLDER", "data/imports"),
        export_root=_path_env("EXPORT_ROOT", "data/exports"),
        log_root=_path_env("LOG_ROOT", "logs"),
        storage_mode=storage_mode,
        extractor_name=os.environ.get("EXTRACTOR_NAME", "v7_modular_audit"),
        extractor_version=os.environ.get("EXTRACTOR_VERSION", "0.1.0"),
        ocr_backend=os.environ.get("OCR_BACKEND", "audit"),
        tesseract_cmd=os.environ.get("TESSERACT_CMD", ""),
        worker_mode=os.environ.get("WORKER_MODE", "local-thread"),
    )
    settings.ensure_directories()
    return settings
