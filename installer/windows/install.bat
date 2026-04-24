@echo off
setlocal enabledelayedexpansion
title BoxCutter installer

echo.
echo  ======================================
echo   BoxCutter  --  Installer
echo  ======================================
echo.

REM Check for Python
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

REM Upgrade pip
echo  [..] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo  [ok] pip ready.
echo.

REM Install Flask
echo  [..] Installing flask...
python -m pip install flask --quiet
if errorlevel 1 (
    echo  [!] Failed to install flask.
    pause
    exit /b 1
)
echo  [ok] flask

REM Install pyrekordbox
echo  [..] Installing pyrekordbox...
python -m pip install pyrekordbox --quiet
if errorlevel 1 (
    echo  [!] Failed to install pyrekordbox.
    pause
    exit /b 1
)
echo  [ok] pyrekordbox

REM Install mutagen
echo  [..] Installing mutagen...
python -m pip install mutagen --quiet
if errorlevel 1 (
    echo  [!] Failed to install mutagen.
    pause
    exit /b 1
)
echo  [ok] mutagen

REM Verify all imports
echo.
echo  [..] Verifying installation...
python -c "import flask; import mutagen; print('  [ok] All dependencies verified.')"
if errorlevel 1 (
    echo  [!] Verification failed. Check errors above and try again.
    pause
    exit /b 1
)

REM pyrekordbox DB key setup
echo.
echo  -------------------------------------------------------
echo   Rekordbox database setup
echo  -------------------------------------------------------
echo.
echo  BoxCutter needs one-time access to your Rekordbox
echo  database key. Make sure Rekordbox is installed first.
echo.
echo  Press any key to run the key setup now.
echo  If you have already done this step, close this window.
echo.
pause >nul
python -m pyrekordbox install-sqlcipher
if errorlevel 1 (
    echo.
    echo  [!] SQLCipher setup failed. This is required to read the
    echo      Rekordbox database. Try running manually:
    echo.
    echo      python -m pyrekordbox install-sqlcipher
    echo.
)

REM Done
echo.
echo  ======================================
echo   Installation complete!
echo  ======================================
echo.
echo  To launch BoxCutter anytime, run:
echo.
echo      start.bat
echo.
echo  The app will open automatically in your browser.
echo.
pause
