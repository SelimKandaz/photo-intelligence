from __future__ import annotations

import json

from .entity_extract import entity_terms, extract_entities, normalize_entities


CATEGORY_HINTS = {
    "photo_intelligence": ("photo_intelligence", "photo intelligence"),
    "iqreseller": ("iqreseller",),
    "email": ("email", "customer email", "mail"),
    "server_report": ("server report", "server_report", "report", "log"),
}


def _preview(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _format_evidence_lines(sources: list[dict[str, object]]) -> str:
    if not sources:
        return "- No sufficiently strong internal evidence was retrieved."
    return "\n".join(
        f"- {source['file_name']} / {source['chunk_id']} / {source['preview']}"
        for source in sources[:5]
    )


def _ensure_answer_format(answer_text: str, sources: list[dict[str, object]], confidence: str) -> str:
    required_headings = ("Summary:", "Evidence:", "Recommended action:", "Confidence:")
    if all(heading in answer_text for heading in required_headings):
        return answer_text
    summary_text = answer_text.strip() or "I could not find enough internal evidence."
    recommendation = (
        "Verify the cited chunks before taking action."
        if confidence != "low"
        else "Re-run ingestion or ask a narrower question using a PO, SO, serial number, or source category."
    )
    return (
        f"Summary:\n{summary_text}\n\n"
        f"Evidence:\n{_format_evidence_lines(sources)}\n\n"
        f"Recommended action:\n- {recommendation}\n\n"
        f"Confidence: {confidence}"
    )


class RAGEngine:
    def __init__(self, settings, ollama_client, qdrant_store) -> None:
        self.settings = settings
        self.ollama_client = ollama_client
        self.qdrant_store = qdrant_store

    @staticmethod
    def build_prompt(question: str, contexts: list[dict[str, object]]) -> str:
        context_sections = []
        for context in contexts:
            context_sections.append(
                "\n".join(
                    [
                        f"Source File: {context['file_name']}",
                        f"Source Category: {context['source_category']}",
                        f"Source Path: {context['source_path']}",
                        f"Chunk ID: {context['chunk_id']}",
                        f"Chunk Label: {context['chunk_label']}",
                        f"Text: {context['text']}",
                    ]
                )
            )
        joined_context = "\n\n".join(context_sections)
        return (
            "You are a private company operations assistant.\n"
            "Use ONLY the provided internal context.\n"
            "Do not use internet knowledge.\n"
            "Do not guess.\n"
            "If not enough evidence exists, say exactly: \"I could not find enough internal evidence.\"\n"
            "Always include sources in the answer.\n"
            "For PO, SO, and serial facts, cite the source file and chunk id.\n"
            "Separate facts from recommendations.\n"
            "Never claim certainty when sources are weak.\n"
            "Return this format exactly:\n"
            "Summary:\n"
            "Evidence:\n"
            "- source file / chunk id / relevant fact\n"
            "Recommended action:\n"
            "Confidence: high|medium|low\n\n"
            f"Question:\n{question}\n\n"
            f"Context:\n{joined_context}\n"
        )

    def rank_results(self, question: str, matches: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
        question_entities = extract_entities(question)
        question_terms = [term.lower() for term in entity_terms(question_entities)]
        question_text = question.lower()
        ranked: list[dict[str, object]] = []
        for match in matches:
            payload = match.get("payload", {})
            payload_entities = json.dumps(
                normalize_entities(payload.get("entities", payload.get("detected_entities")))
            ).lower()
            searchable_text = "\n".join(
                [
                    str(payload.get("text", "")),
                    str(payload.get("file_name", "")),
                    str(payload.get("relative_path", "")),
                    str(payload.get("source_category", "")),
                ]
            ).lower()
            score = float(match.get("score", 0.0))
            boost_reasons: list[str] = []
            for term in question_terms:
                if term and (term in searchable_text or term in payload_entities):
                    score += 0.18
                    boost_reasons.append(f"exact_entity:{term}")
            for category, hints in CATEGORY_HINTS.items():
                if any(hint in question_text for hint in hints) and payload.get("source_category") == category:
                    score += 0.12
                    boost_reasons.append(f"source_category:{category}")
            file_name = str(payload.get("file_name", "")).lower()
            relative_path = str(payload.get("relative_path", "")).lower()
            for term in set(question_text.replace("/", " ").split()):
                if len(term) < 4:
                    continue
                if term in file_name or term in relative_path:
                    score += 0.04
                    boost_reasons.append(f"path_or_filename:{term}")
            ranked.append(
                {
                    "score": score,
                    "base_score": float(match.get("score", 0.0)),
                    "boost_reason": ", ".join(boost_reasons) if boost_reasons else "vector_only",
                    "payload": payload,
                }
            )
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:limit]

    def ask(self, question: str, top_k: int | None = None) -> dict[str, object]:
        clean_question = question.strip()
        if not clean_question:
            raise ValueError("Question cannot be empty.")
        requested_k = top_k or self.settings.top_k
        query_vector = self.ollama_client.embed([clean_question])[0]
        raw_matches = self.qdrant_store.search(query_vector, max(requested_k * 4, 16))
        ranked = self.rank_results(clean_question, raw_matches, requested_k)
        sources = [
            {
                "file_name": item["payload"].get("file_name"),
                "source_category": item["payload"].get("source_category"),
                "source_path": item["payload"].get("source_path"),
                "chunk_id": item["payload"].get("chunk_id"),
                "score": round(float(item["score"]), 4),
                "boost_reason": item["boost_reason"],
                "preview": _preview(str(item["payload"].get("text", ""))),
            }
            for item in ranked
        ]
        if not ranked:
            answer = (
                "Summary:\nI could not find enough internal evidence.\n\n"
                "Evidence:\n- No indexed internal source matched the question.\n\n"
                "Recommended action:\n- Re-run ingestion or ask a narrower PO, SO, serial, email, or report question.\n\n"
                "Confidence: low"
            )
            return {"answer": answer, "sources": [], "confidence": "low", "warnings": ["No indexed context matched the question."]}

        top_score = ranked[0]["score"]
        strong_exact_match = ranked[0]["boost_reason"] != "vector_only"
        warnings: list[str] = []
        if top_score < 0.40 and not strong_exact_match:
            answer = (
                "Summary:\nI could not find enough internal evidence.\n\n"
                f"Evidence:\n{_format_evidence_lines(sources)}\n\n"
                "Recommended action:\n- Re-run ingestion or ask a narrower question using an exact PO, SO, serial number, or source category.\n\n"
                "Confidence: low"
            )
            return {
                "answer": answer,
                "sources": sources,
                "confidence": "low",
                "warnings": ["Retrieved context was too weak to support a grounded answer."],
            }

        contexts: list[dict[str, object]] = []
        consumed_chars = 0
        for item in ranked:
            text = str(item["payload"].get("text", ""))
            if consumed_chars + len(text) > self.settings.max_context_chars and contexts:
                break
            contexts.append(item["payload"])
            consumed_chars += len(text)
        prompt = self.build_prompt(clean_question, contexts)
        generated = self.ollama_client.generate(prompt, temperature=self.settings.answer_temperature)
        confidence = "high" if top_score >= 0.95 else "medium" if top_score >= 0.58 else "low"
        if confidence == "low":
            warnings.append("Sources were weak or indirect. Verify the evidence before acting.")
        answer = _ensure_answer_format(generated, sources, confidence)
        return {"answer": answer, "sources": sources, "confidence": confidence, "warnings": warnings}
