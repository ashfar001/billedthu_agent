#!/usr/bin/env python3
"""
BillLess Virtual Receipt Printer launcher.

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

    default_base = str(Path.home() / "Documents" / "BillLess")
    current_base = str(settings.get("base_folder", ""))
    if platform.system() == "Windows" and (
        not current_base
        or current_base.startswith("/Users/")
        or current_base.startswith("/home/")
    ):
        settings["base_folder"] = default_base

    settings.setdefault("config_version", 5)
    settings.setdefault("api_url", "http://127.0.0.1:8000")
    settings.setdefault("require_https", False)
    settings.setdefault("shop_id", "SHOP001")
    settings.setdefault("device_id", "DEV001")
    settings.setdefault("counter_id", "C1")
    settings.setdefault("printer_name", "BillLess Printer")
    settings.setdefault("printer_capture_filename", "billless_capture.pdf")
    settings.setdefault("auto_start", False)

    SETTINGS.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"Updated {SETTINGS}")
    print(f"base_folder = {settings['base_folder']}")
    print(f"printer_name = {settings['printer_name']}")


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
    print("\nBuild complete. Check dist/BillLessVirtualReceiptPrinter/")


def main() -> None:
    parser = argparse.ArgumentParser(description="BillLess launcher")
    parser.add_argument("--setup", action="store_true", help="Create venv and install requirements")
    parser.add_argument("--build", action="store_true", help="Build executable with PyInstaller")
    parser.add_argument("--check", action="store_true", help="Check environment prerequisites")
    parser.add_argument("--fix-settings", action="store_true", help="Fix Windows settings.json paths and printer defaults")
    args = parser.parse_args()

    os.chdir(ROOT)
    if args.fix_settings:
        fix_settings()
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
