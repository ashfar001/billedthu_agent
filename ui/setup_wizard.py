"""
First-time setup wizard for Bill Eduthu Agent.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from config import get
from services.activation import activate_with_setup_code


class _ActivationThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, setup_code: str, api_url: str):
        super().__init__()
        self._setup_code = setup_code
        self._api_url = api_url

    def run(self) -> None:
        result = activate_with_setup_code(self._setup_code, self._api_url)
        self.finished.emit(result.success, result.message)


class SetupWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bill Eduthu Agent Setup")
        self.setMinimumWidth(460)
        self._worker: _ActivationThread | None = None

        root = QVBoxLayout(self)
        title = QLabel("Welcome to Bill Eduthu Agent")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel("This connects your billing software to digital receipts.")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        form = QFormLayout()
        self._api_url = QLineEdit(get("api_url") or "https://billeduthu.in")
        self._setup_code = QLineEdit()
        self._setup_code.setPlaceholderText("BE-82K4-91QD")
        form.addRow("Server URL", self._api_url)
        form.addRow("Setup code", self._setup_code)
        root.addLayout(form)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._activate = QPushButton("Activate Agent")
        self._activate.clicked.connect(self._start_activation)
        root.addWidget(self._activate, alignment=Qt.AlignmentFlag.AlignRight)

    def _start_activation(self) -> None:
        code = self._setup_code.text().replace("_", "").strip()
        api_url = self._api_url.text().strip()
        self._activate.setEnabled(False)
        self._status.setText("Activating...")
        self._worker = _ActivationThread(code, api_url)
        self._worker.finished.connect(self._activation_finished)
        self._worker.start()

    def _activation_finished(self, success: bool, message: str) -> None:
        self._activate.setEnabled(True)
        self._status.setText(message)
        if success:
            self.accept()
