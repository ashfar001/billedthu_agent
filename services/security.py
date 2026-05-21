"""
BillLess Agent – Security Module

Handles:
  ✅ Device identity verification (HMAC signing)
  ✅ Request signing for all API calls
  ✅ Device secret management
  ✅ Anti-spoofing protection

Fixes: ❌ Device Identity Spoofing Risk
"""

import hashlib
import hmac
import os
import time
import uuid

from config import BASE_DIR, get

_SECRET_FILE = os.path.join(BASE_DIR, ".device_secret")


def get_device_secret() -> str:
    """
    Return a persistent device-unique secret.
    Generated once and stored locally. Used for HMAC signing.
    """
    if os.path.exists(_SECRET_FILE):
        try:
            with open(_SECRET_FILE, "r") as f:
                secret = f.read().strip()
            if secret:
                return secret
        except IOError:
            pass

    # Generate new device secret
    secret = uuid.uuid4().hex + uuid.uuid4().hex   # 64-char hex
    try:
        with open(_SECRET_FILE, "w") as f:
            f.write(secret)
        # Restrict file permissions (owner-only read/write)
        os.chmod(_SECRET_FILE, 0o600)
    except IOError:
        pass
    return secret


def sign_request(payload: dict) -> str:
    """
    Create an HMAC-SHA256 signature for a request payload.
    The backend can verify this to prevent device spoofing.
    
    Signature = HMAC-SHA256(device_secret, canonical_payload + timestamp)
    """
    secret = get_device_secret()
    timestamp = str(int(time.time()))

    # Build canonical string: sorted key=value pairs + timestamp
    canonical_parts = []
    for key in sorted(payload.keys()):
        val = str(payload[key])
        canonical_parts.append(f"{key}={val}")
    canonical_parts.append(f"timestamp={timestamp}")
    canonical = "&".join(canonical_parts)

    signature = hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()

    return f"{timestamp}.{signature}"


def sign_headers(payload: dict) -> dict:
    """
    Return HTTP headers for a signed request.
    Backend checks X-Device-Signature to verify identity.
    """
    device_id = get("device_id") or get("shop_id")
    return {
        "X-Device-Id": device_id,
        "X-Device-Signature": sign_request(payload),
    }


def verify_signature(payload: dict, signature_header: str, secret: str,
                     max_age_seconds: int = 300) -> bool:
    """
    Verify a signature (for testing / local validation).
    In production, the backend does this.
    """
    try:
        timestamp_str, provided_sig = signature_header.split(".", 1)
        timestamp = int(timestamp_str)
    except (ValueError, AttributeError):
        return False

    # Check freshness
    if abs(time.time() - timestamp) > max_age_seconds:
        return False

    # Rebuild canonical
    canonical_parts = []
    for key in sorted(payload.keys()):
        val = str(payload[key])
        canonical_parts.append(f"{key}={val}")
    canonical_parts.append(f"timestamp={timestamp_str}")
    canonical = "&".join(canonical_parts)

    expected = hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(provided_sig, expected)
