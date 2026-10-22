@echo off
REM Start Signal Watch on Windows (no WSL needed). Double-click this file.
REM First run sets everything up (a few minutes), then it opens the app in your browser.
REM To stop the app, close this window or press Ctrl+C.
cd /d "%~dp0"

REM 1. Find Python 3.
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python 3 isn't installed yet.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" during setup,
  echo then double-click this file again.
  pause
  exit /b 1
)

REM 2. First-time setup: private Python environment.
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup. This takes a few minutes, and only happens once...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Couldn't create the Python environment.
    rmdir /s /q .venv >nul 2>&1
    pause
    exit /b 1
  )
)
call ".venv\Scripts\activate.bat"

REM 3. Install packages (again only if requirements.txt changed).
set "NEEDINSTALL=0"
if not exist ".venv\.installed" set "NEEDINSTALL=1"
if exist ".venv\.installed" (
  for /f %%i in ('powershell -NoProfile -Command "if ((Get-Item requirements.txt).LastWriteTime -gt (Get-Item .venv\.installed).LastWriteTime) {1} else {0}"') do set "NEEDINSTALL=%%i"
)
if "%NEEDINSTALL%"=="1" (
  echo Installing packages...
  python -m pip install --upgrade pip -q
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Package install failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
  type nul > ".venv\.installed"
)

REM 4. Keep the Yahoo libraries fresh. Once a day, before the app starts (Windows can't update them while the app runs).
set "TODAY=%date%"
set "LASTUPD="
if exist ".venv\.yf_updated" set /p LASTUPD=<".venv\.yf_updated"
if not "%LASTUPD%"=="%TODAY%" (
  echo Checking for a Yahoo Finance data library update...
  python -m pip install -U -q yfinance curl_cffi
  if not errorlevel 1 (>".venv\.yf_updated" echo %TODAY%)
)

REM 4b. Optional: the real NYSE holiday calendar. If this fails the app still works.
if not exist ".venv\.xcal" (
  python -m pip install -q exchange_calendars >nul 2>&1 && type nul > ".venv\.xcal"
)

REM 5. Skip Streamlit's one-time email prompt.
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  >"%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >>"%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo.
echo Starting Signal Watch. Your browser will open in a moment. If it doesn't, open: http://localhost:8501
echo Leave this window open while you use the app. Close it (or press Ctrl+C) to stop.
echo.
streamlit run signal_app.py --browser.gatherUsageStats false
echo.
echo Signal Watch stopped.
pause
