@echo off
setlocal
cd /d "%~dp0"
title Cloudy Clip Studio - EXE Build

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
if errorlevel 1 goto :failed
if not exist "assets\cloudy_banner.mp4" (
    echo [ERROR] assets\cloudy_banner.mp4 was not found.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name CloudyClipStudio --collect-all PySide6 --collect-all faster_whisper --collect-all ctranslate2 --collect-all cv2 --collect-all numpy --add-data "assets\cloudy_banner.mp4;assets" --add-data "assets\models;assets\models" --add-data "assets\ai_models;assets\ai_models" main.py
if errorlevel 1 goto :failed

echo.
echo EXE created: dist\CloudyClipStudio\CloudyClipStudio.exe
echo To build the installer, open installer\CloudyClipStudio.iss in Inno Setup.
pause
exit /b 0

:failed
echo [ERROR] Build failed. Save the messages shown above.
pause
exit /b 1
