"""
Uploader for the BillLess Virtual Receipt Printer.

It validates captured PDFs, parses receipt data, persists the parsed result,
uploads with duplicate detection and exponential backoff, and moves files
through incoming -> processing -> processed/failed.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time

import requests

from config import AGENT_VERSION, get
from services import logger
from services import database as db
from services.file_manager import move_duplicate_to_processed, move_to_failed, move_to_processed, move_to_processing
from services.parser import parse_receipt
from utils.helpers import file_hash, human_size, validate_file_size
from utils.validators import validate_file


def _validate_receipt_json(receipt_json: dict) -> tuple[bool, str]:
    if not isinstance(receipt_json, dict):
        return False, "receipt_json must be an object"
    if not isinstance(receipt_json.get("items", []), list):
        return False, "items must be an array"
    summary = receipt_json.get("summary", {})
    grand_total = summary.get("grand_total")
    if grand_total is not None and not isinstance(grand_total, (int, float)):
        return False, "grand_total must be numeric or null"
    metadata = receipt_json.get("metadata", {})
    if not metadata.get("raw_text", ""):
        logger.warning("Receipt raw_text is empty; parser will mark it for review")
    return True, ""


class Uploader:
    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._disabled = False
        self.last_uploaded = ""
        self.last_error = ""

    @property
    def stats(self) -> dict:
        counts = db.queue_counts()
        return {
            "success": db.upload_success_count(),
            "failed": db.failed_count() + counts.get(db.QueueStatus.DEAD, 0),
            "queued": counts.get(db.QueueStatus.PENDING, 0) + counts.get(db.QueueStatus.UPLOADING, 0),
        }

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            self._running = True
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        logger.info("Upload queue worker started")

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def enqueue(self, filepath: str) -> None:
        basename = os.path.basename(filepath)
        logger.info(f"Receipt ready for processing: {basename}")

        ok, size_mb = validate_file_size(filepath, float(get("upload_max_file_mb") or 25))
        if not ok:
            logger.warning(f"Receipt exceeds max size ({size_mb:.1f} MB): {basename}")
            move_to_failed(filepath)
            return

        validation = validate_file(filepath)
        if not validation.valid:
            logger.warning(f"Invalid receipt PDF: {validation.reason}")
            move_to_failed(filepath)
            return

        file_sha = file_hash(filepath)
        if db.history_exists(file_sha):
            logger.info(f"Duplicate receipt skipped: {basename}")
            move_duplicate_to_processed(filepath)
            return

        processing_path = move_to_processing(filepath)
        if not processing_path:
            return

        parsed = parse_receipt(processing_path)
        parsed["original_filename"] = basename
        ok, reason = _validate_receipt_json(parsed.get("receipt_json") or parsed)
        if not ok:
            logger.warning(f"Invalid parsed receipt JSON: {reason}")
            move_to_failed(processing_path)
            return
        receipt_id = db.create_receipt(processing_path, file_sha, parsed)
        db.queue_add(receipt_id, processing_path, file_sha)
        logger.info(f"Queued receipt upload: {os.path.basename(processing_path)} ({human_size(os.path.getsize(processing_path))})")
        self.start()

    def _worker(self) -> None:
        while self._running:
            if self._disabled:
                time.sleep(5)
                continue
            item = db.queue_peek(time.time())
            if not item:
                time.sleep(1)
                continue

            row_id = int(item["id"])
            receipt_id = int(item["receipt_id"])
            retries = int(item["retries"])
            max_retries = int(item["max_retries"])
            filepath = item["filepath"]
            file_sha = item["file_hash"]

            if retries >= max_retries:
                db.queue_mark_dead(row_id, receipt_id, "Retry limit exceeded")
                move_to_failed(filepath)
                continue

            db.queue_mark_uploading(row_id)
            success, data = self._upload(filepath, file_sha, item.get("parsed_json") or "{}")
            if success:
                server_bill_id = data.get("bill_id", "")
                confirmed = bool(data.get("confirmed"))
                db.queue_mark_done(row_id, receipt_id, filepath, file_sha, server_bill_id, confirmed)
                moved = move_to_processed(filepath)
                self.last_uploaded = os.path.basename(moved or filepath)
                logger.info(f"Receipt activated: {self.last_uploaded}")
            else:
                error = data.get("error", "Upload failed")
                self.last_error = error
                delay = self._backoff_seconds(retries)
                db.queue_mark_failed(row_id, receipt_id, error, time.time() + delay)
                logger.warning(f"Upload failed; retrying in {delay:.1f}s: {error}")

    def _upload(self, filepath: str, file_sha: str, parsed_json: str) -> tuple[bool, dict]:
        api_url = (get("api_url") or "").rstrip("/")
        api_key = get("api_key")
        if get("require_https") and not api_url.startswith("https://"):
            return False, {"error": "HTTPS is required by configuration"}
        if not os.path.exists(filepath):
            return False, {"error": "File disappeared before upload"}

        headers = {
            "X-Agent-Version": AGENT_VERSION,
            "X-Device-Id": get("device_id") or "",
        }
        if api_key:
            headers["Authorization"] = f"Token {api_key}"

        try:
            parsed = json.loads(parsed_json or "{}")
        except json.JSONDecodeError:
            parsed = {}

        data = {
            "device_id": get("device_id") or "",
            "store_code": get("shop_id") or "",
            "counter_id": parsed.get("receipt", {}).get("counter_id") or get("counter_id") or "",
            "table_id": parsed.get("receipt", {}).get("table_id", ""),
            "file_hash": file_sha,
            "receipt_json": json.dumps(parsed, ensure_ascii=False),
            "raw_text": parsed.get("metadata", {}).get("raw_text", ""),
            "parser_confidence": str(parsed.get("metadata", {}).get("confidence", 0)),
            "upload_status": parsed.get("metadata", {}).get("upload_status", "READY"),
        }
        # Keep the legacy fields until older backend deployments are retired.
        data["shop_id"] = data["store_code"]
        data["parsed_receipt"] = data["receipt_json"]
        url = f"{api_url}/api/bills/upload/"
        mime_type = "application/pdf" if filepath.lower().endswith(".pdf") else "text/plain"
        try:
            with open(filepath, "rb") as handle:
                response = requests.post(
                    url,
                    headers=headers,
                    data=data,
                    files={"file": (os.path.basename(filepath), handle, mime_type)},
                    timeout=int(get("backend_timeout_seconds") or 30),
                )
            if response.status_code in (200, 201):
                payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                return bool(payload.get("confirmed", True)), payload
            return False, {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
        except requests.ConnectionError:
            return False, {"error": "Backend offline"}
        except requests.Timeout:
            return False, {"error": "Backend timeout"}
        except Exception as exc:
            return False, {"error": str(exc)}

    def _backoff_seconds(self, retries_so_far: int) -> float:
        base = float(get("upload_retry_delay") or 2)
        delay = base * (2 ** retries_so_far)
        return min(delay + random.uniform(0, delay * 0.25), 300.0)
