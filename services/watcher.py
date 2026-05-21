"""
BillLess Agent – File Watcher Service (v3)

Watches:  ~/Documents/BillLess/incoming/

On new PDF/CSV:
  1. Wait for file to finish writing (stability check)
  2. Debounce by path (avoid double-fire)
  3. Call callback (which triggers the upload pipeline)
"""

import os
import threading

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import get, incoming_folder, validate_watch_folder
from services import logger
from utils.helpers import file_extension, wait_for_stable_file


class _BillHandler(FileSystemEventHandler):
    """React only to created/moved files with allowed extensions."""

    def __init__(self, callback, extensions):
        super().__init__()
        self.callback = callback
        self.extensions = extensions
        self._seen_paths: set[str] = set()
        self._lock = threading.Lock()

    def _handle(self, path: str):
        # ── Extension whitelist ──────────────────────────────────────────
        ext = file_extension(path)
        if ext not in self.extensions:
            return

        # ── Path-level debounce ──────────────────────────────────────────
        with self._lock:
            if path in self._seen_paths:
                return
            self._seen_paths.add(path)

        # ── Wait for file to finish writing ──────────────────────────────
        stable_timeout = get("file_stable_seconds")
        if not wait_for_stable_file(path, timeout=stable_timeout):
            logger.warning(f"⚠️  File never stabilised, skipping: {os.path.basename(path)}")
            with self._lock:
                self._seen_paths.discard(path)
            return

        if not os.path.exists(path):
            return

        logger.info(f"📄 New file in incoming: {os.path.basename(path)}")
        try:
            self.callback(path)
        except Exception as exc:
            logger.error(f"Callback error for {path}: {exc}")
        finally:
            # Allow same filename to be detected again later
            # (e.g. user drops another file with same name)
            with self._lock:
                self._seen_paths.discard(path)

    def on_created(self, event):
        if not event.is_directory:
            threading.Thread(
                target=self._handle, args=(event.src_path,), daemon=True
            ).start()

    def on_moved(self, event):
        if not event.is_directory:
            threading.Thread(
                target=self._handle, args=(event.dest_path,), daemon=True
            ).start()


class FolderWatcher:
    """Watches ~/Documents/BillLess/incoming/ for new billing files."""

    def __init__(self, on_new_file):
        self._callback = on_new_file
        self._observer: Observer | None = None
        self.error: str | None = None

    def start(self):
        # ── Validate folder permissions ──────────────────────────────────
        ok, msg = validate_watch_folder()
        if not ok:
            self.error = msg
            logger.error(f"❌ Watch folder error: {msg}")
            return False

        folder = incoming_folder()
        extensions = get("watch_extensions")

        handler = _BillHandler(self._callback, extensions)
        self._observer = Observer()
        self._observer.schedule(handler, folder, recursive=False)
        self._observer.daemon = True
        self._observer.start()
        self.error = None
        logger.info(f"👁️  Watching: {folder}")
        return True

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None
            logger.info("👁️  Watcher stopped")

    @property
    def running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
