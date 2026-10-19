# Signal Watch

A small, local stock-signal helper for swing trading, built with Python and Streamlit. It shows buy/sell signals
with plain-English explanations, scans for setups, tracks a practice or real ledger, and gives a Buy / Hold / Sell
read from the last three months of daily data, including an earnings check and a news check.

> **Not financial advice.** Signals are clues, not orders, and they are often wrong. Data comes from Yahoo Finance
> through the unofficial `yfinance` library, so it can be delayed, wrong or missing. The app **never connects to a
> brokerage and never places orders**. Your trades and settings stay in files on your own computer.

## What it does

- **Chart tab:** swing (daily) chart and live intraday chart, hover-to-learn markers, Buy / Hold / Sell verdict with reasons,
  earnings check (next date, past beats/misses, past price reactions), and a **News check** (tagged headlines,
  "Copy for Claude" and "Open Claude" buttons, red flags, your own good/bad call).
- **Scanner:** swing setups, steady uptrends and low-float momentum, sized to your account and risk limits.
- **Portfolio:** positions, stop-raising suggestions, trade history, price alerts. **Practice mode** keeps a separate fake-money ledger.
- **Today / Weekly review:** a daily checklist and a weekly look back with praise and one thing to improve.
- **Backtest & history:** test the swing rules on past data, with plain-English hover help on every column.
- **Learn tab:** lessons on reading a chart and trading support and resistance, bounces, breakouts, pullbacks, flags and
  triangles, using made-up practice charts with every level marked, plus quizzes and a **Practice trades** mode that scores
  you in R. No real money, nothing saved to your ledger.
- **Beginner mode:** plain-English ("explain like I'm five") text everywhere.
- **Guide tab:** what every box in the sidebar does.

## Install and run

You need **Python 3.10 or newer** and an internet connection. The launcher creates its own private environment the
first time (a few minutes), then just opens the app.

### Mac
```bash
git clone https://github.com/NakedSpaceMan/Signal-Watch.git
cd Signal-Watch
bash start_signal_watch.sh
```
Using `git clone` (instead of downloading a zip) avoids the macOS "unidentified developer" prompts.

### Linux / Bazzite
```bash
git clone https://github.com/NakedSpaceMan/Signal-Watch.git
cd Signal-Watch
bash start_signal_watch.sh
```

### Windows (through WSL 2, the tested route)
Open your Ubuntu (WSL) terminal, then:
```bash
sudo apt install python3 python3-venv python3-pip git   # first time only
git clone https://github.com/NakedSpaceMan/Signal-Watch.git
cd Signal-Watch
bash start_signal_watch.sh
```
Your Windows browser opens by itself. If it doesn't, open <http://localhost:8501>.

### Windows without WSL (not tested)
```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run signal_app.py
```

Stop the app with **Ctrl+C** in the terminal. After you update the code, stop and restart the app (a browser refresh is not enough).

## Updating
```bash
git pull
```
Then restart the app. Your own data files are ignored by git, so updating never touches them.

## Your data
Stored next to the app, on your computer only (copy them to back up):
`signal_ledger.db` (real trades), `signal_practice.db` (practice trades), `signal_settings.json` (sidebar settings).

## Testing and feedback
Please open an **Issue** with: what you did, what you expected, what happened, and a screenshot or the error text.
Useful things to try: Practice mode, Beginner mode, the Scanner, the Learn tab (try Practice trades), the News check on a few different stocks
(including foreign ones such as RYCEY), and the Guide tab.

## Known limits
- Yahoo data is unofficial and delayed; earnings dates can be estimates; Yahoo's news feed often misses big stories.
- News tags are keyword-based and can misread a headline. The Verdict thresholds are rules of thumb and have not been backtested.
- Alerts only work while the app is open.
