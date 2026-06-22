from __future__ import annotations

from app.db.repository import Repository


class ContextEngine:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def apply_import_session_context(self, session_id: str) -> None:
        self.repo.clear_context_for_session(session_id)
        last_seen: dict[str, tuple[str, str]] = {}

        for photo in self.repo.photos_for_session(session_id):
            photo_id = photo["id"]
            direct_entities = self.repo.list_current_entities(photo_id)
            direct_by_type: dict[str, list[str]] = {"purchase_order": [], "sales_order": []}
            for entity in direct_entities:
                entity_type = entity["entity_type"]
                if entity_type in direct_by_type:
                    direct_by_type[entity_type].append(entity["value"])

            for entity_type in ("purchase_order", "sales_order"):
                values = direct_by_type[entity_type]
                if values:
                    last_seen[entity_type] = (values[0], photo_id)
                    continue
                if entity_type not in last_seen:
                    continue

                value, source_photo_id = last_seen[entity_type]
                if self.repo.normalized_entity_exists(photo_id, entity_type, value):
                    continue
                label = "PO" if entity_type == "purchase_order" else "SO"
                reason = (
                    f"Likely {label}: {value}; previous photo in the same import session "
                    f"had {label} {value} and no newer PO/SO marker appeared."
                )
                self.repo.add_context_assignment(
                    photo_id=photo_id,
                    entity_type=entity_type,
                    value=value,
                    confidence=0.72,
                    reason=reason,
                    source_photo_id=source_photo_id,
                    batch_id=session_id,
                )
                self.repo.update_searchable_text(photo_id)
