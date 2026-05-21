"""
BillLess Agent – SQLite Queue & State Store (v3)

Hardened with:
  ✅ Claim token system (device_id + session_id + timestamp binding)
  ✅ Full E2E state machine: DETECTED → QUEUED → UPLOADED → CONFIRMED → ACTIVE
  ✅ Counter-aware receipts (shop_id + device_id + counter_id)
  ✅ Mid-upload crash recovery (uploading → pending on restart)
  ✅ Server-time sync fields
  ✅ Config version tracking for migrations
"""

import os
import sqlite3
import threading
import time
import uuid

from config import DB_FILE

_local = threading.local()

# ── Schema version for migrations ────────────────────────────────────────────
SCHEMA_VERSION = 3


def _conn() -> sqlite3.Connection:
    """Return a thread-local connection (SQLite is not thread-safe)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_FILE, timeout=10)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")   # crash-safe
        _local.conn.execute("PRAGMA busy_timeout=5000")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """
    Create tables if they don't exist.  Safe to call multiple times.
    Handles upgrades from older schemas by running migrations
    before creating indexes on new columns.
    """
    conn = _conn()

    # Step 1: Create core tables (minimal schema that always works)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS upload_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath    TEXT    NOT NULL,
            file_hash   TEXT,
            status      TEXT    DEFAULT 'pending',
            retries     INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS upload_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath    TEXT    NOT NULL,
            file_hash   TEXT    UNIQUE NOT NULL,
            uploaded_at TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS receipts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_file   TEXT    NOT NULL,
            file_hash   TEXT    NOT NULL,
            status      TEXT    DEFAULT 'DETECTED',
            device_id   TEXT,
            created_at  TEXT    DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_queue_status ON upload_queue(status);
        CREATE INDEX IF NOT EXISTS idx_history_hash ON upload_history(file_hash);
        CREATE INDEX IF NOT EXISTS idx_receipt_status ON receipts(status);
    """)
    conn.commit()

    # Step 2: Run migrations to add new columns to existing tables
    run_migrations()

    # Step 3: Create indexes on new columns (safe now that columns exist)
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_receipt_device ON receipts(device_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_receipt_token ON receipts(claim_token)",
    ]:
        try:
            conn.execute(idx_sql)
        except sqlite3.OperationalError:
            pass  # column may not exist in very old schemas
    conn.commit()

    # Crash recovery: reset any stuck 'uploading' items back to 'pending'
    _recover_stuck_uploads()


def _recover_stuck_uploads():
    """On startup, move 'uploading' items back to 'pending' (mid-upload crash)."""
    conn = _conn()
    cur = conn.execute(
        "UPDATE upload_queue SET status='pending', "
        "updated_at=datetime('now','localtime') WHERE status='uploading'"
    )
    if cur.rowcount > 0:
        from services import logger
        logger.info(f"🔄 Recovered {cur.rowcount} mid-upload items from crash")
    conn.commit()


def get_schema_version() -> int:
    """Return current schema version."""
    conn = _conn()
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row["value"]) if row else 0


# ── Upload Queue ─────────────────────────────────────────────────────────────

def queue_add(filepath: str, file_hash: str) -> int:
    """Add a file to the upload queue. Returns row ID."""
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO upload_queue (filepath, file_hash) VALUES (?, ?)",
        (filepath, file_hash),
    )
    conn.commit()
    return cur.lastrowid


def queue_peek() -> dict | None:
    """Return the oldest pending item, or None."""
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM upload_queue WHERE status = 'pending' "
        "ORDER BY id ASC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def queue_peek_batch(limit: int = 5) -> list[dict]:
    """Return multiple pending items for batch upload."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM upload_queue WHERE status = 'pending' "
        "ORDER BY id ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def queue_mark_uploading(row_id: int):
    conn = _conn()
    conn.execute(
        "UPDATE upload_queue SET status='uploading', "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (row_id,),
    )
    conn.commit()


def queue_mark_uploaded(row_id: int):
    """Mark as uploaded but not yet confirmed by backend."""
    conn = _conn()
    conn.execute(
        "UPDATE upload_queue SET status='uploaded', "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (row_id,),
    )
    conn.commit()


def queue_mark_confirmed(row_id: int):
    """Backend confirmed storage — safe to remove from queue."""
    conn = _conn()
    conn.execute("DELETE FROM upload_queue WHERE id=?", (row_id,))
    conn.commit()


def queue_mark_done(row_id: int):
    """Legacy: immediate remove (for non-E2E mode)."""
    conn = _conn()
    conn.execute("DELETE FROM upload_queue WHERE id=?", (row_id,))
    conn.commit()


def queue_mark_failed(row_id: int, error_msg: str = ""):
    conn = _conn()
    conn.execute(
        "UPDATE upload_queue SET status='failed', retries=retries+1, "
        "error_msg=?, updated_at=datetime('now','localtime') WHERE id=?",
        (error_msg, row_id),
    )
    conn.commit()


def queue_mark_dead(row_id: int):
    """Permanently failed — exceeded max retries."""
    conn = _conn()
    conn.execute(
        "UPDATE upload_queue SET status='dead', "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (row_id,),
    )
    conn.commit()


def queue_retry_failed():
    """Move 'failed' items back to 'pending' for another attempt."""
    conn = _conn()
    conn.execute(
        "UPDATE upload_queue SET status='pending', "
        "updated_at=datetime('now','localtime') WHERE status='failed'"
    )
    conn.commit()


def queue_count() -> dict:
    """Return counts by status."""
    conn = _conn()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM upload_queue GROUP BY status"
    ).fetchall()
    result = {"pending": 0, "uploading": 0, "uploaded": 0,
              "confirmed": 0, "failed": 0, "dead": 0}
    for r in rows:
        result[r["status"]] = r["cnt"]
    return result


# ── Upload History (dedup) ───────────────────────────────────────────────────

def history_exists(file_hash: str) -> bool:
    conn = _conn()
    row = conn.execute(
        "SELECT 1 FROM upload_history WHERE file_hash=?", (file_hash,)
    ).fetchone()
    return row is not None


def history_add(filepath: str, file_hash: str,
                server_bill_id: str = "", server_timestamp: str = ""):
    """Record a successful upload with server-provided IDs."""
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO upload_history "
            "(filepath, file_hash, server_bill_id, server_timestamp) "
            "VALUES (?, ?, ?, ?)",
            (filepath, file_hash, server_bill_id, server_timestamp),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass


def history_count() -> int:
    conn = _conn()
    row = conn.execute("SELECT COUNT(*) FROM upload_history").fetchone()
    return row[0] if row else 0


# ── Receipt Lifecycle ────────────────────────────────────────────────────────
#
#  Full E2E state machine:
#    DETECTED → QUEUED → UPLOADED → CONFIRMED → ACTIVE → CLAIMED
#                                                     ↘ EXPIRED
#
#  Only ONE active receipt per (device_id + counter_id) at any time.
#  Each receipt gets a unique claim_token bound to:
#    device_id + counter_id + session_id + timestamp

class ReceiptStatus:
    DETECTED = "DETECTED"
    QUEUED = "QUEUED"
    UPLOADED = "UPLOADED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"


def _generate_claim_token(device_id: str, counter_id: str, session_id: str) -> str:
    """
    Generate a unique claim token bound to device + counter + session + time.
    Format: {device_id}-{counter_id}-{session_id}-{timestamp}-{uuid4_short}
    
    This prevents race conditions: User A's claim token is different from User B's.
    """
    ts = str(int(time.time()))
    uid = uuid.uuid4().hex[:8]
    return f"{device_id}-{counter_id}-{session_id}-{ts}-{uid}"


def receipt_create(bill_file: str, file_hash: str, device_id: str,
                   counter_id: str = "", shop_id: str = "",
                   session_id: str = "") -> int:
    """
    Create a new receipt in DETECTED state.
    Auto-expires any previous ACTIVE receipt on this device+counter.
    Generates a unique claim token.
    """
    conn = _conn()

    # Expire old active receipts for this device+counter (only 1 active at a time)
    conn.execute(
        "UPDATE receipts SET status=?, updated_at=datetime('now','localtime') "
        "WHERE device_id=? AND counter_id=? AND status IN (?, ?)",
        (ReceiptStatus.EXPIRED, device_id, counter_id,
         ReceiptStatus.ACTIVE, ReceiptStatus.CONFIRMED),
    )

    # Generate session if not provided
    if not session_id:
        session_id = uuid.uuid4().hex[:12]

    claim_token = _generate_claim_token(device_id, counter_id, session_id)

    cur = conn.execute(
        "INSERT INTO receipts "
        "(bill_file, file_hash, device_id, counter_id, shop_id, "
        " session_id, claim_token, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (bill_file, file_hash, device_id, counter_id, shop_id,
         session_id, claim_token, ReceiptStatus.DETECTED),
    )
    conn.commit()
    return cur.lastrowid


def receipt_transition(receipt_id: int, new_status: str,
                       server_time: str = ""):
    """Move a receipt to the next state."""
    conn = _conn()
    if server_time:
        conn.execute(
            "UPDATE receipts SET status=?, server_time=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (new_status, server_time, receipt_id),
        )
    else:
        conn.execute(
            "UPDATE receipts SET status=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (new_status, receipt_id),
        )
    conn.commit()


def receipt_claim_by_token(claim_token: str) -> dict | None:
    """
    Claim a receipt using its unique token.
    Only works if receipt is ACTIVE. Returns receipt dict or None.
    
    This prevents race conditions — each customer gets a unique token
    bound to their device/counter/session/timestamp.
    """
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM receipts WHERE claim_token=? AND status=?",
        (claim_token, ReceiptStatus.ACTIVE),
    ).fetchone()

    if not row:
        return None

    conn.execute(
        "UPDATE receipts SET status=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (ReceiptStatus.CLAIMED, row["id"]),
    )
    conn.commit()
    return dict(row)


def receipt_activate(receipt_id: int):
    """Shortcut: transition to ACTIVE."""
    receipt_transition(receipt_id, ReceiptStatus.ACTIVE)


def receipt_expire_stale(max_age_seconds: int = 300):
    """Expire receipts that have been ACTIVE for too long (default 5 min)."""
    conn = _conn()
    conn.execute(
        "UPDATE receipts SET status=?, updated_at=datetime('now','localtime') "
        "WHERE status=? AND "
        "(strftime('%%s','now','localtime') - strftime('%%s', updated_at)) > ?",
        (ReceiptStatus.EXPIRED, ReceiptStatus.ACTIVE, max_age_seconds),
    )
    conn.commit()


def receipt_active_for_device(device_id: str,
                              counter_id: str = "") -> dict | None:
    """Return the currently active receipt for a device+counter, or None."""
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM receipts WHERE device_id=? AND counter_id=? "
        "AND status=? LIMIT 1",
        (device_id, counter_id, ReceiptStatus.ACTIVE),
    ).fetchone()
    return dict(row) if row else None


# ── Config Migration ─────────────────────────────────────────────────────────

def run_migrations():
    """
    Run schema migrations based on version.
    Each migration is idempotent (safe to re-run).
    """
    current = get_schema_version()
    conn = _conn()

    if current < 2:
        # Migration 1→2: Add counter_id, claim_token, session_id
        _safe_add_column(conn, "receipts", "counter_id", "TEXT DEFAULT ''")
        _safe_add_column(conn, "receipts", "claim_token", "TEXT DEFAULT ''")
        _safe_add_column(conn, "receipts", "session_id", "TEXT DEFAULT ''")
        _safe_add_column(conn, "receipts", "server_time", "TEXT DEFAULT ''")
        _safe_add_column(conn, "receipts", "expires_at", "TEXT DEFAULT ''")
        _safe_add_column(conn, "receipts", "shop_id", "TEXT DEFAULT ''")

    if current < 3:
        # Migration 2→3: Add error_msg, max_retries, batch fields
        _safe_add_column(conn, "upload_queue", "error_msg", "TEXT DEFAULT ''")
        _safe_add_column(conn, "upload_queue", "max_retries", "INTEGER DEFAULT 3")
        _safe_add_column(conn, "upload_history", "server_bill_id", "TEXT DEFAULT ''")
        _safe_add_column(conn, "upload_history", "server_timestamp", "TEXT DEFAULT ''")

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def _safe_add_column(conn, table: str, column: str, col_type: str):
    """Add a column if it doesn't exist (SQLite has no IF NOT EXISTS for ALTER)."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass  # Column already exists
