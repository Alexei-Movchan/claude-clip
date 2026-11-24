@echo off
setlocal
cd /d "%~dp0"
title Cloudy Clip Studio - Local AI Setup

where ollama >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Ollama is not installed or is not in PATH.
    echo Install it from https://ollama.com/download/windows
    echo Then reopen this window and run this file again.
    pause
    exit /b 1
)

echo Downloading recommended model qwen3:4b...
echo This is a one-time download and may take several minutes.
ollama pull qwen3:4b
if errorlevel 1 (
    echo [ERROR] Model download failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo Local AI is ready.
pause
