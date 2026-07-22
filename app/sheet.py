"""Fetch transaction rows from the Emma Google Sheet.

Sources, in order of preference:
  1. Service account (GOOGLE_SA_JSON path + SHEET_ID) via the Sheets API
  2. Published CSV (SHEET_CSV_URL)
  3. Local xlsx export (EMMA_XLSX path) -- dev seeding
"""

import csv
import io
import os
from datetime import date, datetime

import httpx

HEADER = [
    "ID", "Date", "Amount", "Account", "Bank", "Currency", "Category",
    "Subcategory", "Type", "Tags", "Counterparty", "Custom Name", "Merchant",
    "Additional details", "Notes", "Linked transaction ID",
]

SHEET_TAB = os.environ.get("SHEET_TAB", "Primary")


class SheetNotConfigured(Exception):
    pass


def _parse_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {v!r}")


def _normalize(raw_rows) -> list[dict]:
    rows = []
    for r in raw_rows:
        r = list(r) + [""] * (len(HEADER) - len(r))
        if not r[0] or not str(r[1]).strip():
            continue
        try:
            d = _parse_date(r[1])
            amount = float(str(r[2]).replace(",", ""))
        except ValueError:
            continue
        rows.append({
            "id": str(r[0]).strip(),
            "date": d,
            "amount": amount,
            "account": str(r[3] or "").strip(),
            "bank": str(r[4] or "").strip(),
            "currency": str(r[5] or "GBP").strip(),
            "category_emma": str(r[6] or "").strip(),
            "subcategory": str(r[7] or "").strip(),
            "type": str(r[8] or "").strip(),
            "tags": str(r[9] or "").strip(),
            "counterparty": str(r[10] or "").strip(),
            "custom_name": str(r[11] or "").strip(),
            "merchant": str(r[12] or "").strip(),
            "details": str(r[13] or "").strip(),
            "notes": str(r[14] or "").strip(),
            "linked_id": str(r[15] or "").strip(),
        })
    return rows


def _fetch_via_service_account() -> list[dict]:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_SA_JSON"],
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    creds.refresh(Request())
    sheet_id = os.environ["SHEET_ID"]
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        f"/values/{SHEET_TAB}!A:P?valueRenderOption=UNFORMATTED_VALUE"
        f"&dateTimeRenderOption=FORMATTED_STRING"
    )
    resp = httpx.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=60)
    resp.raise_for_status()
    values = resp.json().get("values", [])
    return _normalize(values[1:] if values else [])


def _fetch_via_csv_url() -> list[dict]:
    resp = httpx.get(os.environ["SHEET_CSV_URL"], follow_redirects=True, timeout=60)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    return _normalize(rows[1:] if rows else [])


def _fetch_via_xlsx() -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(os.environ["EMMA_XLSX"], read_only=True)
    ws = wb[SHEET_TAB]
    it = ws.iter_rows(values_only=True)
    next(it, None)
    return _normalize(it)


def fetch_rows() -> list[dict]:
    if os.environ.get("GOOGLE_SA_JSON") and os.environ.get("SHEET_ID"):
        return _fetch_via_service_account()
    if os.environ.get("SHEET_CSV_URL"):
        return _fetch_via_csv_url()
    if os.environ.get("EMMA_XLSX"):
        return _fetch_via_xlsx()
    raise SheetNotConfigured(
        "Set GOOGLE_SA_JSON + SHEET_ID, or SHEET_CSV_URL, or EMMA_XLSX"
    )
