from __future__ import annotations

import re
from typing import Sequence


def normalize_text(text: str) -> str:
    text = text.upper()
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"[^A-Z0-9]+", "", text)


def clean_inventory_token(text: str) -> str:
    return re.sub(r"[^A-Z0-9.-]+", "", str(text or "").upper())


def candidate_after_serial_tag(line: str) -> str | None:
    m = re.search(
        r"(?:S\s*[/\\]?\s*N|SN|SIN|SIH|SINT|SDN|STN)\s*[:;]?\s*(.+)$",
        line,
        re.IGNORECASE,
    )
    if not m:
        return None

    tokens = re.findall(r"[A-Z0-9]+", m.group(1).upper())
    if not tokens:
        return None

    start = 0
    for i, token in enumerate(tokens):
        if token.startswith("M"):
            start = i
            break

    stop_words = {
        "OER",
        "TEER",
        "AYERS",
        "APACE",
        "ABS",
        "NG",
        "TUV",
        "EAC",
        "EAN",
        "UK",
        "CE",
        "LEE",
        "MODEL",
        "NVIDIA",
        "MADE",
        "CLASS",
        "REV",
        "QTY",
    }

    acc: list[str] = []
    for token in tokens[start:]:
        if acc and token in stop_words:
            break
        acc.append(token)
        raw = "".join(acc)
        if len(raw) >= 10 and sum(ch.isdigit() for ch in token) >= 1 and len(token) >= 4:
            break
        if len(raw) >= 13:
            break

    return "".join(acc) if acc else None


def serial_from_barcode_value(value: str) -> str | None:
    cleaned = clean_inventory_token(value)
    compact = re.sub(r"[^A-Z0-9]", "", cleaned.upper())
    if re.fullmatch(r"[A-Z]{2}\d{4}[A-Z]{2}\d{5}", compact):
        return compact
    return None


def normalize_exact_serial_candidate(raw: str) -> str | None:
    if not raw:
        return None
    r = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if not r:
        return None

    mpos = r.find("M")
    if mpos >= 0:
        r = r[mpos:]
    if len(r) < 13:
        return None

    if r[0] == "M" and r[1:2] in {"T", "7", "1", "I", "L"}:
        r = "MT" + r[2:]

    for i in range(0, max(1, len(r) - 12)):
        cand = r[i : i + 13]
        if len(cand) != 13:
            continue
        if cand[0:2] != "MT":
            continue

        digit_trans = str.maketrans(
            {
                "O": "0",
                "Q": "0",
                "D": "0",
                "I": "1",
                "L": "1",
                "H": "1",
                "S": "5",
                "B": "8",
                "Z": "2",
                "G": "6",
            }
        )
        left_digits = cand[2:6].translate(digit_trans)
        right_digits = cand[8:13].translate(digit_trans)
        middle_letters = cand[6:8]

        letter_trans = str.maketrans({"7": "T", "1": "I", "0": "O", "5": "S", "8": "B"})
        middle_letters = middle_letters.translate(letter_trans)

        normalized = "MT" + left_digits + middle_letters + right_digits
        if re.fullmatch(r"MT\d{4}[A-Z]{2}\d{5}", normalized):
            return normalized
    return None


def anchored_serials_from_ocr_text(raw_text: str) -> list[str]:
    serials: list[str] = []

    def add(value: str | None) -> None:
        if value and value not in serials:
            serials.append(value)

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    for line in lines:
        if not re.search(r"(?:S\s*[/\\]?\s*N|SN|SERIAL|SERI[AI]L|SIN|SIH)", line, re.IGNORECASE):
            continue

        after = candidate_after_serial_tag(line) or line
        add(normalize_exact_serial_candidate(after))

        compact = re.sub(r"[^A-Z0-9]", "", line.upper())
        for m in re.finditer(r"M[T7I1L][A-Z0-9]{11}", compact):
            add(normalize_exact_serial_candidate(m.group(0)))

    return serials


def barcode_serials_from_values(barcode_values: Sequence[str] | None) -> list[str]:
    serials: list[str] = []
    for value in barcode_values or []:
        serial = serial_from_barcode_value(value)
        if serial and serial not in serials:
            serials.append(serial)
    return serials


def normalize_mt26_serial(raw: str) -> str | None:
    if not raw:
        return None

    r = re.sub(r"[^A-Z0-9]", "", raw.upper())
    pos = r.find("M")
    if pos >= 0:
        r = r[pos:]

    if r.startswith(("M126", "MI26", "ML26")):
        r = "MT26" + r[4:]
    elif r.startswith("M26"):
        r = "MT26" + r[3:]
    elif not r.startswith("MT26"):
        idx = r.find("MT26")
        if idx >= 0:
            r = r[idx:]
        else:
            idx = r.find("M26")
            if idx >= 0:
                r = "MT26" + r[idx + 3 :]

    if not r.startswith("MT26"):
        return None

    tail = r[4:]
    trans = str.maketrans(
        {
            "O": "0",
            "Q": "0",
            "D": "0",
            "I": "1",
            "L": "1",
            "H": "1",
            "S": "5",
            "B": "8",
            "Z": "2",
            "G": "6",
            "E": "0",
        }
    )
    digits = "".join(ch for ch in tail.translate(trans) if ch.isdigit())
    if not digits:
        return None

    if len(digits) == 6 and digits.startswith("10"):
        suffix = "1" + digits[-4:]
    elif len(digits) >= 5:
        suffix = digits[-5:]
    elif len(digits) == 4:
        suffix = "1" + digits
    else:
        return None

    return "MT2610FT" + suffix

