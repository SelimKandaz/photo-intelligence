from __future__ import annotations

import tempfile
from pathlib import Path

from app.ocr.image_io import (
    Image,
    ImageLoader,
    OCRBackendError,
    configure_tesseract_executable,
    pytesseract,
)
from app.services.file_types import IMAGE_EXTENSIONS, PDF_EXTENSIONS, detect_file_type

try:
    import fitz  # type: ignore
except Exception:
    fitz = None

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None


class OCRReader:
    def __init__(self, backend: str = "audit") -> None:
        self.backend = backend.lower().strip()
        self.loader = ImageLoader()

    def ocr_pil_with_tesseract(self, img, psm: int = 6, whitelist: str | None = None) -> str:
        if pytesseract is None:
            raise OCRBackendError("pytesseract is not installed. Run: python -m pip install pytesseract pillow")
        config = f"--oem 3 --psm {psm}"
        if whitelist:
            config += f" -c tessedit_char_whitelist={whitelist}"
        try:
            return pytesseract.image_to_string(img, config=config)
        except Exception as exc:
            raise OCRBackendError(f"Tesseract OCR failed: {exc}") from exc

    def extract_text_tesseract(self, image_path: Path, label_crops=None) -> str:
        if pytesseract is None:
            raise OCRBackendError("pytesseract is not installed. Run: python -m pip install pytesseract pillow")
        tesseract_exe = configure_tesseract_executable()
        if not tesseract_exe:
            raise OCRBackendError(
                "The Python package pytesseract is installed, but the native Tesseract OCR program "
                "is not installed or is not in PATH. Install it with PowerShell: "
                "winget install --id UB-Mannheim.TesseractOCR -e --source winget. "
                "Then close and reopen PowerShell/the OCR app."
            )

        try:
            base_img = self.loader.open_image(image_path)
            texts: list[str] = []

            full_img = self.loader.preprocess_for_tesseract(base_img)
            full_text = self.ocr_pil_with_tesseract(full_img, psm=6)
            if full_text.strip():
                texts.append(full_text)

            for crop_idx, crop in enumerate(label_crops(base_img) if label_crops else [], start=1):
                crop_text = self.ocr_pil_with_tesseract(self.loader.preprocess_for_tesseract(crop), psm=6)
                if crop_text.strip():
                    texts.append(f"\n--- LABEL CROP {crop_idx} ---\n{crop_text}")

            return "\n".join(texts)
        except Exception as exc:
            raise OCRBackendError(f"Tesseract OCR failed for {image_path.name} using {tesseract_exe}: {exc}") from exc

    def extract_text_from_image(self, image_path: Path, label_crops=None) -> tuple[str, str]:
        backend = self.backend
        if backend in {"auto", "tesseract", "audit"}:
            return self.extract_text_tesseract(image_path, label_crops=label_crops), "tesseract"
        if backend == "barcode":
            return "", "barcode-only"
        if backend == "paddle":
            raise OCRBackendError("PaddleOCR is not wired into the modular pipeline yet; use OCR_BACKEND=audit.")
        raise OCRBackendError("Unknown backend. Choose 'audit', 'barcode', 'tesseract', 'auto', or 'paddle'.")

    def extract_text_from_pdf(self, pdf_path: Path, label_crops=None) -> tuple[str, str]:
        parts: list[str] = []
        if PdfReader is not None:
            try:
                reader = PdfReader(str(pdf_path))
                for page in reader.pages:
                    text = page.extract_text() or ""
                    if text.strip():
                        parts.append(text)
                if parts:
                    return "\n".join(parts), "pdf-text"
            except Exception:
                pass

        if fitz is not None:
            try:
                doc = fitz.open(str(pdf_path))
                try:
                    for page in doc:
                        text = page.get_text("text") or ""
                        if text.strip():
                            parts.append(text)
                    if parts:
                        return "\n".join(parts), "pdf-text"
                finally:
                    doc.close()
            except Exception:
                pass

        if fitz is None:
            raise OCRBackendError("Scanned PDF fallback needs PyMuPDF. Run: python -m pip install pymupdf")

        page_texts: list[str] = []
        doc = fitz.open(str(pdf_path))
        try:
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp:
                    temp_path = Path(temp.name)
                try:
                    pix.save(str(temp_path))
                    text, _ = self.extract_text_from_image(temp_path, label_crops=label_crops)
                    if text.strip():
                        page_texts.append(text)
                finally:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
        finally:
            doc.close()
        return "\n".join(page_texts), "pdf-ocr"

    def extract_text(self, file_path: Path, label_crops=None) -> tuple[str, str]:
        suffix = file_path.suffix.lower()
        detected = detect_file_type(file_path)
        if suffix in PDF_EXTENSIONS or detected == "pdf":
            return self.extract_text_from_pdf(file_path, label_crops=label_crops)
        if suffix in IMAGE_EXTENSIONS or detected in {"jpeg", "png", "bmp", "tiff", "webp", "heif"}:
            return self.extract_text_from_image(file_path, label_crops=label_crops)
        raise OCRBackendError(f"Unsupported file type. extension={suffix or '<none>'}, detected={detected}.")

