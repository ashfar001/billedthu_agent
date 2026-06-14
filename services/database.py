"""
SQLite persistence for the BillLess Virtual Receipt Printer.

The database is the durable boundary for crash recovery: captured PDFs, parsed
receipt data, queue state, retries, backend IDs, and duplicate hashes all live
here before any network upload is attempted.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from config import DB_FILE, get


SCHEMA_VERSION = 10
_local = threading.local()


class QueueStatus:
    PENDING = "pending"
    UPLOADING = "uploading"
    FAILED = "failed"
    DEAD = "dead"
    DONE = "done"


class ReceiptStatus:
    DETECTED = "DETECTED"
    PARSED = "PARSED"
    QUEUED = "QUEUED"
    UPLOADED = "UPLOADED"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NEEDS_TABLE_ASSIGNMENT = "NEEDS_TABLE_ASSIGNMENT"


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_FILE, timeout=15)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db() -> None:
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT NOT NULL,
            bill_file TEXT DEFAULT '',
            original_filename TEXT DEFAULT '',
            file_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'DETECTED',
            shop_id TEXT DEFAULT '',
            device_id TEXT DEFAULT '',
            counter_id TEXT DEFAULT '',
            bill_number TEXT DEFAULT '',
            total REAL,
            subtotal REAL,
            tax REAL,
            cashier TEXT DEFAULT '',
            payment_method TEXT DEFAULT '',
            shop_name TEXT DEFAULT '',
            receipt_timestamp TEXT DEFAULT '',
            parsed_json TEXT DEFAULT '{}',
            server_bill_id TEXT DEFAULT '',
            server_confirmed INTEGER DEFAULT 0,
            last_error TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS upload_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            filepath TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            retries INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            next_attempt_at REAL DEFAULT 0,
            error_msg TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(receipt_id) REFERENCES receipts(id)
        );

        CREATE TABLE IF NOT EXISTS upload_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER,
            filepath TEXT NOT NULL,
            file_hash TEXT NOT NULL UNIQUE,
            server_bill_id TEXT DEFAULT '',
            uploaded_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_receipts_status ON receipts(status);
        CREATE INDEX IF NOT EXISTS idx_receipts_hash ON receipts(file_hash);
        CREATE INDEX IF NOT EXISTS idx_queue_status ON upload_queue(status, next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_history_hash ON upload_history(file_hash);
        """
    )
    _run_migrations(conn)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.execute(
        "UPDATE upload_queue SET status=?, updated_at=datetime('now','localtime') WHERE status=?",
        (QueueStatus.PENDING, QueueStatus.UPLOADING),
    )
    conn.commit()


def _run_migrations(conn: sqlite3.Connection) -> None:
    for table, column, col_type in [
        ("receipts", "filepath", "TEXT DEFAULT ''"),
        ("receipts", "bill_file", "TEXT DEFAULT ''"),
        ("receipts", "original_filename", "TEXT DEFAULT ''"),
        ("receipts", "shop_id", "TEXT DEFAULT ''"),
        ("receipts", "counter_id", "TEXT DEFAULT ''"),
        ("receipts", "bill_number", "TEXT DEFAULT ''"),
        ("receipts", "total", "REAL"),
        ("receipts", "subtotal", "REAL"),
        ("receipts", "tax", "REAL"),
        ("receipts", "cashier", "TEXT DEFAULT ''"),
        ("receipts", "payment_method", "TEXT DEFAULT ''"),
        ("receipts", "shop_name", "TEXT DEFAULT ''"),
        ("receipts", "receipt_timestamp", "TEXT DEFAULT ''"),
        ("receipts", "parsed_json", "TEXT DEFAULT '{}'"),
        ("receipts", "server_bill_id", "TEXT DEFAULT ''"),
        ("receipts", "server_confirmed", "INTEGER DEFAULT 0"),
        ("receipts", "last_error", "TEXT DEFAULT ''"),
        ("upload_queue", "receipt_id", "INTEGER DEFAULT 0"),
        ("upload_queue", "next_attempt_at", "REAL DEFAULT 0"),
        ("upload_queue", "error_msg", "TEXT DEFAULT ''"),
        ("upload_queue", "max_retries", "INTEGER DEFAULT 3"),
        ("upload_history", "receipt_id", "INTEGER"),
        ("upload_history", "server_bill_id", "TEXT DEFAULT ''"),
    ]:
        _safe_add_column(conn, table, column, col_type)


def _safe_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass


def history_exists(file_hash: str) -> bool:
    row = _conn().execute(
        "SELECT 1 FROM upload_history WHERE file_hash=? UNION SELECT 1 FROM receipts WHERE file_hash=? AND status IN (?, ?)",
        (file_hash, file_hash, ReceiptStatus.ACTIVE, ReceiptStatus.DUPLICATE),
    ).fetchone()
    return row is not None


def create_receipt(filepath: str, file_hash: str, parsed: dict[str, Any]) -> int:
    conn = _conn()
    receipt_json = parsed.get("receipt_json") or parsed
    receipt = receipt_json.get("receipt", {})
    merchant = receipt_json.get("merchant", {})
    summary = receipt_json.get("summary", {})
    metadata = receipt_json.get("metadata", {})
    status = (
        ReceiptStatus.NEEDS_TABLE_ASSIGNMENT
        if metadata.get("upload_status") == ReceiptStatus.NEEDS_TABLE_ASSIGNMENT
        else ReceiptStatus.NEEDS_REVIEW
        if metadata.get("needs_review")
        else ReceiptStatus.PARSED
    )
    cur = conn.execute(
        """
        INSERT INTO receipts (
            filepath, bill_file, original_filename, file_hash, status, shop_id, device_id,
            counter_id, bill_number, total, subtotal, tax, cashier,
            payment_method, shop_name, receipt_timestamp, parsed_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            filepath,
            filepath,
            parsed.get("original_filename", ""),
            file_hash,
            status,
            get("store_code") or get("shop_id") or "",
            get("device_id") or "",
            receipt.get("counter_id") or get("counter_id") or "",
            receipt.get("bill_number") or receipt.get("invoice_number") or "",
            summary.get("grand_total"),
            summary.get("subtotal"),
            summary.get("tax_total"),
            receipt.get("cashier", "") or "",
            receipt.get("payment_method", "") or "",
            merchant.get("name", "") or "",
            " ".join(part for part in (receipt.get("date"), receipt.get("time")) if part),
            json.dumps(receipt_json, ensure_ascii=False),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def mark_receipt(receipt_id: int, status: str, error: str = "", server_bill_id: str = "", confirmed: bool = False) -> None:
    _conn().execute(
        """
        UPDATE receipts
        SET status=?, last_error=?, server_bill_id=COALESCE(NULLIF(?, ''), server_bill_id),
            server_confirmed=?, updated_at=datetime('now','localtime')
        WHERE id=?
        """,
        (status, error, server_bill_id, 1 if confirmed else 0, receipt_id),
    )
    _conn().commit()


def queue_add(receipt_id: int, filepath: str, file_hash: str) -> int:
    cur = _conn().execute(
        """
        INSERT INTO upload_queue (receipt_id, filepath, file_hash, max_retries)
        VALUES (?, ?, ?, ?)
        """,
        (receipt_id, filepath, file_hash, int(get("upload_retry_count") or 3)),
    )
    row = _conn().execute("SELECT status FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    if not row or row["status"] not in (ReceiptStatus.NEEDS_REVIEW, ReceiptStatus.NEEDS_TABLE_ASSIGNMENT):
        mark_receipt(receipt_id, ReceiptStatus.QUEUED)
    return int(cur.lastrowid)


def queue_peek(now: float) -> dict[str, Any] | None:
    row = _conn().execute(
        """
        SELECT q.*, r.parsed_json
        FROM upload_queue q
        JOIN receipts r ON r.id = q.receipt_id
        WHERE q.status=? AND COALESCE(q.next_attempt_at, 0) <= ?
        ORDER BY q.id ASC LIMIT 1
        """,
        (QueueStatus.PENDING, now),
    ).fetchone()
    return dict(row) if row else None


def queue_mark_uploading(row_id: int) -> None:
    _conn().execute(
        "UPDATE upload_queue SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
        (QueueStatus.UPLOADING, row_id),
    )
    _conn().commit()


def queue_mark_failed(row_id: int, receipt_id: int, error: str, next_attempt_at: float) -> None:
    _conn().execute(
        """
        UPDATE upload_queue
        SET status=?, retries=retries+1, error_msg=?, next_attempt_at=?,
            updated_at=datetime('now','localtime')
        WHERE id=?
        """,
        (QueueStatus.PENDING, error, next_attempt_at, row_id),
    )
    mark_receipt(receipt_id, ReceiptStatus.FAILED, error=error)


def queue_mark_dead(row_id: int, receipt_id: int, error: str) -> None:
    _conn().execute(
        "UPDATE upload_queue SET status=?, error_msg=?, updated_at=datetime('now','localtime') WHERE id=?",
        (QueueStatus.DEAD, error, row_id),
    )
    mark_receipt(receipt_id, ReceiptStatus.FAILED, error=error)
    _conn().commit()


def queue_mark_done(row_id: int, receipt_id: int, filepath: str, file_hash: str, server_bill_id: str, confirmed: bool) -> None:
    conn = _conn()
    conn.execute("DELETE FROM upload_queue WHERE id=?", (row_id,))
    conn.execute(
        "INSERT OR IGNORE INTO upload_history (receipt_id, filepath, file_hash, server_bill_id) VALUES (?, ?, ?, ?)",
        (receipt_id, filepath, file_hash, server_bill_id),
    )
    conn.commit()
    mark_receipt(receipt_id, ReceiptStatus.ACTIVE if confirmed else ReceiptStatus.UPLOADED,
                 server_bill_id=server_bill_id, confirmed=confirmed)


def queue_counts() -> dict[str, int]:
    rows = _conn().execute("SELECT status, COUNT(*) AS count FROM upload_queue GROUP BY status").fetchall()
    counts = {QueueStatus.PENDING: 0, QueueStatus.UPLOADING: 0, QueueStatus.DEAD: 0}
    for row in rows:
        counts[row["status"]] = row["count"]
    return counts


def upload_success_count() -> int:
    row = _conn().execute("SELECT COUNT(*) FROM upload_history").fetchone()
    return int(row[0] if row else 0)


def failed_count() -> int:
    row = _conn().execute(
        "SELECT COUNT(*) FROM receipts WHERE status=?",
        (ReceiptStatus.FAILED,),
    ).fetchone()
    return int(row[0] if row else 0)


def last_receipt() -> dict[str, Any] | None:
    row = _conn().execute(
        "SELECT * FROM receipts ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None
