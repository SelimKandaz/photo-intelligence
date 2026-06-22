from __future__ import annotations

from app.db.repository import Repository


class FeedbackManager:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def add_feedback(
        self,
        photo_id: str,
        rating: str,
        note: str = "",
        query_id: str | None = None,
        query_fingerprint: str = "",
        result_rank: int | None = None,
    ) -> dict:
        feedback_id = self.repo.add_feedback(
            photo_id,
            rating,
            note,
            query_id,
            query_fingerprint=query_fingerprint,
            result_rank=result_rank,
        )
        return {"feedback_id": feedback_id, "photo_id": photo_id, "rating": rating}

    def add_correction(
        self,
        photo_id: str,
        entity_type: str,
        corrected_value: str,
        *,
        old_value: str = "",
        note: str = "",
        corrected_by: str = "",
    ) -> dict:
        correction_id = self.repo.add_correction(
            photo_id,
            entity_type,
            corrected_value,
            old_value=old_value,
            note=note,
            corrected_by=corrected_by,
        )
        return {
            "correction_id": correction_id,
            "photo_id": photo_id,
            "entity_type": entity_type,
            "corrected_value": corrected_value,
        }
