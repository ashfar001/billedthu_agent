"""
Receipt parser for PDFs produced by the BillLess virtual printer.

Receipts vary heavily between POS products, so this parser uses conservative
pattern extraction and stores the full text alongside structured best-effort
fields for backend reconciliation.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation

from services import logger


_MONEY = r"([0-9]+(?:,[0-9]{2,3})*(?:\.[0-9]{1,2})?)"


def parse_receipt(filepath: str) -> dict:
    text = extract_text(filepath)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    parsed = {
        "original_filename": os.path.basename(filepath),
        "bill_number": _first_match(text, [
            r"(?:bill|invoice|receipt)\s*(?:no|number|#)\s*[:#-]?\s*([A-Z0-9/-]+)",
            r"\b(?:inv|rcpt)\s*[:#-]?\s*([A-Z0-9/-]+)",
        ]),
        "total": _money_after(text, ["grand total", "net total", "amount due", "total"]),
        "subtotal": _money_after(text, ["subtotal", "sub total", "taxable amount"]),
        "tax": _money_after(text, ["tax", "gst", "vat", "cgst", "sgst"]),
        "cashier": _first_match(text, [r"cashier\s*[:#-]?\s*([A-Za-z0-9 ._-]+)"]),
        "payment_method": _first_match(text, [r"(cash|card|upi|wallet|credit|debit|net banking)"], flags=re.I),
        "items": _extract_items(lines),
        "quantity": None,
        "shop_name": lines[0] if lines else "",
        "timestamp": _first_match(text, [
            r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)",
            r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\s+\d{1,2}:\d{2}(?::\d{2})?)",
        ]),
        "raw_text": text,
    }
    parsed["quantity"] = sum(item.get("quantity") or 0 for item in parsed["items"]) or None
    logger.info(f"Parsed receipt fields from {os.path.basename(filepath)}")
    return parsed


def extract_text(filepath: str) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(filepath) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
    except Exception as exc:
        logger.debug(f"pdfplumber extraction failed: {exc}")

    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:
        logger.warning(f"Could not extract PDF text from {os.path.basename(filepath)}: {exc}")
        return ""


def _first_match(text: str, patterns: list[str], flags: int = re.I) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return ""


def _money_after(text: str, labels: list[str]) -> float | None:
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:#-]?\s*(?:rs\.?|inr|\$)?\s*{_MONEY}"
        match = re.search(pattern, text, re.I)
        if match:
            return _to_float(match.group(1))
    return None


def _to_float(value: str) -> float | None:
    try:
        return float(Decimal(value.replace(",", "")))
    except (InvalidOperation, ValueError):
        return None


def _extract_items(lines: list[str]) -> list[dict]:
    items = []
    item_pattern = re.compile(
        rf"^(.+?)\s+([0-9]+(?:\.[0-9]+)?)\s+(?:x\s*)?(?:rs\.?|inr|\$)?\s*{_MONEY}\s+(?:rs\.?|inr|\$)?\s*{_MONEY}$",
        re.I,
    )
    for line in lines:
        if any(label in line.lower() for label in ("total", "subtotal", "tax", "cashier", "invoice")):
            continue
        match = item_pattern.search(line)
        if not match:
            continue
        name = match.group(1).strip()
        if len(name) < 2:
            continue
        items.append({
            "name": name,
            "quantity": _to_float(match.group(2)),
            "unit_price": _to_float(match.group(3)),
            "total": _to_float(match.group(4)),
        })
    return items[:200]
