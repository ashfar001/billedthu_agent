"""
BillLess Agent – Telemetry / Remote Observability

Sends operational metrics to backend so support can monitor
hundreds of shops remotely without SSH access.

Reports:
  ✅ Error counts & types
  ✅ Upload success/failure rate
  ✅ Last upload timestamp
  ✅ Device health
  ✅ Queue depth
  ✅ File lifecycle stats
  ✅ System resource usage

Fixes: ❌ No Observability (BIG ONE), ❌ Support Difficulty
"""

import os
import platform
import threading
import time

import requests

from config import get, AGENT_VERSION
from services import logger
from services.store import queue_count, history_count
from services.security import sign_headers


class TelemetryService:
    """Periodically reports agent metrics to backend."""

    def __init__(self, device=None, uploader=None):
        self._device = device
        self._uploader = uploader
        self._running = False
        self._thread: threading.Thread | None = None
        self._error_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def record_error(self, error_type: str):
        """Increment an error counter (called from other services)."""
        with self._lock:
            self._error_counts[error_type] = self._error_counts.get(error_type, 0) + 1

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("📊 Telemetry service started")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _loop(self):
        # Wait a bit before first report
        time.sleep(30)
        while self._running:
            try:
                self._send_report()
            except Exception as exc:
                logger.debug(f"Telemetry error: {exc}")
            time.sleep(300)     # every 5 minutes

    def _send_report(self):
        api_url = get("api_url").rstrip("/")
        api_key = get("api_key")
        shop_id = get("shop_id")
        device_id = get("device_id")

        url = f"{api_url}/api/agent/telemetry/"

        # ── Build metrics payload ────────────────────────────────────────
        try:
            q_counts = queue_count()
        except Exception:
            q_counts = {}

        try:
            uploaded_total = history_count()
        except Exception:
            uploaded_total = 0

        # File lifecycle stats
        try:
            from services.file_manager import get_lifecycle_stats
            lifecycle = get_lifecycle_stats()
        except Exception:
            lifecycle = {}

        payload = {
            "shop_id": shop_id,
            "device_id": device_id,
            "agent_version": AGENT_VERSION,
            "platform": platform.system(),
            "platform_version": platform.release(),
            "device_status": self._device.status if self._device else "unknown",
            "queue_pending": q_counts.get("pending", 0),
            "queue_failed": q_counts.get("failed", 0),
            "total_uploaded": uploaded_total,
            "last_uploaded": self._uploader.last_uploaded if self._uploader else None,
            "lifecycle_processed": lifecycle.get("processed", 0),
            "lifecycle_failed": lifecycle.get("failed", 0),
            "lifecycle_archived": lifecycle.get("archive", 0),
            "uptime_seconds": int(time.monotonic()),
        }

        # Include error counts (and reset)
        with self._lock:
            payload["error_counts"] = dict(self._error_counts)
            self._error_counts.clear()

        # ── Sign and send ────────────────────────────────────────────────
        headers = {
            "Authorization": f"Token {api_key}",
            "X-Agent-Version": AGENT_VERSION,
            "Content-Type": "application/json",
        }
        headers.update(sign_headers(payload))

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            if resp.status_code in (200, 201):
                logger.debug("📊 Telemetry report sent")
            # Don't log failures (this is a best-effort service)
        except Exception:
            pass
