"""
Parse a lead-contact file (CSV or Excel) into rows of ``{column_name: value}``.

The rows are used two ways:
  * the phone column drives which number is dialled, and
  * every column value is available to the *dynamic script* — placeholders in the
    greeting / announcement text are replaced, e.g. {name}, {amount}, {city}.

Phone column auto-detection tries common headers first (phone / mobile / number /
contact...), then falls back to the first column whose values look like phone
numbers. You can override with a ``phone_column`` hint.
"""
from __future__ import annotations

import io
import csv
from typing import Optional

_PHONE_HEADERS = (
    "phone", "phone_number", "phonenumber", "mobile", "mobile_number",
    "mobile_no", "contact", "contact_number", "contact_no", "number", "tel",
    "telephone", "cell", "customer_phone", "phone1",
)


def _looks_like_phone(v: str) -> bool:
    v = (v or "").strip()
    if not v:
        return False
    digits = "".join(ch for ch in v if ch.isdigit())
    return len(digits) >= 7 and len(digits) <= 15


def _detect_phone_column(headers: list[str], rows: list[dict]) -> str:
    # 1) Exact/contained header match.
    for h in headers:
        hl = (h or "").strip().lower()
        if hl in _PHONE_HEADERS or any(k in hl for k in _PHONE_HEADERS):
            return h
    # 2) First column whose values look like phone numbers.
    for h in headers:
        candidates = [rows[i].get(h) for i in range(min(5, len(rows)))]
        if candidates and any(_looks_like_phone(str(c)) for c in candidates):
            return h
    # 3) Fallback: first column.
    return headers[0] if headers else "phone"


def parse_lead_file(filename: str, content: bytes, phone_column: Optional[str] = None) -> dict:
    """Return ``{"rows": [...], "phone_column": "...", "count": n}``.

    Each row is a ``{header: value}`` dict (whitespace-stripped, empty cells kept
    as ""). Rows with no phone number are dropped and counted separately.
    """
    lower = (filename or "").lower()
    rows: dict[str, dict] = {}  # use dict per row; preserve header order via headers list

    if lower.endswith(".csv"):
        text = content.decode("utf-8", errors="ignore")
        reader = csv.reader(io.StringIO(text))
        raw = [r for r in reader if any(cell.strip() for cell in r)]
    elif lower.endswith(".xlsx") or lower.endswith(".xls") or lower.endswith(".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        raw = []
        for row in ws.iter_rows(values_only=True):
            if any(v is not None and str(v).strip() for v in row):
                raw.append(["" if v is None else str(v).strip() for v in row])
        wb.close()
    else:
        raise ValueError("Unsupported lead file. Use .csv or .xlsx/.xls")

    if not raw:
        raise ValueError("The file is empty.")

    # Treat the first row as the header (column names).
    header = raw[0]
    rows = []
    for r in raw[1:]:
        row = {}
        for i, h in enumerate(header):
            key = (str(h).strip() or f"col{i}")
            row[key] = r[i].strip() if i < len(r) else ""
        # Keep a numbered duplicate for placeholders without a header.
        rows.append(row)

    columns = [str(h).strip() or f"col{i}" for i, h in enumerate(header)]
    phone_col = phone_column or _detect_phone_column(columns, rows)

    # Drop rows that have no phone number.
    kept = []
    dropped = 0
    for row in rows:
        phone = (row.get(phone_col) or "").strip()
        if not phone or not any(ch.isdigit() for ch in phone):
            dropped += 1
            continue
        kept.append(row)

    return {"rows": kept, "phone_column": phone_col, "count": len(kept), "dropped": dropped}


def build_phone(row: dict, phone_column: str) -> str:
    """Normalise a phone for dialling: prepend a '+' if it's a bare national number."""
    p = (row.get(phone_column) or "").strip()
    if not p:
        return ""
    digits = "".join(ch for ch in p if ch.isdigit())
    if not digits:
        return p
    # Keep any leading '+' — treat as already E.164.
    if p.startswith("+"):
        return "+" + digits
    return "+" + digits if len(digits) > 10 else digits


def render_template(template: str, data: dict) -> str:
    """Replace ``{column}`` (case-insensitive) placeholders with the lead's values."""
    if not template:
        return template
    out = template
    for k, v in (data or {}).items():
        out = out.replace("{" + k + "}", str(v))
        out = out.replace("{" + k.lower() + "}", str(v))
        out = out.replace("{" + k.upper() + "}", str(v))
    return out
