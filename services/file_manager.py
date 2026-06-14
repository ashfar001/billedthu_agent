"""
BillLess Agent – File Lifecycle Manager (v2)

Clean folder structure:
  ~/Documents/BillLess/
  ├── incoming/      ← watcher monitors this
  ├── processing/    ← file moved here during upload
  ├── processed/     ← successful uploads land here
  ├── failed/        ← permanently failed uploads
  └── archive/       ← old processed files (auto-cleanup)

Flow:
  incoming → processing → upload → processed
                                → failed (on permanent failure)
  processed → archive (after 7 days) → deleted (after 30 days)
"""

import os
import shutil
import time
from datetime import datetime

from config import (
    get, incoming_folder, processing_folder,
    processed_folder, failed_folder, archive_folder,
)
from services import logger

_ARCHIVE_AFTER_DAYS = 7
_DELETE_AFTER_DAYS = 30


# ── Unique filename generation ───────────────────────────────────────────────

def generate_unique_name(original_path: str) -> str:
    """
    Generate the BillLess receipt filename:
      SHOP001_DEV001_C1_20260506_132500.pdf
    """
    shop_id = get("store_code") or get("shop_id") or "SHOP"
    device_id = get("device_id") or "DEV"
    counter_id = get("counter_id") or "C0"
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    ext = os.path.splitext(original_path)[1].lower() or ".pdf"

    return f"{shop_id}_{device_id}_{counter_id}_{timestamp}{ext}"


# ── Lifecycle moves ──────────────────────────────────────────────────────────

def move_to_processing(filepath: str) -> str | None:
    """
    Move file from incoming → processing and rename with unique prefix.
    Returns the new filepath in processing/, or None on failure.
    """
    if not os.path.exists(filepath):
        logger.warning(f"⚠️  File disappeared before processing: {os.path.basename(filepath)}")
        return None

    basename = os.path.basename(filepath)
    expected_prefix = f"{get('store_code') or get('shop_id') or 'SHOP'}_{get('device_id') or 'DEV'}_{get('counter_id') or 'C0'}_"
    new_name = basename if basename.startswith(expected_prefix) else generate_unique_name(filepath)
    dest = os.path.join(processing_folder(), new_name)

    # Handle collision (extremely unlikely with timestamp)
    if os.path.exists(dest):
        name, ext = os.path.splitext(new_name)
        dest = os.path.join(processing_folder(), f"{name}_{int(time.time())}{ext}")

    try:
        shutil.move(filepath, dest)
        logger.info(f"📂 Moved to processing: {os.path.basename(filepath)} → {new_name}")
        return dest
    except (IOError, shutil.Error) as exc:
        logger.error(f"❌ Failed to move to processing: {exc}")
        return None


def move_to_processed(filepath: str) -> str | None:
    """Move file from processing → processed after successful upload."""
    return _move_file(filepath, processed_folder(), "processed")


def move_to_failed(filepath: str) -> str | None:
    """Move file from processing → failed after permanent failure."""
    return _move_file(filepath, failed_folder(), "failed")


def move_duplicate_to_processed(filepath: str) -> str | None:
    """Move a duplicate file to processed/ (it was already uploaded before)."""
    return _move_file(filepath, processed_folder(), "processed (duplicate)")


# ── Internal ─────────────────────────────────────────────────────────────────

def _move_file(filepath: str, dest_dir: str, label: str) -> str | None:
    """Move a file to a destination directory."""
    if not os.path.exists(filepath):
        return None
    try:
        basename = os.path.basename(filepath)
        dest = os.path.join(dest_dir, basename)

        # Handle name collision
        if os.path.exists(dest):
            name, ext = os.path.splitext(basename)
            dest = os.path.join(dest_dir, f"{name}_{int(time.time())}{ext}")

        shutil.move(filepath, dest)
        logger.info(f"📦 Moved to {label}: {basename}")
        return dest
    except (IOError, shutil.Error) as exc:
        logger.error(f"❌ File move error ({label}): {exc}")
        return None


# ── Auto-cleanup ─────────────────────────────────────────────────────────────

def cleanup_old_files():
    """
    Periodic cleanup:
      1. Move processed files older than 7 days → archive
      2. Delete archived files older than 30 days
    """
    now = time.time()
    _age_move(processed_folder(), archive_folder(), _ARCHIVE_AFTER_DAYS, now)
    _age_delete(archive_folder(), _DELETE_AFTER_DAYS, now)


def _age_move(src_dir: str, dest_dir: str, max_days: int, now: float):
    cutoff = now - (max_days * 86400)
    try:
        for name in os.listdir(src_dir):
            path = os.path.join(src_dir, name)
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                _move_file(path, dest_dir, "archive")
    except OSError:
        pass


def _age_delete(directory: str, max_days: int, now: float):
    cutoff = now - (max_days * 86400)
    try:
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                logger.debug(f"🗑️  Deleted archived: {name}")
    except OSError:
        pass


# ── Stats ────────────────────────────────────────────────────────────────────

def get_lifecycle_stats() -> dict:
    """Return file counts per lifecycle stage."""
    stats = {}
    for label, folder_fn in [("incoming", incoming_folder),
                              ("processing", processing_folder),
                              ("processed", processed_folder),
                              ("failed", failed_folder),
                              ("archive", archive_folder)]:
        try:
            d = folder_fn()
            stats[label] = len([f for f in os.listdir(d)
                                if os.path.isfile(os.path.join(d, f))])
        except OSError:
            stats[label] = 0
    return stats
