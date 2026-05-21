"""
Capture the fixed Microsoft Print to PDF output file and move it into incoming.
"""

from __future__ import annotations

import os
import shutil
import threading
import time

from config import get, incoming_folder, printer_capture_file
from services import logger
from services.file_manager import generate_unique_name
from utils.helpers import wait_for_stable_file


class PDFCaptureService:
    def __init__(self, on_captured):
        self._on_captured = on_captured
        self._running = False
        self._thread: threading.Thread | None = None
        self.last_captured: str = ""

    @property
    def running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"PDF capture watching {printer_capture_file()}")

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while self._running:
            path = printer_capture_file()
            if os.path.exists(path) and wait_for_stable_file(path, timeout=float(get("file_stable_seconds") or 2)):
                self._capture(path)
            time.sleep(0.5)

    def _capture(self, path: str) -> None:
        name = generate_unique_name(path)
        dest = os.path.join(incoming_folder(), name)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(name)
            dest = os.path.join(incoming_folder(), f"{stem}_{int(time.time())}{ext}")
        try:
            shutil.move(path, dest)
            self.last_captured = os.path.basename(dest)
            logger.info(f"Captured receipt PDF: {self.last_captured}")
            self._on_captured(dest)
        except Exception as exc:
            logger.error(f"Could not capture PDF output: {exc}")
