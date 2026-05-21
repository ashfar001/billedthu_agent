"""
Windows user-mode virtual printer setup.

This does not install a kernel driver. It creates a normal Windows printer named
"BillLess Printer" using the built-in "Microsoft Print To PDF" driver and a
fixed local-port file. The capture service renames that file after each job.
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass

from config import get, printer_capture_file, ensure_lifecycle_dirs
from services import logger


PDF_DRIVER_NAME = "Microsoft Print To PDF"


@dataclass
class PrinterState:
    available: bool
    installed: bool
    name: str
    message: str = ""


class VirtualPrinter:
    def __init__(self, name: str | None = None):
        self.name = name or get("printer_name")

    @property
    def is_windows(self) -> bool:
        return platform.system() == "Windows"

    def status(self) -> PrinterState:
        if not self.is_windows:
            return PrinterState(False, False, self.name, "Windows 10/11 required")
        try:
            import win32print
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            printers = win32print.EnumPrinters(flags)
            names = {printer[2] for printer in printers}
            installed = self.name in names
            return PrinterState(installed, installed, self.name,
                                "Ready" if installed else "Printer is not installed")
        except Exception as exc:
            return PrinterState(False, False, self.name, str(exc))

    def ensure_installed(self) -> PrinterState:
        state = self.status()
        if state.installed:
            return state
        if not self.is_windows:
            logger.warning("BillLess Printer can only be installed on Windows 10/11")
            return state

        ensure_lifecycle_dirs()
        capture_path = printer_capture_file()
        os.makedirs(os.path.dirname(capture_path), exist_ok=True)

        script = (
            "$ErrorActionPreference='Stop';"
            f"$port='{capture_path}';"
            f"$printer='{self.name}';"
            f"$driver='{PDF_DRIVER_NAME}';"
            "if (-not (Get-PrinterDriver -Name $driver -ErrorAction SilentlyContinue)) "
            "{ throw 'Microsoft Print To PDF driver is not installed. Enable Windows optional feature Microsoft-Print-To-PDF.' };"
            "if (-not (Get-PrinterPort -Name $port -ErrorAction SilentlyContinue)) "
            "{ Add-PrinterPort -Name $port };"
            "if (-not (Get-Printer -Name $printer -ErrorAction SilentlyContinue)) "
            "{ Add-Printer -Name $printer -DriverName $driver -PortName $port };"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"Installed Windows printer: {self.name}")
        except subprocess.CalledProcessError as exc:
            msg = (exc.stderr or exc.stdout or str(exc)).strip()
            logger.error(f"Could not install {self.name}: {msg}")
            return PrinterState(False, False, self.name, msg)
        return self.status()

    def test_print(self) -> bool:
        if not self.is_windows:
            logger.warning("Test print is available only on Windows")
            return False
        try:
            import win32api
            test_file = os.path.join(os.environ.get("TEMP", os.getcwd()), "billless_test_print.txt")
            with open(test_file, "w", encoding="utf-8") as handle:
                handle.write("BillLess test receipt\nItem 1 1 10.00 10.00\nTotal 10.00\n")
            win32api.ShellExecute(0, "printto", test_file, f'"{self.name}"', ".", 0)
            logger.info("Sent test print to BillLess Printer")
            return True
        except Exception as exc:
            logger.error(f"Test print failed: {exc}")
            return False
