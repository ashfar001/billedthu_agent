#!/usr/bin/env python3
"""
Bill Eduthu Agent launcher.

Usage on Windows:
  python start.py              Run the app using the project venv
  python start.py --setup      Create venv and install requirements
  python start.py --build      Build the Windows executable with PyInstaller
  python start.py --check      Print environment and printer prerequisites
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / "venv"
REQ = ROOT / "requirements.txt"
MAIN = ROOT / "main.py"
SPEC = ROOT / "billless_virtual_printer.spec"
SETTINGS = ROOT / "settings.json"


def venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(cmd: list[str | Path], *, check: bool = True) -> subprocess.CompletedProcess:
    printable = " ".join(str(part) for part in cmd)
    print(f"\n> {printable}")
    return subprocess.run([str(part) for part in cmd], cwd=ROOT, check=check)


def setup() -> None:
    py = venv_python()
    if not py.exists():
        if VENV.exists():
            print(f"Existing venv is not valid for this OS: {VENV}")
            print("Removing it and rebuilding a Windows venv.")
            shutil.rmtree(VENV)
        try:
            run([sys.executable, "-m", "venv", VENV])
        except subprocess.CalledProcessError:
            print("\nNormal venv creation failed while bootstrapping pip.")
            print("Retrying with --without-pip, then installing pip from the system Python.")
            if VENV.exists():
                shutil.rmtree(VENV)
            run([sys.executable, "-m", "venv", "--without-pip", VENV])
        else:
            pass
    py = venv_python()
    if not py.exists():
        raise FileNotFoundError(f"Could not create venv Python at {py}")
    if subprocess.run([str(py), "-m", "pip", "--version"], cwd=ROOT).returncode != 0:
        print("\nPip is missing in the venv. Installing it via system pip.")
        run([sys.executable, "-m", "pip", "--python", py, "install", "--upgrade", "pip"])
    else:
        run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", REQ])
    print("\nSetup complete.")


def check() -> None:
    print(f"Project: {ROOT}")
    print(f"OS: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Venv Python: {venv_python()}")
    print(f"Venv exists: {venv_python().exists()}")

    if platform.system() != "Windows":
        print("\nPrinter integration is Windows-only. You can still edit/test Python syntax here.")
        return

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-WindowsOptionalFeature -Online -FeatureName Printing-PrintToPDFServices-Features",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        print("\nMicrosoft Print to PDF feature:")
        print((result.stdout or result.stderr).strip())
    except FileNotFoundError:
        print("\nPowerShell was not found.")


def fix_settings() -> None:
    settings = {}
    if SETTINGS.exists():
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup = SETTINGS.with_suffix(".json.bak")
            shutil.copy2(SETTINGS, backup)
            print(f"settings.json was invalid JSON. Backup created: {backup}")
            settings = {}

    if platform.system() == "Windows":
        default_base = str(Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "BillEduthuAgent")
    else:
        default_base = str(Path.home() / "Documents" / "BillEduthuAgent")
    current_base = str(settings.get("base_folder", ""))
    if platform.system() == "Windows" and (
        not current_base
        or current_base.startswith("/Users/")
        or current_base.startswith("/home/")
    ):
        settings["base_folder"] = default_base

    settings.setdefault("config_version", 7)
    if not settings.get("api_url") or settings.get("api_url") == "https://billeduthu.in":
        settings["api_url"] = "https://billeduthu.onrender.com"
    settings.setdefault("require_https", True)
    settings.setdefault("shop_id", "")
    settings.setdefault("store_code", "")
    settings.setdefault("device_id", "")
    settings.setdefault("counter_id", "")
    settings.setdefault("merchant_name", "")
    settings.setdefault("printer_name", "Bill Eduthu Printer")
    settings.setdefault("printer_capture_filename", "billless_capture.pdf")
    settings.setdefault("auto_start", True)

    SETTINGS.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"Updated {SETTINGS}")
    print(f"base_folder = {settings['base_folder']}")
    print(f"printer_name = {settings['printer_name']}")


def test_backend() -> None:
    try:
        import requests
    except ImportError:
        print("requests is not installed yet. Run: python start.py --setup")
        return

    settings = {}
    if SETTINGS.exists():
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))

    api_url = str(settings.get("api_url", "")).rstrip("/")
    api_key = settings.get("api_key", "")
    shop_id = settings.get("shop_id", "")
    device_id = settings.get("device_id", "")
    counter_id = settings.get("counter_id", "")
    if not api_url or not api_key:
        print("Missing api_url or api_key in settings.json")
        return

    url = f"{api_url}/api/agent/heartbeat/"
    payload = {
        "shop_id": shop_id,
        "device_id": device_id,
        "counter_id": counter_id,
        "agent_version": "3.1.0",
        "device_status": "printer",
        "queue_pending": 0,
        "queue_failed": 0,
        "total_uploaded": 0,
    }
    headers = {
        "Authorization": f"Token {api_key}",
        "X-Agent-Version": "3.1.0",
        "X-Device-Id": device_id,
        "X-Shop-Id": shop_id,
        "X-Counter-Id": counter_id,
        "Content-Type": "application/json",
    }
    print(f"POST {url}")
    print(f"Device: {device_id} | Shop: {shop_id} | Counter: {counter_id}")
    response = requests.post(url, headers=headers, json=payload, timeout=20)
    print(f"Status: {response.status_code}")
    print(response.text[:1000])


def run_app() -> None:
    py = venv_python()
    if not py.exists():
        print("Venv not found. Running setup first.")
        setup()
    run([py, MAIN])


def build() -> None:
    py = venv_python()
    if not py.exists():
        print("Venv not found. Running setup first.")
        setup()
    run([py, "-m", "PyInstaller", SPEC])
    print("\nBuild complete. Check dist/BillEduthuAgent/")


def main() -> None:
    parser = argparse.ArgumentParser(description="BillLess launcher")
    parser.add_argument("--setup", action="store_true", help="Create venv and install requirements")
    parser.add_argument("--build", action="store_true", help="Build executable with PyInstaller")
    parser.add_argument("--check", action="store_true", help="Check environment prerequisites")
    parser.add_argument("--fix-settings", action="store_true", help="Fix Windows settings.json paths and printer defaults")
    parser.add_argument("--test-backend", action="store_true", help="Send a heartbeat request using settings.json")
    args = parser.parse_args()

    os.chdir(ROOT)
    if args.fix_settings:
        fix_settings()
        return
    if args.test_backend:
        test_backend()
        return
    if args.check:
        check()
        return
    if args.setup:
        setup()
        return
    if args.build:
        build()
        return
    run_app()


if __name__ == "__main__":
    main()
