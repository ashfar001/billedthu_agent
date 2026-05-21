@echo off
setlocal
cd /d "%~dp0"

echo Removing old venv...
if exist venv rmdir /s /q venv

echo Creating Windows venv...
python -m venv venv
if errorlevel 1 (
  echo Normal venv creation failed. Retrying without pip...
  if exist venv rmdir /s /q venv
  python -m venv --without-pip venv
  if errorlevel 1 exit /b 1
  python -m pip --python venv\Scripts\python.exe install --upgrade pip
  if errorlevel 1 exit /b 1
)

echo Installing requirements...
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
if errorlevel 1 exit /b 1
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo.
echo Setup complete. Run:
echo python start.py
endlocal
