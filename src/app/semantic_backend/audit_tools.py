from __future__ import annotations

import re

from .db import Database


FOLLOWUP_PHRASES = (
    "please update",
    "any update",
    "following up",
    "status",
    "eta",
    "waiting",
    "haven't heard",
    "could you confirm",
)
FAILED_PHRASES = ("failed", "error", "warning", "pass_with_warnings", "missing report")
PRINTED_SERIAL_PATTERN = re.compile(r"(?:printed_serials?|printed serials?)\s*[:=]\s*([A-Z0-9-]+)", re.IGNORECASE)
BARCODE_SERIAL_PATTERN = re.compile(r"(?:barcode_or_qr_serials?|barcode_serials?|barcode serials?)\s*[:=]\s*([A-Z0-9-]+)", re.IGNORECASE)
SUBJECT_PATTERN = re.compile(r"^\s*Subject:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def _snippet(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _normalize_query_candidates(query: str) -> set[str]:
    raw = query.strip().upper()
    digits = re.sub(r"\D", "", raw)
    candidates = {raw}
    if digits:
        candidates.update({digits, f"PO{digits}", f"SO{digits}"})
    return {value for value in candidates if value}


class AuditTools:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _chunks(self) -> list[dict[str, object]]:
        return self.db.iter_chunks()

    def serial_conflicts(self) -> list[dict[str, object]]:
        findings: list[dict[str, object]] = []
        seen: set[tuple[str, str, str]] = set()
        for chunk in self._chunks():
            text = str(chunk["text"])
            printed_match = PRINTED_SERIAL_PATTERN.search(text)
            barcode_match = BARCODE_SERIAL_PATTERN.search(text)
            printed = printed_match.group(1).upper() if printed_match else ""
            barcode = barcode_match.group(1).upper() if barcode_match else ""
            lowered = text.lower()
            if printed and barcode and printed != barcode:
                key = (chunk["source_path"], printed, barcode)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    {
                        "severity": "high",
                        "issue_type": "serial_conflict",
                        "printed_serial": printed,
                        "barcode_serial": barcode,
                        "summary": f"Printed serial {printed} does not match barcode serial {barcode}.",
                        "source_file": chunk["file_name"],
                        "source_path": chunk["source_path"],
                        "evidence_snippet": _snippet(text),
                        "recommended_action": "Review the original file and confirm which serial should be treated as authoritative.",
                    }
                )
            elif "mismatch" in lowered or "conflict" in lowered:
                findings.append(
                    {
                        "severity": "medium",
                        "issue_type": "serial_conflict",
                        "printed_serial": printed or "",
                        "barcode_serial": barcode or "",
                        "summary": "Conflict or mismatch wording was detected in indexed content.",
                        "source_file": chunk["file_name"],
                        "source_path": chunk["source_path"],
                        "evidence_snippet": _snippet(text),
                        "recommended_action": "Review the cited evidence and determine whether a serial mismatch still needs action.",
                    }
                )
        return findings

    def duplicate_serials(self) -> list[dict[str, object]]:
        locations: dict[str, list[dict[str, object]]] = {}
        for chunk in self._chunks():
            for serial in chunk["entities"].get("serial_numbers", []):
                locations.setdefault(serial, []).append(chunk)
        findings: list[dict[str, object]] = []
        for serial, chunks in sorted(locations.items()):
            unique_locations = {(chunk["source_path"], chunk["chunk_id"]) for chunk in chunks}
            if len(unique_locations) < 2:
                continue
            source_files = sorted({chunk["file_name"] for chunk in chunks})
            evidence_snippets = [_snippet(chunk["text"]) for chunk in chunks[:3]]
            findings.append(
                {
                    "severity": "medium",
                    "issue_type": "duplicate_serial",
                    "serial_number": serial,
                    "count": len(unique_locations),
                    "source_files": source_files,
                    "summary": f"Serial {serial} appears in {len(unique_locations)} indexed chunks across {len(source_files)} file(s).",
                    "source_file": source_files[0],
                    "evidence_snippet": " | ".join(evidence_snippets),
                    "evidence_snippets": evidence_snippets,
                    "recommended_action": "Review each occurrence and confirm whether the serial is duplicated by mistake or legitimately reused.",
                }
            )
        return findings

    def customer_followups(self) -> list[dict[str, object]]:
        findings: list[dict[str, object]] = []
        for chunk in self._chunks():
            text = str(chunk["text"])
            lowered = text.lower()
            if not any(phrase in lowered for phrase in FOLLOWUP_PHRASES):
                continue
            if not ("@" in text or "subject:" in lowered or chunk.get("source_category") == "email"):
                continue
            subject_match = SUBJECT_PATTERN.search(text)
            emails = chunk["entities"].get("emails", [])
            customers = chunk["entities"].get("customers", [])
            findings.append(
                {
                    "severity": "medium",
                    "issue_type": "customer_followup",
                    "customer_or_email": customers[0] if customers else (emails[0] if emails else ""),
                    "subject": subject_match.group(1).strip() if subject_match else "",
                    "summary": "Customer communication appears to be waiting on a status response.",
                    "source_file": chunk["file_name"],
                    "source_path": chunk["source_path"],
                    "evidence_snippet": _snippet(text),
                    "recommended_action": "Review the thread and prepare a human-approved reply with the latest internal status.",
                }
            )
        return findings

    def failed_reports(self) -> list[dict[str, object]]:
        findings: list[dict[str, object]] = []
        for chunk in self._chunks():
            text = str(chunk["text"])
            lowered = text.lower()
            matched = [phrase for phrase in FAILED_PHRASES if phrase in lowered]
            if not matched:
                continue
            severity = "high" if any(token in lowered for token in ("failed", "error", "missing report")) else "medium"
            findings.append(
                {
                    "severity": severity,
                    "issue_type": "failed_report",
                    "summary": f"Server or report content contains: {', '.join(matched)}.",
                    "source_file": chunk["file_name"],
                    "source_path": chunk["source_path"],
                    "evidence_snippet": _snippet(text),
                    "recommended_action": "Review the report, confirm the failure or warning, and decide the next remediation step.",
                }
            )
        return findings

    def po_so_summary(self, query: str) -> dict[str, object]:
        if not query.strip():
            return {
                "query": query,
                "related_source_files": [],
                "serials_found": [],
                "conflicts_found": [],
                "emails_found": [],
                "reports_found": [],
                "summary": "No query was provided.",
                "evidence_snippets": [],
            }
        candidates = _normalize_query_candidates(query)
        related_chunks: list[dict[str, object]] = []
        for chunk in self._chunks():
            entities = chunk["entities"]
            searchable_terms = {
                *entities.get("po_numbers", []),
                *entities.get("so_numbers", []),
                str(chunk["text"]).upper(),
            }
            if any(candidate in term for candidate in candidates for term in searchable_terms):
                related_chunks.append(chunk)
        serials_found = sorted({serial for chunk in related_chunks for serial in chunk["entities"].get("serial_numbers", [])})
        emails_found = sorted({email for chunk in related_chunks for email in chunk["entities"].get("emails", [])})
        related_source_files = sorted({chunk["file_name"] for chunk in related_chunks})
        evidence_snippets = [_snippet(chunk["text"]) for chunk in related_chunks[:6]]
        conflicts_found = [
            {
                "source_file": item["source_file"],
                "printed_serial": item.get("printed_serial", ""),
                "barcode_serial": item.get("barcode_serial", ""),
                "summary": item["summary"],
            }
            for item in self.serial_conflicts()
            if item["source_file"] in related_source_files
        ]
        reports_found = [
            {
                "source_file": item["source_file"],
                "severity": item["severity"],
                "summary": item["summary"],
            }
            for item in self.failed_reports()
            if item["source_file"] in related_source_files
        ]
        if related_chunks:
            summary = (
                f"Found {len(related_chunks)} chunk(s) related to {query}, across {len(related_source_files)} source file(s), "
                f"with {len(serials_found)} serial(s), {len(conflicts_found)} conflict signal(s), "
                f"{len(emails_found)} email address(es), and {len(reports_found)} related report finding(s)."
            )
        else:
            summary = "I could not find enough internal evidence."
        return {
            "query": query,
            "related_source_files": related_source_files,
            "serials_found": serials_found,
            "conflicts_found": conflicts_found,
            "emails_found": emails_found,
            "reports_found": reports_found,
            "summary": summary,
            "evidence_snippets": evidence_snippets,
        }
