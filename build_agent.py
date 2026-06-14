#!/usr/bin/env python3
"""
Production build helper for Bill Eduthu Agent.

Usage:
  python build_agent.py

Outputs:
  dist/BillEduthuAgent/
  installer/BillEduthuAgentSetup.exe when Inno Setup is installed on Windows
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "billless_virtual_printer.spec"
INSTALLER_SCRIPT = ROOT / "installer" / "BillEduthuAgent.iss"


def run(cmd: list[str | Path]) -> None:
    print("> " + " ".join(str(part) for part in cmd))
    subprocess.run([str(part) for part in cmd], cwd=ROOT, check=True)


def main() -> None:
    run([sys.executable, "-m", "PyInstaller", "--clean", SPEC])
    print("\nExecutable build ready: dist/BillEduthuAgent/")

    if platform.system() != "Windows":
        print("Installer build skipped: Inno Setup runs on Windows.")
        return

    iscc = shutil.which("ISCC.exe") or shutil.which("iscc")
    if not iscc:
        print("Installer build skipped: install Inno Setup and ensure ISCC.exe is on PATH.")
        return

    os.makedirs(ROOT / "installer", exist_ok=True)
    run([iscc, INSTALLER_SCRIPT])
    print("Installer ready: installer/BillEduthuAgentSetup.exe")


if __name__ == "__main__":
    main()
