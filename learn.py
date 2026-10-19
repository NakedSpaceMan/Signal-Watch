"""
learn.py - the Learn tab: lessons that teach you to read a chart, plus a practice mode.

Everything here uses MADE-UP charts from learn_charts.py (never real stocks, no money at risk, nothing is
saved to your ledger). Lessons explain a pattern with every level marked and then let you reveal what
happened next. The quiz hides the markup. Practice mode shows an unmarked chart: you decide whether to buy,
where your stop goes and where your target goes, then it plays out and scores you in R.

Not financial advice. Patterns fail often; that is part of the lesson.
"""

import random

import learn_charts as lc

try:
    import streamlit as st
except Exception:  # no Streamlit (tests)
    st = None


def _no_fragment(f=None, **kw):
    return f if f is not None else (lambda g: g)


# st.fragment reruns just this tab when you click inside it, so the rest of the app doesn't reload
_fragment = getattr(st, "fragment", None) or _no_fragment


def _md(text):
    """Streamlit treats text between two $ as math. Escape them so prices print normally."""
    return text.replace("$", "\\$")


ODDS = ("These practice charts fail about half the time on purpose, because real setups do. What matters is the size of "
        "wins against losses: if your winners are twice as big as your losers, you can lose half your trades and still come "
        "out ahead. See 'Why a low win rate can still be a good thing' on the Backtest tab.")

LESSONS = {
    "basics": dict(
        kind="none", title="1. How to read a chart", tagline="Candles, wicks, volume, the 20-day line and RSI.",
        idea=("A chart is a diary of a stock's price. Each **candle** is one trading day. Learn to read one candle and you can "
              "read the whole chart. Turn on 'Show what happened next' any time to see the following weeks."),
        spot=["**Trend:** are the highs and lows creeping up (uptrend), down (downtrend) or sideways?",
              "**Levels:** are there prices where the stock keeps turning around?",
              "**Volume:** are big moves backed by big volume?",
              "**Context:** where is price relative to the orange 20-day line?"],
        trade=None, mistakes=["Reading one candle on its own. A candle only means something next to the ones around it.",
                              "Ignoring volume. A breakout on thin volume is much less believable."],
        quiz=[
            dict(q="A green candle means...", options=["The stock closed higher than it opened that day",
                                                       "The stock went up all day without dipping", "You should buy it"],
                 answer=0, why="Green means the close was above the open. It can still have dipped during the day (that is what the "
                               "lower wick shows). It is a description of one day, not a buy signal."),
            dict(q="Why does volume matter?", options=["It shows the stock's price",
                                                       "A move on heavy volume has more traders behind it, so it is more believable",
                                                       "High volume always means the price will rise"],
                 answer=1, why="Volume is how many shares traded. Heavy volume means many traders agreed with the move. It does not "
                               "say which way price goes next."),
            dict(q="Price sits above a rising 20-day line (EMA 20). That suggests...", options=["The short-term trend is up",
                                                                                              "The stock must be a buy",
                                                                                              "The stock is about to crash"],
                 answer=0, why="Price above a rising average means recent buyers are in control. It is context, not a trade by itself.")]),
    "range": dict(
        kind="range", title="2. Support and resistance", tagline="The floor and ceiling price keeps bumping into.",
        idea=("**Support** is a price where the stock keeps stopping its fall, like a floor. **Resistance** is a price where it keeps "
              "stopping its rise, like a ceiling. These levels exist because traders remember them: buyers wait at support, sellers "
              "wait at resistance. The more times a level holds, the more traders watch it."),
        spot=["At least two or three touches of the same price area, with a turn each time.",
              "The touches are on different days, not one bad day.",
              "Look for round areas, not a perfect line. Think zone, not hairline."],
        trade=dict(entry="Buy the next open after a candle bounces off support. Don't buy before it turns.",
                   stop="A little below support. If support breaks, the idea was wrong. Leave.",
                   target="Just under resistance, the next place sellers have appeared."),
        mistakes=["Buying in the middle of the range, far from both levels.",
                  "Moving your stop down when price breaks support 'to give it room'. That turns a small loss into a big one."],
        quiz=[
            dict(q="What makes a support or resistance level strong?", options=["It was drawn at a round number",
                                                                               "Price has turned around there several times",
                                                                               "It is close to the current price"],
                 answer=1, why="Repeated tests. Each time it holds, more traders notice it."),
            dict(q="Price closes clearly below support. What does that mean?", options=["Buy more, it's cheaper",
                                                                                      "The level failed, so the idea was wrong. Leave",
                                                                                      "Nothing, ignore it"],
                 answer=1, why="A floor that breaks often turns into a ceiling. Support is only a reason to buy while it holds.")]),
    "bounce": dict(
        kind="bounce", title="3. The bounce", tagline="A beaten-down stock turning up at support.",
        idea=("A **bounce** happens when a stock falls fast into a level where buyers have shown up before (support) and then turns "
              "up. After a quick drop, a stock is **oversold** (see RSI under 30 at the bottom of the chart): sellers have run out "
              "of steam. This is the setup the Scanner's 'Bounce' picks look for."),
        spot=["A sharp fall into a level that held before.",
              "RSI low (under about 35).",
              "A **reversal candle**: a hammer (long lower wick, closes near its high) or a green candle that swallows the red one before it."],
        trade=dict(entry="After the reversal candle, buy the next open. Do not buy the falling knife before it turns.",
                   stop="Below the low of the reversal candle. If a new low forms, the bounce failed.",
                   target="2 times your risk, or the middle of the previous drop."),
        mistakes=["Buying just because the price is 'cheap'. Cheap can get cheaper.",
                  "Ignoring that you are betting against the recent direction. Keep these trades small."],
        quiz=[
            dict(q="A hammer candle (long lower wick, closes near the high) suggests...", options=[
                "Sellers pushed it down, but buyers took it back, so selling may be drying up",
                "The stock will rise for sure", "The stock is about to fall further"],
                 answer=0, why="The long wick shows sellers tried and failed. It is a hint, not a guarantee. That is why the stop sits below it."),
            dict(q="You bought a bounce and price closes below the hammer's low. What do you do?", options=[
                "Move the stop lower to wait", "Take the stop: the bounce failed", "Buy more to lower your average price"],
                 answer=1, why="A new low below the reversal candle means the idea was wrong. Moving the stop or adding to a loser is how small losses become big ones.")]),
    "breakout": dict(
        kind="breakout", title="4. The breakout", tagline="Price pushes through a ceiling it couldn't crack before.",
        idea=("A **breakout** is when price finally closes above a resistance level that has been turning it back. Several failed "
              "attempts followed by a strong, high-volume push says the sellers there are used up and new buyers are in control. "
              "The old resistance then tends to act as new support."),
        spot=["A flat-ish ceiling touched 2-3 times, often with shallower dips.",
              "Quiet volume during the base.",
              "A strong candle that CLOSES above the ceiling on volume well above normal (about 2 times or more)."],
        trade=dict(entry="Buy the next open after a strong close above resistance. Don't chase a candle that is already far above it.",
                   stop="Just under the old resistance. If price falls back into the base, the breakout failed.",
                   target="2 times your risk."),
        mistakes=["Buying a poke above resistance that closes back below it. Wait for the close.",
                  "Buying breakouts on thin volume. They fail more often.",
                  "Chasing: the later you buy, the farther your stop is and the worse the deal."],
        quiz=[
            dict(q="Which breakout is more believable?", options=["A poke above resistance on thin volume",
                                                                "A strong close above resistance on heavy volume",
                                                                "Price still inside the base"],
                 answer=1, why="Closing above (not just poking) on heavy volume shows real buyers. A thin-volume poke often fades."),
            dict(q="A day or two after you buy, price closes back inside the old base. That is called...", options=[
                "A retest", "A false breakout. This is exactly what the stop is for", "A new support level"],
                 answer=1, why="False breakouts happen often. A stop just under the breakout level takes you out for a small, planned loss.")]),
    "pullback": dict(
        kind="pullback", title="5. The pullback", tagline="Buying a small dip inside a healthy uptrend.",
        idea=("In an uptrend, price rarely goes straight up. It surges, rests, surges again. A **pullback** is the rest. Healthy "
              "uptrends often dip to the rising **20-day line (EMA 20)**, where buyers step back in. Buying the dip is cheaper than "
              "chasing the surge, and your stop can be close."),
        spot=["A clear uptrend: higher highs and higher lows, 20-day line rising.",
              "A dip of a few days, ideally on lighter volume.",
              "The dip stops near the 20-day line, then a green candle closes above the day before's high."],
        trade=dict(entry="Buy the next open after that green candle. It shows buyers are back.",
                   stop="Just under the dip's low. If the dip's low breaks, the trend may be over.",
                   target="2 times your risk, or a new high."),
        mistakes=["Buying while it is still falling instead of waiting for the green candle.",
                  "Buying a dip in a stock that is not in an uptrend. That is just a downtrend."],
        quiz=[
            dict(q="What is the ideal sign to buy a dip in an uptrend?", options=[
                "Price drops below the 20-day line and keeps falling",
                "Price dips to a rising 20-day line, then a green candle closes above the prior day's high",
                "Price has been up 10 days in a row"],
                 answer=1, why="You want the dip to stop and buyers to show up before you buy, not guess the bottom."),
            dict(q="Price falls well below the 20-day line and keeps going. Is it still a pullback?", options=[
                "Yes, buy more", "No. The trend may be changing. Respect your stop", "Yes, but only if volume is low"],
                 answer=1, why="A healthy pullback holds near the rising average. Falling through it means the uptrend is in question.")]),
    "flag": dict(
        kind="flag", title="6. The bull flag", tagline="A strong run, a tight pause, then the next leg up.",
        idea=("A **bull flag** is a strong run up (the **pole**) followed by a short, tight pause that drifts slightly down in a "
              "sloping channel (the **flag**) on shrinking volume. Think of runners catching their breath. When price breaks above "
              "the top of the flag, the run often continues."),
        spot=["A fast, high-volume run-up first (the pole).",
              "Then 1-3 weeks of drifting down in a tight channel, with volume shrinking.",
              "Break above the top line of the channel, ideally on rising volume."],
        trade=dict(entry="Buy the next open after price closes above the top of the flag.",
                   stop="Under the lowest low of the flag. If it falls back through the whole flag, the pattern failed.",
                   target="2 times your risk (some traders aim for the pole's height above the breakout)."),
        mistakes=["Calling any dip a flag. A flag is TIGHT and follows a strong, fast run.",
                  "Buying inside the flag before it breaks. Wait for the break."],
        quiz=[
            dict(q="What is the 'pole'?", options=["The sharp, high-volume run-up before the pause",
                                                 "The line along the top of the flag", "The final breakout candle"],
                 answer=0, why="Pole and flag: the pole is the strong move, the flag is the pause."),
            dict(q="What should volume do during the flag?", options=["Rise steadily", "Shrink (a quiet pause)", "Stay exactly the same"],
                 answer=1, why="A quiet pause means sellers aren't pushing hard, which is why the run can resume.")]),
    "triangle": dict(
        kind="triangle", title="7. The ascending triangle", tagline="A flat ceiling with rising lows: a squeeze before the move.",
        idea=("In an **ascending triangle** price keeps hitting the same ceiling, but each dip is shallower than the last. Buyers "
              "are getting more aggressive while sellers hold one line. The range squeezes like a spring. These break upward more "
              "often than down, but they can fail."),
        spot=["A flat top touched 3-4 times.",
              "Higher lows (a rising yellow line underneath).",
              "Volume drying up as the triangle tightens.",
              "A close above the flat top on a burst of volume."],
        trade=dict(entry="Buy the next open after a strong close above the flat top.",
                   stop="Back inside the pattern, just under the old top. If price falls back in, it was a false breakout.",
                   target="2 times your risk."),
        mistakes=["Buying while it is still inside the triangle, hoping for the breakout.",
                  "Forgetting these can break DOWN through the rising floor. If it does, that's your signal to stay away."],
        quiz=[
            dict(q="In an ascending triangle, which is flat and which rises?", options=["The lows are flat, the highs rise",
                                                                                       "The highs are flat, the lows rise",
                                                                                       "Both rise together"],
                 answer=1, why="Flat ceiling, rising floor. That's what squeezes the price."),
            dict(q="What should volume do as the triangle tightens, and on the breakout?", options=[
                "Dry up, then jump on the breakout", "Rise the whole time", "It does not matter"],
                 answer=0, why="Quiet squeeze, then a burst of volume shows the buyers have taken over.")]),
    "none": dict(
        kind="none", title="8. When there is no trade", tagline="The most underrated skill: doing nothing.",
        idea=("Most charts on most days are not a setup. Price is drifting in the middle of nowhere with no level, no clean "
              "trend, no squeeze and no volume burst. Buying anyway is just guessing. Waiting is a position too, and with a small "
              "account it protects you from a lot of small cuts."),
        spot=["No level that has been tested repeatedly.", "No clear trend up.", "No tight squeeze and no burst of volume.",
              "You would have to guess where to put your stop."],
        trade=None, mistakes=["Feeling that you 'must' trade something today.",
                              "Lowering your standards because nothing looks great."],
        quiz=[
            dict(q="There's no clear level, trend or squeeze. Best move?", options=["Buy a small amount anyway", "Wait. Not every chart is a trade",
                                                                                  "Buy more to make up for earlier losses"],
                 answer=1, why="No setup means no edge. You can always come back when a clean one appears."),
            dict(q="Why is buying in the middle of nowhere a bad idea?", options=[
                "Prices in the middle always fall", "There is no nearby level to anchor a stop, so your risk is a guess",
                "It costs more in fees"],
                 answer=1, why="A stop should sit just beyond the level that proves you wrong. With no level there is no reason to pick any stop.")]),
}
ORDER = ["basics", "range", "bounce", "breakout", "pullback", "flag", "triangle", "none"]
STOP_QUIZ_KINDS = {"range", "bounce", "breakout", "pullback", "flag", "triangle"}
STOP_WHY = {"good": "Right: just beyond the level that proves the idea wrong, so normal wiggles don't knock you out but a real failure does.",
            "tight": "Too tight: so close to the entry that ordinary day-to-day wiggle would knock you out before the idea has a chance.",
            "far": "Too far: a stop this deep means that if you're wrong you lose far more than the setup justifies."}


# ------------------------------------------------------------------ small UI helpers
def _plot(fig, key):
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key=key)


def _new_seed(key, extra_keys=()):
    st.session_state[key] = random.randint(1, 10 ** 6)
    for k in extra_keys:
        st.session_state[k] = False


def _result_line(out, r_dollars=None):
    r = out["r"]
    base = {"Target": "Target hit", "Target (gap)": "Target hit (price gapped past it)", "Stop": "Stopped out",
            "Stop (gap)": "Stopped out (price gapped through the stop, so the loss is a bit bigger)",
            "Time limit": f"Neither level was hit in {lc.MAX_HOLD} days, so you leave at the close"}.get(out["reason"], out["reason"])
    txt = f"**{base}: {r:+.1f}R.**"
    if r_dollars:
        txt += f" If you had risked ${r_dollars:,.2f}, that is {'+' if r >= 0 else '-'}${abs(r) * r_dollars:,.2f}."
    return txt


# ------------------------------------------------------------------ lessons
def _lesson_view(key, risk_dollars):
    L = LESSONS[key]
    ss = st.session_state
    sk, rk = f"lrn_seed_{key}", f"lrn_reveal_{key}"
    ss.setdefault(sk, random.randint(1, 10 ** 6))
    st.subheader(L["title"])
    st.caption(L["tagline"])
    st.markdown(L["idea"])

    c1, c2 = st.columns([1, 2])
    c1.button("New example chart", key=f"lrn_new_{key}", on_click=_new_seed, args=(sk, (rk,)))
    reveal = c2.checkbox("Show what happened next", key=rk)
    chart = lc.make_chart(L["kind"], ss[sk])
    basics = key == "basics"
    _plot(lc.build_figure(chart, markup=True, reveal=reveal, basics=basics, show_plan=L["trade"] is not None),
          f"lrn_fig_{key}")
    st.caption("Practice chart made up by the app (not a real stock). The dotted vertical line is the moment you would decide.")

    notes = lc.basics_notes(chart)[1] if basics else chart["g"]["notes"]
    st.markdown("**What to notice**")
    for n in notes:
        st.markdown("- " + _md(n))
    if reveal and L["trade"]:
        out = chart["outcome"]
        st.markdown(_md(_result_line(out, risk_dollars)))
        st.caption("This example was chosen to win or lose at random. Roughly half the time, setups like this fail. "
                   "That is not a flaw; it is why the stop exists.")

    with st.expander("How to spot it", expanded=True):
        for s in L["spot"]:
            st.markdown("- " + s)
    if L["trade"]:
        with st.expander("How to trade it", expanded=True):
            t = L["trade"]
            st.markdown(f"**Entry:** {t['entry']}\n\n**Stop:** {t['stop']}\n\n**Target:** {t['target']}")
            st.caption("The stop is placed where the idea is proven wrong, not where you 'can afford' to lose. If that "
                       "stop is too far for your account, make the position smaller or skip the trade.")
    with st.expander("Common mistakes"):
        for m in L["mistakes"]:
            st.markdown("- " + m)
    if L["kind"] in lc.SUCCESS_P:
        with st.expander("The honest odds"):
            st.markdown(ODDS)

    _quiz(key, L)


def _quiz(key, L):
    ss = st.session_state
    qk = f"lrn_qseed_{key}"
    ss.setdefault(qk, random.randint(1, 10 ** 6))
    qseed = ss[qk]
    with st.expander("Test yourself"):
        chart = lc.make_chart(L["kind"], qseed)
        lines, answer, why = ([], None, {})
        has_stop = key != "basics" and L["kind"] in STOP_QUIZ_KINDS
        if has_stop:
            lines, answer, why = lc.quiz_stop_options(chart, qseed)
        _plot(lc.build_figure(chart, markup=False, reveal=False, quiz_lines=lines, show_plan=False), f"lrn_qfig_{key}_{qseed}")
        with st.form(f"lrn_form_{key}_{qseed}"):
            picks = []
            if has_stop:
                picks.append(st.radio("Imagine you buy tomorrow's open. Which dashed line is the best place for your stop?",
                                      ["A", "B", "C"], index=None, key=f"lrn_qs_{key}_{qseed}", horizontal=True))
            for i, q in enumerate(L["quiz"]):
                picks.append(st.radio(q["q"], q["options"], index=None, key=f"lrn_q{i}_{key}_{qseed}"))
            done = st.form_submit_button("Check my answers")
        if done:
            score, total, idx = 0, 0, 0
            if has_stop:
                total += 1
                p = picks[0]
                if p == answer:
                    score += 1
                    st.success(f"Stop question: correct ({answer}). " + STOP_WHY["good"])
                elif p is None:
                    st.warning("Stop question: you didn't pick one. The best stop was " + answer + ". " + STOP_WHY["good"])
                else:
                    st.error(f"Stop question: not quite. Line {p} is the wrong one. " + STOP_WHY[why[p]] + f" The best was {answer}.")
                idx = 1
            for i, q in enumerate(L["quiz"]):
                total += 1
                p = picks[idx + i]
                ok = p == q["options"][q["answer"]]
                score += ok
                if ok:
                    st.success(f"{q['q']}  Correct. {q['why']}")
                elif p is None:
                    st.warning(f"{q['q']}  You didn't pick one. Answer: {q['options'][q['answer']]}. {q['why']}")
                else:
                    st.error(f"{q['q']}  Not quite. Answer: {q['options'][q['answer']]}. {q['why']}")
            st.markdown(f"**Score: {score} of {total}.**")
            st.caption("Here is the same chart with everything marked up and the result revealed:")
            _plot(lc.build_figure(chart, markup=True, reveal=True, basics=False, show_plan=True), f"lrn_qans_{key}_{qseed}")
        st.button("New quiz chart", key=f"lrn_qnew_{key}", on_click=_new_seed, args=(qk,))


# ------------------------------------------------------------------ practice mode
def _score():
    return st.session_state.setdefault("lrn_score", dict(trades=0, wins=0, r=0.0, skips=0, good_skips=0))


def _pkind(seed):
    rng = random.Random(seed)
    return rng.choices(list(lc.PRACTICE_WEIGHTS), weights=list(lc.PRACTICE_WEIGHTS.values()))[0]


def _play(seed):
    ss = st.session_state
    kind = _pkind(seed)
    chart = lc.make_chart(kind, seed)
    action = ss.get(f"lrn_pa_{seed}", "Buy at the next open")
    pct = float(ss.get(f"lrn_ps_{seed}", 4.0))
    rr = float(ss.get(f"lrn_pt_{seed}", 2.0))
    sc = _score()
    p = chart["plan"]
    res = {"seed": seed, "kind": kind, "action": action}
    if action.startswith("Buy"):
        entry = p["entry"]
        stop = entry * (1 - pct / 100)
        target = entry + rr * (entry - stop)
        out = lc.simulate_plan(chart["fut"], entry, stop, target)
        res.update(plan=dict(entry=entry, stop=stop, target=target), out=out)
        sc["trades"] += 1
        sc["wins"] += int(out["r"] > 0)
        sc["r"] += float(out["r"])
    else:
        sc["skips"] += 1
        sc["good_skips"] += int(kind == "none")
    ss["lrn_pres"] = res
    ss["lrn_pplayed"] = seed


def _next_practice():
    st.session_state["lrn_pseed"] = random.randint(1, 10 ** 6)
    st.session_state["lrn_pplayed"] = None


def _reset_score():
    st.session_state["lrn_score"] = dict(trades=0, wins=0, r=0.0, skips=0, good_skips=0)


def _practice_view(risk_dollars):
    ss = st.session_state
    ss.setdefault("lrn_pseed", random.randint(1, 10 ** 6))
    seed = ss["lrn_pseed"]
    kind = _pkind(seed)
    chart = lc.make_chart(kind, seed)
    sc = _score()
    st.subheader("Practice trades")
    st.caption("Made-up charts, no money at risk, and nothing here touches your ledger. Decide at the dotted line: buy at the "
               "next open or skip, then pick your stop and target. Some charts have a real setup and some have nothing at all.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Trades taken", sc["trades"])
    m2.metric("Win rate", f"{sc['wins'] / sc['trades'] * 100:.0f}%" if sc["trades"] else "-",
              help="How often your trade made money. A win rate near half is normal. What matters is the size of wins versus losses.")
    m3.metric("Avg R per trade", f"{sc['r'] / sc['trades']:+.2f}" if sc["trades"] else "-",
              help="Average result per trade in units of what you risked. Above 0 means you made money on average.")
    m4.metric("Skipped", sc["skips"], help="Skipping is a decision too. Skipping a chart with no setup is a good one.")

    played = ss.get("lrn_pplayed") == seed
    res = ss.get("lrn_pres") if played else None
    if not played:
        _plot(lc.build_figure(chart, markup=False, reveal=False, show_plan=False), f"lrn_pfig_{seed}")
        last = float(chart["hist"].Close.iloc[-1])
        a, b, c = st.columns(3)
        a.radio("Your call", ["Buy at the next open", "Skip this one"], key=f"lrn_pa_{seed}")
        pct = b.slider("Stop: % below your entry", 0.5, 12.0, 4.0, 0.5, key=f"lrn_ps_{seed}",
                       help="Where you give up if you are wrong. Put it just beyond a level that would prove the idea wrong.")
        c.select_slider("Target: times your risk", options=[1.0, 1.5, 2.0, 3.0, 4.0], value=2.0, key=f"lrn_pt_{seed}",
                        help="How far above your entry you take profit, measured in units of what you risk. 2 means a win pays twice a loss.")
        st.caption(_md(f"Last close ${last:,.2f}. With a {pct:g}% stop, your stop is about ${last * (1 - pct / 100):,.2f}."
                       + (f" If you risked ${risk_dollars:,.2f} per trade, a loss costs about that much." if risk_dollars else "")))
        with st.expander("Stuck? What to look for"):
            st.markdown("- Is there a level price keeps turning around (support or resistance)?\n"
                        "- Is the stock in an uptrend (price above a rising orange line)?\n"
                        "- Is price squeezing into a tight range, or did it just break out on big volume?\n"
                        "- Can you see a spot for a stop that is clearly 'wrong if it breaks'?\n"
                        "- If you can't answer these, skipping is a fine choice.")
        st.button("Play it out", key=f"lrn_play_{seed}", on_click=_play, args=(seed,), type="primary")
        return

    # ---- result
    p = chart["plan"]
    if res["action"].startswith("Buy"):
        _plot(lc.build_figure(chart, markup=False, reveal=True, user_plan=res["plan"], show_plan=False), f"lrn_pres_{seed}")
        st.markdown(_md(_result_line(res["out"], risk_dollars)))
    else:
        _plot(lc.build_figure(chart, markup=False, reveal=True, show_plan=False), f"lrn_pres_{seed}")
        st.markdown("**You skipped.**")
    tb = lc.simulate_plan(chart["fut"], p["entry"], p["stop"], p["target"])
    if kind == "none":
        if res["action"].startswith("Buy"):
            st.warning("This chart had no real setup: no level, no clean trend, no squeeze. Buying here is a guess, even if it worked "
                       "out. Judge the decision, not just the result.")
        else:
            st.success("Good skip. This chart had no real setup. Waiting for a clean one is the skill.")
    else:
        verb = "worked" if tb["r"] > 0 else "failed"
        st.info(_md(f"This was a **{lc.NAMES[kind]}** setup. A textbook plan (stop {p['stop']:,.2f}, target {p['target']:,.2f}) "
                    f"{verb} this time ({tb['r']:+.1f}R)."))
        if not res["action"].startswith("Buy"):
            st.caption("Skipping a real setup is fine. You can't take every one. Judge a decision by whether the setup was "
                       "valid, not by one outcome.")
    with st.expander("See this chart marked up"):
        _plot(lc.build_figure(chart, markup=True, reveal=True, show_plan=True), f"lrn_pmark_{seed}")
        for n in chart["g"]["notes"]:
            st.markdown("- " + _md(n))
    st.button("Next chart", key=f"lrn_next_{seed}", on_click=_next_practice, type="primary")


# ------------------------------------------------------------------ the tab
@_fragment
def _tab(risk_dollars=None):
    st.markdown("Learn to read charts and trade the common patterns. Every chart here is **made up by the app** so the "
                "lessons are clean and you can practice as much as you like with no money at risk.")
    mode = st.radio("What do you want to do?", ["Lessons", "Practice trades"], horizontal=True, key="lrn_mode")
    if mode == "Lessons":
        pick = st.selectbox("Lesson", ORDER, format_func=lambda k: LESSONS[k]["title"], key="lrn_lesson")
        _lesson_view(pick, risk_dollars)
    else:
        _practice_view(risk_dollars)
        st.button("Reset my score", key="lrn_reset", on_click=_reset_score)


def show(risk_dollars=None):
    """Draw the Learn tab (call inside `with tab_learn:`). risk_dollars is your planned loss per trade, for examples."""
    _tab(risk_dollars)
