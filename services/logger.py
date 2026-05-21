"""
BillLess Agent – Logger Service
Rotating file logger + in-memory ring buffer for the UI log viewer.
"""

import logging
import os
import threading
from collections import deque
from logging.handlers import RotatingFileHandler

from config import LOG_DIR, get

os.makedirs(LOG_DIR, exist_ok=True)


# ── In-memory ring buffer (last 500 entries for UI) ─────────────────────────
_buffer: deque = deque(maxlen=500)
_buffer_lock = threading.Lock()
_listeners: list = []           # callables that receive new log lines


class _BufferHandler(logging.Handler):
    """Push every formatted record into the ring buffer + notify listeners."""

    def emit(self, record):
        msg = self.format(record)
        with _buffer_lock:
            _buffer.append(msg)
        for cb in _listeners:
            try:
                cb(msg)
            except Exception:
                pass


def add_listener(callback):
    """Register a callable that receives each new log line (for UI)."""
    _listeners.append(callback)


def get_history() -> list[str]:
    """Return a snapshot of buffered log lines."""
    with _buffer_lock:
        return list(_buffer)


# ── Build the root logger once ──────────────────────────────────────────────
_logger = logging.getLogger("billless")
_logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter(
    "[%(asctime)s] %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# File handler (rotating)
_fh = RotatingFileHandler(
    os.path.join(LOG_DIR, "agent.log"),
    maxBytes=get("log_max_bytes"),
    backupCount=get("log_backup_count"),
)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
_logger.addHandler(_fh)

# Console handler
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(_fmt)
_logger.addHandler(_ch)

# Buffer handler (for UI)
_bh = _BufferHandler()
_bh.setLevel(logging.DEBUG)
_bh.setFormatter(_fmt)
_logger.addHandler(_bh)


# ── Public helpers ──────────────────────────────────────────────────────────
def debug(msg: str):
    _logger.debug(msg)


def info(msg: str):
    _logger.info(msg)


def warning(msg: str):
    _logger.warning(msg)


def error(msg: str):
    _logger.error(msg)


def critical(msg: str):
    _logger.critical(msg)
