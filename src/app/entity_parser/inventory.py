from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from app.entity_parser.serials import (
    anchored_serials_from_ocr_text,
    barcode_serials_from_values,
    candidate_after_serial_tag,
    clean_inventory_token,
    normalize_mt26_serial,
    normalize_text,
    serial_from_barcode_value,
)
from app.models.types import ExtractedEntity, normalize_entity_value


@dataclass
class InventoryParseResult:
    fields: dict[str, str]
    entities: list[ExtractedEntity]
    serial_mismatch: str
    structured_text: str


class InventoryEntityParser:
    def parse(self, raw_text: str, barcode_values: Sequence[str] | None = None) -> InventoryParseResult:
        barcode_values = list(barcode_values or [])
        printed_serials: list[str] = []
        barcode_serials: list[str] = []
        clean_serials: list[str] = []
        ocr_candidates: list[str] = []
        models: list[str] = []
        parts: list[str] = []
        eans: list[str] = []
        entities: list[ExtractedEntity] = []
        seen_entities: set[tuple[str, str, str]] = set()

        def add_unique(items: list[str], value: str | None) -> None:
            if value and value not in items:
                items.append(value)

        def add_entity(
            entity_type: str,
            value: str | None,
            confidence: float,
            source_type: str,
            evidence_text: str = "",
            metadata: dict | None = None,
        ) -> None:
            if not value:
                return
            key = (entity_type, normalize_entity_value(value), source_type)
            if key in seen_entities:
                return
            seen_entities.add(key)
            entities.append(
                ExtractedEntity(
                    entity_type=entity_type,
                    value=value,
                    confidence=confidence,
                    source_type=source_type,
                    evidence_text=evidence_text,
                    metadata=metadata or {},
                )
            )

        for value in barcode_values:
            cleaned = clean_inventory_token(value)
            barcode_serial = serial_from_barcode_value(cleaned)
            add_unique(barcode_serials, barcode_serial)

            if barcode_serial:
                add_entity("barcode_serial_number", barcode_serial, 0.99, "barcode_qr", value)
                add_entity("serial_number", barcode_serial, 0.90, "barcode_qr", value)

            if re.fullmatch(r"\d{13}", cleaned):
                add_unique(eans, cleaned)
                add_entity(
                    "unknown_possible_identifier",
                    cleaned,
                    0.85,
                    "barcode_qr",
                    value,
                    {"kind": "ean"},
                )

            if cleaned in {"MMA4Z00NS400", "MMA4Z00-NS400"} or ("MMA4Z00" in cleaned and "NS400" in cleaned):
                add_unique(models, "MMA4Z00")
                add_unique(parts, "MMA4Z00-NS400")

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        for serial in anchored_serials_from_ocr_text(raw_text):
            add_unique(printed_serials, serial)
            evidence = self._line_with_value(lines, serial) or "S/N anchored OCR"
            add_entity("printed_serial_number", serial, 0.96, "printed_ocr", evidence)
            add_entity("serial_number", serial, 0.96, "printed_ocr", evidence)

        for serial in printed_serials:
            add_unique(clean_serials, serial)
        for serial in barcode_serials:
            add_unique(clean_serials, serial)

        for line in lines:
            candidate = candidate_after_serial_tag(line)
            serial = normalize_mt26_serial(candidate or "")
            if serial and serial not in clean_serials:
                add_unique(ocr_candidates, serial)
                add_entity(
                    "unknown_possible_identifier",
                    serial,
                    0.35,
                    "regex_guess",
                    line,
                    {"kind": "ocr_serial_candidate", "review": True},
                )

            for m in re.finditer(r"M\s*[T1I]?\s*2\s*6\s*[A-Z0-9\s]{4,18}", line, re.IGNORECASE):
                serial = normalize_mt26_serial(m.group(0))
                if serial and serial not in clean_serials:
                    add_unique(ocr_candidates, serial)
                    add_entity(
                        "unknown_possible_identifier",
                        serial,
                        0.30,
                        "regex_guess",
                        line,
                        {"kind": "ocr_serial_candidate", "review": True},
                    )

            compact = clean_inventory_token(line)
            if "MMA" in compact or "MMV" in compact or "MMAA" in compact:
                if re.search(r"MM[A-Z0-9]{2}Z[O0D]{2}", compact) or "MMA4Z00" in compact or "MMAAZ00" in compact:
                    add_unique(models, "MMA4Z00")
                if "NS400" in compact or "NS40D" in compact or "N5400" in compact or "NS4OD" in compact:
                    add_unique(parts, "MMA4Z00-NS400")

            pn = re.search(r"(?:P\s*[/\\]?\s*N|PIN|PN)\s*[:;]?\s*([A-Z0-9 ._-]{6,35})", line, re.IGNORECASE)
            if pn:
                token = clean_inventory_token(pn.group(1))
                if "MMA" in token or "MMV" in token:
                    if "NS" in token or "N5" in token:
                        add_unique(parts, "MMA4Z00-NS400")
                        add_entity("part_number", "MMA4Z00-NS400", 0.82, "printed_ocr", line)
                else:
                    add_entity("part_number", token[:35], 0.74, "printed_ocr", line)

            self._extract_business_entities_from_line(line, add_entity)

        compact_all = normalize_text(raw_text)
        if "MMA4Z00" in compact_all or "MMAAZ00" in compact_all or "MMVA4Z00" in compact_all:
            add_unique(models, "MMA4Z00")
        if "MMA4Z00NS400" in compact_all or "MMAAZ00NS400" in compact_all or "MMAAZD0NS40" in compact_all:
            add_unique(parts, "MMA4Z00-NS400")

        digit_blob = re.sub(r"\D+", "", raw_text)
        for m in re.finditer(r"7290110\d{6}", digit_blob):
            ean = m.group(0)[:13]
            add_unique(eans, ean)
            add_entity(
                "unknown_possible_identifier",
                ean,
                0.70,
                "regex_guess",
                raw_text[:240],
                {"kind": "ean"},
            )

        for value in models:
            add_entity("model_number", value, 0.88, "regex_guess", "model pattern")
        for value in parts:
            add_entity("part_number", value, 0.88, "regex_guess", "part pattern")

        self._add_unknown_identifiers(raw_text, {e.normalized_value for e in entities}, add_entity)

        mismatch = self._serial_audit(printed_serials, barcode_serials)
        if mismatch.startswith("MISMATCH"):
            for entity in entities:
                if entity.entity_type == "serial_number" and entity.source_type == "barcode_qr":
                    entity.metadata["review_reason"] = mismatch

        structured_lines = self._structured_lines(
            models,
            parts,
            printed_serials,
            barcode_serials,
            mismatch,
            clean_serials,
            ocr_candidates,
            eans,
            barcode_values,
        )
        fields = {
            "structured_text": "\n".join(structured_lines),
            "serial_numbers": " | ".join(clean_serials),
            "printed_serial_numbers": " | ".join(printed_serials),
            "barcode_serial_numbers": " | ".join(barcode_serials),
            "serial_mismatch": mismatch,
            "serial_candidates_ocr": " | ".join(ocr_candidates),
            "part_numbers": " | ".join(parts),
            "model_numbers": " | ".join(models),
            "ean_numbers": " | ".join(eans),
            "barcode_values": " | ".join(barcode_values),
        }
        return InventoryParseResult(fields, entities, mismatch, fields["structured_text"])

    def _extract_business_entities_from_line(self, line: str, add_entity) -> None:
        patterns = [
            ("purchase_order", r"\bP\s*O(?:\s*#|\s*NO\.?|\s*NUMBER|[:\s-])*([A-Z0-9][A-Z0-9-]{2,})"),
            ("purchase_order", r"\bPO[#:\s-]*([0-9]{3,})\b"),
            ("sales_order", r"\bS\s*O(?:\s*#|\s*NO\.?|\s*NUMBER|[:\s-])*([A-Z0-9][A-Z0-9-]{2,})"),
            ("sales_order", r"\bSO[#:\s-]*([0-9]{3,})\b"),
            ("model_number", r"\bMODEL(?:\s*#|[:\s-])*([A-Z0-9][A-Z0-9_.-]{2,})"),
            ("service_tag", r"\bSERVICE\s*TAG(?:\s*#|[:\s-])*([A-Z0-9][A-Z0-9-]{3,})"),
            ("invoice_number", r"\bINV(?:OICE)?(?:\s*#|[:\s-])*([A-Z0-9][A-Z0-9-]{2,})"),
            ("quantity", r"\bQTY(?:\.|:|\s)*([0-9]{1,6})\b"),
            ("vendor", r"\bVENDOR(?:\s*#|[:\s-])*([A-Z0-9 &._-]{2,40})"),
            ("customer", r"\bCUSTOMER(?:\s*#|[:\s-])*([A-Z0-9 &._-]{2,40})"),
            ("date", r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
            ("tracking_number", r"\b(1Z[0-9A-Z]{10,22})\b"),
        ]
        for entity_type, pattern in patterns:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                value = clean_inventory_token(match.group(1))
                if entity_type in {"vendor", "customer"}:
                    value = re.sub(r"\s+", " ", match.group(1)).strip(" :-")
                if value:
                    add_entity(entity_type, value, 0.70, "regex_guess", line)

    def _add_unknown_identifiers(self, raw_text: str, known: set[str], add_entity) -> None:
        stop = {
            "SERIAL",
            "MODEL",
            "NVIDIA",
            "MELLANOX",
            "INVOICE",
            "CUSTOMER",
            "VENDOR",
            "WARNING",
            "CLASS",
            "MADE",
        }
        added = 0
        for token in re.findall(r"\b[A-Z0-9][A-Z0-9._-]{5,32}\b", raw_text.upper()):
            normalized = normalize_entity_value(token)
            if normalized in known or token in stop:
                continue
            if not any(ch.isdigit() for ch in token):
                continue
            if not any(ch.isalpha() for ch in token):
                continue
            add_entity(
                "unknown_possible_identifier",
                token.strip("._-"),
                0.22,
                "regex_guess",
                "identifier-shaped token",
                {"kind": "unclassified"},
            )
            added += 1
            if added >= 20:
                break

    def _serial_audit(self, printed_serials: Sequence[str], barcode_serials: Sequence[str]) -> str:
        if printed_serials and barcode_serials:
            printed_set = set(printed_serials)
            barcode_set = set(barcode_serials)
            if printed_set != barcode_set:
                missing_from_barcode = sorted(printed_set - barcode_set)
                barcode_not_printed = sorted(barcode_set - printed_set)
                parts_msg = []
                if missing_from_barcode:
                    parts_msg.append("printed_not_in_barcode=" + ";".join(missing_from_barcode))
                if barcode_not_printed:
                    parts_msg.append("barcode_not_printed=" + ";".join(barcode_not_printed))
                return "MISMATCH: " + " | ".join(parts_msg)
            return "MATCH"
        if printed_serials and not barcode_serials:
            return "PRINTED_ONLY"
        if barcode_serials and not printed_serials:
            return "BARCODE_ONLY"
        return ""

    def _structured_lines(
        self,
        models: Sequence[str],
        parts: Sequence[str],
        printed_serials: Sequence[str],
        barcode_serials: Sequence[str],
        mismatch: str,
        clean_serials: Sequence[str],
        ocr_candidates: Sequence[str],
        eans: Sequence[str],
        barcode_values: Sequence[str],
    ) -> list[str]:
        structured_lines: list[str] = []
        for value in models:
            structured_lines.append(f"Model: {value}")
        for value in parts:
            structured_lines.append(f"P/N: {value}")
        for value in printed_serials:
            structured_lines.append(f"Printed S/N: {value}")
        for value in barcode_serials:
            structured_lines.append(f"Barcode S/N: {value}")
        if mismatch:
            structured_lines.append(f"Serial audit: {mismatch}")
        for value in clean_serials:
            structured_lines.append(f"S/N: {value}")
        for value in ocr_candidates:
            structured_lines.append(f"OCR-ONLY S/N CANDIDATE - REVIEW: {value}")
        for value in eans:
            structured_lines.append(f"EAN: {value}")
        for value in barcode_values:
            if value not in eans and value not in clean_serials:
                structured_lines.append(f"Barcode: {value}")
        return structured_lines

    def _line_with_value(self, lines: Sequence[str], value: str) -> str:
        normalized_value = normalize_entity_value(value)
        for line in lines:
            if normalized_value in normalize_entity_value(line):
                return line
        return ""

