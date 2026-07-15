@echo off
REM One-click launcher for the Steam Curator Scraper (Windows).
REM Double-click this file. First run sets everything up (a few minutes);
REM later runs start in seconds.
cd /d "%~dp0"

echo ==============================================
echo   Steam Curator Scraper - Launcher
echo ==============================================

REM 1. Find Python 3
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (
    where python >nul 2>nul && set PY=python
)
if not defined PY (
    echo.
    echo ERROR: Python 3 is not installed.
    echo Install it from https://www.python.org/downloads/
    echo IMPORTANT: tick "Add Python to PATH" during install, then run this again.
    pause
    exit /b 1
)

REM 2. Create virtual environment on first run
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] First run: creating Python virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        pause
        exit /b 1
    )
)
set PYV=.venv\Scripts\python.exe

REM 3. Install/update dependencies (fast no-op after first run)
echo [2/3] Checking dependencies...
"%PYV%" -m pip install --quiet --upgrade pip
"%PYV%" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)
"%PYV%" -m playwright install chromium

REM 4. Launch the app (opens in your browser)
echo [3/3] Starting the app - your browser will open shortly.
echo       Keep this window open while using the app. Close it to stop.
"%PYV%" run_app.py
pause
