"""
Receipt extraction for Bill Eduthu Agent print capture.

The parser prefers digital text from PDFs/text files. OCR is only attempted when
PDF extraction returns no usable text and Google Vision support is configured.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from typing import Any

from config import get
from services import logger


PARSER_VERSION = "v1"
SOURCE = "AGENT_PRINT_CAPTURE"
LOW_CONFIDENCE_THRESHOLD = 0.55
_MONEY = r"([+-]?\d+(?:,\d{2,3})*(?:\.\d{1,2})?)"
_GSTIN = r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"
_PHONE = r"(?:\+?91[-\s]?)?[6-9]\d{9}\b"
_DATE = r"\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\b"
_TIME = r"\b(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)\b"

_SUMMARY_LABELS = (
    "subtotal",
    "sub total",
    "taxable",
    "tax",
    "gst",
    "cgst",
    "sgst",
    "igst",
    "discount",
    "round",
    "total",
    "grand total",
    "balance due",
    "amount due",
    "total amount",
    "net total",
    "paid",
    "change",
)
_NON_ITEM_WORDS = (
    "gstin",
    "phone",
    "mobile",
    "invoice",
    "bill no",
    "receipt",
    "date",
    "time",
    "cashier",
    "counter",
    "table",
    "room",
    "kot",
    "address",
    "payment",
    "mode",
    "qty",
    "quantity",
    "rate",
    "price",
    "amount",
)


def parse_receipt(filepath: str) -> dict[str, Any]:
    raw_text, extraction_method = extract_raw_text(filepath)
    lines = _clean_lines(raw_text)
    receipt_json = _standard_receipt()
    receipt_json["metadata"]["raw_text"] = raw_text
    receipt_json["metadata"]["extraction_method"] = extraction_method

    _parse_merchant(receipt_json, lines, raw_text)
    _parse_receipt_header(receipt_json, raw_text)
    receipt_json["items"] = _extract_items(lines)
    _parse_summary(receipt_json, raw_text)
    _validate_receipt_json(receipt_json)
    _score_receipt(receipt_json, raw_text)

    parsed = _with_legacy_fields(receipt_json, filepath)
    logger.info(
        f"Parsed receipt {os.path.basename(filepath)} with "
        f"{receipt_json['metadata']['confidence']:.2f} confidence"
        f"{' (needs review)' if receipt_json['metadata']['needs_review'] else ''}"
    )
    return parsed


def extract_raw_text(filepath: str) -> tuple[str, str]:
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        text = _extract_pdf_text(filepath)
        if text.strip():
            return text, "PDF_TEXT"
        local_ocr_text = _local_tesseract_ocr(filepath)
        if local_ocr_text.strip():
            return local_ocr_text, "LOCAL_TESSERACT_OCR"
        ocr_text = _google_vision_ocr(filepath)
        return ocr_text, "GOOGLE_VISION_OCR" if ocr_text else "EMPTY_PDF"
    if ext in {".txt", ".text", ".csv"}:
        return _read_text_file(filepath), "TEXT_FILE"
    return _read_text_file(filepath), "TEXT_FILE"


def extract_text(filepath: str) -> str:
    text, _method = extract_raw_text(filepath)
    return text


def _extract_pdf_text(filepath: str) -> str:
    try:
        import fitz

        chunks = []
        with fitz.open(filepath) as doc:
            for page in doc:
                chunks.append(page.get_text("text", sort=True) or "")
        text = "\n".join(chunks).strip()
        if text:
            return text
    except Exception as exc:
        logger.debug(f"PyMuPDF extraction failed: {exc}")

    try:
        import pdfplumber

        chunks = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text(
                    x_tolerance=1,
                    y_tolerance=3,
                    layout=True,
                    keep_blank_chars=True,
                )
                chunks.append(text or "")
        text = "\n".join(chunks).strip()
        if text:
            return text
    except Exception as exc:
        logger.debug(f"pdfplumber extraction failed: {exc}")

    try:
        from pypdf import PdfReader

        reader = PdfReader(filepath)
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:
        logger.warning(f"Could not extract PDF text from {os.path.basename(filepath)}: {exc}")
        return ""


def _read_text_file(filepath: str) -> str:
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            with open(filepath, "r", encoding=encoding, errors="replace") as handle:
                return handle.read().strip()
        except Exception:
            continue
    return ""


def _google_vision_ocr(filepath: str) -> str:
    if not get("google_vision_enabled"):
        logger.info("PDF has no selectable text; Google Vision OCR is not enabled")
        return ""
    try:
        from google.cloud import vision
    except Exception as exc:
        logger.warning(f"Google Vision OCR unavailable: {exc}")
        return ""

    try:
        client = vision.ImageAnnotatorClient()
        texts = []
        for content in _ocr_image_payloads(filepath):
            response = client.document_text_detection(image=vision.Image(content=content))
            if response.error.message:
                logger.warning(f"Google Vision OCR failed: {response.error.message}")
                continue
            if response.full_text_annotation.text:
                texts.append(response.full_text_annotation.text)
        return "\n".join(texts).strip()
    except Exception as exc:
        logger.warning(f"Google Vision OCR failed: {exc}")
        return ""


def _local_tesseract_ocr(filepath: str) -> str:
    if not get("local_ocr_enabled"):
        logger.info("PDF has no selectable text; local OCR is disabled")
        return ""

    tesseract = get("tesseract_cmd") or shutil.which("tesseract")
    if not tesseract:
        logger.warning("PDF has no selectable text; install Tesseract OCR for free local OCR fallback")
        return ""

    try:
        image_paths = _render_pdf_pages_for_ocr(filepath)
        if not image_paths:
            return ""
        texts = []
        for image_path in image_paths:
            result = subprocess.run(
                [tesseract, image_path, "stdout", "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                texts.append(result.stdout.strip())
            elif result.stderr.strip():
                logger.debug(f"Tesseract OCR warning: {result.stderr.strip()[:200]}")
        return "\n".join(texts).strip()
    except subprocess.TimeoutExpired:
        logger.warning("Local OCR timed out")
        return ""
    except Exception as exc:
        logger.warning(f"Local OCR failed: {exc}")
        return ""
    finally:
        for path in locals().get("image_paths", []):
            try:
                os.remove(path)
            except OSError:
                pass


def _render_pdf_pages_for_ocr(filepath: str) -> list[str]:
    try:
        import fitz

        paths = []
        max_pages = int(get("local_ocr_max_pages") or 3)
        with fitz.open(filepath) as doc:
            for index in range(min(max_pages, doc.page_count)):
                page = doc.load_page(index)
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                fd, path = tempfile.mkstemp(prefix="bill_eduthu_ocr_", suffix=".png")
                os.close(fd)
                pix.save(path)
                paths.append(path)
        return paths
    except Exception as exc:
        logger.warning(f"Could not render PDF for local OCR: {exc}")
        return []


def _ocr_image_payloads(filepath: str) -> list[bytes]:
    if filepath.lower().endswith(".pdf"):
        try:
            import fitz

            payloads = []
            with fitz.open(filepath) as doc:
                for index in range(min(5, doc.page_count)):
                    page = doc.load_page(index)
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    payloads.append(pix.tobytes("png"))
            return payloads
        except Exception as exc:
            logger.warning(f"Could not render PDF for OCR fallback: {exc}")
            return []
    try:
        with open(filepath, "rb") as handle:
            return [handle.read()]
    except Exception:
        return []


def _standard_receipt() -> dict[str, Any]:
    return {
        "merchant": {"name": "", "gstin": "", "address": "", "phone": ""},
        "receipt": {
            "bill_number": "",
            "invoice_number": "",
            "date": "",
            "time": "",
            "payment_method": "",
            "counter_id": "",
            "table_id": "",
            "cashier": "",
            "customer_name": "",
        },
        "items": [],
        "summary": {
            "subtotal": None,
            "discount": None,
            "cgst": None,
            "sgst": None,
            "igst": None,
            "tax_total": None,
            "round_off": None,
            "grand_total": None,
        },
        "metadata": {
            "source": SOURCE,
            "parser_version": PARSER_VERSION,
            "raw_text": "",
            "confidence": 0,
            "needs_review": False,
        },
    }


def _clean_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.rstrip() for line in normalized.splitlines() if line.strip()]


def _parse_merchant(receipt_json: dict[str, Any], lines: list[str], text: str) -> None:
    merchant = receipt_json["merchant"]
    merchant["gstin"] = _first_match(text, [_GSTIN], flags=re.I)
    merchant["phone"] = _first_match(text, [_PHONE])
    merchant["name"] = _detect_store_name(lines)
    merchant["address"] = _detect_address(lines)


def _detect_store_name(lines: list[str]) -> str:
    for line in lines[:8]:
        stripped = _collapse(line)
        lower = stripped.lower()
        if not stripped or len(stripped) < 3:
            continue
        if any(word in lower for word in _NON_ITEM_WORDS):
            continue
        if re.search(_GSTIN, stripped, re.I) or re.search(_PHONE, stripped):
            continue
        if _looks_like_money_line(stripped):
            continue
        return stripped[:120]
    return ""


def _detect_address(lines: list[str]) -> str:
    parts = []
    for line in lines[:12]:
        stripped = _collapse(line)
        lower = stripped.lower()
        if not stripped:
            continue
        if any(word in lower for word in ("bill", "invoice", "receipt", "date", "time", "cashier", "payment")):
            continue
        if re.search(_GSTIN, stripped, re.I) or re.search(_PHONE, stripped):
            continue
        if any(word in lower for word in ("road", "street", "nagar", "colony", "market", "near", "opp", "floor")):
            parts.append(stripped)
        elif len(parts) and len(parts) < 3 and not _looks_like_money_line(stripped):
            parts.append(stripped)
    return ", ".join(parts[:3])


def _parse_receipt_header(receipt_json: dict[str, Any], text: str) -> None:
    receipt = receipt_json["receipt"]
    receipt["bill_number"] = _first_match(text, [
        r"\b(?:bill|receipt)\s*(?:no|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{1,})",
        r"\b(?:rcpt|token)\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{1,})",
    ])
    receipt["invoice_number"] = _first_match(text, [
        r"\b(?:invoice|inv)\s*(?:no|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{1,})",
    ])
    receipt["date"] = _first_match(text, [_DATE])
    receipt["time"] = _first_match(text, [_TIME])
    receipt["payment_method"] = _first_match(text, [
        r"\b(?:payment|mode|paid by)\s*[:#-]?\s*(cash|card|upi|wallet|credit|debit|net banking)",
        r"\b(cash|card|upi|wallet|credit|debit|net banking)\b",
    ], flags=re.I).upper()
    receipt["counter_id"] = _first_match(text, [
        r"\b(?:counter|terminal|pos)\s*(?:id|no|number)?\s*[:#-]?\s*([A-Z0-9-]+)",
    ])
    receipt["table_id"] = _first_match(text, [
        r"\b(?:kot\s*)?table\s*(?:no|number|#)?\s*[:#-]?\s*([A-Z0-9-]+)",
        r"\btbl\s*[:#-]?\s*([A-Z0-9-]+)",
        r"\bdine\s*in\s*[:#-]?\s*([A-Z0-9-]+)",
        r"\broom\s*[:#-]?\s*([A-Z0-9-]+)",
    ])
    receipt["cashier"] = _first_match(text, [r"\bcashier\s*[:#-]?\s*([A-Za-z0-9 ._-]{2,40})"])
    receipt["customer_name"] = _first_match(text, [
        r"\bcustomer\s*(?:name)?\s*[:#-]?\s*([A-Za-z][A-Za-z ._-]{1,50})",
    ])


def _parse_summary(receipt_json: dict[str, Any], text: str) -> None:
    summary = receipt_json["summary"]
    summary["subtotal"] = _money_after(text, ["subtotal", "sub total", "taxable amount"])
    summary["discount"] = _money_after(text, ["discount", "disc"])
    summary["cgst"] = _money_after(text, ["cgst"])
    summary["sgst"] = _money_after(text, ["sgst"])
    summary["igst"] = _money_after(text, ["igst"])
    summary["round_off"] = _money_after(text, ["round off", "roundoff", "rounded"])

    explicit_tax = _money_after(text, ["tax total", "total tax", "gst total"])
    tax_parts = [summary.get("cgst"), summary.get("sgst"), summary.get("igst")]
    summary["tax_total"] = explicit_tax if explicit_tax is not None else _sum_present(tax_parts)

    for labels in (
        ["grand total", "net total"],
        ["balance due"],
        ["amount due"],
        ["total amount"],
        ["total"],
        ["subtotal", "sub total"],
    ):
        value = _money_after(text, labels)
        if value is not None:
            summary["grand_total"] = value
            break


def _extract_items(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_line in lines:
        line = _collapse(raw_line)
        if not _could_be_item_line(line):
            continue

        parsed = _parse_item_line(line)
        if not parsed:
            continue
        name, qty, unit_price, total_price, tax_rate = parsed
        if not _valid_item_name(name):
            continue
        if total_price is not None and _money_is_identifier(total_price, line):
            total_price = None
        if unit_price is not None and _money_is_identifier(unit_price, line):
            unit_price = None
        confidence = _item_confidence(name, qty, unit_price, total_price)
        items.append({
            "name": name,
            "quantity": qty,
            "unit_price": unit_price,
            "total_price": total_price,
            "tax_rate": tax_rate,
            "category": "",
            "confidence": confidence,
        })
    return items[:200]


def _parse_item_line(line: str) -> tuple[str, float, float | None, float | None, float | None] | None:
    tax_rate = _extract_tax_rate(line)
    stripped = re.sub(r"\b\d{1,2}(?:\.\d+)?\s*%\b", "", line).strip()
    money_matches = list(re.finditer(rf"(?:rs\.?|inr|₹)?\s*{_MONEY}\b", stripped, re.I))
    if not money_matches:
        missing_price = re.match(r"^([A-Za-z][A-Za-z0-9 ._&'/-]{2,})\s+(\d+(?:\.\d+)?)\s*(?:pcs|nos?)?$", stripped, re.I)
        if not missing_price:
            return None
        qty = _to_float(missing_price.group(2)) or 1.0
        if qty <= 0 or qty > 999:
            return None
        return missing_price.group(1).strip(" -:\t")[:120], qty, None, None, tax_rate
    if len(money_matches) == 1:
        only = money_matches[0]
        prefix = stripped[only.start():only.end()]
        name_before = stripped[: only.start()].strip(" -:\t")
        if (
            name_before
            and not re.search(r"(?:rs\.?|inr|₹)", prefix, re.I)
            and only.end() == len(stripped)
            and _quantity_is_plausible(only.group(1), None)
            and "." not in only.group(1)
        ):
            return name_before[:120], _to_float(only.group(1)) or 1.0, None, None, tax_rate

    amount_values = [_to_float(match.group(1)) for match in money_matches]
    amount_values = [value for value in amount_values if value is not None]
    if not amount_values:
        return None

    total_price = amount_values[-1]
    before_total = stripped[: money_matches[-1].start()].strip(" -:\t")
    if not before_total:
        return None

    unit_price = None
    qty = 1.0

    structured = re.match(
        rf"^(.+?)\s+(\d+(?:\.\d+)?)\s+(?:x\s*)?(?:rs\.?|inr|₹)?\s*{_MONEY}(?:\s|$)",
        before_total,
        re.I,
    )
    if structured:
        name = structured.group(1).strip(" -:\t")
        qty = _to_float(structured.group(2)) or 1.0
        unit_price = _to_float(structured.group(3))
    else:
        qty_match = re.search(r"\b(?:qty|qnty)\s*[:x-]?\s*(\d+(?:\.\d+)?)\b", before_total, re.I)
        if qty_match:
            qty = _to_float(qty_match.group(1)) or 1.0
            name = before_total[: qty_match.start()].strip(" -:\t")
        else:
            tail_qty = re.search(r"\s+(\d+(?:\.\d+)?)\s*(?:x|pcs|nos?)?$", before_total, re.I)
            if tail_qty and _quantity_is_plausible(tail_qty.group(1), total_price):
                qty = _to_float(tail_qty.group(1)) or 1.0
                name = before_total[: tail_qty.start()].strip(" -:\t")
            else:
                name = before_total

    if not name:
        return None
    if unit_price is not None and _same_number(unit_price, qty):
        unit_price = None
    return name[:120], qty, unit_price, total_price, tax_rate


def _could_be_item_line(line: str) -> bool:
    lower = line.lower()
    if len(line) < 4 or not re.search(r"[A-Za-z]", line):
        return False
    if any(label in lower for label in _SUMMARY_LABELS):
        return False
    if any(word in lower for word in _NON_ITEM_WORDS):
        return False
    if re.search(_GSTIN, line, re.I) or re.search(_PHONE, line) or re.search(_DATE, line):
        return False
    return bool(re.search(_MONEY, line) or re.search(r"^[A-Za-z][A-Za-z0-9 ._&'/-]{2,}\s+\d+(?:\.\d+)?\s*(?:pcs|nos?)?$", line, re.I))


def _valid_item_name(name: str) -> bool:
    lower = name.lower()
    if len(name) < 2 or not re.search(r"[A-Za-z]", name):
        return False
    if any(word in lower for word in _NON_ITEM_WORDS):
        return False
    if re.search(_GSTIN, name, re.I) or re.search(_PHONE, name):
        return False
    return True


def _validate_receipt_json(receipt_json: dict[str, Any]) -> None:
    if not isinstance(receipt_json.get("items"), list):
        receipt_json["items"] = []
    summary = receipt_json["summary"]
    for key in ("subtotal", "discount", "cgst", "sgst", "igst", "tax_total", "round_off", "grand_total"):
        summary[key] = _number_or_none(summary.get(key))
    for item in receipt_json["items"]:
        item["quantity"] = _number_or_default(item.get("quantity"), 1)
        item["unit_price"] = _number_or_none(item.get("unit_price"))
        item["total_price"] = _number_or_none(item.get("total_price"))
        item["tax_rate"] = _number_or_none(item.get("tax_rate"))
        item["confidence"] = max(0, min(1, float(item.get("confidence") or 0)))


def _score_receipt(receipt_json: dict[str, Any], raw_text: str) -> None:
    score = 0.0
    if raw_text.strip():
        score += 0.2
    if receipt_json["merchant"]["name"]:
        score += 0.1
    if receipt_json["merchant"]["gstin"]:
        score += 0.1
    if receipt_json["receipt"]["bill_number"] or receipt_json["receipt"]["invoice_number"]:
        score += 0.12
    if receipt_json["receipt"]["date"]:
        score += 0.08
    if receipt_json["items"]:
        score += min(0.2, 0.08 + len(receipt_json["items"]) * 0.025)
    if receipt_json["summary"]["grand_total"] is not None:
        score += 0.2
    if receipt_json["receipt"]["payment_method"]:
        score += 0.04
    confidence = round(min(score, 1.0), 2)
    receipt_json["metadata"]["confidence"] = confidence

    looks_restaurant = _looks_like_restaurant(raw_text)
    missing_table = looks_restaurant and not receipt_json["receipt"]["table_id"]
    receipt_json["metadata"]["needs_table_assignment"] = missing_table
    receipt_json["metadata"]["upload_status"] = (
        "NEEDS_TABLE_ASSIGNMENT" if missing_table else "NEEDS_REVIEW" if confidence < LOW_CONFIDENCE_THRESHOLD else "READY"
    )
    receipt_json["metadata"]["needs_review"] = confidence < LOW_CONFIDENCE_THRESHOLD or missing_table


def _with_legacy_fields(receipt_json: dict[str, Any], filepath: str) -> dict[str, Any]:
    receipt = receipt_json["receipt"]
    summary = receipt_json["summary"]
    merchant = receipt_json["merchant"]
    parsed = {
        **receipt_json,
        "receipt_json": receipt_json,
        "original_filename": os.path.basename(filepath),
        "bill_number": receipt.get("bill_number") or receipt.get("invoice_number") or "",
        "total": summary.get("grand_total"),
        "subtotal": summary.get("subtotal"),
        "tax": summary.get("tax_total"),
        "cashier": receipt.get("cashier", ""),
        "payment_method": receipt.get("payment_method", ""),
        "shop_name": merchant.get("name", ""),
        "timestamp": " ".join(part for part in (receipt.get("date"), receipt.get("time")) if part),
        "raw_text": receipt_json["metadata"].get("raw_text", ""),
        "parser_confidence": receipt_json["metadata"].get("confidence", 0),
        "needs_review": receipt_json["metadata"].get("needs_review", False),
        "upload_status": receipt_json["metadata"].get("upload_status", "READY"),
        "table_id": receipt.get("table_id", ""),
        "counter_id": receipt.get("counter_id", ""),
    }
    return parsed


def _first_match(text: str, patterns: list[str], flags: int = re.I) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return _collapse(match.group(1) if match.groups() else match.group(0))
    return ""


def _money_after(text: str, labels: list[str]) -> float | None:
    matches: list[tuple[int, float]] = []
    for label in labels:
        pattern = rf"\b{re.escape(label)}\b\s*[:#-]?\s*(?:rs\.?|inr|₹)?\s*{_MONEY}"
        for match in re.finditer(pattern, text, re.I):
            value = _to_float(match.group(1))
            if value is not None:
                matches.append((match.start(), value))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]


def _to_float(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value).replace(",", "").strip()))
    except (InvalidOperation, ValueError):
        return None


def _number_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return _to_float(value)


def _number_or_default(value: Any, default: float) -> float:
    parsed = _to_float(value)
    return parsed if parsed is not None else default


def _sum_present(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(sum(present), 2) if present else None


def _extract_tax_rate(line: str) -> float | None:
    match = re.search(r"\b(\d{1,2}(?:\.\d+)?)\s*%\b", line)
    return _to_float(match.group(1)) if match else None


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _looks_like_money_line(line: str) -> bool:
    return bool(re.search(_MONEY, line)) and not re.search(r"[A-Za-z]{3,}", line)


def _quantity_is_plausible(value: str, total_price: float | None) -> bool:
    quantity = _to_float(value)
    if quantity is None or quantity <= 0 or quantity > 999:
        return False
    if total_price is not None and _same_number(quantity, total_price):
        return False
    return True


def _same_number(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) < 0.001


def _money_is_identifier(value: float, line: str) -> bool:
    digits = re.sub(r"\D", "", str(value))
    return len(digits) >= 10 or bool(re.search(_PHONE, line) or re.search(_GSTIN, line, re.I))


def _item_confidence(name: str, qty: float, unit_price: float | None, total_price: float | None) -> float:
    score = 0.45
    if len(name) > 2:
        score += 0.15
    if qty > 0:
        score += 0.1
    if total_price is not None:
        score += 0.2
    if unit_price is not None:
        score += 0.1
    return round(min(score, 1.0), 2)


def _looks_like_restaurant(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in ("table", "tbl", "kot", "dine in", "room", "waiter", "steward"))
