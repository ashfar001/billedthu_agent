#!/usr/bin/env python3
"""
BillLess Virtual Receipt Printer - Entry Point.

Windows-only user-mode virtual printer workflow:
POS print -> BillLess Printer -> silent PDF capture -> parse -> upload.
"""

from __future__ import annotations

import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication

from config import (
    AGENT_VERSION,
    ensure_lifecycle_dirs,
    get,
    load_and_migrate,
    printer_capture_file,
    validate_api_url,
)
from services import logger
from services.database import init_db
from services.file_manager import cleanup_old_files
from services.heartbeat import HeartbeatService
from services.pdf_capture import PDFCaptureService
from services.spool_monitor import SpoolMonitor
from services.uploader import Uploader
from services.virtual_printer import VirtualPrinter
from ui.main_window import MainWindow


def _preflight_checks() -> None:
    logger.info(f"BillLess Virtual Receipt Printer v{AGENT_VERSION}")
    logger.info(f"Platform: {platform.system()} {platform.release()}")
    if platform.system() != "Windows":
        logger.warning("This product is Windows-only. Printer capture is disabled on this OS.")

    cfg = load_and_migrate()
    logger.info(f"Config version: {cfg.get('config_version', '?')}")

    ok, msg = validate_api_url()
    if ok:
        logger.info(f"Backend API: {get('api_url')}")
    else:
        logger.warning(msg)

    logger.info(f"Printer name: {get('printer_name')}")
    logger.info(f"PDF capture file: {printer_capture_file()}")
    logger.info(
        f"Shop: {get('shop_id') or '-'} | "
        f"Device: {get('device_id') or '-'} | "
        f"Counter: {get('counter_id') or '-'}"
    )


def main() -> None:
    logger.info("=" * 56)
    logger.info("BillLess Virtual Receipt Printer starting")
    logger.info("=" * 56)

    _preflight_checks()
    ensure_lifecycle_dirs()

    try:
        init_db()
        logger.info("SQLite queue initialised in WAL mode")
    except Exception as exc:
        logger.error(f"Database init failed: {exc}")
        sys.exit(1)

    try:
        cleanup_old_files()
    except Exception:
        pass

    virtual_printer = VirtualPrinter()
    printer_state = virtual_printer.ensure_installed()
    if not printer_state.available:
        logger.warning(f"Printer unavailable: {printer_state.message}")

    uploader = Uploader()
    pdf_capture = PDFCaptureService(on_captured=uploader.enqueue)
    spool_monitor = SpoolMonitor(printer_name=get("printer_name"))
    heartbeat = HeartbeatService(device=None, uploader=uploader)

    app = QApplication(sys.argv)
    app.setApplicationName("BillLess Virtual Receipt Printer")
    app.setOrganizationName("BillLess")
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow(
        virtual_printer=virtual_printer,
        spool_monitor=spool_monitor,
        pdf_capture=pdf_capture,
        uploader=uploader,
        heartbeat=heartbeat,
    )

    spool_monitor.start()
    pdf_capture.start()
    uploader.start()
    heartbeat.start()
    logger.info("Background printer capture services running")

    window.show()
    exit_code = app.exec()

    logger.info("Shutting down")
    heartbeat.stop()
    pdf_capture.stop()
    spool_monitor.stop()
    uploader.stop()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
