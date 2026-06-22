from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.entity_parser.inventory import InventoryEntityParser
from app.entity_parser.serials import normalize_exact_serial_candidate
from app.models.types import normalize_entity_value


@dataclass
class ParsedQuery:
    original: str
    entities: list[dict] = field(default_factory=list)
    normalized_terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "original": self.original,
            "entities": self.entities,
            "normalized_terms": self.normalized_terms,
        }


class QueryParser:
    def __init__(self) -> None:
        self.inventory_parser = InventoryEntityParser()

    def parse(self, query: str) -> ParsedQuery:
        parsed = ParsedQuery(original=query)
        parse_result = self.inventory_parser.parse(query, [])
        seen: set[tuple[str, str]] = set()

        def add(entity_type: str, value: str, source: str = "query") -> None:
            normalized = normalize_entity_value(value)
            if not normalized:
                return
            key = (entity_type, normalized)
            if key in seen:
                return
            seen.add(key)
            parsed.entities.append(
                {
                    "entity_type": entity_type,
                    "value": value,
                    "normalized_value": normalized,
                    "source": source,
                }
            )

        for entity in parse_result.entities:
            if entity.entity_type != "unknown_possible_identifier":
                add(entity.entity_type, entity.value, "parser")

        for token in re.findall(r"\b[A-Z0-9][A-Z0-9._-]{3,40}\b", query.upper()):
            serial = normalize_exact_serial_candidate(token)
            if serial:
                add("serial_number", serial, "serial_shape")

        for pattern, entity_type in (
            (r"\bPO[#:\s-]*([A-Z0-9-]{3,})\b", "purchase_order"),
            (r"\bSO[#:\s-]*([A-Z0-9-]{3,})\b", "sales_order"),
        ):
            for match in re.finditer(pattern, query, re.IGNORECASE):
                add(entity_type, match.group(1).strip(), "query_regex")

        for term in re.findall(r"[A-Z0-9][A-Z0-9._-]{1,40}", query.upper()):
            normalized = normalize_entity_value(term)
            if normalized and normalized not in parsed.normalized_terms:
                parsed.normalized_terms.append(normalized)
        return parsed

