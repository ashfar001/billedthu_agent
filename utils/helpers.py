"""
BillLess Agent – Helpers / Utilities
"""

import hashlib
import os
import time


def file_hash(path: str) -> str:
    """Return SHA-256 hex digest for a file (used to detect duplicates)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def file_extension(path: str) -> str:
    """Return lowercase file extension including the dot."""
    return os.path.splitext(path)[1].lower()


def human_size(nbytes: int | float) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def timestamp() -> str:
    """ISO-8601 local timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def safe_filename(name: str) -> str:
    """Sanitise a string so it's safe for use as a filename."""
    keep = (" ", ".", "_", "-")
    return "".join(c for c in name if c.isalnum() or c in keep).strip()


def wait_for_stable_file(path: str, timeout: float = 5.0, interval: float = 0.5) -> bool:
    """
    Wait until a file's size stops changing (i.e. writing is complete).
    Returns True if file stabilised, False on timeout or missing file.
    
    Fixes: ❌ Corrupted / Incomplete Files
    """
    if not os.path.exists(path):
        return False
    
    deadline = time.monotonic() + timeout
    prev_size = -1
    stable_count = 0
    required_stable = 2  # must be same size for 2 consecutive checks

    while time.monotonic() < deadline:
        try:
            curr_size = os.path.getsize(path)
        except OSError:
            return False

        if curr_size == prev_size and curr_size > 0:
            stable_count += 1
            if stable_count >= required_stable:
                return True
        else:
            stable_count = 0

        prev_size = curr_size
        time.sleep(interval)

    return False


def validate_file_size(path: str, max_mb: float) -> tuple[bool, float]:
    """
    Check if file is within the allowed size limit.
    Returns (is_valid, size_mb).
    
    Fixes: ❌ Large File Upload Delay
    """
    try:
        size_bytes = os.path.getsize(path)
        size_mb = size_bytes / (1024 * 1024)
        return size_mb <= max_mb, size_mb
    except OSError:
        return False, 0.0
