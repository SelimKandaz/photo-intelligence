from __future__ import annotations

import time
from pathlib import Path

from app.barcode.scanner import BarcodeScanner
from app.entity_parser.inventory import InventoryEntityParser
from app.models.types import ExtractionOutput
from app.ocr.image_io import ImageLoader
from app.ocr.tesseract import OCRReader
from app.services.file_types import PDF_EXTENSIONS, detect_file_type


class PhotoExtractor:
    def __init__(
        self,
        extractor_name: str,
        extractor_version: str,
        backend: str = "audit",
    ) -> None:
        self.extractor_name = extractor_name
        self.extractor_version = extractor_version
        self.backend = backend.lower().strip()
        self.image_loader = ImageLoader()
        self.barcode_scanner = BarcodeScanner()
        self.ocr_reader = OCRReader(backend=self.backend)
        self.parser = InventoryEntityParser()

    def extract(self, file_path: Path, progress_callback=None) -> ExtractionOutput:
        raw_text = ""
        backend_used = "none"
        barcode_values: list[str] = []
        errors: list[str] = []
        detected = detect_file_type(file_path)
        is_pdf = file_path.suffix.lower() in PDF_EXTENSIONS or detected == "pdf"
        started = time.perf_counter()

        if not is_pdf:
            try:
                image = self.image_loader.open_image(file_path)
                if self.backend in {"audit", "auto"}:
                    barcode_values = self.barcode_scanner.decode_barcodes_deep(
                        image,
                        progress_callback=progress_callback,
                    )
                    backend_used = "barcode-deep"
                else:
                    barcode_values = self.barcode_scanner.decode_barcodes_optional(image)
                    backend_used = "barcode-fast"
            except Exception as exc:
                errors.append(f"barcode/image pass failed: {exc}")

        if self.backend == "barcode":
            backend_used = backend_used or "barcode-only"
        else:
            try:
                text, text_backend = self.ocr_reader.extract_text(
                    file_path,
                    label_crops=self.barcode_scanner.detect_label_crops,
                )
                raw_text = text
                backend_used = f"{backend_used}+{text_backend}" if backend_used != "none" else text_backend
            except Exception as exc:
                raw_text = f"[OCR AUDIT ERROR] {exc}"
                errors.append(str(exc))
                backend_used = f"{backend_used}+ocr-error" if backend_used != "none" else "ocr-error"

        parsed = self.parser.parse(raw_text, barcode_values)
        duration_ms = int((time.perf_counter() - started) * 1000)
        metadata_entity_note = f"duration_ms={duration_ms}"
        if parsed.structured_text:
            structured_text = parsed.structured_text + "\n" + metadata_entity_note
        else:
            structured_text = metadata_entity_note

        return ExtractionOutput(
            raw_ocr_text=raw_text,
            raw_barcode_values=barcode_values,
            entities=parsed.entities,
            structured_text=structured_text,
            extractor_name=self.extractor_name,
            extractor_version=self.extractor_version,
            backend=backend_used,
            serial_mismatch=parsed.serial_mismatch,
            errors=errors,
        )

