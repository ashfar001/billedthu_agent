"""
Single-instance guard for the desktop agent.
"""

from __future__ import annotations

import os
import platform

from config import DATA_DIR


class SingleInstance:
    def __init__(self, name: str = "BillEduthuAgent"):
        self.name = name
        self._handle = None
        self._lock_file = None

    def acquire(self) -> bool:
        if platform.system() == "Windows":
            try:
                import win32api
                import win32event
                import winerror

                self._handle = win32event.CreateMutex(None, False, self.name)
                return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS
            except Exception:
                return True

        try:
            import fcntl

            os.makedirs(DATA_DIR, exist_ok=True)
            self._lock_file = open(os.path.join(DATA_DIR, "agent.lock"), "w")
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except Exception:
            return False

    def release(self) -> None:
        if self._handle:
            try:
                import win32api

                win32api.CloseHandle(self._handle)
            except Exception:
                pass
        if self._lock_file:
            try:
                self._lock_file.close()
            except Exception:
                pass
