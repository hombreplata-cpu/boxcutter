@echo off
setlocal enabledelayedexpansion
title rekordbox-tools installer

echo.
echo  ======================================
echo   rekordbox-tools  --  Installer
echo  ======================================
echo.

REM ── Check for Python ──────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [!] Python not found.
    echo.
    echo  Python 3.9 or higher is required.
    echo  Download it from: https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: On the installer screen, check the box that says
    echo  "Add Python to PATH" before clicking Install.
    echo.
    echo  After installing Python, re-run this installer.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  [ok] Python %PYVER% found.
echo.

REM ── Upgrade pip ───────────────────────────────────────────────────────────
echo  [..] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo  [ok] pip up to date.
echo.

REM ── Install dependencies ──────────────────────────────────────────────────
echo  [..] Installing dependencies...
echo.

python -m pip install flask --quiet
if errorlevel 1 ( echo  [!] Failed to install flask. & pause & exit /b 1 )
echo  [ok] flask

python -m pip install pyrekordbox --quiet
if errorlevel 1 ( echo  [!] Failed to install pyrekordbox. & pause & exit /b 1 )
echo  [ok] pyrekordbox

python -m pip install mutagen --quiet
if errorlevel 1 ( echo  [!] Failed to install mutagen. & pause & exit /b 1 )
echo  [ok] mutagen

echo.
echo  [ok] All dependencies installed.
echo.

REM ── pyrekordbox DB key setup ───────────────────────────────────────────────
echo  -------------------------------------------------------
echo   IMPORTANT: Rekordbox database setup
echo  -------------------------------------------------------
echo.
echo  rekordbox-tools needs access to your Rekordbox database.
echo  pyrekordbox requires a one-time key extraction step.
echo.
echo  Run the following command to set it up:
echo.
echo      python -m pyrekordbox download-key
echo.
echo  This only needs to be done once. If you have already done
echo  this step you can skip it.
echo.
echo  Press any key to run it now, or close this window to skip.
pause >nul
python -m pyrekordbox download-key
echo.

REM ── Done ──────────────────────────────────────────────────────────────────
echo  ======================================
echo   Installation complete!
echo  ======================================
echo.
echo  To launch rekordbox-tools, run:
echo.
echo      start.bat
echo.
echo  Or from PowerShell / Command Prompt:
echo.
echo      python app.py
echo.
echo  The app will open in your browser at http://localhost:5000
echo.
pause
