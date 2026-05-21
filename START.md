# BillLess Virtual Receipt Printer - Windows Start Guide

This app is for Windows 10/11 only.

It creates a virtual printer named:

```text
BillLess Printer
```

Flow:

```text
POS Software
-> BillLess Printer
-> silent PDF capture
-> receipt parsing
-> backend upload
```

No physical printer is required.

## Requirements

Install these first:

1. Windows 10 or Windows 11
2. Python 3.12 or newer
3. Microsoft Print to PDF enabled
4. Internet connection for installing Python packages

When installing Python, tick:

```text
Add python.exe to PATH
```

Check Python:

```powershell
python --version
```

## Project Setup

Open PowerShell or Command Prompt.

Go to the project folder:

```powershell
cd /d D:\Development\billless-agent\billless-agent
```

Run setup:

```powershell
python start.py --setup
```

If you see this error:

```text
FileNotFoundError: [WinError 2] ... venv\Scripts\python.exe
```

your `venv` folder is from another OS or is broken. Run:

```powershell
rmdir /s /q venv
python start.py --setup
```

Or use the reset helper:

```powershell
reset_windows_venv.bat
```

This will:

```text
create venv
install requirements.txt
prepare the app dependencies
```

## Run the App

```powershell
python start.py
```

On first run, the app will try to create:

```text
BillLess Printer
```

If printer creation fails, run PowerShell as Administrator and try again:

```powershell
python start.py
```

## Check Windows Printer Requirement

Run:

```powershell
python start.py --check
```

To manually check Microsoft Print to PDF:

```powershell
Get-WindowsOptionalFeature -Online -FeatureName Printing-PrintToPDFServices-Features
```

To enable Microsoft Print to PDF:

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Printing-PrintToPDFServices-Features
```

Run PowerShell as Administrator for the enable command.

## Configure Backend

Edit:

```text
settings.json
```

For production, this is the main file you must change before giving the app to a merchant.

Required production changes:

```text
api_url
require_https
shop_id
device_id
counter_id
base_folder
api_key
```

On Windows, `base_folder` must be a Windows path. Do not leave the Mac development path.

Wrong:

```json
"base_folder": "/Users/ashfar/Documents/BillLess"
```

Correct:

```json
"base_folder": "C:\\Users\\azinz\\Documents\\BillLess"
```

The printer capture file name can also be changed here:

```json
"printer_capture_filename": "billless_capture.pdf"
```

Normally keep it as `billless_capture.pdf` for production unless you have a specific reason to change it.

Example:

```json
{
  "api_url": "https://your-backend-domain.com",
  "require_https": true,
  "shop_id": "SHOP001",
  "device_id": "DEV001",
  "counter_id": "C1",
  "base_folder": "C:\\Users\\YourUser\\Documents\\BillLess",
  "printer_name": "BillLess Printer",
  "api_key": "YOUR_BACKEND_TOKEN"
}
```

Production example:

```json
{
  "config_version": 5,
  "api_url": "https://api.yourdomain.com",
  "require_https": true,
  "shop_id": "SHOP001",
  "device_id": "DEV001",
  "counter_id": "C1",
  "base_folder": "C:\\Users\\azinz\\Documents\\BillLess",
  "printer_name": "BillLess Printer",
  "printer_capture_filename": "billless_capture.pdf",
  "api_key": "PASTE_PRODUCTION_TOKEN_HERE",
  "auto_start": true
}
```

For local backend testing:

```json
{
  "api_url": "http://127.0.0.1:8000",
  "require_https": false
}
```

## Test Print

Start the app:

```powershell
python start.py
```

Click:

```text
Test Print
```

Expected result:

```text
PDF captured
receipt parsed
upload queued
backend upload attempted
logs updated
```

## Build Windows EXE

Run:

```powershell
python start.py --build
```

Output:

```text
dist\BillLessVirtualReceiptPrinter\
```

Run:

```powershell
dist\BillLessVirtualReceiptPrinter\BillLessVirtualReceiptPrinter.exe
```

## Common Problems

### venv error or missing python.exe

Remove old venv and setup again:

```powershell
rmdir /s /q venv
python start.py --setup
```

Alternative:

```powershell
reset_windows_venv.bat
```

### pip or ensurepip error

Upgrade system pip:

```powershell
python -m pip install --upgrade pip
python start.py --setup
```

### PyQt6 install problem

Try:

```powershell
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Printer not created

Run PowerShell as Administrator:

```powershell
python start.py
```

Also confirm Microsoft Print to PDF is enabled.

### No Save Dialog Requirement

The app is designed to avoid a Save As dialog by using a fixed Microsoft Print to PDF local port capture file.

The app captures that file automatically and renames it like:

```text
SHOP001_DEV001_C1_YYYYMMDD_HHMMSS.pdf
```

## Useful Commands

Setup:

```powershell
python start.py --setup
```

Fix Windows settings paths:

```powershell
python start.py --fix-settings
```

Run:

```powershell
python start.py
```

Check:

```powershell
python start.py --check
```

Build:

```powershell
python start.py --build
```

Manual run with venv:

```powershell
venv\Scripts\activate
python main.py
```

Manual install requirements:

```powershell
venv\Scripts\python.exe -m pip install -r requirements.txt
```
