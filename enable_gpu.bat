@echo off
setlocal
cd /d "%~dp0"
title Cloudy Clip Studio - Enable NVIDIA GPU

rem Keep this file ASCII-only.
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Run install.bat first.
    pause
    exit /b 1
)
where nvidia-smi >nul 2>nul
if errorlevel 1 (
    echo [ERROR] NVIDIA driver was not found. Install the latest GeForce driver first.
    pause
    exit /b 1
)
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
echo.
echo Downloading NVIDIA cuBLAS and cuDNN for speech recognition (about 1.3 GB)...
".venv\Scripts\python.exe" -m pip install -r requirements-gpu.txt
if errorlevel 1 (
    echo [ERROR] Download failed. Check your internet connection and run this file again.
    pause
    exit /b 1
)
echo.
echo Checking the GPU...
".venv\Scripts\python.exe" -m cloudy_clip.gpu
echo.
echo ================================================
echo GPU SETUP FINISHED. Start the program with run.bat
echo ================================================
pause
