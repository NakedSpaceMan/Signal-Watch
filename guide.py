"""
guide.py - the Guide tab: what every box and slider in the left sidebar does, and how to use the app
after a long break. Plain text only, so it is safe to edit.
"""

QUICK_START = [
    "Open the **Today** tab and work down the checklist. It tells you what to do in order.",
    "Look at the **Market weather** banner at the top. Sunny = good time to look for trades, Stormy = consider waiting.",
    "Check the **Alerts** box (above the tabs). Red or yellow items need a look.",
    "In **Portfolio**, make sure every stock you own has a stop order at Robinhood and is recorded here.",
    "Only if the weather is okay and you have a free slot: run the **Scanner** (Swing setups), then study each pick in **Chart**.",
    "After any buy or sell at Robinhood, record it in **Portfolio** > Record a trade. This app never connects to "
    "Robinhood, so it only knows what you type in.",
    "On the weekend, read the **Weekly review** for praise on what went well and one thing to work on.",
]

TABS = [
    ("Today", "The daily checklist. Tick boxes as you go; they reset each day. Shows your streak of finished days."),
    ("Scanner", "Finds stocks that match a recipe (Swing, Steady, or Low-float momentum) and sizes each one to your "
                "account. Run it after the market closes or before you buy."),
    ("Chart", "Swing (daily) chart with hover-to-learn markers, or the Intraday signals chart that updates live. Both show a Buy / Hold / Sell verdict built from the last 3 months of daily data, with the reasons and an earnings check (next report date, "
              "recent beats and misses, and how the stock moved around past reports) and a News check: recent Yahoo headlines tagged "
              "Good / Bad / Mixed / Neutral, plus a Copy for Claude button and an Open Claude button so you can have Claude explain "
              "the news and then set your own news call."),
    ("Portfolio", "What you own, your profit and loss, stop-raising suggestions, a place to record trades, finished "
                  "trades and price alerts."),
    ("Weekly review", "A look back at the week with praise for good habits and one thing to improve. Add a lesson "
                      "to each finished trade."),
    ("Backtest & history", "Test the swing rules on past prices, and see how past scan picks performed."),
    ("Guide", "This page."),
]

# (section, [(control label exactly as shown in the sidebar, what it does)])
SIDEBAR = [
    ("Mode", [
        ("Practice mode (fake money)",
         "Turns on a separate practice ledger. Trades you record are kept apart from your real ones, and the app "
         "shows a purple banner while it is on. Use it to learn the app, or to let someone else try it. Switch it "
         "off to go back to your real account. It has its own Account value, so set a pretend amount."),
    ]),
    ("Search", [
        ("Ticker (press Enter to load)",
         "The stock the Chart tab shows. Type a symbol like AAPL and press Enter. The Portfolio forms also start "
         "with this symbol."),
        ("Bar size",
         "How much time each candle on the Intraday chart covers (1m, 5m, 15m, 30m, 1h, 1d). Choosing anything "
         "shorter than 1d switches the Chart tab to the Intraday chart. The Swing chart is always daily."),
    ]),
    ("Live updates", [
        ("Auto-refresh the chart", "Keeps the chart updating by itself while the app is open."),
        ("Refresh every (seconds)", "How often the chart refreshes. 60 is fine. Yahoo data can be a few minutes late anyway."),
    ]),
    ("Explanations", [
        ("Beginner mode (plain English, explain like I'm five)",
         "Rewrites chart hovers, alerts and the 'Current read' in everyday words, and shows a small glossary on the "
         "Chart tab. Good for anyone new to stocks."),
    ]),
    ("Account & risk", [
        ("Account value ($, total including stocks you own)",
         "Your total account value: cash plus what your stocks are worth. Update it as it changes. Every size "
         "calculation starts from this number."),
        ("Cash to keep uninvested ($)",
         "Money you want to leave untouched. The scanner will not plan to spend it."),
        ("Max loss per trade (% of account)",
         "How much of your account you are willing to lose if one trade hits its stop. 1% to 2% is typical. On "
         "a $100 account, 2% is $2. Smaller is safer."),
        ("Max total risk ($): open stop risk + today's losses stay under this",
         "A cap on how much you could lose across everything at once (all open stops plus losses already taken "
         "today). The scanner hides picks that would push you past it. 0 means no cap."),
        ("Risk not in the Portfolio tab ($)",
         "Risk you are carrying that is not recorded here, for example a position you have not entered yet. "
         "Leave it at 0 if everything is recorded."),
        ("Biggest single position (% of account)",
         "No single stock may be more than this share of your account. Stops one stock from dominating."),
        ("Most new positions per scan plan",
         "How many new stocks the scanner's combined plan may suggest at once."),
        ("Most open positions at once (0 = no cap)",
         "The most stocks you want to hold at the same time. When you are full, the scanner says there is no free slot."),
        ("Allow fractional shares",
         "Tick this if Robinhood lets you buy part of a share (for example 0.5 shares). Note that the stop / "
         "target pair order at Robinhood only works on whole shares."),
    ]),
    ("Trade levels", [
        ("Stop = ATRs below price",
         "How far below your entry the stop goes, measured in ATRs (the stock's normal daily swing). 2 means two "
         "normal days of movement, which gives a trade room to breathe. Bigger = wider stop and fewer shares."),
        ("Target = x times risk",
         "How far above entry the profit target goes, as a multiple of what you risk. 2 means you aim to make "
         "twice what you risk."),
        ("Save these settings",
         "Remembers your sidebar choices (in signal_settings.json next to the app) so they are there next time."),
    ]),
    ("Scanner", [
        ("Auto-rescan", "Re-runs the scan on a timer while the app is open. Leave it off for the swing scan; once a day is enough."),
        ("Rescan every (minutes)", "How often auto-rescan runs."),
    ]),
    ("Chart options", [
        ("Volume", "Shows how many shares traded under the price chart."),
        ("VWAP (intraday only)", "The day's volume-weighted average price. Big traders watch it. Intraday chart only."),
        ("Support / resistance lines", "Draws price levels where the stock has turned several times before."),
        ("Bollinger Bands", "Dotted bands showing how stretched the price is. Intraday chart only."),
        ("MACD panel", "A momentum gauge under the chart. Intraday chart only."),
        ("Bars shown on chart", "How many candles the Intraday chart shows. The Swing chart has its own Time range buttons."),
    ]),
    ("Signal settings", [
        ("Signal threshold (higher = fewer signals)",
         "How many clues must line up before a BUY or SELL arrow appears. Higher gives fewer but stronger signals."),
        ("Pattern memory (bars)",
         "How many recent candles a clue stays 'fresh' for, so clues that happen close together can add up."),
    ]),
]

GLOSSARY = [
    ("EMA", "An average of recent prices that favors the latest ones. The app uses the 9, 20 and 200 EMA, like the Legend chart."),
    ("ATR", "Average True Range: how much the stock normally moves in a day. Used to place stops sensibly."),
    ("RSI", "A 0 to 100 mood gauge. Above 70 = very excited buying; below 30 = heavy selling."),
    ("R", "Your planned risk on a trade. +2R means you made twice what you risked; -1R means you lost what you planned to."),
    ("Stop (stop order)", "A sell order that triggers if the price falls to a level, to limit your loss. At Robinhood it "
                          "becomes a market order, so a gap can fill you lower."),
    ("Target", "The price where you plan to sell and take profit."),
    ("Swing trade", "Holding a stock for days to weeks instead of minutes."),
    ("Market weather", "A quick grade of the overall market (S&P 500, Nasdaq and the VIX fear gauge)."),
    ("Practice mode", "A separate fake-money ledger for learning."),
    ("News check", "Recent headlines for the stock with a rough Good / Bad tag from keywords. It needs at least 3 headlines "
                   "from the last 7 days before the mood counts. A red-flag headline (a share offering, going-concern or delisting "
                   "warning, reverse split, lawsuit or investigation) counts on its own. News can hold a BUY back to HOLD but never "
                   "creates a BUY."),
    ("Not counted headlines", "The News check ignores lists ('stocks to watch'), daily market blurbs, fund explainers and headlines "
                              "that do not name the company, so filler can not fake a good or bad mood. They stay visible, marked "
                              "'Not counted'. If none are real news the app says the news is unknown, not quiet."),
    ("Earnings inside the trade", "If the next earnings report falls within the plan's longest hold (about 3 weeks), a yellow "
                                  "warning appears on the verdict, with what options traders expect the stock to move. The BUY stays, "
                                  "but plan to sell before the report or buy less."),
    ("Event date box", "In the News check, 'Know about a trading update...' lets you type a date for an event Yahoo doesn't list "
                       "(trading update, investor day). Within 7 days it holds a BUY back to HOLD, like an earnings report. "
                       "Foreign stocks (ADRs like RYCEY) often have no Yahoo news; the app then tries the home-market listing or a "
                       "name search, and Claude can search the web for you."),
    ("Copy for Claude", "Copies a ready-made question (headlines + the app's verdict) to paste into a Claude chat. Open Claude "
                        "in a new tab opens claude.ai so you can paste and send. Afterwards pick Good / Neutral / Bad under the "
                        "headlines. 'Bad news' holds a BUY back; your pick is remembered until you close the app."),
]

FILES = ("Your real trades are stored in signal_ledger.db, practice trades in signal_practice.db, and your sidebar "
         "settings in signal_settings.json, all in the same folder as the app, on your computer only. Copy those "
         "files to back them up. The app sends nothing anywhere (headlines only leave your computer if you paste them into Claude yourself), and it never places orders.")


def show(st):
    st.subheader("How to use Signal Watch")
    st.caption("Come back here any time. Not financial advice: the signals are clues, not orders, and they are often wrong.")
    st.markdown("#### Quick start (also good after a long break)")
    for i, step in enumerate(QUICK_START, 1):
        st.markdown(f"{i}. {step}")
    st.markdown("#### The tabs")
    for name, text in TABS:
        st.markdown(f"**{name}:** {text}")
    st.markdown("#### The left sidebar, box by box")
    st.caption("Labels below match the sidebar exactly.")
    for section, items in SIDEBAR:
        with st.expander(section, expanded=False):
            for label, text in items:
                st.markdown(f"**{label}**  \n{text}")
    st.markdown("#### Words you will see")
    for term, text in GLOSSARY:
        st.markdown(f"**{term}:** {text}")
    st.markdown("#### Where your data lives")
    st.write(FILES)
