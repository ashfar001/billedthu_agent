"""
Setup-code activation for Bill Eduthu Agent.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass

import requests

from config import get, load, save, set_device_secret, clear_device_secret, ensure_lifecycle_dirs
from services import logger


@dataclass
class ActivationResult:
    success: bool
    message: str
    payload: dict | None = None


def is_activated() -> bool:
    return bool(get("activated") and get("device_id") and (get("store_code") or get("shop_id")))


def activate_with_setup_code(setup_code: str, api_url: str | None = None, machine_name: str | None = None) -> ActivationResult:
    setup_code = setup_code.strip().upper()
    if not setup_code:
        return ActivationResult(False, "Enter a setup code.")

    base_url = (api_url or get("api_url") or "").rstrip("/")
    if not base_url:
        return ActivationResult(False, "API URL is missing.")

    payload = {
        "setup_code": setup_code,
        "machine_name": machine_name or platform.node(),
    }
    url = f"{base_url}/api/agent/activate/"
    try:
        response = requests.post(url, json=payload, timeout=int(get("backend_timeout_seconds") or 30))
    except requests.ConnectionError:
        return ActivationResult(False, "Cannot reach Bill Eduthu server.")
    except requests.Timeout:
        return ActivationResult(False, "Activation request timed out.")
    except Exception as exc:
        return ActivationResult(False, str(exc))

    if response.status_code not in (200, 201):
        return ActivationResult(False, "Invalid or expired setup code. Contact Bill Eduthu support.")

    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    required = ("device_id", "device_secret", "counter_id")
    missing = [key for key in required if not data.get(key)]
    if missing:
        return ActivationResult(False, f"Activation response missing: {', '.join(missing)}")

    store_code = data.get("store_code") or data.get("shop_id") or ""
    cfg = load()
    cfg.update({
        "api_url": base_url,
        "upload_url": data.get("upload_url", cfg.get("upload_url", "")),
        "device_id": data["device_id"],
        "shop_id": store_code,
        "store_code": store_code,
        "counter_id": data["counter_id"],
        "merchant_name": data.get("merchant_name", ""),
        "machine_name": payload["machine_name"],
        "activated": True,
    })
    cfg.pop("api_key", None)
    cfg.pop("device_secret", None)
    save(cfg)
    set_device_secret(data["device_secret"])
    ensure_lifecycle_dirs()
    logger.info(
        f"Agent activated for {cfg.get('merchant_name') or store_code} "
        f"counter {cfg.get('counter_id')}"
    )
    return ActivationResult(True, "Activation complete.", data)


def reset_activation() -> None:
    cfg = load()
    for key in ("device_id", "counter_id", "store_code", "shop_id", "merchant_name", "upload_url"):
        cfg[key] = ""
    cfg["activated"] = False
    save(cfg)
    clear_device_secret()
    logger.warning("Agent setup was reset")
