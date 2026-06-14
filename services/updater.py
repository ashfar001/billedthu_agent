"""
BillLess Agent – Auto-Updater

Handles:
  ✅ Download new agent version from backend
  ✅ Verify download integrity (SHA-256)
  ✅ Replace files safely (backup old → install new)
  ✅ Restart agent after update
  ✅ Rollback on failure

Fixes: ❌ No Update Delivery System
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

import requests

from config import get, AGENT_VERSION, BASE_DIR
from services import logger


class UpdateResult:
    def __init__(self, success: bool, message: str, new_version: str = ""):
        self.success = success
        self.message = message
        self.new_version = new_version


class AutoUpdater:
    """Download, verify, and install agent updates."""

    BACKUP_DIR = os.path.join(BASE_DIR, ".update_backup")
    DOWNLOAD_DIR = os.path.join(BASE_DIR, ".update_download")

    def check_for_update(self) -> dict | None:
        """
        Ask backend if an update is available.
        Returns update info dict or None.
        """
        api_url = get("api_url").rstrip("/")
        api_key = get("api_key")

        url = f"{api_url}/api/agent/version/"
        headers = {"X-Agent-Version": AGENT_VERSION}
        if api_key:
            headers["Authorization"] = f"Token {api_key}"

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("update_available"):
                    return {
                        "version": data.get("latest_version", "?"),
                        "download_url": data.get("download_url", ""),
                        "checksum": data.get("sha256", ""),
                        "changelog": data.get("changelog", ""),
                        "mandatory": data.get("mandatory", False),
                    }
            return None
        except Exception as exc:
            logger.warning(f"⚠️  Update check failed: {exc}")
            return None

    def download_and_install(self, update_info: dict) -> UpdateResult:
        """
        Full update flow:
          1. Download update package
          2. Verify SHA-256 checksum
          3. Backup current version
          4. Extract new files
          5. Restart (or signal restart)
        """
        download_url = update_info.get("download_url")
        expected_hash = update_info.get("checksum", "")
        new_version = update_info.get("version", "unknown")

        if not download_url:
            return UpdateResult(False, "No download URL provided")

        logger.info(f"📥 Downloading update v{new_version}…")

        # ── Step 1: Download ─────────────────────────────────────────────
        os.makedirs(self.DOWNLOAD_DIR, exist_ok=True)
        pkg_path = os.path.join(self.DOWNLOAD_DIR, f"update_{new_version}.zip")

        try:
            resp = requests.get(download_url, stream=True, timeout=120)
            resp.raise_for_status()
            with open(pkg_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
        except Exception as exc:
            return UpdateResult(False, f"Download failed: {exc}")

        # ── Step 2: Verify checksum ──────────────────────────────────────
        if expected_hash:
            actual_hash = self._sha256(pkg_path)
            if actual_hash != expected_hash:
                os.remove(pkg_path)
                return UpdateResult(
                    False,
                    f"Checksum mismatch: expected {expected_hash[:16]}… "
                    f"got {actual_hash[:16]}…"
                )
            logger.info("✅ Checksum verified")

        # ── Step 3: Backup current version ───────────────────────────────
        try:
            self._backup_current()
        except Exception as exc:
            return UpdateResult(False, f"Backup failed: {exc}")

        # ── Step 4: Extract update ───────────────────────────────────────
        try:
            self._extract_update(pkg_path)
            logger.info(f"✅ Update v{new_version} installed")
        except Exception as exc:
            # Rollback
            logger.error(f"❌ Install failed, rolling back: {exc}")
            self._rollback()
            return UpdateResult(False, f"Install failed (rolled back): {exc}")

        # ── Step 5: Cleanup ──────────────────────────────────────────────
        try:
            os.remove(pkg_path)
        except OSError:
            pass

        return UpdateResult(True, f"Updated to v{new_version}", new_version)

    def restart_agent(self):
        """Restart the agent process after a successful update."""
        logger.info("🔄 Restarting agent…")
        python = sys.executable
        main_py = os.path.join(BASE_DIR, "main.py")
        try:
            subprocess.Popen([python, main_py])
            # The current process should exit
            sys.exit(0)
        except Exception as exc:
            logger.error(f"❌ Restart failed: {exc}")

    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _sha256(filepath: str) -> str:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _backup_current(self):
        """Backup current source files."""
        if os.path.exists(self.BACKUP_DIR):
            shutil.rmtree(self.BACKUP_DIR)
        os.makedirs(self.BACKUP_DIR)

        # Backup only Python source files
        for root, dirs, files in os.walk(BASE_DIR):
            # Skip venv, backup, download dirs
            rel = os.path.relpath(root, BASE_DIR)
            if any(skip in rel for skip in ("venv", ".update_", "logs", "__pycache__", "lifecycle")):
                continue
            for fname in files:
                if fname.endswith(".py"):
                    src = os.path.join(root, fname)
                    dest_dir = os.path.join(self.BACKUP_DIR, rel)
                    os.makedirs(dest_dir, exist_ok=True)
                    shutil.copy2(src, dest_dir)

        logger.info("💾 Current version backed up")

    def _extract_update(self, zip_path: str):
        """Extract update ZIP over the current installation."""
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Security: prevent path traversal
            for info in zf.infolist():
                if info.filename.startswith("/") or ".." in info.filename:
                    raise ValueError(f"Unsafe path in update: {info.filename}")
            zf.extractall(BASE_DIR)

    def _rollback(self):
        """Restore from backup."""
        if not os.path.exists(self.BACKUP_DIR):
            logger.error("❌ No backup found for rollback!")
            return

        try:
            for root, dirs, files in os.walk(self.BACKUP_DIR):
                rel = os.path.relpath(root, self.BACKUP_DIR)
                for fname in files:
                    src = os.path.join(root, fname)
                    dest = os.path.join(BASE_DIR, rel, fname)
                    shutil.copy2(src, dest)
            logger.info("✅ Rollback complete")
        except Exception as exc:
            logger.error(f"❌ Rollback failed: {exc}")
