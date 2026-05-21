"""
BillLess Agent – Heartbeat Service (v2)

System-level hardening:
  ✅ Kill-switch support (backend can disable agent remotely)
  ✅ Server-time sync (all timestamps from backend)
  ✅ Telemetry stats in heartbeat
  ✅ Auto-update trigger
  ✅ Stale receipt cleanup
  ✅ Progressive failure suppression

Fixes: ❌ Kill-Switch, ❌ Time Sync, ❌ Monitoring, ❌ Version Mismatch
"""

import threading
import time

import requests

from config import get, AGENT_VERSION
from services import database as db
from services import logger
from services.security import sign_headers


class HeartbeatService:
    """Background heartbeat to backend with kill-switch and server-time sync."""

    def __init__(self, device=None, uploader=None):
        self._device = device
        self._uploader = uploader
        self._running = False
        self._thread: threading.Thread | None = None
        self.backend_online = False
        self.version_ok = True
        self.server_time: str = ""        # last known server time
        self.agent_disabled = False       # kill-switch state
        self._consecutive_failures = 0

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("💓 Heartbeat service started")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _loop(self):
        while self._running:
            interval = get("heartbeat_interval")
            try:
                self._ping_backend()
            except Exception as exc:
                logger.debug(f"Heartbeat error: {exc}")

            time.sleep(interval)

    def _ping_backend(self):
        api_url = get("api_url").rstrip("/")
        api_key = get("api_key")
        shop_id = get("shop_id")
        device_id = get("device_id")
        counter_id = get("counter_id") if get("counter_id") else ""

        url = f"{api_url}/api/agent/heartbeat/"

        # ── Build payload with stats ─────────────────────────────────────
        try:
            q_counts = db.queue_counts()
        except Exception:
            q_counts = {}

        payload = {
            "shop_id": shop_id,
            "device_id": device_id,
            "counter_id": counter_id,
            "agent_version": AGENT_VERSION,
            "device_status": self._device.status if self._device else "printer",
            "queue_pending": q_counts.get("pending", 0),
            "queue_failed": q_counts.get("failed", 0),
            "total_uploaded": db.upload_success_count(),
        }

        headers = {
            "Authorization": f"Token {api_key}",
            "X-Agent-Version": AGENT_VERSION,
            "X-Device-Id": device_id,
            "X-Shop-Id": shop_id,
            "X-Counter-Id": counter_id,
            "Content-Type": "application/json",
        }
        headers.update(sign_headers(payload))

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)

            if resp.status_code in (200, 201):
                self.backend_online = True
                self._consecutive_failures = 0

                data = resp.json() if resp.headers.get(
                    "content-type", ""
                ).startswith("application/json") else {}

                # ── Server time sync ─────────────────────────────────────
                if "server_time" in data:
                    self.server_time = data["server_time"]

                # ── Version check ────────────────────────────────────────
                if data.get("update_required"):
                    self.version_ok = False
                    latest = data.get("latest_version", "?")
                    logger.warning(
                        f"🔄 Update available: v{latest} (current: {AGENT_VERSION})"
                    )

                    # Trigger auto-update if mandatory
                    if data.get("mandatory_update"):
                        self._trigger_update(data)
                else:
                    self.version_ok = True

                # ── Kill-switch ───────────────────────────────────────────
                if data.get("agent_disabled"):
                    if not self.agent_disabled:
                        logger.warning("🛑 Agent DISABLED by backend")
                    self.agent_disabled = True
                    if self._uploader:
                        self._uploader.set_disabled(True)
                else:
                    if self.agent_disabled:
                        logger.info("✅ Agent RE-ENABLED by backend")
                    self.agent_disabled = False
                    if self._uploader:
                        self._uploader.set_disabled(False)

            else:
                self._handle_failure(f"HTTP {resp.status_code}")

        except requests.ConnectionError:
            self._handle_failure("Connection error")
        except requests.Timeout:
            self._handle_failure("Timeout")
        except Exception as exc:
            self._handle_failure(str(exc))

    def _handle_failure(self, reason: str):
        self._consecutive_failures += 1
        self.backend_online = False
        if self._consecutive_failures <= 3:
            logger.warning(f"💔 Heartbeat failed: {reason}")
        elif self._consecutive_failures == 4:
            logger.error(
                f"❌ Backend appears offline ({self._consecutive_failures} "
                f"consecutive failures). Will keep trying silently."
            )

    def _trigger_update(self, data: dict):
        """Trigger auto-update in background."""
        try:
            from services.updater import AutoUpdater
            updater = AutoUpdater()
            update_info = {
                "version": data.get("latest_version", ""),
                "download_url": data.get("download_url", ""),
                "checksum": data.get("sha256", ""),
                "mandatory": True,
            }
            if update_info["download_url"]:
                result = updater.download_and_install(update_info)
                if result.success:
                    logger.info(f"✅ Updated to v{result.new_version}, restarting…")
                    updater.restart_agent()
                else:
                    logger.error(f"❌ Auto-update failed: {result.message}")
        except Exception as exc:
            logger.error(f"❌ Auto-update error: {exc}")
