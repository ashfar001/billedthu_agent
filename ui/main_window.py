"""
Modern PyQt6 dashboard for the Bill Eduthu Agent.
"""

from __future__ import annotations

import os
import json
import subprocess
import sys

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from config import AGENT_VERSION, APP_NAME, get, incoming_folder, printer_capture_file
from services import database as db
from services import logger
from services.activation import reset_activation
from services.updater import AutoUpdater
from ui.settings_dialog import SettingsDialog, require_settings_unlock
from ui.setup_wizard import SetupWizard


_INK = "#201b16"
_MUTED = "#7b746d"
_LINE = "#e8e1d9"
_PAPER = "#fbfaf8"
_CARD = "#ffffff"
_ACCENT = "#f47b20"
_ACCENT_DARK = "#bc4f0d"
_GREEN = "#1f9d55"
_RED = "#c24132"
_AMBER = "#c78105"


_STYLE = f"""
QMainWindow, QWidget#central {{
    background: {_PAPER};
}}
QFrame.card {{
    background: {_CARD};
    border: 1px solid {_LINE};
    border-radius: 8px;
}}
QLabel {{
    color: {_INK};
    background: transparent;
    border: none;
}}
QLabel.kicker {{
    color: {_MUTED};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0px;
}}
QLabel.title {{
    color: {_INK};
    font-size: 23px;
    font-weight: 800;
    letter-spacing: 0px;
}}
QLabel.value {{
    font-size: 25px;
    font-weight: 800;
    letter-spacing: 0px;
}}
QLabel.subtle {{
    color: {_MUTED};
    font-size: 12px;
    letter-spacing: 0px;
}}
QLabel.statusDot {{
    font-size: 18px;
}}
QPushButton {{
    background: {_ACCENT};
    color: white;
    border: none;
    border-radius: 7px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton:hover {{
    background: {_ACCENT_DARK};
}}
QPushButton.secondary {{
    background: #f3eee8;
    color: {_INK};
    border: 1px solid {_LINE};
}}
QPushButton.secondary:hover {{
    background: #ebe3da;
}}
QPlainTextEdit {{
    background: #fffdfb;
    border: 1px solid {_LINE};
    border-radius: 8px;
    color: #4b433b;
    padding: 10px;
    font-family: Consolas, Menlo, monospace;
    font-size: 11px;
}}
"""


def _shadow(widget: QWidget, blur: int = 22, alpha: int = 28) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 7)
    effect.setColor(QColor(82, 50, 23, alpha))
    widget.setGraphicsEffect(effect)


class MainWindow(QMainWindow):
    _log_signal = pyqtSignal(str)

    def __init__(self, virtual_printer, spool_monitor, pdf_capture, network_printer, uploader, heartbeat):
        super().__init__()
        self._virtual_printer = virtual_printer
        self._spool_monitor = spool_monitor
        self._pdf_capture = pdf_capture
        self._network_printer = network_printer
        self._uploader = uploader
        self._heartbeat = heartbeat

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(760, 620)
        self.resize(940, 700)
        self.setStyleSheet(_STYLE)

        self._build_ui()
        self._connect_logs()
        self._setup_tray()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1500)
        self._refresh()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setProperty("class", "title")
        subtitle = QLabel("Windows print capture, receipt parsing, queueing, and secure upload")
        subtitle.setProperty("class", "subtle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        version = QLabel(f"v{AGENT_VERSION}")
        version.setProperty("class", "subtle")
        header.addWidget(version)
        root.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        root.addLayout(grid)

        self._printer_card = self._status_card("Printer Status")
        self._printer_value = self._printer_card.findChild(QLabel, "value")
        self._printer_detail = self._printer_card.findChild(QLabel, "detail")
        grid.addWidget(self._printer_card, 0, 0)

        self._backend_card = self._status_card("Backend Status")
        self._backend_value = self._backend_card.findChild(QLabel, "value")
        self._backend_detail = self._backend_card.findChild(QLabel, "detail")
        grid.addWidget(self._backend_card, 0, 1)

        self._queue_card = self._metric_card("Upload Queue", "0", _AMBER)
        self._queue_value = self._queue_card.findChild(QLabel, "metric")
        grid.addWidget(self._queue_card, 1, 0)

        self._success_card = self._metric_card("Upload Success Count", "0", _GREEN)
        self._success_value = self._success_card.findChild(QLabel, "metric")
        grid.addWidget(self._success_card, 1, 1)

        self._failed_card = self._metric_card("Failed Uploads", "0", _RED)
        self._failed_value = self._failed_card.findChild(QLabel, "metric")
        grid.addWidget(self._failed_card, 1, 2)

        self._last_card = QFrame()
        self._last_card.setProperty("class", "card")
        _shadow(self._last_card)
        last_layout = QVBoxLayout(self._last_card)
        last_layout.setContentsMargins(16, 14, 16, 14)
        label = QLabel("Last Receipt")
        label.setProperty("class", "kicker")
        self._last_name = QLabel("-")
        self._last_name.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {_INK};")
        self._last_meta = QLabel("Waiting for first captured print job")
        self._last_meta.setProperty("class", "subtle")
        self._last_meta.setWordWrap(True)
        last_layout.addWidget(label)
        last_layout.addWidget(self._last_name)
        last_layout.addWidget(self._last_meta)
        grid.addWidget(self._last_card, 0, 2)

        self._identity_card = QFrame()
        self._identity_card.setProperty("class", "card")
        _shadow(self._identity_card)
        identity_layout = QVBoxLayout(self._identity_card)
        identity_layout.setContentsMargins(16, 14, 16, 14)
        identity_label = QLabel("Agent Identity")
        identity_label.setProperty("class", "kicker")
        self._identity_value = QLabel("-")
        self._identity_value.setWordWrap(True)
        self._identity_value.setProperty("class", "subtle")
        identity_layout.addWidget(identity_label)
        identity_layout.addWidget(self._identity_value)
        grid.addWidget(self._identity_card, 2, 0, 1, 3)

        actions = QHBoxLayout()
        self._test_button = QPushButton("Test Print")
        self._test_button.clicked.connect(self._test_print)
        actions.addWidget(self._test_button)
        self._connection_button = QPushButton("Test Connection")
        self._connection_button.setProperty("class", "secondary")
        self._connection_button.clicked.connect(self._test_connection)
        actions.addWidget(self._connection_button)
        self._folder_button = QPushButton("Open Incoming Folder")
        self._folder_button.setProperty("class", "secondary")
        self._folder_button.clicked.connect(self._open_incoming_folder)
        actions.addWidget(self._folder_button)
        self._settings_button = QPushButton("Settings")
        self._settings_button.setProperty("class", "secondary")
        self._settings_button.clicked.connect(self._open_settings)
        actions.addWidget(self._settings_button)
        self._start_button = QPushButton("Start")
        self._start_button.setProperty("class", "secondary")
        self._start_button.clicked.connect(self._start_services)
        actions.addWidget(self._start_button)
        self._stop_button = QPushButton("Stop")
        self._stop_button.setProperty("class", "secondary")
        self._stop_button.clicked.connect(self._stop_services)
        actions.addWidget(self._stop_button)
        actions.addStretch()
        root.addLayout(actions)

        capture = QLabel(f"Capture file: {printer_capture_file()} | Watch folder: {incoming_folder()}")
        capture.setProperty("class", "subtle")
        capture.setWordWrap(True)
        root.addWidget(capture)

        logs_label = QLabel("Logs")
        logs_label.setProperty("class", "kicker")
        root.addWidget(logs_label)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(600)
        self._log_view.setMinimumHeight(190)
        root.addWidget(self._log_view, stretch=1)

    def _status_card(self, title: str) -> QFrame:
        card = QFrame()
        card.setProperty("class", "card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        kicker = QLabel(title)
        kicker.setProperty("class", "kicker")
        value = QLabel("Checking")
        value.setObjectName("value")
        value.setStyleSheet(f"font-size: 21px; font-weight: 800; color: {_INK};")
        detail = QLabel("-")
        detail.setObjectName("detail")
        detail.setProperty("class", "subtle")
        layout.addWidget(kicker)
        layout.addWidget(value)
        layout.addWidget(detail)
        return card

    def _metric_card(self, title: str, value: str, color: str) -> QFrame:
        card = QFrame()
        card.setProperty("class", "card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        kicker = QLabel(title)
        kicker.setProperty("class", "kicker")
        metric = QLabel(value)
        metric.setObjectName("metric")
        metric.setProperty("class", "value")
        metric.setStyleSheet(f"color: {color};")
        layout.addWidget(kicker)
        layout.addWidget(metric)
        return card

    def _connect_logs(self) -> None:
        self._log_signal.connect(self._append_log)
        logger.add_listener(self._log_signal.emit)
        for line in logger.get_history():
            self._append_log(line)

    def _append_log(self, text: str) -> None:
        self._log_view.appendPlainText(text)
        bar = self._log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _refresh(self) -> None:
        state = self._virtual_printer.status()
        self._printer_value.setText("Ready" if state.available else "Needs setup")
        self._printer_value.setStyleSheet(
            f"font-size: 21px; font-weight: 800; color: {_GREEN if state.available else _RED};"
        )
        detail = state.message or state.name
        if self._spool_monitor.error:
            detail = self._spool_monitor.error
        if self._network_printer.error:
            detail = f"LAN listener: {self._network_printer.error}"
        self._printer_detail.setText(detail)

        if self._heartbeat.backend_online:
            self._backend_value.setText("Online")
            self._backend_value.setStyleSheet(f"font-size: 21px; font-weight: 800; color: {_GREEN};")
        else:
            self._backend_value.setText("Offline")
            self._backend_value.setStyleSheet(f"font-size: 21px; font-weight: 800; color: {_RED};")
        self._backend_detail.setText(get("api_url") or "No API URL configured")

        stats = self._uploader.stats
        self._queue_value.setText(str(stats["queued"]))
        self._success_value.setText(str(stats["success"]))
        self._failed_value.setText(str(stats["failed"]))
        self._identity_value.setText(
            f"{get('merchant_name') or '-'} | store {get('store_code') or get('shop_id') or '-'} | "
            f"counter {get('counter_id') or '-'} | device {get('device_id') or '-'} | "
            f"watch {incoming_folder()}"
        )

        last = db.last_receipt()
        if last:
            self._last_name.setText(os.path.basename(last["filepath"]))
            receipt_json = self._load_receipt_json(last.get("parsed_json") or "{}")
            merchant = receipt_json.get("merchant", {})
            receipt = receipt_json.get("receipt", {})
            summary = receipt_json.get("summary", {})
            metadata = receipt_json.get("metadata", {})
            total = summary.get("grand_total") if summary.get("grand_total") is not None else last["total"]
            table = receipt.get("table_id") or "-"
            counter = receipt.get("counter_id") or last.get("counter_id") or get("counter_id") or "-"
            confidence = metadata.get("confidence", 0)
            status = metadata.get("upload_status") or last["status"]
            if metadata.get("needs_review"):
                status = "Needs review" if status != "NEEDS_TABLE_ASSIGNMENT" else "Needs table assignment"
            self._last_meta.setText(
                f"{status} | store {merchant.get('name') or last.get('shop_name') or '-'} | "
                f"total {total if total is not None else '-'} | table {table} | "
                f"counter {counter} | confidence {confidence}"
            )
        elif self._pdf_capture.last_captured:
            self._last_name.setText(self._pdf_capture.last_captured)
            self._last_meta.setText("Captured, waiting for parser")
        elif self._network_printer.last_receipt:
            self._last_name.setText(self._network_printer.last_receipt)
            self._last_meta.setText("LAN print captured, waiting for parser")

    def _load_receipt_json(self, value: str) -> dict:
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _test_print(self) -> None:
        self._virtual_printer.ensure_installed()
        self._virtual_printer.test_print()

    def _test_connection(self) -> None:
        self._heartbeat._ping_backend()
        QMessageBox.information(
            self,
            "Connection",
            "Backend is online." if self._heartbeat.backend_online else "Backend is offline. Receipts will stay queued.",
        )

    def _open_incoming_folder(self) -> None:
        folder = incoming_folder()
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            QMessageBox.warning(self, "Open Folder", str(exc))

    def _open_settings(self) -> None:
        if not require_settings_unlock(self):
            return
        dialog = SettingsDialog(self)
        dialog.exec()

    def _reconfigure(self) -> None:
        wizard = SetupWizard(self)
        if wizard.exec() == SetupWizard.DialogCode.Accepted:
            self._virtual_printer.ensure_installed()
            self._refresh()

    def _reset_setup(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Reset Setup",
            "Reset this device activation? You will need a new setup code.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            reset_activation()
            self._reconfigure()

    def _toggle_pause_uploads(self) -> None:
        disabled = not getattr(self._uploader, "_disabled", False)
        self._uploader.set_disabled(disabled)
        logger.warning("Uploads paused" if disabled else "Uploads resumed")

    def _check_update(self) -> None:
        update = AutoUpdater().check_for_update()
        if update:
            QMessageBox.information(self, "Update Available", f"New version available: {update.get('version')}")
        else:
            QMessageBox.information(self, "Update", "No update available.")

    def _start_services(self) -> None:
        self._virtual_printer.ensure_installed()
        self._spool_monitor.start()
        self._pdf_capture.start()
        self._network_printer.start()
        self._uploader.start()
        self._heartbeat.start()
        logger.info("Services started")

    def _stop_services(self) -> None:
        self._heartbeat.stop()
        self._pdf_capture.stop()
        self._network_printer.stop()
        self._spool_monitor.stop()
        self._uploader.stop()
        logger.info("Services stopped")

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip(APP_NAME)
        menu = QMenu()
        show_action = menu.addAction("Open Dashboard")
        show_action.triggered.connect(self.show)
        pause_action = menu.addAction("Pause Uploads")
        pause_action.triggered.connect(self._toggle_pause_uploads)
        test_action = menu.addAction("Test Print")
        test_action.triggered.connect(self._test_print)
        connection_action = menu.addAction("Test Connection")
        connection_action.triggered.connect(self._test_connection)
        logs_action = menu.addAction("View Logs")
        logs_action.triggered.connect(self.show)
        restart_action = menu.addAction("Restart Agent")
        restart_action.triggered.connect(self._restart_agent)
        counter_action = menu.addAction("Change Counter")
        counter_action.triggered.connect(self._reconfigure)
        reset_action = menu.addAction("Logout / Reset Setup")
        reset_action.triggered.connect(self._reset_setup)
        update_action = menu.addAction("Check for Updates")
        update_action.triggered.connect(self._check_update)
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(QApplication.quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show()
            self.raise_()
            self.activateWindow()

    def _restart_agent(self) -> None:
        subprocess.Popen([sys.executable] + sys.argv)
        QApplication.quit()

    def closeEvent(self, event) -> None:
        if hasattr(self, "_tray") and self._tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()
