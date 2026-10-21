"""
Keeps Yahoo data working: updates the data libraries once a day, and remembers when Yahoo is limiting you
so the app can stop hammering it and tell you to wait.
"""
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

STATE_FILE = Path(__file__).with_name("yahoo_state.json")
COOLDOWN_MINUTES = 45          # Yahoo limits usually clear in 30-60 minutes
PACKAGES = ["yfinance", "curl_cffi"]

_LIMIT_HINTS = ("429", "too many requests", "ratelimit", "rate limit", "rate-limit",
                "ssl_error_syscall", "connection closed abruptly", "failed to perform, curl: (35)")


def _read(path=None):
    try:
        return json.loads(Path(path or STATE_FILE).read_text())
    except Exception:
        return {}


def _write(state, path=None):
    try:
        Path(path or STATE_FILE).write_text(json.dumps(state))
    except Exception:
        pass


def is_rate_limit_error(err):
    """True if an exception (or its text) looks like Yahoo limiting or cutting off the connection."""
    text = f"{type(err).__name__} {err}".lower()
    return any(h in text for h in _LIMIT_HINTS)


def note_limited(minutes=COOLDOWN_MINUTES, path=None, now=None):
    state = _read(path)
    state["limited_until"] = (now if now is not None else time.time()) + minutes * 60
    _write(state, path)


def note_if_limited(err, path=None):
    if is_rate_limit_error(err):
        note_limited(path=path)
        return True
    return False


def limited_until(path=None, now=None):
    """Epoch time until which we should stay away from Yahoo, or 0 if not limited."""
    until = float(_read(path).get("limited_until", 0) or 0)
    return until if until > (now if now is not None else time.time()) else 0


def clear_limit(path=None):
    state = _read(path)
    state.pop("limited_until", None)
    _write(state, path)


def limit_message(until):
    when = time.strftime("%-I:%M %p", time.localtime(until))
    return ("Yahoo is limiting you (too many requests). Wait 30 to 60 minutes before doing another scan or "
            f"refresh. The app is pausing its own Yahoo requests until about {when}. Each extra request "
            "can make the wait longer.")


def _forget_modules():
    for name in list(sys.modules):
        if name.split(".")[0] in ("yfinance", "curl_cffi"):
            sys.modules.pop(name, None)


def daily_update(today=None, path=None, runner=None):
    """
    Once per calendar day, upgrade yfinance and curl_cffi (Yahoo changes often and old versions get blocked).
    Returns None if nothing ran today, else a short status string.
    """
    today = str(today or date.today())
    state = _read(path)
    if state.get("last_update") == today:
        return None
    state["last_update"] = today          # one attempt a day, even if it fails
    _write(state, path)
    run = runner or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=180))
    try:
        r = run([sys.executable, "-m", "pip", "install", "-U", "--quiet", *PACKAGES])
        if r.returncode != 0:
            return "Daily update of the Yahoo libraries did not finish (you may be offline). It will try again tomorrow."
    except Exception:
        return "Daily update of the Yahoo libraries did not finish (you may be offline). It will try again tomorrow."
    _forget_modules()   # so the next import picks up the new version
    return "Yahoo libraries checked for updates. If prices or scans still fail, close and reopen Signal Watch once."
