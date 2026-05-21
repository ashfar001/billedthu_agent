"""
Settings dialog for BillLess Virtual Receipt Printer.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from config import ensure_lifecycle_dirs, load, save
from services import logger
from services.autostart import install_autostart, remove_autostart


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BillLess Settings")
        self.setMinimumWidth(420)
        self._cfg = load()

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._api_url = QLineEdit(self._cfg.get("api_url", ""))
        self._api_key = QLineEdit(self._cfg.get("api_key", ""))
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._shop_id = QLineEdit(self._cfg.get("shop_id", ""))
        self._device_id = QLineEdit(self._cfg.get("device_id", ""))
        self._counter_id = QLineEdit(self._cfg.get("counter_id", ""))
        self._base_folder = QLineEdit(self._cfg.get("base_folder", ""))
        self._auto_start = QCheckBox("Start BillLess when Windows starts")
        self._auto_start.setChecked(bool(self._cfg.get("auto_start", True)))

        form.addRow("API URL", self._api_url)
        form.addRow("API key", self._api_key)
        form.addRow("Shop ID", self._shop_id)
        form.addRow("Device ID", self._device_id)
        form.addRow("Counter ID", self._counter_id)
        form.addRow("Base folder", self._base_folder)
        form.addRow("", self._auto_start)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        apply = QPushButton("Save")
        apply.clicked.connect(self._save)
        buttons.addWidget(apply)
        root.addLayout(buttons)

    def _save(self) -> None:
        cfg = load()
        cfg.update({
            "api_url": self._api_url.text().strip(),
            "api_key": self._api_key.text().strip(),
            "shop_id": self._shop_id.text().strip(),
            "device_id": self._device_id.text().strip(),
            "counter_id": self._counter_id.text().strip(),
            "base_folder": self._base_folder.text().strip(),
            "auto_start": self._auto_start.isChecked(),
        })
        save(cfg)
        ensure_lifecycle_dirs()
        if self._auto_start.isChecked():
            install_autostart()
        else:
            remove_autostart()
        logger.info("Settings saved")
        self.accept()
