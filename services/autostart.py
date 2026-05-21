"""
BillLess Agent – Auto-Start Installer

Creates a macOS LaunchAgent plist so the agent runs on login.
On Linux, creates a systemd user service.
On Windows, creates a startup shortcut.

Fixes: ❌ No Auto Start, ❌ Manual Setup Complexity
"""

import os
import sys
import platform
import stat

from config import BASE_DIR
from services import logger


_PLIST_NAME = "io.billless.agent.plist"
_SYSTEMD_NAME = "billless-agent.service"


def install_autostart():
    """Install auto-start for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return _install_macos()
    elif system == "Linux":
        return _install_linux()
    elif system == "Windows":
        return _install_windows()
    else:
        logger.warning(f"⚠️  Auto-start not supported on {system}")
        return False


def remove_autostart():
    """Remove auto-start for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return _remove_macos()
    elif system == "Linux":
        return _remove_linux()
    elif system == "Windows":
        return _remove_windows()
    return False


# ── macOS ────────────────────────────────────────────────────────────────────

def _install_macos() -> bool:
    python = sys.executable
    main_py = os.path.join(BASE_DIR, "main.py")
    plist_dir = os.path.expanduser("~/Library/LaunchAgents")
    plist_path = os.path.join(plist_dir, _PLIST_NAME)

    os.makedirs(plist_dir, exist_ok=True)

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>io.billless.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{main_py}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>{BASE_DIR}</string>
    <key>StandardOutPath</key>
    <string>{os.path.join(BASE_DIR, "logs", "stdout.log")}</string>
    <key>StandardErrorPath</key>
    <string>{os.path.join(BASE_DIR, "logs", "stderr.log")}</string>
</dict>
</plist>
"""
    try:
        with open(plist_path, "w") as f:
            f.write(plist_content)
        logger.info(f"✅ macOS LaunchAgent installed: {plist_path}")
        logger.info("   Will auto-start on next login.")
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to install LaunchAgent: {exc}")
        return False


def _remove_macos() -> bool:
    plist_path = os.path.join(
        os.path.expanduser("~/Library/LaunchAgents"), _PLIST_NAME
    )
    try:
        if os.path.exists(plist_path):
            os.remove(plist_path)
            logger.info("✅ macOS LaunchAgent removed")
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to remove LaunchAgent: {exc}")
        return False


# ── Linux ────────────────────────────────────────────────────────────────────

def _install_linux() -> bool:
    python = sys.executable
    main_py = os.path.join(BASE_DIR, "main.py")
    service_dir = os.path.expanduser("~/.config/systemd/user")
    service_path = os.path.join(service_dir, _SYSTEMD_NAME)

    os.makedirs(service_dir, exist_ok=True)

    service_content = f"""[Unit]
Description=BillLess Agent
After=network.target

[Service]
Type=simple
ExecStart={python} {main_py}
WorkingDirectory={BASE_DIR}
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""
    try:
        with open(service_path, "w") as f:
            f.write(service_content)
        logger.info(f"✅ systemd user service installed: {service_path}")
        logger.info("   Run: systemctl --user enable billless-agent && systemctl --user start billless-agent")
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to install systemd service: {exc}")
        return False


def _remove_linux() -> bool:
    service_path = os.path.join(
        os.path.expanduser("~/.config/systemd/user"), _SYSTEMD_NAME
    )
    try:
        if os.path.exists(service_path):
            os.remove(service_path)
            logger.info("✅ systemd user service removed")
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to remove systemd service: {exc}")
        return False


# ── Windows ──────────────────────────────────────────────────────────────────

def _install_windows() -> bool:
    try:
        import winreg
        python = sys.executable
        main_py = os.path.join(BASE_DIR, "main.py")
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "BillLessAgent", 0, winreg.REG_SZ,
                          f'"{python}" "{main_py}"')
        winreg.CloseKey(key)
        logger.info("✅ Windows auto-start registry entry created")
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to install Windows auto-start: {exc}")
        return False


def _remove_windows() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, "BillLessAgent")
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
        logger.info("✅ Windows auto-start registry entry removed")
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to remove Windows auto-start: {exc}")
        return False
