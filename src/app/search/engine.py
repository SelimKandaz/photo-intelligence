from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.db.repository import Repository
from app.models.types import normalize_entity_value
from app.search.query_parser import QueryParser


class SearchEngine:
    ENTITY_COMPATIBILITY = {
        "serial_number": {"serial_number", "printed_serial_number", "barcode_serial_number"},
        "printed_serial_number": {"printed_serial_number", "serial_number"},
        "barcode_serial_number": {"barcode_serial_number", "serial_number"},
        "purchase_order": {"purchase_order"},
        "sales_order": {"sales_order"},
        "part_number": {"part_number"},
        "model_number": {"model_number"},
        "service_tag": {"service_tag"},
        "tracking_number": {"tracking_number"},
        "invoice_number": {"invoice_number"},
    }

    WEIGHTS = {
        "printed_serial_number": 140,
        "serial_number": 120,
        "barcode_serial_number": 105,
        "purchase_order": 95,
        "sales_order": 95,
        "part_number": 85,
        "model_number": 80,
        "service_tag": 80,
        "tracking_number": 70,
        "invoice_number": 70,
    }

    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        self.parser = QueryParser()

    def search(self, query: str, limit: int = 50, mode: str = "fast") -> dict:
        mode = mode.lower().strip()
        if mode not in {"fast", "deep"}:
            raise ValueError("mode must be 'fast' or 'deep'")
        parsed = self.parser.parse(query)
        query_id = self.repo.record_search_query(query, parsed.as_dict())
        query_fingerprint = self._query_fingerprint(parsed.normalized_terms)
        results = []
        normalized_query = normalize_entity_value(query)
        terms = parsed.normalized_terms
        total_photo_count = self.repo.photo_count()
        exact_ids = self.repo.exact_candidate_photo_ids(parsed.entities, self.ENTITY_COMPATIBILITY)
        fts_ids = self.repo.fts_candidate_photo_ids(terms)
        candidate_ids = exact_ids | fts_ids
        warning = ""
        used_deep_scan = mode == "deep"
        if mode == "fast":
            photo_ids = candidate_ids
            if not candidate_ids:
                warning = (
                    "Fast search found no exact entity or FTS candidates. "
                    "Try Deep Search if you expect this item to exist."
                )
        else:
            photo_ids = None

        for photo in self.repo.search_corpus(photo_ids):
            score = 0.0
            reasons: list[str] = []
            match_sources: set[str] = set()
            if photo["id"] in exact_ids:
                match_sources.add("exact_entity")
            if photo["id"] in fts_ids:
                match_sources.add("fts")
            entity_blob = " ".join(
                [entity["normalized_value"] for entity in photo["entities"]]
                + [normalize_entity_value(ctx["value"]) for ctx in photo["context"]]
            )
            barcode_blob = normalize_entity_value(" ".join(photo.get("raw_barcode_values", [])))
            raw_source_blob = (
                photo.get("raw_ocr_text", "")
                + " "
                + " ".join(photo.get("raw_barcode_values", []))
                + " "
                + photo.get("path", "")
            )
            raw_blob = normalize_entity_value(
                raw_source_blob
            )

            for query_entity in parsed.entities:
                q_type = query_entity["entity_type"]
                q_value = query_entity["normalized_value"]
                compatible = self.ENTITY_COMPATIBILITY.get(q_type, {q_type})
                for entity in photo["entities"]:
                    if entity["entity_type"] not in compatible:
                        continue
                    if entity["normalized_value"] == q_value:
                        weight = self.WEIGHTS.get(entity["entity_type"], 60)
                        confidence = float(entity["confidence"] or 0.0)
                        score += weight * max(confidence, 0.35)
                        reasons.append(f"exact {entity['entity_type']} match: {entity['value']}")
                        match_sources.add("exact_entity")
                        if entity["entity_type"] == "barcode_serial_number":
                            match_sources.add("barcode")

                for ctx in photo["context"]:
                    if ctx["entity_type"] == q_type and normalize_entity_value(ctx["value"]) == q_value:
                        score += 55 * float(ctx["confidence"] or 0.0)
                        reasons.append(f"context {ctx['entity_type']} guess: {ctx['value']}")
                        match_sources.add("context")

            if normalized_query and normalized_query in entity_blob:
                score += 45
                reasons.append("query found in structured entities")
                match_sources.add("exact_entity")
            elif normalized_query and normalized_query in raw_blob:
                score += 25
                reasons.append("query found in OCR/barcode text")
                match_sources.add("raw_ocr")
                if normalized_query in barcode_blob:
                    match_sources.add("barcode")

            for term in terms:
                if len(term) < 3:
                    continue
                if term in entity_blob:
                    score += 18
                    reasons.append(f"term in entities: {term}")
                    match_sources.add("exact_entity")
                elif term in raw_blob:
                    score += 8
                    match_sources.add("raw_ocr")
                    if term in barcode_blob:
                        match_sources.add("barcode")
                else:
                    best_ratio = self._best_token_ratio(term, raw_source_blob)
                    if best_ratio >= 0.82:
                        score += 6
                        reasons.append(f"fuzzy OCR term: {term}")
                        match_sources.add("raw_ocr")

            learning = self.repo.learning_signal_score(query_fingerprint, photo["id"])
            if learning:
                score += learning
                if learning > 0:
                    reasons.append("learning boost from prior correct feedback")
                else:
                    reasons.append("learning penalty from prior wrong feedback")
                match_sources.add("learning_boost")

            if score <= 0:
                continue

            results.append(
                {
                    "query_id": query_id,
                    "query_fingerprint": query_fingerprint,
                    "photo_id": photo["id"],
                    "path": photo["path"],
                    "thumbnail_path": photo.get("thumbnail_path", ""),
                    "status": photo.get("status", ""),
                    "score": round(score, 2),
                    "reasons": reasons[:8],
                    "match_sources": sorted(match_sources),
                    "entities": photo["entities"],
                    "context": photo["context"],
                    "snippet": self._snippet(photo.get("raw_ocr_text", ""), query),
                }
            )

        results.sort(key=lambda item: (-item["score"], item["path"]))
        for idx, result in enumerate(results[:limit], start=1):
            result["rank"] = idx
            result["nearby"] = self.repo.nearby_photos(result["photo_id"], radius=2)
        return {
            "query_id": query_id,
            "query_fingerprint": query_fingerprint,
            "parsed": parsed.as_dict(),
            "candidate_count": len(candidate_ids),
            "total_photo_count": total_photo_count,
            "search_mode": mode,
            "used_deep_scan": used_deep_scan,
            "warning": warning,
            "results": results[:limit],
        }

    def _query_fingerprint(self, terms: list[str]) -> str:
        clean = sorted({term for term in terms if len(term) >= 3})
        return "|".join(clean[:20])

    def _best_token_ratio(self, term: str, raw_blob: str) -> float:
        tokens = re.findall(r"[A-Z0-9]{3,40}", raw_blob.upper())
        if not tokens:
            return 0.0
        return max(SequenceMatcher(None, term, token).ratio() for token in tokens[:2000])

    def _snippet(self, raw_text: str, query: str, width: int = 180) -> str:
        collapsed = re.sub(r"\s+", " ", raw_text or "").strip()
        if not collapsed:
            return ""
        idx = collapsed.upper().find(query.upper())
        if idx < 0:
            return collapsed[:width]
        start = max(0, idx - width // 2)
        end = min(len(collapsed), idx + len(query) + width // 2)
        return collapsed[start:end]
