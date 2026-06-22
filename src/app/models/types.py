from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ENTITY_TYPES = {
    "serial_number",
    "printed_serial_number",
    "barcode_serial_number",
    "purchase_order",
    "sales_order",
    "part_number",
    "model_number",
    "service_tag",
    "tracking_number",
    "invoice_number",
    "vendor",
    "customer",
    "quantity",
    "date",
    "unknown_possible_identifier",
}

SOURCE_TYPES = {
    "printed_ocr",
    "barcode_qr",
    "context_guess",
    "user_corrected",
    "regex_guess",
    "ml_guess",
}


@dataclass(frozen=True)
class ExtractedEntity:
    entity_type: str
    value: str
    confidence: float
    source_type: str
    evidence_text: str = ""
    evidence_bbox: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_value(self) -> str:
        return normalize_entity_value(self.value)


@dataclass
class ExtractionOutput:
    raw_ocr_text: str
    raw_barcode_values: list[str]
    entities: list[ExtractedEntity]
    structured_text: str
    extractor_name: str
    extractor_version: str
    backend: str
    serial_mismatch: str = ""
    errors: list[str] = field(default_factory=list)


def normalize_entity_value(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def split_pipe(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split("|") if part.strip()]

