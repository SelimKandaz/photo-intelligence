from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence


PO_PATTERN = re.compile(r"\b(?:P\.?\s*O\.?|PO|Purchase Order)\s*#?:?\s*(\d{3,})\b", re.IGNORECASE)
SO_PATTERN = re.compile(r"\b(?:S\.?\s*O\.?|SO|Sales Order)\s*#?:?\s*(\d{3,})\b", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
DATE_PATTERN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    r"January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4})\b",
    re.IGNORECASE,
)
LABELED_SERIAL_PATTERN = re.compile(
    r"\b(?:S/N|SN|Serial(?: Number)?|printed_serials?|barcode_or_qr_serials?|barcode_serial|printed_serial|serial_number)"
    r"\s*[:=#-]?\s*([A-Z0-9-]{4,})\b",
    re.IGNORECASE,
)
GENERIC_SERIAL_PATTERN = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)+\b|\b(?=[A-Z0-9-]{6,}\b)(?=.*[A-Z])(?=.*\d)[A-Z0-9-]+\b")
STATUS_TERMS = (
    "failed",
    "pass",
    "warning",
    "pass_with_warnings",
    "completed",
    "pending",
    "review",
    "mismatch",
    "conflict",
    "duplicate",
    "missing",
)
STATUS_PATTERN = re.compile(r"\b(" + "|".join(re.escape(term) for term in STATUS_TERMS) + r")\b", re.IGNORECASE)
LABELED_NAME_PATTERN = re.compile(r"^\s*(Customer|Vendor|Company|From|To):\s*([^\n<]+)", re.IGNORECASE | re.MULTILINE)
ENTITY_KEYS = (
    "po_numbers",
    "so_numbers",
    "serial_numbers",
    "emails",
    "dates",
    "customers",
    "vendors",
    "status_terms",
)


def empty_entities() -> dict[str, list[str]]:
    return {key: [] for key in ENTITY_KEYS}


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _normalize_serial(candidate: str) -> str | None:
    value = candidate.strip().upper().strip(".,;:()[]{}")
    if len(value) < 4:
        return None
    if value.startswith(("PO", "SO")) and value[2:].isdigit():
        return None
    if value in {term.upper() for term in STATUS_TERMS}:
        return None
    if "@" in value or "/" in value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    if not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
        return None
    return value


def _normalize_value_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values: Sequence[object] = [value]
    elif isinstance(value, Mapping):
        values = value.values()
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        values = [value]
    normalized: list[str] = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            normalized.append(text)
    return _unique(normalized)


def normalize_entities(value: object) -> dict[str, list[str]]:
    if value is None:
        return empty_entities()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return empty_entities()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return empty_entities()
        return normalize_entities(parsed)
    if not isinstance(value, Mapping):
        return empty_entities()

    normalized = empty_entities()
    for key in ENTITY_KEYS:
        normalized[key] = _normalize_value_list(value.get(key))
    return normalized


def entities_to_json(value: object) -> str:
    return json.dumps(normalize_entities(value), ensure_ascii=True)


def extract_entities(text: str) -> dict[str, list[str]]:
    po_numbers = [f"PO{match.group(1)}" for match in PO_PATTERN.finditer(text)]
    so_numbers = [f"SO{match.group(1)}" for match in SO_PATTERN.finditer(text)]
    emails = [match.group(0).lower() for match in EMAIL_PATTERN.finditer(text)]
    dates = [match.group(0) for match in DATE_PATTERN.finditer(text)]

    customers: list[str] = []
    vendors: list[str] = []
    for label, value in LABELED_NAME_PATTERN.findall(text):
        clean_value = value.strip()
        normalized_label = label.lower()
        if normalized_label in {"customer", "company", "to"}:
            customers.append(clean_value)
        else:
            vendors.append(clean_value)

    serial_candidates = [match.group(1) for match in LABELED_SERIAL_PATTERN.finditer(text)]
    serial_candidates.extend(match.group(0) for match in GENERIC_SERIAL_PATTERN.finditer(text))
    serial_numbers = [normalized for candidate in serial_candidates if (normalized := _normalize_serial(candidate))]
    status_terms = [match.group(1).lower() for match in STATUS_PATTERN.finditer(text)]

    return normalize_entities({
        "po_numbers": _unique(po_numbers),
        "so_numbers": _unique(so_numbers),
        "serial_numbers": _unique(serial_numbers),
        "emails": _unique(emails),
        "dates": _unique(dates),
        "customers": _unique(customers),
        "vendors": _unique(vendors),
        "status_terms": _unique(status_terms),
    })


def entity_terms(entities: dict[str, list[str]]) -> list[str]:
    terms: list[str] = []
    for values in entities.values():
        terms.extend(values)
    return _unique(terms)
