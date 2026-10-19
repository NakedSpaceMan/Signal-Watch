# Signal Watch

A small, local stock-signal helper for swing trading, built with Python and Streamlit. It shows buy/sell signals
with plain-English explanations, scans for setups, tracks a practice or real ledger, and gives a Buy / Hold / Sell
read from the last three months of daily data, including an earnings check and a news check.

> **Not financial advice.** Signals are clues, not orders, and they are often wrong. Data comes from Yahoo Finance
> through the unofficial `yfinance` library, so it can be delayed, wrong or missing. The app **never connects to a
> brokerage and never places orders**. Your trades and settings stay in files on your own computer.

## What it does

When you open the app, the start screen asks whether you want **Stocks** or **Crypto**. Each is its own environment with its own trades and settings.

### Stocks

- **Chart tab:** swing (daily) chart and live intraday chart, hover-to-learn markers, Buy / Hold / Sell verdict with reasons,
  earnings check (next date, past beats/misses, past price reactions), and a **News check** (tagged headlines,
  "Copy for Claude" and "Open Claude" buttons, red flags, your own good/bad call).
- **Scanner:** swing setups, steady uptrends and low-float momentum, sized to your account and risk limits.
- **Portfolio:** positions, stop-raising suggestions, trade history, price alerts. **Practice mode** keeps a separate fake-money ledger.
- **Today / Weekly review:** a daily checklist and a weekly look back with praise and one thing to improve.
- **Backtest & history:** test the swing rules on past data, with plain-English hover help on every column.

### Both modes

- **Learn tab:** lessons on reading a chart and trading support and resistance, bounces, breakouts, pullbacks, flags,
  triangles, double bottoms, cup and handles and when to stay out, using made-up practice charts with every level marked,
  plus quizzes and a **Practice trades** mode that scores you in R. No real money, nothing saved to your ledger.
- **Beginner mode:** plain-English ("explain like I'm five") text everywhere.
- **Guide tab:** what every box in the sidebar does.

## Crypto mode

> [!WARNING]
> **CRYPTO MODE IS UNTESTED AGAINST THE LIVE MARKET.**
> It has only been checked with made-up data. Treat every pick as experimental, start with small amounts you can afford to lose,
> and double-check prices and symbols in Robinhood before you trade.

Crypto is its own environment for coins on Robinhood's list, with the same tabs as stocks (Scanner, Chart, Portfolio, Backtest, Learn, Guide).

- **Trades 24/7:** weekends included. Daily candles close at midnight UTC (5 PM Pacific in summer, 4 PM in winter).
- **Built for bigger swings:** wider stops and smaller positions than stocks.
- **Market weather:** reads Bitcoin's trend (Sunny, Partly cloudy or Stormy) and gets pickier when it is weak.
- **Fee aware:** results show "R after fees", using Robinhood's lowest-tier crypto fees as the default.
- **Its own files:** trades in `signal_crypto.db` and settings in `crypto_settings.json`, apart from your stocks.

### One shared account

Stocks and crypto draw from the same pool of money.

- The account value is a single number, shared by both sides.
- What you hold on one side is subtracted from the other side's free cash (`shared.py`).
- The crypto sidebar shows your **Buying power**, with a hover note on where the rest of your money is.

### Weekend Warrior

A sidebar checkbox for people who trade stocks during the week and want cash back before Monday.

- **The plan:** buy on Friday night and sell by Sunday night, so cash is free when the stock market opens Monday at 6:30 AM Pacific.
- **Tighter rules:** a tighter stop, a nearer target, and a two-day hold.
- **Timing:** each plan row has a "Sell by" time, and a banner shows whether the weekend window is open.
- **Backtest:** only tests setups seen on a Friday.
- **Chart:** opens on the Monday-to-Sunday week.

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

Stop the app with **Ctrl+C** in the terminal. After you update the code, Streamlit usually shows a "Source file changed" banner: click **Rerun** (or **Always rerun**) to load it. Restart the app after adding a new file or changing `.streamlit/config.toml` (which hides the Deploy button).

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
