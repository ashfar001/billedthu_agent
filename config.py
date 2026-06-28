"""
Bill Eduthu Agent - Configuration

Folder lifecycle:
  Windows: C:\\ProgramData\\BillEduthuAgent\\
  ├── incoming/      ← agent watches this
  ├── processing/    ← file moved here during upload
  ├── processed/     ← successful uploads
  ├── failed/        ← permanently failed uploads
  └── archive/       ← old processed files (auto-cleanup)
"""

import json
import os
import platform
import sys
import hashlib

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _default_data_dir() -> str:
    if platform.system() == "Windows":
        return os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "BillEduthuAgent")
    return os.path.expanduser("~/Documents/BillEduthuAgent")


DATA_DIR = os.environ.get("BILL_EDUTHU_DATA_DIR", _default_data_dir())
CONFIG_FILE = os.path.join(DATA_DIR, "settings.json")
LOG_DIR = os.path.join(DATA_DIR, "logs")
DB_FILE = os.path.join(DATA_DIR, "agent.db")

# ─── Version ─────────────────────────────────────────────────────────────────
AGENT_VERSION = "3.1.0"
CONFIG_VERSION = 7
APP_NAME = "Bill Eduthu Agent"
PRINTER_NAME = "Bill Eduthu Printer"
PRODUCTION_API_URL = os.environ.get("BILL_EDUTHU_API_URL", "https://billeduthu.onrender.com")
_DEFAULT_SETTINGS_PASSWORD_HASH = "948440723ee05890f597c8a0a727762bd0d9cff69f894cc2b2c0681ffa3ad7c8"

# ─── Keyring service name ────────────────────────────────────────────────────
_KEYRING_SERVICE = "BillEduthuAgent"
_API_KEYRING_KEY = "api_key"
_DEVICE_SECRET_KEY = "device_secret"

# ─── Defaults ────────────────────────────────────────────────────────────────
DEFAULTS = {
    "config_version": CONFIG_VERSION,
    "api_url": PRODUCTION_API_URL,
    "upload_url": "",
    "shop_id": "",
    "store_code": "",
    "merchant_name": "",
    "device_id": "",
    "counter_id": "",
    "base_folder": DATA_DIR,
    "device_port": "auto",
    "device_baud_rate": 9600,
    "device_vid_pid": "",
    "upload_retry_count": 3,
    "upload_retry_delay": 2,
    "upload_max_file_mb": 25,
    "watch_extensions": [".pdf", ".txt", ".text", ".csv"],
    "printer_name": PRINTER_NAME,
    "printer_capture_filename": "billless_capture.pdf",
    "file_stable_seconds": 2,
    "poll_interval": 1,
    "log_max_bytes": 5_242_880,
    "log_backup_count": 3,
    "auto_start": True,
    "theme": "dark",
    "heartbeat_interval": 60,
    "rate_limit_per_minute": 30,
    "require_https": True,
    "telemetry_enabled": True,
    "auto_update_enabled": True,
    "spool_poll_interval": 1,
    "backend_timeout_seconds": 30,
    "network_printer_enabled": True,
    "network_printer_host": "0.0.0.0",
    "network_printer_port": 9100,
    "google_vision_enabled": False,
    "local_ocr_enabled": True,
    "local_ocr_max_pages": 3,
    "tesseract_cmd": "",
    "activated": False,
    "machine_name": platform.node(),
    "settings_password_hash": os.environ.get(
        "BILL_EDUTHU_SETTINGS_PASSWORD_HASH",
        _DEFAULT_SETTINGS_PASSWORD_HASH,
    ),
}

# ─── Derived folder paths (computed from base_folder) ────────────────────────

def get_folder(subfolder: str) -> str:
    """Return absolute path for a lifecycle subfolder."""
    base = load().get("base_folder", DEFAULTS["base_folder"])
    return os.path.join(base, subfolder)


def incoming_folder() -> str:
    return get_folder("incoming")


def processing_folder() -> str:
    return get_folder("processing")


def processed_folder() -> str:
    return get_folder("processed")


def failed_folder() -> str:
    return get_folder("failed")


def archive_folder() -> str:
    return get_folder("archive")


def logs_folder() -> str:
    return os.path.join(load().get("base_folder", DEFAULTS["base_folder"]), "logs")


def queue_folder() -> str:
    return get_folder("queue")


def parser_profiles_folder() -> str:
    return get_folder("parser_profiles")


def spool_capture_folder() -> str:
    return os.path.join(incoming_folder(), "_spool_capture")


def printer_capture_file() -> str:
    return os.path.join(spool_capture_folder(), get("printer_capture_filename"))


# ─── Config Migrations ──────────────────────────────────────────────────────

_MIGRATIONS = {
    1: lambda cfg: cfg.update({"device_id": "", "device_vid_pid": "",
                               "upload_max_file_mb": 25, "file_stable_seconds": 2,
                               "heartbeat_interval": 60, "rate_limit_per_minute": 30,
                               "require_https": True}),
    2: lambda cfg: cfg.update({"counter_id": "", "telemetry_enabled": True,
                               "auto_update_enabled": True}),
    3: lambda cfg: cfg.update({
        "base_folder": os.path.expanduser("~/Documents/BillLess"),
    }),
    4: lambda cfg: cfg.update({
        "printer_name": PRINTER_NAME,
        "printer_capture_filename": "billless_capture.pdf",
        "spool_poll_interval": 1,
        "backend_timeout_seconds": 30,
        "network_printer_enabled": True,
        "network_printer_host": "0.0.0.0",
        "network_printer_port": 9100,
    }),
    5: lambda cfg: cfg.update({
        "store_code": cfg.get("store_code") or cfg.get("shop_id", ""),
        "merchant_name": cfg.get("merchant_name", ""),
        "upload_url": cfg.get("upload_url", ""),
        "activated": bool(cfg.get("device_id") and (cfg.get("shop_id") or cfg.get("store_code"))),
        "base_folder": DATA_DIR if sys.platform.startswith("win") else cfg.get("base_folder", DATA_DIR),
        "printer_name": PRINTER_NAME,
        "google_vision_enabled": False,
        "machine_name": platform.node(),
    }),
    6: lambda cfg: cfg.update({
        "api_url": PRODUCTION_API_URL,
        "settings_password_hash": cfg.get("settings_password_hash")
        or os.environ.get("BILL_EDUTHU_SETTINGS_PASSWORD_HASH")
        or _DEFAULT_SETTINGS_PASSWORD_HASH,
    }),
    7: lambda cfg: cfg.update({
        "network_printer_enabled": True,
        "network_printer_host": "0.0.0.0",
        "network_printer_port": 9100,
    }),
}


def _migrate_config(cfg: dict) -> dict:
    """Run config migrations to bring old configs up to current version."""
    current = cfg.get("config_version", 1)
    if current >= CONFIG_VERSION:
        return cfg

    for ver in range(current, CONFIG_VERSION):
        if ver in _MIGRATIONS:
            _MIGRATIONS[ver](cfg)

    # Remove legacy key
    cfg.pop("watch_folder", None)

    cfg["config_version"] = CONFIG_VERSION
    save(cfg)
    return cfg


# ─── Keyring helpers (encrypted API key) ─────────────────────────────────────

def _keyring_available() -> bool:
    try:
        import keyring
        return True
    except ImportError:
        return False


def get_api_key() -> str:
    """Retrieve API key from settings, falling back to system keyring."""
    configured = load().get("api_key", "")
    if configured:
        return configured
    if _keyring_available():
        import keyring
        try:
            val = keyring.get_password(_KEYRING_SERVICE, _API_KEYRING_KEY)
            if val:
                return val
        except Exception:
            pass
    return ""


def set_api_key(key: str):
    """Store API key in system keyring. Falls back to config file."""
    if _keyring_available():
        import keyring
        try:
            keyring.set_password(_KEYRING_SERVICE, _API_KEYRING_KEY, key)
            return
        except Exception:
            pass
    cfg = load()
    cfg["api_key"] = key
    save(cfg)


def get_device_secret() -> str:
    """Retrieve the backend-issued device secret without exposing it in UI."""
    if _keyring_available():
        import keyring
        try:
            val = keyring.get_password(_KEYRING_SERVICE, _DEVICE_SECRET_KEY)
            if val:
                return val
        except Exception:
            pass
    return load().get("device_secret", "")


def set_device_secret(secret: str) -> None:
    """Store the device secret securely when possible."""
    if _keyring_available():
        import keyring
        try:
            keyring.set_password(_KEYRING_SERVICE, _DEVICE_SECRET_KEY, secret)
            cfg = load()
            cfg.pop("device_secret", None)
            save(cfg)
            return
        except Exception:
            pass
    cfg = load()
    cfg["device_secret"] = secret
    save(cfg)


def clear_device_secret() -> None:
    if _keyring_available():
        import keyring
        try:
            keyring.delete_password(_KEYRING_SERVICE, _DEVICE_SECRET_KEY)
        except Exception:
            pass
    cfg = load()
    cfg.pop("device_secret", None)
    save(cfg)


# ─── Directory helpers ───────────────────────────────────────────────────────

def ensure_lifecycle_dirs():
    """Create all lifecycle directories."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(logs_folder(), exist_ok=True)
    for folder_fn in (incoming_folder, processing_folder,
                      processed_folder, failed_folder, archive_folder, queue_folder, parser_profiles_folder):
        os.makedirs(folder_fn(), exist_ok=True)
    os.makedirs(spool_capture_folder(), exist_ok=True)


def validate_watch_folder() -> tuple[bool, str]:
    """Check that the incoming folder exists and is readable/writable."""
    folder = incoming_folder()
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder, exist_ok=True)
        except PermissionError:
            return False, f"Cannot create folder: {folder}"
    if not os.access(folder, os.R_OK):
        return False, f"No read permission: {folder}"
    if not os.access(folder, os.W_OK):
        return False, f"No write permission: {folder}"
    return True, folder


def validate_api_url() -> tuple[bool, str]:
    """Enforce HTTPS unless explicitly disabled."""
    cfg = load()
    url = cfg.get("api_url", DEFAULTS["api_url"])
    require_https = cfg.get("require_https", DEFAULTS["require_https"])
    if require_https and not url.startswith("https://"):
        return False, f"HTTPS required but URL is: {url}"
    return True, url


def verify_settings_password(password: str) -> bool:
    configured_hash = load().get("settings_password_hash") or _DEFAULT_SETTINGS_PASSWORD_HASH
    entered_hash = hashlib.sha256((password or "").encode("utf-8")).hexdigest()
    return entered_hash == configured_hash


# ─── Load / Save ─────────────────────────────────────────────────────────────

def load() -> dict:
    """Load settings from disk, falling back to defaults."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                stored = json.load(f)
            merged = {**DEFAULTS, **stored}
            if sys.platform.startswith("win") and (
                str(merged.get("base_folder", "")).startswith("/Users/")
                or str(merged.get("base_folder", "")).startswith("/home/")
            ):
                merged["base_folder"] = DATA_DIR
            return merged
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULTS)


def load_and_migrate() -> dict:
    """Load settings and run any pending migrations."""
    cfg = load()
    return _migrate_config(cfg)


def save(settings: dict):
    """Persist settings to disk (atomic write)."""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(settings, f, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except Exception:
        with open(CONFIG_FILE, "w") as f:
            json.dump(settings, f, indent=2)


def get(key: str):
    """Convenience accessor for a single setting."""
    if key == "api_key":
        return get_api_key()
    # Legacy compat: watch_folder → incoming_folder
    if key == "watch_folder":
        return incoming_folder()
    return load().get(key, DEFAULTS.get(key))
