"""
coach.py - the daily checklist and the weekly review (with praise and gentle coaching).

Pure functions with no Streamlit and no network, so they are easy to test.

The review looks at habits, not just profit. A small account grows by doing the same
sensible things over and over: set a stop, keep losses small, wait for good setups.
Each habit is marked "on track" (praise, with the numbers) or "work on" (what happened
and one concrete thing to try next time). Habits with no data this week are left out.
"""

import pandas as pd

# ----------------------------------------------------------------- daily checklist
# (id, section, text)
TRADING_DAY = [
    ("weather", "Start here (5 minutes)",
     "Look at the Market weather banner at the top. If it says Stormy, today can be a no-buying day."),
    ("alerts", "Start here (5 minutes)",
     "Open the Alerts box and read anything red or yellow."),
    ("stops", "Check what I own",
     "Portfolio tab: every position I own has a stop order at Robinhood AND recorded here."),
    ("raise", "Check what I own",
     "Portfolio tab: look at 'Raise your stops'. If a stop is suggested, replace it at Robinhood and record it."),
    ("records", "Check what I own",
     "Record any buys or sells I made since last time (Portfolio tab, 'Record a trade')."),
    ("scan", "Look for ideas (only if weather is not Stormy and I have an open slot)",
     "Scanner tab: run the Swing scan."),
    ("study", "Look for ideas (only if weather is not Stormy and I have an open slot)",
     "Chart tab: for each pick, open the swing chart, hover the latest marker and read the why."),
    ("catalyst", "Look for ideas (only if weather is not Stormy and I have an open slot)",
     "Check each pick's news and earnings date. Skip it if earnings are close or headlines mention an offering."),
    ("decide", "Decide and buy safely",
     "Decide on at most 1 or 2 trades and write one line on why in the Notes box."),
    ("buy", "Decide and buy safely",
     "If I bought: place the stop order right away, then record the trade here with its stop and target."),
    ("close", "End of day",
     "Near the close: record any fills and update my Account value in the sidebar."),
    ("win", "End of day",
     "Write down one thing I did well today (box below)."),
]

WEEKEND = [
    ("w_review", "Weekend reset", "Open the Weekly review tab and read it."),
    ("w_lessons", "Weekend reset", "Write what I learned on each finished trade (Weekly review tab)."),
    ("w_weather", "Weekend reset", "Check the Market weather and decide how bold to be next week."),
    ("w_win", "Weekend reset", "Write down one thing I did well this week (box below)."),
]


def checklist_for(day):
    """The checklist that applies to this date (weekday routine or weekend reset)."""
    return WEEKEND if pd.Timestamp(day).weekday() >= 5 else TRADING_DAY


def streak(counts, today=None, need=None):
    """
    Consecutive finished weekdays (weekends are skipped, not counted against you).
    counts: {"YYYY-MM-DD": number of boxes ticked}. need: boxes required for a finished day.
    If today is not finished yet it does not break the streak.
    """
    need = need or len(TRADING_DAY)
    d = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    n, first = 0, True
    for _ in range(800):
        if d.weekday() < 5:
            if counts.get(d.strftime("%Y-%m-%d"), 0) >= need:
                n += 1
            elif not first:
                break
            first = False
        d -= pd.Timedelta(days=1)
    return n


# ----------------------------------------------------------------- weekly review
def week_bounds(day):
    """Monday 00:00 up to (not including) the next Monday."""
    d = pd.Timestamp(day).normalize()
    start = d - pd.Timedelta(days=d.weekday())
    return start, start + pd.Timedelta(days=7)


def lesson_key(symbol, closed_ts):
    return f"{symbol}|{pd.Timestamp(closed_ts):%Y-%m-%d %H:%M:%S}"


def weekly_review(closed, tx, week_start, counts=None, account_value=0.0, risk_pct=1.0):
    """
    Review one week (Monday to Sunday). Returns a dict:
      stats     headline numbers
      habits    list of {"key","title","status": "good"|"work","message","tip"}
      praise    list of encouraging sentences (always lead with these)
      improve   list of (what happened, what to try)
      focus     one thing to focus on next week
      trades    the finished trades closed this week
    """
    ws = pd.Timestamp(week_start).normalize()
    we = ws + pd.Timedelta(days=7)
    counts = counts or {}
    if closed is not None and len(closed):
        c = closed[(closed["Closed"] >= ws) & (closed["Closed"] < we)].copy()
    else:
        c = pd.DataFrame(columns=["Symbol", "Closed", "Days", "P&L $", "P&L %", "R"])
    buys = tx[(tx["side"] == "BUY") & (tx["ts"] >= ws) & (tx["ts"] < we)] if len(tx) else tx
    wins = c[c["P&L $"] > 0]
    losses = c[c["P&L $"] <= 0]
    pnl = float(c["P&L $"].sum()) if len(c) else 0.0
    r_all = c["R"].dropna()
    stats = {"trades": int(len(c)), "wins": int(len(wins)), "losses": int(len(losses)), "pnl": pnl,
             "win_rate": float(len(wins) / len(c) * 100) if len(c) else None,
             "avg_r": float(r_all.mean()) if len(r_all) else None, "new_buys": int(len(buys)),
             "best": c.loc[c["P&L $"].idxmax()] if len(c) else None,
             "worst": c.loc[c["P&L $"].idxmin()] if len(c) else None}

    habits = []

    def add(key, title, status, message, tip=""):
        habits.append({"key": key, "title": title, "status": status, "message": message, "tip": tip})

    # 1. a stop on every trade
    if len(c):
        missing = c[c["R"].isna()]
        if missing.empty:
            add("stops", "A stop on every trade", "good",
                "You recorded a stop on every trade you closed. The stop is what caps a loss, so this is the most "
                "important habit there is.")
        else:
            add("stops", "A stop on every trade", "work",
                f"No stop was recorded for {', '.join(sorted(set(missing['Symbol'])))}. Without one, a loss has no limit.",
                "Place the stop order right after you buy, and record it with the trade.")

    # 2. losses stay small
    lr = losses["R"].dropna()
    if len(lr):
        worst = float(lr.min())
        if worst >= -1.25:
            add("small_losses", "Small losses", "good",
                f"Every loss stayed close to what you planned (worst was {worst:.1f}R). Keeping losses small is "
                "what lets a small account survive long enough to grow.")
        else:
            sym = losses.loc[losses["R"].idxmin(), "Symbol"]
            add("small_losses", "Small losses", "work",
                f"{sym} lost {abs(worst):.1f}R, more than the 1R you planned to risk.",
                "Never move a stop down. A bigger loss often means a gap or a stop that was not in place, so use "
                "smaller sizes around earnings.")

    # 3. winners bigger than losers
    wr = wins["R"].dropna()
    if len(wr) and len(lr):
        aw, al = float(wr.mean()), abs(float(lr.mean()))
        if aw >= al:
            add("winners", "Winners bigger than losers", "good",
                f"Your average win ({aw:.1f}R) was at least as big as your average loss ({al:.1f}R). "
                "That is exactly how small accounts grow.")
        elif aw < 0.8 * al:
            add("winners", "Winners bigger than losers", "work",
                f"Your average win ({aw:.1f}R) was smaller than your average loss ({al:.1f}R).",
                "Let winners run toward the target, and use the 'Raise your stops' prompts so a win cannot "
                "turn into a loss.")

    # 4. wrote down why
    if len(buys):
        notes = buys["notes"].fillna("").astype(str).str.strip()
        blank = int((notes == "").sum())
        if blank == 0:
            add("notes", "Wrote down why", "good",
                "You wrote a reason for every buy. That makes this review meaningful and trains good judgment.")
        else:
            add("notes", "Wrote down why", "work",
                f"{blank} of {len(buys)} buys had no 'why' note.",
                "One sentence is enough, like 'pullback to the 20 EMA, uptrend, no earnings soon'.")

    # 5. not holding losers longer than winners
    if len(wins) and len(losses):
        dl, dw = float(losses["Days"].mean()), float(wins["Days"].mean())
        if dl >= 3 and dl > 1.5 * max(dw, 1):
            add("patience", "Cutting losers", "work",
                f"You held losing trades about {dl:.0f} days but winners only about {dw:.0f}.",
                "If the reason you bought is gone, let the stop do its job instead of hoping.")
        else:
            add("patience", "Cutting losers", "good",
                "You did not hang on to losers longer than winners. Cutting losses is hard, and you did it.")

    # 6. selective
    if len(buys):
        if len(buys) <= 4:
            add("selective", "Selective", "good",
                f"You took {len(buys)} new trade(s) this week. Being picky beats being busy.")
        else:
            add("selective", "Selective", "work",
                f"{len(buys)} new trades in one week is a lot for a small account.",
                "Aim for your best one or two. Each extra trade costs focus and fees.")

    # 7. no revenge trades
    if len(losses):
        rev = []
        for r in losses.itertuples():
            again = buys[(buys["symbol"] == r.Symbol) & (buys["ts"] > r.Closed) &
                         (buys["ts"] <= r.Closed + pd.Timedelta(days=1))] if len(buys) else buys
            if len(again):
                rev.append(r.Symbol)
        if rev:
            add("revenge", "Calm after a loss", "work",
                f"You bought {', '.join(sorted(set(rev)))} again within a day of a loss on it.",
                "After a loss, step away until the next day's checklist. Trades made to win it back rarely work.")
        else:
            add("revenge", "Calm after a loss", "good",
                "After your losses you stayed calm and did not jump straight back in. That is hard and it matters.")

    # 8. your own risk rule
    if account_value > 0 and len(losses):
        cap = account_value * risk_pct / 100
        bad = losses[losses["P&L $"] < -1.5 * cap]
        if len(bad):
            r0 = bad.loc[bad["P&L $"].idxmin()]
            add("risk_rule", "Followed my risk rule", "work",
                f"{r0['Symbol']} lost ${abs(r0['P&L $']):,.2f}, more than your {risk_pct:g}% rule "
                f"(about ${cap:,.2f} per trade).",
                "Use the 'Max shares' column in the Scanner to size each trade.")
        else:
            add("risk_rule", "Followed my risk rule", "good",
                f"No loss went past your {risk_pct:g}% per-trade rule. Your sizing is protecting you.")

    # 9. the daily routine
    need = len(TRADING_DAY)
    week_days = [(ws + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]
    if any(counts.get(d, 0) > 0 for d in week_days):
        done = sum(1 for d in week_days if counts.get(d, 0) >= need)
        if done >= 3:
            msg = ("You finished the daily checklist every weekday. That consistency is the real edge."
                   if done == 5 else
                   f"You finished the daily checklist on {done} day(s). A routine is what makes trading calm.")
            add("routine", "Daily routine", "good", msg)
        else:
            add("routine", "Daily routine", "work", f"The daily checklist was finished on {done} day(s).",
                "Even ticking the first three boxes counts. Start small and build from there.")

    # ---- praise (always first)
    praise = []
    if not len(c) and not len(buys):
        praise.append("Quiet week: no trades. Waiting for clear setups is a real skill, and flat weeks protect a "
                      "small account.")
    if len(c):
        if pnl > 0:
            praise.append(f"You closed the week up ${pnl:,.2f} across {len(c)} trade(s). Nice work.")
        elif pnl < 0:
            praise.append("A down week is information, not a verdict. What matters most is whether you followed "
                          "your rules, and the habits below show how you did.")
        if len(wins):
            b = stats["best"]
            praise.append(f"Best trade: {b['Symbol']} for +${b['P&L $']:,.2f}"
                          + (f" ({b['R']:+.1f}R)." if pd.notna(b["R"]) else "."))
    praise += [h["message"] for h in habits if h["status"] == "good"]
    n_good = sum(h["status"] == "good" for h in habits)
    if habits and n_good * 2 < len(habits):
        praise.append("Every trader has weeks like this. You are reviewing it honestly, and that is the habit that "
                      "fixes it. Pick just the first thing below and ignore the rest for now.")

    order = ["stops", "small_losses", "risk_rule", "revenge", "winners", "patience", "selective", "notes", "routine"]
    work = sorted((h for h in habits if h["status"] == "work"), key=lambda h: order.index(h["key"]))
    improve = [(h["message"], h["tip"]) for h in work]
    good_n = sum(h["status"] == "good" for h in habits)
    if improve:
        focus = improve[0][1]
    elif habits:
        focus = "Keep doing exactly what you did this week. Repeating good habits is how accounts grow."
    elif not len(c) and not len(buys):
        focus = "Do the daily checklist, record your trades as you make them, and this review will fill in."
    else:
        focus = "Record a stop and a reason on each trade so next week's review has more to say."
    return {"stats": stats, "habits": habits, "praise": praise, "improve": improve, "focus": focus,
            "good": good_n, "total": len(habits), "trades": c}
