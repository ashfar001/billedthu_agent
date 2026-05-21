"""
Windows print spool monitor for the BillLess printer queue.
"""

from __future__ import annotations

import platform
import threading
import time

from config import get
from services import logger


class SpoolMonitor:
    def __init__(self, printer_name: str | None = None):
        self.printer_name = printer_name or get("printer_name")
        self._running = False
        self._thread: threading.Thread | None = None
        self._active_jobs: dict[int, str] = {}
        self.last_job: str = ""
        self.error: str = ""

    @property
    def running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"Spool monitor started for {self.printer_name}")

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        if platform.system() != "Windows":
            self.error = "Windows print spool is unavailable on this OS"
            logger.warning(self.error)
            while self._running:
                time.sleep(5)
            return

        try:
            import win32print
        except Exception as exc:
            self.error = f"pywin32 unavailable: {exc}"
            logger.error(self.error)
            return

        while self._running:
            try:
                handle = win32print.OpenPrinter(self.printer_name)
                try:
                    jobs = win32print.EnumJobs(handle, 0, 99, 1)
                finally:
                    win32print.ClosePrinter(handle)

                seen = set()
                for job in jobs:
                    job_id = job.get("JobId")
                    document = job.get("pDocument") or "Receipt"
                    seen.add(job_id)
                    if job_id not in self._active_jobs:
                        self._active_jobs[job_id] = document
                        self.last_job = document
                        logger.info(f"Print job received: {document}")

                completed = [job_id for job_id in self._active_jobs if job_id not in seen]
                for job_id in completed:
                    document = self._active_jobs.pop(job_id, "Receipt")
                    logger.info(f"Print job released by spooler: {document}")
                self.error = ""
            except Exception as exc:
                self.error = str(exc)
                logger.debug(f"Spool monitor check failed: {exc}")
            time.sleep(float(get("spool_poll_interval") or 1))
