@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Cloudy Clip Studio - Installer

rem Keep this file ASCII-only: avoids Windows CMD code-page corruption.
set "PYTHON="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON=py -3.11"
)
if not defined PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,11) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON=python"
    )
)

if not defined PYTHON (
    echo [ERROR] Python 3.11 x64 was not found.
    echo Install Python 3.11 from:
    echo https://www.python.org/downloads/release/python-3119/
    echo During setup, enable Add python.exe to PATH.
    echo If using the Windows Python launcher, run: py install 3.11
    echo Then run this installer again.
    pause
    exit /b 1
)

echo Python found:
%PYTHON% --version
if errorlevel 1 goto :failed

echo.
echo [1/3] Creating virtual environment...
if not exist ".venv\Scripts\python.exe" (
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :fail_venv
) else (
    echo Existing virtual environment found. Reusing it.
)

echo.
echo [2/3] Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail_pip

echo.
echo [3/3] Installing application packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail_requirements

where nvidia-smi >nul 2>nul
if not errorlevel 1 (
    echo.
    echo [4/4] NVIDIA GPU found. Installing GPU libraries for fast speech recognition, about 1.3 GB...
    ".venv\Scripts\python.exe" -m pip install -r requirements-gpu.txt
    if errorlevel 1 echo [WARNING] GPU libraries were not installed. The program will use the CPU. You can run enable_gpu.bat later.
)

echo.
echo Creating desktop and Start menu shortcuts...
".venv\Scripts\python.exe" -m cloudy_clip.shortcuts

echo.
echo ================================================
echo INSTALLATION COMPLETED SUCCESSFULLY
echo Start the program with the "Cloudy Clip Studio" shortcut on your desktop.
echo Updates will be offered automatically when the program starts.
echo ================================================
pause
exit /b 0

:fail_venv
echo [ERROR] Could not create the virtual environment.
goto :failed
:fail_pip
echo [ERROR] Could not update pip. Check your internet connection.
goto :failed
:fail_requirements
echo [ERROR] Could not install packages. Check the error messages above.
goto :failed
:failed
echo.
echo Installation stopped. No files were deleted.
echo Take a screenshot of this window and send it to support.
pause
exit /b 1
