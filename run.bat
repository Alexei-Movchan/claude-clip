@echo off
setlocal
cd /d "%~dp0"
title Cloudy Clip Studio

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python environment was not found.
    echo Run install.bat first and wait for it to finish.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo.
    echo [ERROR] The application stopped with an error.
    echo Save or screenshot the messages above.
    pause
)
