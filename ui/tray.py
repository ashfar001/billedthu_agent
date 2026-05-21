"""
Small tray helper kept as a separate module for packaging clarity.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def create_tray(parent, tooltip: str, on_show, on_quit=None) -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(parent)
    tray.setToolTip(tooltip)
    menu = QMenu()
    show_action = menu.addAction("Show")
    show_action.triggered.connect(on_show)
    quit_action = menu.addAction("Quit")
    quit_action.triggered.connect(on_quit or QApplication.quit)
    tray.setContextMenu(menu)
    tray.show()
    return tray
