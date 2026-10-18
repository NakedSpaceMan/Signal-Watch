#!/bin/bash
# Start Signal Watch on Linux, WSL (Windows) or Bazzite. Run it from a terminal:
#     bash start_signal_watch.sh
# It sets everything up the first time, then opens the app in your browser.
# To stop the app, press Ctrl+C or close the terminal.

cd "$(dirname "$0")" || exit 1

# ---- which kind of computer is this?  (SIGNAL_FORCE_OS is only for testing)
OS_KIND="${SIGNAL_FORCE_OS:-}"
if [ -z "$OS_KIND" ]; then
  if [ "$(uname -s)" = "Darwin" ]; then
    OS_KIND="mac"
  elif grep -qi microsoft /proc/version 2>/dev/null; then
    OS_KIND="wsl"
  else
    OS_KIND="linux"
  fi
fi

# Only the Mac double-click window needs a "press any key" pause. In a terminal (Linux, WSL) it just gets in the way.
pause_and_exit() {
  echo
  if [ "$OS_KIND" = "mac" ] || [ -n "$SIGNAL_PAUSE" ]; then
    read -n 1 -s -r -p "Press any key to close this window..."
    echo
  fi
  exit 1
}

# 1. Python 3 must be installed.
if ! python3 --version >/dev/null 2>&1; then
  echo "Python 3 isn't installed yet."
  case "$OS_KIND" in
    mac)
      echo "If a window just popped up offering to install developer tools, click Install,"
      echo "wait for it to finish, then double-click this file again."
      echo "Otherwise install Python from https://www.python.org/downloads/ and try again." ;;
    *)
      echo "Install it with:  sudo apt install python3 python3-venv python3-pip   (Ubuntu / Debian / WSL)"
      echo "or use your system's package manager, then run this again." ;;
  esac
  pause_and_exit
fi

# 2. First-time setup: create the private Python environment.
if [ ! -d ".venv" ]; then
  echo "First-time setup. This takes a few minutes, and only happens once..."
  if ! python3 -m venv .venv; then
    rm -rf .venv
    echo "Couldn't create the Python environment."
    if [ "$OS_KIND" != "mac" ]; then
      echo "On Ubuntu / Debian / WSL this usually means a package is missing. Run:"
      echo "    sudo apt install python3-venv python3-pip"
      echo "then run this again."
    fi
    pause_and_exit
  fi
fi
source .venv/bin/activate

# 3. Install the needed packages (again only if requirements.txt changed).
if [ ! -f ".venv/.installed" ] || [ requirements.txt -nt ".venv/.installed" ]; then
  echo "Installing packages..."
  pip install --upgrade pip -q
  if pip install -r requirements.txt; then
    touch .venv/.installed
  else
    echo "Package install failed. Check your internet connection and try again."
    pause_and_exit
  fi
fi

# 4. Keep the Yahoo Finance library fresh (it breaks when Yahoo changes things). Weekly.
if [ ! -f ".venv/.yf_updated" ] || [ -n "$(find .venv/.yf_updated -mtime +7 2>/dev/null)" ]; then
  echo "Checking for a Yahoo Finance data library update..."
  pip install -U -q yfinance && touch .venv/.yf_updated
fi

# 4b. Optional: the real NYSE holiday calendar (so holidays and early closes are handled exactly).
#     If this fails the app still works and assumes a normal Mon-Fri 4:00 PM close.
if [ ! -f ".venv/.xcal" ]; then
  pip install -q exchange_calendars >/dev/null 2>&1 && touch .venv/.xcal
fi

# 5. Skip Streamlit's one-time email prompt so nothing waits for typing.
mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

URL="http://localhost:8501"
ARGS=(--browser.gatherUsageStats false)

# On WSL, Streamlit's own "open the browser" step fails ("gio: Operation not supported"), so we open the
# Windows browser ourselves a few seconds after the app starts.
if [ "$OS_KIND" = "wsl" ]; then
  ARGS+=(--server.headless true)
  (
    sleep 4
    if command -v wslview >/dev/null 2>&1; then wslview "$URL" >/dev/null 2>&1
    elif command -v cmd.exe >/dev/null 2>&1; then cmd.exe /c start "" "$URL" >/dev/null 2>&1
    elif command -v powershell.exe >/dev/null 2>&1; then powershell.exe -NoProfile -Command "Start-Process '$URL'" >/dev/null 2>&1
    else echo "Open this address in your browser: $URL"
    fi
  ) &
  OPENER=$!
fi

echo
echo "Starting Signal Watch."
if [ "$OS_KIND" = "wsl" ]; then
  echo "Your Windows browser should open in a few seconds. If it doesn't, open: $URL"
else
  echo "Your browser will open in a moment. If it doesn't, open: $URL"
fi
echo "Leave this window open while you use the app. Close it (or press Ctrl+C) to stop."
echo

trap 'echo; echo "Stopping Signal Watch..."' INT
streamlit run signal_app.py "${ARGS[@]}"
status=$?
trap - INT
[ -n "$OPENER" ] && kill "$OPENER" 2>/dev/null

# Mac: keep the window open if the app stopped with an error so it can be read.
# Linux / WSL: just give the terminal its prompt back on a fresh line.
echo
if [ "$OS_KIND" = "mac" ] || [ -n "$SIGNAL_PAUSE" ]; then
  [ "$status" -ne 0 ] && { read -n 1 -s -r -p "The app stopped. Press any key to close this window..."; echo; }
else
  echo "Signal Watch stopped."
fi
