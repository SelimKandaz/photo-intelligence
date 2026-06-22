from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.services.file_types import detect_file_type

try:
    import pytesseract  # type: ignore
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps  # type: ignore
except Exception:
    pytesseract = None
    Image = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None

try:
    from pillow_heif import open_heif, register_heif_opener  # type: ignore
except Exception:
    open_heif = None
    register_heif_opener = None

if register_heif_opener is not None:
    register_heif_opener()


class OCRBackendError(RuntimeError):
    pass


def configure_tesseract_executable() -> str | None:
    if pytesseract is None:
        return None

    configured = os.environ.get("TESSERACT_CMD", "").strip().strip('"').strip("'")
    if configured:
        candidate = Path(configured)
        if candidate.exists():
            try:
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
            except Exception:
                pass
            return str(candidate)

    found = shutil.which("tesseract")
    if found:
        try:
            pytesseract.pytesseract.tesseract_cmd = found
        except Exception:
            pass
        return found

    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
            except Exception:
                pass
            return str(candidate)
    return None


class ImageLoader:
    def file_signature(self, image_path: Path) -> str:
        try:
            size = image_path.stat().st_size
        except Exception:
            size = -1
        try:
            with image_path.open("rb") as f:
                header = f.read(32)
            header_hex = header.hex(" ").upper()
        except Exception as exc:
            header_hex = f"could not read header: {exc}"
        detected = detect_file_type(image_path)
        return f"detected={detected}, size={size} bytes, first_32_bytes={header_hex}"

    def open_heif_image(self, image_path: Path):
        if Image is None or ImageOps is None:
            raise OCRBackendError("Pillow is not installed. Run: python -m pip install pillow")
        if register_heif_opener is None:
            raise OCRBackendError(
                "This looks like an iPhone HEIC/HEIF photo. Install support with: "
                "python -m pip install pillow-heif"
            )
        try:
            img = Image.open(image_path)
            return ImageOps.exif_transpose(img)
        except Exception:
            if open_heif is None:
                raise
            heif_file = open_heif(str(image_path))
            img = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data, "raw")
            return ImageOps.exif_transpose(img)

    def open_image(self, image_path: Path):
        if Image is None or ImageOps is None:
            raise OCRBackendError("Pillow is not installed. Run: python -m pip install pillow")

        detected = detect_file_type(image_path)
        if detected == "heif":
            try:
                return self.open_heif_image(image_path)
            except Exception as exc:
                sig = self.file_signature(image_path)
                raise OCRBackendError(
                    "Could not read this iPhone HEIC/HEIF image. Install/upgrade support with: "
                    "python -m pip install -U pillow-heif pillow. "
                    f"{sig}"
                ) from exc

        if image_path.suffix.lower() in {".heic", ".heif"} and register_heif_opener is None:
            raise OCRBackendError("HEIC/HEIF support needs pillow-heif. Run: python -m pip install pillow-heif")

        try:
            with Image.open(image_path) as probe:
                probe.verify()
            img = Image.open(image_path)
            return ImageOps.exif_transpose(img)
        except Exception as exc:
            sig = self.file_signature(image_path)
            raise OCRBackendError(
                "Pillow cannot identify/read this image. The file may be corrupt, incomplete, "
                "a cloud placeholder, or a real iPhone HEIC/JPEG file renamed incorrectly. "
                "Try opening it in Windows Photos and Save As JPEG, or install pillow-heif. "
                f"{sig}"
            ) from exc

    def image_metadata(self, image_path: Path) -> dict:
        if Image is None:
            return {}
        try:
            with Image.open(image_path) as img:
                exif_raw = {}
                try:
                    exif_raw = {str(k): str(v) for k, v in (img.getexif() or {}).items()}
                except Exception:
                    exif_raw = {}
                return {
                    "width": img.width,
                    "height": img.height,
                    "format": img.format or "",
                    "exif": exif_raw,
                }
        except Exception:
            return {}

    def preprocess_for_tesseract(self, img):
        if ImageOps is None or ImageEnhance is None or ImageFilter is None:
            return img
        work = ImageOps.grayscale(img)
        work = ImageEnhance.Contrast(work).enhance(2.5)
        scale = 2
        if max(work.size) < 1800:
            scale = 4
        elif max(work.size) < 3000:
            scale = 3
        work = work.resize((work.width * scale, work.height * scale), Image.Resampling.LANCZOS)
        work = work.filter(ImageFilter.SHARPEN)
        return work
