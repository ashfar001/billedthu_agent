"""
Store-specific parser profile support.

Profiles let support/admin teach the agent a known receipt structure without
changing code for every POS format.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from config import BASE_DIR, get, parser_profiles_folder


def load_parser_profile(raw_text: str = "") -> dict[str, Any]:
    profile: dict[str, Any] = {}
    for path in _candidate_paths():
        if not os.path.exists(path):
            continue
        if path.lower().endswith(".json"):
            profile.update(_read_json_profile(path))
        elif path.lower().endswith((".txt", ".text")):
            profile.update(_infer_profile_from_sample(_read_text(path)))

    if not profile and raw_text:
        profile.update(_infer_profile_from_sample(raw_text))
    return profile


def _candidate_paths() -> list[str]:
    names = []
    for value in (get("store_code"), get("shop_id"), get("merchant_name")):
        safe = _safe_name(value or "")
        if safe and safe not in names:
            names.append(safe)

    folders = [
        parser_profiles_folder(),
        os.path.join(BASE_DIR, "parser_profiles"),
    ]
    paths = []
    for folder in folders:
        for name in names:
            paths.append(os.path.join(folder, f"{name}.json"))
            paths.append(os.path.join(folder, f"{name}.txt"))
    return paths


def _read_json_profile(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except Exception:
        return ""


def _infer_profile_from_sample(text: str) -> dict[str, Any]:
    lower = text.lower()
    profile: dict[str, Any] = {}
    if re.search(r"\bitem\b.{0,20}\bprice\b.{0,20}\bqty\b.{0,20}\btotal\b", lower, re.S):
        profile["item_layout"] = "item_price_qty_total"
    elif re.search(r"\bitem\b.{0,20}\bqty\b.{0,20}\bprice\b.{0,20}\btotal\b", lower, re.S):
        profile["item_layout"] = "item_qty_price_total"

    total_labels = []
    if "sub-total" in lower:
        total_labels.append("sub-total")
    if total_labels:
        profile["subtotal_labels"] = total_labels
    return profile


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return safe.strip("_")
