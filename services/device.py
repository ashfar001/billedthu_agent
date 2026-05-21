"""
BillLess Agent – Device Service (v2)

Hardened with:
  ✅ Auto-detect serial port (scan by VID:PID or name pattern)
  ✅ Auto-reconnect on disconnect
  ✅ Health-check loop with recovery
  ✅ Graceful fallback when no device present
"""

import glob
import os
import threading
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

from config import get
from services import logger


class DeviceStatus:
    DISCONNECTED = "disconnected"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"


class DeviceManager:
    """Manage serial communication with the BillLess LED/NFC device."""

    # Simple command protocol (single-byte commands)
    CMD_READY  = b"\x01"
    CMD_UPLOAD = b"\x02"
    CMD_OK     = b"\x03"
    CMD_FAIL   = b"\x04"
    CMD_PING   = b"\x05"

    def __init__(self):
        self._port: "serial.Serial | None" = None
        self._lock = threading.Lock()
        self.status = DeviceStatus.DISCONNECTED
        self._monitor_thread: threading.Thread | None = None
        self._running = False
        self._reconnect_interval = 15     # seconds between reconnect attempts

    # ── Auto-detect serial port ──────────────────────────────────────────
    @staticmethod
    def _detect_port() -> str | None:
        """
        Try to find the BillLess device:
          1. Match by VID:PID if configured
          2. Fall back to common USB serial patterns
        """
        if serial is None:
            return None

        vid_pid = get("device_vid_pid")
        ports = list(serial.tools.list_ports.comports())

        # Strategy 1: match by VID:PID (e.g. "2341:0043")
        if vid_pid:
            try:
                vid_str, pid_str = vid_pid.split(":")
                vid = int(vid_str, 16)
                pid = int(pid_str, 16)
                for p in ports:
                    if p.vid == vid and p.pid == pid:
                        logger.info(f"🔍 Auto-detected device on {p.device} (VID:PID match)")
                        return p.device
            except (ValueError, AttributeError):
                pass

        # Strategy 2: match common USB serial names
        patterns = [
            "/dev/tty.usbserial*",
            "/dev/tty.usbmodem*",
            "/dev/ttyUSB*",
            "/dev/ttyACM*",
        ]
        for pattern in patterns:
            matches = glob.glob(pattern)
            if matches:
                logger.info(f"🔍 Auto-detected device on {matches[0]} (pattern match)")
                return matches[0]

        # Strategy 3: use serial.tools
        for p in ports:
            if p.description and "USB" in p.description.upper():
                logger.info(f"🔍 Auto-detected device on {p.device} ({p.description})")
                return p.device

        return None

    # ── lifecycle ────────────────────────────────────────────────────────
    def connect(self) -> bool:
        """Open serial port to the device (auto-detect or explicit)."""
        if serial is None:
            logger.warning("⚠️  pyserial not available – device disabled")
            self.status = DeviceStatus.DISCONNECTED
            return False

        port_name = get("device_port")
        baud = get("device_baud_rate")

        # Auto-detect if configured
        if port_name == "auto":
            detected = self._detect_port()
            if not detected:
                logger.info("🔍 No device found – will retry in background")
                self.status = DeviceStatus.DISCONNECTED
                self._start_monitor()   # monitor will keep trying
                return False
            port_name = detected

        try:
            self._port = serial.Serial(port_name, baud, timeout=2)
            time.sleep(1)  # wait for Arduino reset
            self.status = DeviceStatus.READY
            logger.info(f"🔌 Device connected on {port_name}")
            self._start_monitor()
            return True
        except serial.SerialException as exc:
            logger.warning(f"⚠️  Device connection failed: {exc}")
            self.status = DeviceStatus.DISCONNECTED
            self._start_monitor()       # auto-reconnect
            return False

    def disconnect(self):
        self._running = False
        if self._port and self._port.is_open:
            try:
                self._port.close()
            except Exception:
                pass
        self._port = None
        self.status = DeviceStatus.DISCONNECTED
        logger.info("🔌 Device disconnected")

    # ── commands ─────────────────────────────────────────────────────────
    def signal_ready(self):
        self._send(self.CMD_READY)

    def signal_uploading(self):
        self._send(self.CMD_UPLOAD)

    def signal_success(self):
        self._send(self.CMD_OK)

    def signal_failure(self):
        self._send(self.CMD_FAIL)

    def ping(self) -> bool:
        return self._send(self.CMD_PING)

    # ── internal ─────────────────────────────────────────────────────────
    def _send(self, cmd: bytes) -> bool:
        with self._lock:
            if not self._port or not self._port.is_open:
                return False
            try:
                self._port.write(cmd)
                self._port.flush()
                return True
            except Exception as exc:
                logger.error(f"Device write error: {exc}")
                self.status = DeviceStatus.ERROR
                return False

    def _start_monitor(self):
        """Start the health-check / auto-reconnect thread (once)."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True
        )
        self._monitor_thread.start()

    def _monitor_loop(self):
        """Periodically ping the device. Auto-reconnect if disconnected."""
        while self._running:
            time.sleep(self._reconnect_interval)

            # ── Connected: health-check ──────────────────────────────────
            if self._port and self._port.is_open:
                if self.ping():
                    if self.status == DeviceStatus.ERROR:
                        self.status = DeviceStatus.READY
                        logger.info("🔌 Device recovered")
                else:
                    self.status = DeviceStatus.ERROR
                    logger.warning("⚠️  Device health-check failed")
                    # Try to close stale port
                    try:
                        self._port.close()
                    except Exception:
                        pass
                    self._port = None
                continue

            # ── Disconnected: auto-reconnect ─────────────────────────────
            port_name = get("device_port")
            baud = get("device_baud_rate")

            if port_name == "auto":
                detected = self._detect_port()
                if not detected:
                    continue
                port_name = detected

            try:
                self._port = serial.Serial(port_name, baud, timeout=2)
                time.sleep(1)
                self.status = DeviceStatus.READY
                logger.info(f"🔌 Device auto-reconnected on {port_name}")
            except Exception:
                self.status = DeviceStatus.DISCONNECTED
