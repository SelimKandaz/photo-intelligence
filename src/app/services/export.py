from __future__ import annotations

import csv
import io
from typing import Any

from app.db.repository import Repository


def serial_rows_csv(repo: Repository) -> str:
    serial_map: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_row(
        *,
        serial: str,
        source: str,
        confidence: str,
        path: str,
        photo_id: str,
        file_name: str,
        captured_at: str,
        import_session_id: str,
        review_status: str,
        models: list[str],
        parts: list[str],
        eans: list[str],
        printed: list[str],
        barcode: list[str],
        mismatch: str,
    ) -> None:
        key = (serial, source, photo_id)
        entry = serial_map.setdefault(
            key,
            {
                "serial_number": serial,
                "photo_id": photo_id,
                "file_name": file_name,
                "captured_at": captured_at,
                "import_session_id": import_session_id,
                "review_status": review_status,
                "serial_source": source,
                "confidence": confidence,
                "model_number": models[0] if models else "",
                "part_number": parts[0] if parts else "",
                "ean_number": eans[0] if eans else "",
                "serial_mismatch": mismatch,
                "printed_serials_in_image": set(),
                "barcode_serials_in_image": set(),
                "source_paths": [],
            },
        )
        entry["printed_serials_in_image"].update(printed)
        entry["barcode_serials_in_image"].update(barcode)
        if path and path not in entry["source_paths"]:
            entry["source_paths"].append(path)
        if not entry["model_number"] and models:
            entry["model_number"] = models[0]
        if not entry["part_number"] and parts:
            entry["part_number"] = parts[0]
        if mismatch and mismatch != "MATCH":
            entry["serial_mismatch"] = mismatch

    for row in repo.serial_export_source_rows():
        path = row["path"]
        photo_id = row["photo_id"]
        file_name = row["file_name"]
        captured_at = row["captured_at"]
        import_session_id = row["import_session_id"]
        review_status = row["review_status"]
        models = row["model_numbers"]
        parts = row["part_numbers"]
        eans = row["ean_numbers"]
        printed = row["printed_serial_numbers"]
        barcode = row["barcode_serial_numbers"]
        mismatch = row["serial_mismatch"]

        for serial in printed:
            add_row(
                serial=serial,
                photo_id=photo_id,
                file_name=file_name,
                captured_at=captured_at,
                import_session_id=import_session_id,
                review_status=review_status,
                source="printed-s/n",
                confidence="high",
                path=path,
                models=models,
                parts=parts,
                eans=eans,
                printed=printed,
                barcode=barcode,
                mismatch=mismatch,
            )

        for serial in barcode:
            if serial in printed:
                source = "barcode-confirmed-same-as-printed"
                confidence = "high"
            elif printed:
                source = "barcode-only-mismatch-review"
                confidence = "review"
            else:
                source = "barcode-only-no-printed-s/n-read"
                confidence = "medium"
            add_row(
                serial=serial,
                photo_id=photo_id,
                file_name=file_name,
                captured_at=captured_at,
                import_session_id=import_session_id,
                review_status=review_status,
                source=source,
                confidence=confidence,
                path=path,
                models=models,
                parts=parts,
                eans=eans,
                printed=printed,
                barcode=barcode,
                mismatch=mismatch,
            )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "photo_id",
            "file_name",
            "captured_at",
            "import_session_id",
            "review_status",
            "serial_number",
            "serial_source",
            "confidence",
            "model_number",
            "part_number",
            "ean_number",
            "serial_mismatch",
            "printed_serials_in_image",
            "barcode_serials_in_image",
            "source_paths",
        ]
    )
    for key in sorted(serial_map):
        entry = serial_map[key]
        writer.writerow(
            [
                entry["photo_id"],
                entry["file_name"],
                entry["captured_at"],
                entry["import_session_id"],
                entry["review_status"],
                entry["serial_number"],
                entry["serial_source"],
                entry["confidence"],
                entry["model_number"],
                entry["part_number"],
                entry["ean_number"],
                entry["serial_mismatch"],
                " | ".join(sorted(entry["printed_serials_in_image"])),
                " | ".join(sorted(entry["barcode_serials_in_image"])),
                " | ".join(entry["source_paths"]),
            ]
        )
    return output.getvalue()


def all_entities_csv(repo: Repository) -> str:
    rows = repo.conn.execute(
        """
        SELECT
            p.id AS photo_id,
            p.file_name,
            p.path,
            p.original_path,
            p.import_session_id,
            p.captured_at,
            e.entity_type,
            e.value,
            e.confidence,
            e.source_type,
            e.evidence_text,
            e.extractor_name,
            e.extractor_version,
            e.created_at
        FROM entities e
        JOIN photos p ON p.id = e.photo_id
        WHERE e.is_current = 1
        ORDER BY p.file_name, e.entity_type, e.value
        """
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "photo_id",
            "file_name",
            "path",
            "original_path",
            "import_session_id",
            "captured_at",
            "entity_type",
            "value",
            "confidence",
            "source_type",
            "evidence_text",
            "extractor_name",
            "extractor_version",
            "created_at",
        ]
    )
    for row in rows:
        writer.writerow([row[key] or "" for key in row.keys()])
    return output.getvalue()


def review_queue_csv(repo: Repository) -> str:
    rows = repo.conn.execute(
        """
        SELECT
            rq.id,
            rq.photo_id,
            p.file_name,
            p.path,
            rq.reason,
            rq.status,
            rq.priority,
            rq.created_at,
            rq.resolved_at
        FROM review_queue rq
        JOIN photos p ON p.id = rq.photo_id
        ORDER BY rq.status, rq.priority DESC, rq.created_at
        """
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "review_id",
            "photo_id",
            "file_name",
            "path",
            "reason",
            "status",
            "priority",
            "created_at",
            "resolved_at",
        ]
    )
    for row in rows:
        writer.writerow([row[key] or "" for key in row.keys()])
    return output.getvalue()


# ---------------------------------------------------------------------------
# Simple Serial Harvest export
# ---------------------------------------------------------------------------
# This is intentionally separate from serial_rows_csv().  The detailed export
# is for audit/review.  Serial Harvest is for daily inventory work: one unique
# serial value per row, with just enough photo/context traceability to verify it.

from datetime import date, datetime


SOURCE_RANK = {"ocr": 1, "barcode": 2, "barcode+ocr": 3}
CONFIDENCE_RANK = {"review": 1, "medium": 2, "high": 3}


def _serial_key(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _parse_filter_date(value: str | None) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    cleaned = raw.replace("Z", "").replace("T", " ").split(".")[0].strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        return None


def _row_effective_date(row: dict[str, Any]) -> date | None:
    captured = _parse_filter_date(str(row.get("captured_at") or ""))
    if captured:
        return captured
    modified_time = row.get("modified_time")
    if modified_time not in (None, ""):
        try:
            return datetime.fromtimestamp(float(modified_time)).date()
        except Exception:
            pass
    created_at = _parse_filter_date(str(row.get("created_at") or ""))
    return created_at


def _date_source(row: dict[str, Any]) -> str:
    if _parse_filter_date(str(row.get("captured_at") or "")):
        return "exif"
    if row.get("modified_time") not in (None, ""):
        return "file_time"
    if _parse_filter_date(str(row.get("created_at") or "")):
        return "db_created_at"
    return "unknown"


def _safe_int(value: Any, default: int = 999999) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def _context_label(po_values: list[str] | None, so_values: list[str] | None) -> str:
    parts: list[str] = []
    po = [str(v) for v in po_values or [] if str(v).strip()]
    so = [str(v) for v in so_values or [] if str(v).strip()]
    if po:
        parts.append("PO " + "/".join(po[:2]))
    if so:
        parts.append("SO " + "/".join(so[:2]))
    return " | ".join(parts)


def _row_context_label(row: dict[str, Any]) -> str:
    return _context_label(list(row.get("purchase_orders") or []), list(row.get("sales_orders") or []))


def _sort_photo_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("import_session_id") or ""),
            _safe_int(row.get("sequence_index")),
            row.get("modified_time") or 0,
            str(row.get("file_name") or ""),
        ),
    )


def _infer_nearby_context(
    row: dict[str, Any],
    all_rows: list[dict[str, Any]],
    *,
    context_window: int,
) -> tuple[str, str]:
    direct = _row_context_label(row)
    if direct:
        return direct, "direct_or_propagated"

    seq = _safe_int(row.get("sequence_index"), default=-999999)
    session_id = str(row.get("import_session_id") or "")
    if seq < 0 or not session_id:
        return "", "none"

    candidates: list[tuple[int, int, str]] = []
    for other in all_rows:
        if str(other.get("import_session_id") or "") != session_id:
            continue
        label = _row_context_label(other)
        if not label:
            continue
        other_seq = _safe_int(other.get("sequence_index"), default=-999999)
        if other_seq < 0:
            continue
        gap = abs(other_seq - seq)
        if gap <= context_window:
            # Prefer nearer context.  If distance ties, prefer previous photos
            # because a PO/SO cover sheet often comes before the item photos.
            direction_rank = 0 if other_seq <= seq else 1
            candidates.append((gap, direction_rank, label))
    if not candidates:
        return "", "none"
    candidates.sort()
    return candidates[0][2], f"nearby_photo_within_{context_window}"


def _is_better_source(new_source: str, new_confidence: str, old_source: str, old_confidence: str) -> bool:
    new_tuple = (SOURCE_RANK.get(new_source, 0), CONFIDENCE_RANK.get(new_confidence, 0))
    old_tuple = (SOURCE_RANK.get(old_source, 0), CONFIDENCE_RANK.get(old_confidence, 0))
    return new_tuple > old_tuple


def serial_harvest_rows(
    repo: Repository,
    *,
    session_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    target_type: str = "any",
    gap_threshold: int = 10,
    context_window: int = 8,
) -> list[dict[str, Any]]:
    """Return one deduplicated row per serial number.

    Deduplication is by normalized serial value.  The output preserves
    traceability by collecting all photo names/paths where the serial appeared.

    Smart grouping is intentionally conservative:
    - use import-session order first, not download date
    - carry PO/SO context from current/nearby photos when possible
    - start a new group when PO/SO context changes or serial photos are far apart
    """
    start_date = _parse_filter_date(date_from)
    end_date = _parse_filter_date(date_to)
    target = (target_type or "any").strip().lower()
    gap_threshold = max(1, int(gap_threshold or 10))
    context_window = max(0, int(context_window or 0))

    source_rows = _sort_photo_rows(repo.serial_export_source_rows())
    rows_by_serial: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []

    def include_row(photo_row: dict[str, Any]) -> bool:
        if session_id and str(photo_row.get("import_session_id") or "") != session_id:
            return False
        effective = _row_effective_date(photo_row)
        if start_date and effective and effective < start_date:
            return False
        if end_date and effective and effective > end_date:
            return False
        # RAM-like / SSD-like are deliberately conservative for now.  Without
        # reliable object recognition, filtering by item type can hide valid serials.
        if target not in {"any", "ram", "ram-like", "ssd", "ssd-like"}:
            return False
        return True

    def add_candidate(photo_row: dict[str, Any], serial: str, source: str, confidence: str) -> None:
        key = _serial_key(serial)
        if len(key) < 5:
            return
        file_name = str(photo_row.get("file_name") or "")
        path = str(photo_row.get("path") or "")
        captured_at = str(photo_row.get("captured_at") or "")
        import_session_id = str(photo_row.get("import_session_id") or "")
        sequence_index = _safe_int(photo_row.get("sequence_index"))
        effective_date = _row_effective_date(photo_row)
        context_label, context_source = _infer_nearby_context(photo_row, source_rows, context_window=context_window)

        if key not in rows_by_serial:
            rows_by_serial[key] = {
                "serial_number": key,
                "first_photo": file_name,
                "photo_names": [],
                "photo_paths": [],
                "source": source,
                "confidence": confidence,
                "duplicate_count": 0,
                "photo_count": 0,
                "first_captured_at": captured_at,
                "first_effective_date": effective_date.isoformat() if effective_date else "",
                "date_source": _date_source(photo_row),
                "import_session_id": import_session_id,
                "first_sequence_index": sequence_index,
                "sequence_indices": [],
                "context_label": context_label,
                "context_source": context_source,
                "group_id": "",
                "group_label": "",
                "group_reason": "",
                "gap_from_previous": "",
            }
            ordered_keys.append(key)
        entry = rows_by_serial[key]
        entry["duplicate_count"] += 1
        if file_name and file_name not in entry["photo_names"]:
            entry["photo_names"].append(file_name)
            entry["photo_count"] = len(entry["photo_names"])
        if path and path not in entry["photo_paths"]:
            entry["photo_paths"].append(path)
        if sequence_index not in entry["sequence_indices"]:
            entry["sequence_indices"].append(sequence_index)
            entry["sequence_indices"].sort()
        if sequence_index < int(entry.get("first_sequence_index") or 999999):
            entry["first_sequence_index"] = sequence_index
            entry["first_photo"] = file_name
        if context_label and not entry.get("context_label"):
            entry["context_label"] = context_label
            entry["context_source"] = context_source
        if _is_better_source(source, confidence, entry["source"], entry["confidence"]):
            entry["source"] = source
            entry["confidence"] = confidence

    for row in source_rows:
        if not include_row(row):
            continue
        printed = list(row.get("printed_serial_numbers") or [])
        barcode = list(row.get("barcode_serial_numbers") or [])
        printed_keys = {_serial_key(value) for value in printed if _serial_key(value)}
        barcode_keys = {_serial_key(value) for value in barcode if _serial_key(value)}

        for serial in barcode:
            key = _serial_key(serial)
            if not key:
                continue
            if key in printed_keys:
                add_candidate(row, serial, "barcode+ocr", "high")
            elif printed:
                add_candidate(row, serial, "barcode", "review")
            else:
                add_candidate(row, serial, "barcode", "high")

        for serial in printed:
            key = _serial_key(serial)
            if not key or key in barcode_keys:
                continue
            if barcode:
                add_candidate(row, serial, "ocr", "review")
            else:
                add_candidate(row, serial, "ocr", "medium")

    final_rows: list[dict[str, Any]] = []
    for key in ordered_keys:
        entry = dict(rows_by_serial[key])
        entry["photo_names"] = "; ".join(entry["photo_names"])
        entry["photo_paths"] = "; ".join(entry["photo_paths"])
        entry["sequence_indices"] = "; ".join(str(i) for i in entry["sequence_indices"] if i != 999999)
        final_rows.append(entry)

    final_rows.sort(
        key=lambda row: (
            str(row.get("import_session_id") or ""),
            int(row.get("first_sequence_index") or 999999),
            str(row.get("serial_number") or ""),
        )
    )
    _assign_serial_groups(final_rows, gap_threshold=gap_threshold)
    return final_rows


def _assign_serial_groups(rows: list[dict[str, Any]], *, gap_threshold: int) -> None:
    group_id = 0
    previous_session = ""
    previous_seq: int | None = None
    previous_context = ""

    for row in rows:
        session = str(row.get("import_session_id") or "")
        seq = int(row.get("first_sequence_index") or 999999)
        context = str(row.get("context_label") or "")
        new_group_reason = "first"

        if group_id == 0:
            group_id = 1
        elif session != previous_session:
            group_id += 1
            new_group_reason = "new_import_session"
        elif context and previous_context and context != previous_context:
            group_id += 1
            new_group_reason = "po_so_context_changed"
        elif previous_seq is not None and seq != 999999 and previous_seq != 999999 and seq - previous_seq > gap_threshold:
            group_id += 1
            new_group_reason = f"photo_gap>{gap_threshold}"
        else:
            new_group_reason = "same_group"

        label_parts = [f"Group {group_id}"]
        if context:
            label_parts.append(context)
        row["group_id"] = str(group_id)
        row["group_label"] = " - ".join(label_parts)
        row["group_reason"] = new_group_reason
        row["gap_from_previous"] = "" if previous_seq is None or seq == 999999 or previous_seq == 999999 else str(seq - previous_seq)

        previous_session = session
        previous_seq = seq
        if context:
            previous_context = context


def serial_harvest_txt(rows: list[dict[str, Any]], *, grouped: bool = True) -> str:
    lines: list[str] = []
    previous_group = None
    for row in rows:
        group = row.get("group_id") if grouped else None
        if grouped and previous_group is not None and group != previous_group:
            lines.append("")
        lines.append(str(row["serial_number"]))
        previous_group = group
    text = "\n".join(lines)
    return text + ("\n" if text else "")


def serial_harvest_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "group_id",
            "group_label",
            "group_reason",
            "serial_number",
            "first_photo",
            "photo_names",
            "source",
            "confidence",
            "duplicate_count",
            "photo_count",
            "first_sequence_index",
            "sequence_indices",
            "gap_from_previous",
            "context_label",
            "context_source",
            "first_effective_date",
            "date_source",
            "photo_paths",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("group_id", ""),
                row.get("group_label", ""),
                row.get("group_reason", ""),
                row.get("serial_number", ""),
                row.get("first_photo", ""),
                row.get("photo_names", ""),
                row.get("source", ""),
                row.get("confidence", ""),
                row.get("duplicate_count", 0),
                row.get("photo_count", 0),
                row.get("first_sequence_index", ""),
                row.get("sequence_indices", ""),
                row.get("gap_from_previous", ""),
                row.get("context_label", ""),
                row.get("context_source", ""),
                row.get("first_effective_date", ""),
                row.get("date_source", ""),
                row.get("photo_paths", ""),
            ]
        )
    return output.getvalue()


def serial_harvest_review_csv(rows: list[dict[str, Any]]) -> str:
    review_rows = [row for row in rows if row.get("confidence") == "review"]
    return serial_harvest_csv(review_rows)


def serial_harvest_conflicts_csv(repo: Repository, *, session_id: str | None = None) -> str:
    """Export printed-vs-barcode conflicts by photo without deciding which is correct."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "photo_name",
            "sequence_index",
            "context_label",
            "printed_serials",
            "barcode_or_qr_serials",
            "all_serials",
            "mismatch_note",
            "captured_at",
            "import_session_id",
            "photo_path",
        ]
    )
    rows = _sort_photo_rows(repo.serial_export_source_rows())
    for row in rows:
        if session_id and str(row.get("import_session_id") or "") != session_id:
            continue
        printed = sorted({_serial_key(v) for v in row.get("printed_serial_numbers") or [] if _serial_key(v)})
        barcode = sorted({_serial_key(v) for v in row.get("barcode_serial_numbers") or [] if _serial_key(v)})
        if not printed or not barcode or set(printed) == set(barcode):
            continue
        context_label, _ = _infer_nearby_context(row, rows, context_window=8)
        writer.writerow(
            [
                row.get("file_name", ""),
                row.get("sequence_index", ""),
                context_label,
                " | ".join(printed),
                " | ".join(barcode),
                " | ".join(sorted(set(printed) | set(barcode))),
                row.get("serial_mismatch", "MISMATCH"),
                row.get("captured_at", ""),
                row.get("import_session_id", ""),
                row.get("path", ""),
            ]
        )
    return output.getvalue()
