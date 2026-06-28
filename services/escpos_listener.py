"""
Raw ESC/POS LAN printer listener for POS apps such as FoodChow.

Thermal-printer POS apps commonly send receipt bytes to a network printer on
TCP port 9100. This service receives that stream, strips common ESC/POS control
bytes, writes a text receipt into incoming/, and lets the normal parser/uploader
pipeline continue from there.
"""

from __future__ import annotations

import os
import re
import socket
import threading
import time

from config import get, incoming_folder
from services import logger
from services.file_manager import generate_unique_name


class EscPosNetworkPrinter:
    def __init__(self, on_receipt):
        self._on_receipt = on_receipt
        self._running = False
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self.last_receipt = ""
        self.error = ""

    @property
    def running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if not get("network_printer_enabled"):
            return
        if self.running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _serve(self) -> None:
        host = get("network_printer_host") or "0.0.0.0"
        port = int(get("network_printer_port") or 9100)
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((host, port))
            self._sock.listen(5)
            self._sock.settimeout(1)
            self.error = ""
            logger.info(f"LAN thermal printer listener ready on {host}:{port}")
        except OSError as exc:
            self.error = str(exc)
            logger.error(f"LAN printer listener failed on {host}:{port}: {exc}")
            return

        while self._running:
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True).start()

    def _handle_client(self, conn: socket.socket, addr) -> None:
        chunks = []
        conn.settimeout(2)
        try:
            while True:
                try:
                    data = conn.recv(8192)
                except socket.timeout:
                    break
                if not data:
                    break
                chunks.append(data)
        finally:
            try:
                conn.close()
            except OSError:
                pass

        raw = b"".join(chunks)
        if not raw.strip():
            return

        text = _escpos_to_text(raw)
        if not text.strip():
            logger.warning(f"LAN print received from {addr}, but no readable text was found")
            return

        path = self._write_text_receipt(text)
        self.last_receipt = os.path.basename(path)
        logger.info(f"LAN print captured from {addr[0]}: {self.last_receipt}")
        self._on_receipt(path)

    def _write_text_receipt(self, text: str) -> str:
        os.makedirs(incoming_folder(), exist_ok=True)
        name = generate_unique_name("network-receipt.txt")
        path = os.path.join(incoming_folder(), name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.strip())
            handle.write("\n")
        return path


def _escpos_to_text(raw: bytes) -> str:
    data = bytearray()
    i = 0
    while i < len(raw):
        b = raw[i]
        if b in (0x1B, 0x1D):  # ESC / GS command prefixes
            i += 2
            if i < len(raw) and raw[i - 1] in (0x21, 0x56, 0x64, 0x77, 0x68, 0x28, 0x6B):
                i += 1
            continue
        if b in (0x0A, 0x0D, 0x09) or 32 <= b <= 126 or 160 <= b <= 255:
            data.append(b)
        i += 1

    text = data.decode("utf-8", errors="ignore")
    if len(text.strip()) < 3:
        text = data.decode("cp437", errors="ignore")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
