from __future__ import annotations

from pathlib import Path


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".jfif",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
}
PDF_EXTENSIONS = {".pdf"}
IGNORED_EXTENSIONS = {".aae", ".mov", ".mp4"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS


def detect_file_type(file_path: Path) -> str:
    try:
        with file_path.open("rb") as f:
            header = f.read(64)
    except Exception:
        return "unknown"

    if header.startswith(b"%PDF"):
        return "pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"BM"):
        return "bmp"
    if header.startswith(b"II*\x00") or header.startswith(b"MM\x00*"):
        return "tiff"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"

    heif_brands = (
        b"ftypheic",
        b"ftypheix",
        b"ftyphevc",
        b"ftyphevx",
        b"ftypheim",
        b"ftypheis",
        b"ftypmif1",
        b"ftypmsf1",
    )
    if any(brand in header[:32] for brand in heif_brands):
        return "heif"

    return "unknown"


def is_supported_file(file_path: Path) -> bool:
    suffix = file_path.suffix.lower()
    if suffix in IGNORED_EXTENSIONS:
        return False
    if suffix in SUPPORTED_EXTENSIONS:
        return True
    return detect_file_type(file_path) in {"jpeg", "png", "bmp", "tiff", "webp", "heif", "pdf"}


def discover_supported_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and is_supported_file(path):
            files.append(path)
    return sorted(files, key=lambda p: (p.stat().st_mtime, str(p).lower()))

