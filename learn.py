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
    "double": dict(
        kind="double", title="8. The double bottom", tagline="A 'W' shape: price tests the same low twice and fails to go lower.",
        idea=("After a long fall, price makes a low, bounces, then drops back to about the **same low** and holds. The shape looks "
              "like a **W**. The second test on lighter volume says the sellers are used up. The trade comes when price closes "
              "above the **neckline**, the high of the bounce in the middle of the W."),
        spot=["A clear downtrend or long fall first.",
              "Two lows at about the same price (within a couple of percent).",
              "Lighter volume on the second low.",
              "A strong close above the neckline on a burst of volume."],
        trade=dict(entry="Buy the next open after price closes above the neckline.",
                   stop="Just under the neckline (or, more cautiously, under the second bottom).",
                   target="2 times your risk."),
        mistakes=["Buying at the second low before it has proved anything. Wait for the neckline break.",
                  "Calling two unrelated dips a double bottom. The lows should be close to each other in price."],
        quiz=[
            dict(q="Where does a double bottom give its buy signal?", options=["At the first low", "When price closes above the neckline",
                                                                              "At the second low"],
                 answer=1, why="The neckline break is the confirmation. Until then it is only a hope."),
            dict(q="What does lighter volume on the second low suggest?", options=["Sellers are running out", "Buyers are gone",
                                                                                  "Nothing at all"],
                 answer=0, why="The sellers who panicked at the first low are already out, so the second test has less push behind it.")]),
    "cup": dict(
        kind="cup", title="9. Cup and handle", tagline="A rounded dip, a climb back to the rim, then a small pause before the move.",
        idea=("A **cup and handle** starts with a rounded, U-shaped dip (not a crash), then price climbs back to where it started "
              "(the **rim**). It pauses with a small, shallow dip on light volume (the **handle**). A close above the rim on strong "
              "volume is the signal. The slow rounded shape shows selling fading gradually, not in a panic."),
        spot=["A rounded bottom, not a sharp V.",
              "Price returns to about where the dip began (the rim).",
              "A short, shallow dip after that (the handle), on light volume.",
              "A close above the rim on a burst of volume."],
        trade=dict(entry="Buy the next open after a strong close above the rim.",
                   stop="Under the low of the handle. If that breaks, the pattern failed.",
                   target="2 times your risk."),
        mistakes=["Calling any dip a cup. A cup is smooth and rounded and takes weeks.",
                  "A handle that dips too deep (more than about a third of the cup) is a warning sign."],
        quiz=[
            dict(q="What does the handle do?", options=["Shakes out the last impatient sellers with a small, quiet dip",
                                                       "Marks the bottom of the cup", "Shows the final target"],
                 answer=0, why="A short quiet dip clears out weak holders before the move resumes."),
            dict(q="Which shape is a cup?", options=["A sharp V", "A smooth, rounded U", "A jagged zig-zag"],
                 answer=1, why="The rounded shape means selling faded slowly and buyers returned slowly.")]),
    "none": dict(
        kind="none", title="10. When there is no trade", tagline="The most underrated skill: doing nothing.",
        idea=("Most charts on most days are not a setup. Sometimes price chops around with no level, sometimes it is in a "
              "steady fall (a 'falling knife'), sometimes it has already sprinted far above its 20-day line (extended), and "
              "sometimes it sits in the middle of a range. Buying anyway is just guessing. Waiting is a position too, and with a small "
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
ORDER = ["basics", "range", "bounce", "breakout", "pullback", "flag", "triangle", "double", "cup", "none"]
STOP_QUIZ_KINDS = {"range", "bounce", "breakout", "pullback", "flag", "triangle", "double", "cup"}
STOP_WHY = {"good": "Right: just beyond the level that proves the idea wrong, so normal wiggles don't knock you out but a real failure does.",
            "tight": "Too tight: so close to the entry that ordinary day-to-day wiggle would knock you out before the idea has a chance.",
            "far": "Too far: a stop this deep means that if you're wrong you lose far more than the setup justifies."}


HINTS = {
    "range": "Price has been bouncing between a floor and a ceiling. Notice where the last candle sits compared with them.",
    "bounce": "A sharp sell-off has run into a price where the stock stopped before, and the last candle has a long lower wick.",
    "breakout": "Price kept getting turned back at the same ceiling, and the last candle just closed above it on heavy volume.",
    "pullback": "The stock is in an uptrend and has just dipped to its rising orange line. The last candle is green.",
    "flag": "A fast run-up was followed by a short, tight drift down on quiet volume, and the last candle breaks out of it.",
    "triangle": "The highs are flat while the lows keep rising, squeezing price tighter, and the last candle closes above the flat top.",
    "double": "After a long fall, price made a low, bounced, fell back to about the same low, and the last candle just closed above the bounce's high.",
    "cup": "Price fell in a smooth rounded dip, climbed back to where it started, paused with a small dip, and the last candle breaks above that level.",
    "none": "Nothing stands out: no level that keeps repeating, no clean trend, no squeeze. Ask yourself if you could name a clear place for a stop.",
}


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


CONE_HELP = ("The shaded cone shows how far this stock usually wanders over the next 15 trading days, based on how much it "
             "has been moving. The darker band is the usual range (about 2 times out of 3); the lighter band is almost everything "
             "(about 19 times out of 20). It says nothing about direction, so it is a map of what is normal, not a prediction.")


def _show_cone(key):
    """The 'show the cone' checkbox shared by lessons and the quiz; on by default."""
    return bool(st.session_state.get(key, True))


def _cone_note(cone, stop=None, target=None):
    """Where a stop or target sits relative to the 15-day cone, in plain English."""
    bits = []
    if target is not None:
        hi68, hi95 = cone["hi68"][-1], cone["hi95"][-1]
        bits.append("your target is " + ("inside the usual range, so it is within normal movement" if target <= hi68 else
                                         "inside the wider range but outside the usual one, so it is possible but not typical"
                                         if target <= hi95 else "beyond even the wider range, so it would take an unusual move"))
    if stop is not None:
        lo68, lo95 = cone["lo68"][-1], cone["lo95"][-1]
        bits.append("your stop is " + ("inside the usual range, so ordinary wiggles could hit it" if stop >= lo68 else
                                       "outside the usual range, so it takes a bigger-than-normal drop to hit it"))
    return ("Against the range cone: " + "; ".join(bits) + ".") if bits else ""


# ------------------------------------------------------------------ lessons
def _lesson_view(key, risk_dollars):
    L = LESSONS[key]
    ss = st.session_state
    sk, rk = f"lrn_seed_{key}", f"lrn_reveal_{key}"
    ss.setdefault(sk, random.randint(1, 10 ** 6))
    st.subheader(L["title"])
    st.caption(L["tagline"])
    st.markdown(L["idea"])

    c1, c2, c3 = st.columns([1, 1.3, 1.7])
    c1.button("New example chart", key=f"lrn_new_{key}", on_click=_new_seed, args=(sk, (rk,)))
    reveal = c2.checkbox("Show what happened next", key=rk)
    show_cone = c3.checkbox("Show the likely range cone", value=True, key="lrn_cone", help=CONE_HELP)
    chart = lc.make_chart(L["kind"], ss[sk])
    basics = key == "basics"
    cone = lc.chart_cone(chart) if show_cone else None
    _plot(lc.build_figure(chart, markup=True, reveal=reveal, basics=basics, show_plan=L["trade"] is not None, cone=cone),
          f"lrn_fig_{key}")
    st.caption("Practice chart made up by the app (not a real stock). The dotted vertical line is the moment you would decide."
               + (" The blue cone is the likely range for the next 15 days (not a prediction)." if cone else ""))

    notes = lc.basics_notes(chart)[1] if basics else chart["g"]["notes"]
    st.markdown("**What to notice**")
    for n in notes:
        st.markdown("- " + _md(n))
    if cone and L["trade"]:
        pl = chart["plan"]
        st.markdown("- " + _md(_cone_note(cone, pl["stop"], pl["target"]).replace("your", "the plan's")))
    if reveal and L["trade"]:
        out = chart["outcome"]
        st.markdown(_md(_result_line(out, risk_dollars)))
        why_txt = WHY_WIN.get(L["kind"]) if out["r"] > 0 else WHY_LOSS.get(L["kind"])
        if why_txt:
            st.markdown("**Why:** " + why_txt)
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


def _shuffled(options, seed):
    """Same answers, in a different order each new quiz chart, so the right one isn't always in the same slot."""
    opts = list(options)
    random.Random(int(seed) * 31 + len(opts)).shuffle(opts)
    return opts


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
        qcone = lc.chart_cone(chart) if _show_cone("lrn_cone") else None
        _plot(lc.build_figure(chart, markup=False, reveal=False, quiz_lines=lines, show_plan=False, cone=qcone),
              f"lrn_qfig_{key}_{qseed}")
        with st.form(f"lrn_form_{key}_{qseed}"):
            picks = []
            if has_stop:
                picks.append(st.radio("Imagine you buy tomorrow's open. Which dashed line is the best place for your stop?",
                                      ["A", "B", "C"], index=None, key=f"lrn_qs_{key}_{qseed}", horizontal=True))
            for i, q in enumerate(L["quiz"]):
                picks.append(st.radio(q["q"], _shuffled(q["options"], qseed + i), index=None, key=f"lrn_q{i}_{key}_{qseed}"))
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
            _plot(lc.build_figure(chart, markup=True, reveal=True, basics=False, show_plan=True, cone=qcone),
                  f"lrn_qans_{key}_{qseed}")
        st.button("New quiz chart", key=f"lrn_qnew_{key}", on_click=_new_seed, args=(qk,))


WHY_WIN = {
    "range": "Support held again. Buyers stepped in at the same floor as before, and price rose back toward the ceiling.",
    "bounce": "The reversal was real. Sellers ran out of steam at support and buyers pushed price back up.",
    "breakout": "The breakout was real. Price held above the old ceiling (which turned into support) and new buyers kept pushing.",
    "pullback": "The uptrend resumed. The dip held near the rising 20-day line and buyers came back.",
    "flag": "The pause was just a pause. Buyers returned and the strong run continued.",
    "triangle": "The squeeze released upward. Buyers kept lifting the lows until they overpowered the flat ceiling.",
    "double": "The second bottom held. Sellers were exhausted at the same low, and the neckline break let buyers take control.",
    "cup": "The rim broke for real. The rounded base and quiet handle had cleared out sellers, so buyers had little resistance.",
}
WHY_LOSS = {
    "range": "Support broke. Price fell below the floor, so the idea (buyers defend this level) was wrong. Leaving is exactly the plan.",
    "bounce": "The bounce failed. Price made a new low under the reversal candle, so sellers were not finished.",
    "breakout": "A false breakout. Price fell back under the old ceiling, so the new buyers weren't really there. This happens "
                "often, and a stop just under the breakout level keeps it small.",
    "pullback": "The dip kept going. Price fell through the 20-day line and the dip's low, which can be the start of a trend "
                "change instead of a rest.",
    "flag": "The flag failed. Price dropped back through the pause instead of continuing, so the buyers did not return.",
    "triangle": "A false breakout. Price fell back inside the pattern. Triangles can fail, which is why the stop sits inside them.",
    "double": "The neckline break failed. Price fell back under it, so the buyers were not strong enough and the 'W' did not complete.",
    "cup": "The breakout failed. Price slipped back under the rim, so the sellers there were not finished.",
}


def _explain(chart, res):
    """Plain-English reasons a practice trade won, lost or went nowhere. Uses what price really did."""
    kind, fut, p, tb = chart["kind"], chart["fut"], chart["plan"], chart["outcome"]
    out, pl = res["out"], res["plan"]
    entry, su, tu = pl["entry"], pl["stop"], pl["target"]
    bars = fut.iloc[: out["bar"] + 1]
    hi, lo = float(bars.High.max()), float(bars.Low.min())
    won, lost = out["reason"].startswith("Target"), out["reason"].startswith("Stop")
    tb_won, tb_lost = tb["reason"].startswith("Target"), tb["reason"].startswith("Stop")
    lines = []
    if kind == "none":
        lines.append(chart["g"].get("none_why", "There was no real setup.") + " Whatever happened afterwards was mostly noise. " + (
                         "A win here is luck, not skill." if won else "A loss here is the price of guessing."))
        return lines

    if won:
        lines.append(f"**Why it worked:** price rose to your target (${tu:,.2f}) before it fell to your stop (${su:,.2f}).")
        if tb_won:
            lines.append(WHY_WIN[kind])
        elif tb_lost:
            how = ("your target was closer than the textbook one, so price reached it before the setup failed"
                   if tu < p["target"] else "your stop was wider than the textbook one, so the early dip didn't knock you out"
                   if su < p["stop"] else "you got out before the setup failed")
            lines.append("The textbook trade for this setup actually lost this time. You won because " + how + ". A win is "
                         "not proof of a good plan, so judge by whether your stop and target were sensible.")
    elif lost:
        gap = " Price gapped through your stop overnight, so you got out a little worse than planned." if "gap" in out["reason"] else ""
        lines.append(f"**Why it lost:** price fell to your stop (${su:,.2f}) before it reached your target (${tu:,.2f}). "
                     f"Your loss was limited to what your stop allowed.{gap}")
        if tb_lost:
            lines.append(WHY_LOSS[kind] + " Even the textbook plan lost here. Some setups fail, and the stop did its job.")
        elif tb_won:
            if entry - su < 0.8 * (entry - p["stop"]):
                lines.append(f"**Your stop was tighter than the pattern needed.** It sat at ${su:,.2f}; the level that proves the "
                             f"idea wrong was about ${p['stop']:,.2f}. Price dipped to ${lo:,.2f} and shook you out, then the setup "
                             "worked. A stop that is too tight loses to ordinary day-to-day wiggle.")
            elif su > p["stop"]:
                lines.append(f"**Close, but just short.** Your stop (${su:,.2f}) sat a little above the pattern's natural stop "
                             f"(about ${p['stop']:,.2f}). Price dipped to ${lo:,.2f}, enough to stop you out before the setup worked. "
                             "That is the trade-off: a closer stop means a smaller loss but more shake-outs.")
            else:
                lines.append(f"**The setup worked, but your target was too far.** Price rose to about ${hi:,.2f} and then turned "
                             f"around before reaching ${tu:,.2f}. A target near where sellers appeared (about ${p['target']:,.2f}) "
                             "would have locked the profit in.")
        else:
            lines.append(f"Price never got past ${hi:,.2f}, so your target looked a bit far for this move.")
    else:
        lines.append(f"**Why neither level was hit:** in {lc.MAX_HOLD} days price peaked at ${hi:,.2f} (your target was "
                     f"${tu:,.2f}) and bottomed at ${lo:,.2f} (your stop was ${su:,.2f}). A target that is too far or a stop that "
                     "is too wide ties your money up. A nearer target at a level where sellers appeared would have worked better.")

    # how the stop and target compare with the pattern's own levels
    risk_u, risk_t = entry - su, entry - p["stop"]
    if risk_u < 0.8 * risk_t:
        lines.append(f"**Stop check:** yours was about {risk_u / entry * 100:.1f}% below your entry; the pattern's natural stop was "
                     f"about {risk_t / entry * 100:.1f}% below. Tighter stops get hit by normal wiggle.")
    elif risk_u > 1.6 * risk_t:
        lines.append(f"**Stop check:** yours was about {risk_u / entry * 100:.1f}% below your entry; the pattern's natural stop was "
                     f"about {risk_t / entry * 100:.1f}%. A stop that far means a bigger loss when you're wrong.")
    else:
        lines.append(f"**Stop check:** your stop was about {risk_u / entry * 100:.1f}% below your entry, close to where the pattern "
                     "says you are wrong. Good.")

    reward_u, reward_t = tu - entry, p["target"] - entry
    peak = f"In your trade's window price peaked at ${hi:,.2f} ({(hi - entry) / entry * 100:+.1f}% from entry)."
    if reward_u < 0.7 * reward_t:
        lines.append(f"**Target check:** yours was about {reward_u / entry * 100:.1f}% above your entry; a sensible target for this "
                     f"setup was about {reward_t / entry * 100:.1f}% (${p['target']:,.2f}). A target that near locks in a small win "
                     f"and may leave profit on the table. {peak}")
    elif reward_u > 1.5 * reward_t:
        lines.append(f"**Target check:** yours was about {reward_u / entry * 100:.1f}% above your entry; a sensible target was about "
                     f"{reward_t / entry * 100:.1f}% (${p['target']:,.2f}). A target that far is rarely reached before the move "
                     f"runs out of steam. {peak}")
    else:
        lines.append(f"**Target check:** yours was about {reward_u / entry * 100:.1f}% above your entry, close to a sensible "
                     f"target of about {reward_t / entry * 100:.1f}% (${p['target']:,.2f}). Good. {peak}")
    return lines


def _process_note(chart, res):
    """For a trade that didn't make money: praise a sound stop (and target) so a loss isn't read as a mistake."""
    out, pl, p = res["out"], res["plan"], chart["plan"]
    if out["r"] > 0:
        return None
    entry = pl["entry"]
    risk_u, risk_t = entry - pl["stop"], entry - p["stop"]
    reward_u, reward_t = pl["target"] - entry, p["target"] - entry
    stop_ok = 0.8 * risk_t <= risk_u <= 1.6 * risk_t
    target_ok = 0.7 * reward_t <= reward_u <= 1.5 * reward_t
    if not stop_ok:
        return None
    lost = out["reason"].startswith("Stop")
    base = ("While you didn't make money this time, you set your stop in a sensible place" if not target_ok else
            "While you didn't make money this time, your stop and your target were both sensible")
    what = ("Your loss stayed small and planned, which is exactly what a stop is for. " if lost else
            "Neither level was hit, and you got out with a small result. ")
    tail = ("Good trades lose sometimes; even a well-planned setup fails about half the time. Judge the plan, not the outcome. "
            "Do this over and over and the winners pay for the losers.")
    extra = "" if target_ok else " Your target was a bit off (see the Target check above), but the stop did its job."
    return f"{base}. {what}{tail}{extra}"


# ------------------------------------------------------------------ practice mode
def _score():
    return st.session_state.setdefault("lrn_score", dict(trades=0, wins=0, r=0.0, skips=0, good_skips=0, hints=0))


def _pkind(seed):
    rng = random.Random(seed)
    return rng.choices(list(lc.PRACTICE_WEIGHTS), weights=list(lc.PRACTICE_WEIGHTS.values()))[0]


def _play(seed):
    ss = st.session_state
    kind = _pkind(seed)
    chart = lc.make_chart(kind, seed)
    action = ss.get(f"lrn_pa_{seed}", "Buy at the next open")
    sc = _score()
    p = chart["plan"]
    res = {"seed": seed, "kind": kind, "action": action, "hint": bool(ss.get(f"lrn_hint_{seed}"))}
    if action.startswith("Buy"):
        entry = p["entry"]
        stop = float(ss.get(f"lrn_ps_{seed}") or 0.0)
        target = float(ss.get(f"lrn_pt_{seed}") or 0.0)
        if not (0 < stop < entry < target):
            return          # the form already explains this; nothing is played or scored
        out = lc.simulate_plan(chart["fut"], entry, stop, target)
        res.update(plan=dict(entry=entry, stop=stop, target=target), out=out)
        sc["trades"] += 1
        sc["wins"] += int(out["r"] > 0)
        sc["r"] += float(out["r"])
    else:
        sc["skips"] += 1
        sc["good_skips"] += int(kind == "none")
    sc["hints"] = sc.get("hints", 0) + int(res["hint"])
    ss["lrn_pres"] = res
    ss["lrn_pplayed"] = seed


def _use_hint(seed):
    st.session_state[f"lrn_hint_{seed}"] = True


def _next_practice():
    st.session_state["lrn_pseed"] = random.randint(1, 10 ** 6)
    st.session_state["lrn_pplayed"] = None


def _reset_score():
    st.session_state["lrn_score"] = dict(trades=0, wins=0, r=0.0, skips=0, good_skips=0, hints=0)


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
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Trades taken", sc["trades"])
    m2.metric("Win rate", f"{sc['wins'] / sc['trades'] * 100:.0f}%" if sc["trades"] else "-",
              help="How often your trade made money. A win rate near half is normal. What matters is the size of wins versus losses.")
    m3.metric("Avg R per trade", f"{sc['r'] / sc['trades']:+.2f}" if sc["trades"] else "-",
              help="Average result per trade in units of what you risked. Above 0 means you made money on average.")
    m4.metric("Skipped", sc["skips"], help="Skipping is a decision too. Skipping a chart with no setup is a good one.")
    m5.metric("Hints used", sc.get("hints", 0), help="Fewer is better, but using a hint to learn is fine.")

    played = ss.get("lrn_pplayed") == seed
    res = ss.get("lrn_pres") if played else None
    show_cone = st.checkbox("Show the likely range cone (next 15 trading days)", value=True, key="lrn_pcone", help=CONE_HELP)
    cone = lc.chart_cone(chart) if show_cone else None
    if not played:
        _plot(lc.build_figure(chart, markup=False, reveal=False, show_plan=False, cone=cone), f"lrn_pfig_{seed}")
        last = float(chart["hist"].Close.iloc[-1])
        buy_first = st.radio("Your call", ["Buy at the next open", "Skip this one"], key=f"lrn_pa_{seed}", horizontal=True)
        buying = buy_first.startswith("Buy")
        ok = True
        if buying:
            b1, b2 = st.columns(2)
            stop_v = b1.number_input("Your stop price ($)", min_value=0.01, value=None, placeholder="Type a price", step=0.05,
                                     format="%.2f", key=f"lrn_ps_{seed}",
                                     help="If price falls to this, you sell and take the loss. Put it just beyond a level "
                                          "that would prove your idea wrong.")
            tgt_v = b2.number_input("Your target price ($)", min_value=0.01, value=None, placeholder="Type a price", step=0.05,
                                    format="%.2f", key=f"lrn_pt_{seed}",
                                    help="If price rises to this, you sell and take the profit. A spot where sellers have "
                                         "shown up before, or a multiple of your risk.")
            if stop_v is None or tgt_v is None:
                ok = False
                st.info(_md(f"Last close ${last:,.2f}. Type your own stop (below it) and target (above it), then press Enter. "
                            "Look at the chart for the levels you would use."))
            elif stop_v > last * 0.99 or tgt_v < last * 1.01:
                ok = False
                st.error(_md(f"Your stop must be below the last close (${last:,.2f}) and your target above it, each by at least 1%. "
                             "You would buy at about the last close."))
            else:
                risk, reward = last - stop_v, tgt_v - last
                rr = reward / risk
                st.caption(_md(
                    f"Last close ${last:,.2f}. Risk ${risk:,.2f} per share ({risk / last * 100:.1f}%), reward ${reward:,.2f} "
                    f"({reward / last * 100:.1f}%). Your reward is {rr:.1f} times your risk, so you would need to win about "
                    f"{100 / (1 + rr):.0f}% of trades like this to break even."
                    + (f" If you risked ${risk_dollars:,.2f}, a full win would be about ${risk_dollars * rr:,.2f}."
                       if risk_dollars else "")
                    ))
                if rr < 1:
                    st.warning("Your target is closer than your stop. You would need to win more than half your trades just to break even.")
        h1, h2 = st.columns([1, 3])
        used = bool(ss.get(f"lrn_hint_{seed}"))
        h1.button("Show one hint" if not used else "Hint used", key=f"lrn_hintbtn_{seed}", on_click=_use_hint, args=(seed,),
                  disabled=used, help="One hint per chart. It tells you what is going on without giving away the stop or target.")
        if used:
            h2.info(chart["g"].get("hint") or HINTS[kind])
        with st.expander("Stuck? A checklist"):
            st.markdown("- Is there a level price keeps turning around (support or resistance)?\n"
                        "- Is the stock in an uptrend (price above a rising orange line)?\n"
                        "- Is price squeezing into a tight range, or did it just break out on big volume?\n"
                        "- Can you see a spot for a stop that is clearly 'wrong if it breaks'?\n"
                        "- If you can't answer these, skipping is a fine choice.")
        st.button("Play it out", key=f"lrn_play_{seed}", on_click=_play, args=(seed,), type="primary", disabled=not ok)
        return

    # ---- result
    p = chart["plan"]
    if res["action"].startswith("Buy"):
        _plot(lc.build_figure(chart, markup=False, reveal=True, user_plan=res["plan"], show_plan=False, cone=cone),
              f"lrn_pres_{seed}")
        pl = res["plan"]
        st.markdown(_md(_result_line(res["out"], risk_dollars)))
        st.caption(_md(f"Your plan: buy about ${pl['entry']:,.2f}, stop ${pl['stop']:,.2f}, target ${pl['target']:,.2f} "
                       f"({(pl['target'] - pl['entry']) / (pl['entry'] - pl['stop']):.1f} times your risk)."))
        for line in _explain(chart, res):
            st.markdown("- " + _md(line))
        if kind != "none":
            note = _process_note(chart, res)
            if note:
                st.success(_md(note))
    else:
        _plot(lc.build_figure(chart, markup=False, reveal=True, show_plan=False, cone=cone), f"lrn_pres_{seed}")
        st.markdown("**You skipped.**")
    tb = lc.simulate_plan(chart["fut"], p["entry"], p["stop"], p["target"])
    if kind == "none":
        if res["action"].startswith("Buy"):
            st.warning("This chart had no real setup. Buying here is a guess, even if it worked out. Judge the decision, "
                       "not just the result.")
            for line in _explain(chart, res):
                st.markdown("- " + _md(line))
        else:
            st.success("Good skip. This chart had no real setup. Waiting for a clean one is the skill.")
            st.markdown("- **Why there was nothing to trade:** " + chart["g"].get("none_why", "no clear setup."))
    else:
        verb = "worked" if tb["r"] > 0 else "failed"
        st.info(_md(f"This was a **{lc.NAMES[kind]}** setup. A textbook plan (stop {p['stop']:,.2f}, target {p['target']:,.2f}) "
                    f"{verb} this time ({tb['r']:+.1f}R)."))
        if not res["action"].startswith("Buy"):
            st.markdown("- " + (("**Why it would have worked:** " + WHY_WIN[kind]) if tb["r"] > 0
                                else ("**Why it would have failed:** " + WHY_LOSS[kind])))
            st.caption("Skipping a real setup is fine. You can't take every one. Judge a decision by whether the setup was "
                       "valid, not by one outcome.")
    with st.expander("See this chart marked up"):
        _plot(lc.build_figure(chart, markup=True, reveal=True, show_plan=True, cone=cone), f"lrn_pmark_{seed}")
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
