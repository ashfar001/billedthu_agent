"""
Settings dialog for Bill Eduthu Agent.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from config import ensure_lifecycle_dirs, load, save, verify_settings_password
from services import logger
from services.autostart import install_autostart, remove_autostart


def _detect_tesseract_path() -> str:
    import os
    import shutil

    for candidate in (
        shutil.which("tesseract") or "",
        r"C:\Program Files\Tesseract\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def require_settings_unlock(parent=None) -> bool:
    password, ok = QInputDialog.getText(
        parent,
        "Support Unlock",
        "Enter Bill Eduthu support password:",
        QLineEdit.EchoMode.Password,
    )
    if not ok:
        return False
    if verify_settings_password(password):
        return True
    QMessageBox.warning(parent, "Settings Locked", "Incorrect support password.")
    return False


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bill Eduthu Settings")
        self.setMinimumWidth(420)
        self._cfg = load()

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._api_url = QLineEdit(self._cfg.get("api_url", ""))
        self._merchant_name = QLineEdit(self._cfg.get("merchant_name", ""))
        self._merchant_name.setReadOnly(True)
        self._store_code = QLineEdit(self._cfg.get("store_code") or self._cfg.get("shop_id", ""))
        self._store_code.setReadOnly(True)
        self._device_id = QLineEdit(self._cfg.get("device_id", ""))
        self._device_id.setReadOnly(True)
        self._counter_id = QLineEdit(self._cfg.get("counter_id", ""))
        self._counter_id.setReadOnly(True)
        self._base_folder = QLineEdit(self._cfg.get("base_folder", ""))
        self._tesseract_cmd = QLineEdit(self._cfg.get("tesseract_cmd", ""))
        self._tesseract_cmd.setPlaceholderText(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        self._detect_tesseract = QPushButton("Detect Tesseract")
        self._detect_tesseract.clicked.connect(self._detect_tesseract_clicked)
        self._auto_start = QCheckBox("Start Bill Eduthu when Windows starts")
        self._auto_start.setChecked(bool(self._cfg.get("auto_start", True)))
        self._local_ocr = QCheckBox("Use free local OCR for image-only PDFs")
        self._local_ocr.setChecked(bool(self._cfg.get("local_ocr_enabled", True)))

        form.addRow("API URL", self._api_url)
        form.addRow("Merchant", self._merchant_name)
        form.addRow("Store code", self._store_code)
        form.addRow("Device ID", self._device_id)
        form.addRow("Counter ID", self._counter_id)
        form.addRow("Base folder", self._base_folder)
        form.addRow("Tesseract path", self._tesseract_cmd)
        form.addRow("", self._detect_tesseract)
        form.addRow("", self._local_ocr)
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
            "base_folder": self._base_folder.text().strip(),
            "tesseract_cmd": self._tesseract_cmd.text().strip(),
            "local_ocr_enabled": self._local_ocr.isChecked(),
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

    def _detect_tesseract_clicked(self) -> None:
        path = _detect_tesseract_path()
        if path:
            self._tesseract_cmd.setText(path)
        else:
            QMessageBox.warning(self, "Tesseract", "Tesseract was not found on this computer.")
