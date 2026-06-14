"""
Security helpers for Bill Eduthu Agent.

Uploads and heartbeats are signed with the backend-issued device secret:
HMAC_SHA256(device_secret, request_body + timestamp).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from config import get, get_device_secret


def canonical_body(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_body(body: str, timestamp: str | None = None, secret: str | None = None) -> tuple[str, str]:
    timestamp = timestamp or str(int(time.time()))
    secret = secret if secret is not None else get_device_secret()
    if not secret:
        return timestamp, ""
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{body}{timestamp}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return timestamp, signature


def sign_headers(payload: Any) -> dict[str, str]:
    body = canonical_body(payload)
    timestamp, signature = sign_body(body)
    headers = {
        "X-Device-ID": get("device_id") or "",
        "X-Timestamp": timestamp,
    }
    if signature:
        headers["X-Signature"] = signature
    return headers


def verify_signature(body: Any, timestamp: str, signature: str, secret: str, max_age_seconds: int = 300) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > max_age_seconds:
        return False
    expected_timestamp, expected = sign_body(canonical_body(body), timestamp=timestamp, secret=secret)
    return expected_timestamp == timestamp and hmac.compare_digest(expected, signature or "")
