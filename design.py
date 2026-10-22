"""
Signal Watch look and feel.

Idea: a lighthouse watching the market at night. A deep blue-night base, one amber "beacon" accent, and a
beacon in the header that takes the colour of the market weather (teal = sunny, amber = partly cloudy,
coral = stormy). Type is Atkinson Hyperlegible, a face made for easy reading at a glance.

Colours also live in .streamlit/config.toml (the official theme); this file adds the finer touches.
"""
from html import escape

NIGHT = "#0F1722"     # page
HARBOR = "#172233"    # sidebar, cards, boxes
TIDE = "#2A3B55"      # borders, grid lines
FOG = "#E6ECF4"       # text
MIST = "#9AA9BD"      # quiet text
BEACON = "#F5B544"    # the one accent: buttons, selected tab, links
GAIN = "#3DBFA0"      # sunny / up
LOSS = "#F07167"      # stormy / down
SKY = "#7DB3F0"       # neutral information

WEATHER_COLOURS = {"success": GAIN, "info": SKY, "warning": BEACON, "error": LOSS}

CONFIG_TOML = f"""[client]
toolbarMode = "minimal"

[theme]
base = "dark"
primaryColor = "{BEACON}"
backgroundColor = "{NIGHT}"
secondaryBackgroundColor = "{HARBOR}"
textColor = "{FOG}"
"""


def ensure_config(app_file):
    """
    Streamlit only reads colours from .streamlit/config.toml. If that hidden file didn't get copied along with
    the app, write it. Returns True if it was just created (the app must be restarted once to pick it up).
    """
    from pathlib import Path
    cfg = Path(app_file).with_name(".streamlit") / "config.toml"
    if cfg.exists():
        return False
    try:
        cfg.parent.mkdir(exist_ok=True)
        cfg.write_text(CONFIG_TOML)
        return True
    except Exception:
        return False


CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&display=swap');

:root {{
  --sw-night: {NIGHT}; --sw-harbor: {HARBOR}; --sw-tide: {TIDE}; --sw-fog: {FOG};
  --sw-mist: {MIST}; --sw-beacon: {BEACON}; --sw-gain: {GAIN}; --sw-loss: {LOSS};
  --sw-font: 'Atkinson Hyperlegible', 'Segoe UI', system-ui, -apple-system, sans-serif;
}}

/* Type: set only on text containers so Streamlit's icon fonts are left alone. */
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4, [data-testid="stCaptionContainer"],
[data-testid="stWidgetLabel"] p, button[role="tab"] p, .stButton button p,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stExpander"] summary p,
.stTextInput input, .stNumberInput input, .stTextArea textarea, .sw-head, .sw-practice {{
  font-family: var(--sw-font);
}}
[data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {{ font-weight: 700; letter-spacing: -0.01em; }}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {{ line-height: 1.55; }}
[data-testid="stMetricValue"], [data-testid="stDataFrame"], table, td {{ font-variant-numeric: tabular-nums; }}

/* Header */
.sw-head {{ display: flex; align-items: center; gap: 14px; padding: 4px 0 14px; }}
.sw-beacon {{ width: 54px; height: 54px; flex: none; color: var(--sw-beacon-now, var(--sw-beacon)); }}
.sw-beacon .glow {{ transform-origin: 32px 24px; animation: sw-glow 5s ease-in-out infinite; }}
.sw-title {{ font-size: 1.75rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.1; color: var(--sw-fog); }}
.sw-sub {{ color: var(--sw-mist); font-size: 0.98rem; margin-top: 3px; }}
@keyframes sw-glow {{ 0%, 100% {{ opacity: 0.55; transform: scale(0.94); }} 50% {{ opacity: 1; transform: scale(1.06); }} }}
@media (prefers-reduced-motion: reduce) {{ .sw-beacon .glow {{ animation: none; opacity: 0.9; }} }}

/* Practice-mode notice */
.sw-practice {{ background: #2B2450; color: var(--sw-fog); padding: 10px 14px; border-radius: 10px;
  border-left: 4px solid #A98BFF; margin-bottom: 10px; }}

/* Tabs: bigger targets, clear selected state */
[data-testid="stTabs"] button[role="tab"] {{ padding: 10px 14px; }}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] p {{ font-weight: 700; color: var(--sw-fog); }}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 4px; }}

/* Buttons */
.stButton > button, [data-testid="stBaseButton-secondary"] {{
  border-radius: 10px; border: 1px solid var(--sw-tide); background: var(--sw-harbor); color: var(--sw-fog);
  transition: border-color 120ms ease, background 120ms ease;
}}
.stButton > button:hover, [data-testid="stBaseButton-secondary"]:hover {{
  border-color: var(--sw-beacon); background: #1D2B41; color: var(--sw-fog);
}}
.stButton > button:focus-visible {{ outline: 2px solid var(--sw-beacon); outline-offset: 2px; }}
button[kind="primary"], [data-testid="stBaseButton-primary"] {{
  background: var(--sw-beacon); color: var(--sw-night); border: 1px solid var(--sw-beacon);
  border-radius: 10px; font-weight: 700;
}}
button[kind="primary"] p, [data-testid="stBaseButton-primary"] p {{ color: var(--sw-night); }}

/* Boxes */
[data-testid="stAlert"] {{ border-radius: 12px; }}
[data-testid="stExpander"] {{ border: 1px solid var(--sw-tide); border-radius: 12px; background: var(--sw-harbor); }}
[data-testid="stMetric"] {{ background: var(--sw-harbor); border: 1px solid var(--sw-tide); border-radius: 12px;
  padding: 12px 16px; }}
[data-testid="stSidebar"] {{ border-right: 1px solid var(--sw-tide); }}
[data-testid="stDataFrame"] {{ border-radius: 10px; }}

/* Phones */
@media (max-width: 640px) {{
  .sw-title {{ font-size: 1.4rem; }}
  .sw-beacon {{ width: 44px; height: 44px; }}
}}
"""


def inject():
    """Add the stylesheet to the page. Call once, near the top of the app."""
    import streamlit as st
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


def header(weather_level=None, weather_label=None):
    """Wordmark with a beacon that takes the colour of the market weather."""
    import streamlit as st
    colour = WEATHER_COLOURS.get(weather_level, BEACON)
    title = f"Market weather: {escape(str(weather_label))}" if weather_label else "Market weather unavailable"
    svg = (
        f'<svg class="sw-beacon" viewBox="0 0 64 64" role="img" aria-label="{title}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<g class="glow" fill="currentColor"><circle cx="32" cy="24" r="14" opacity="0.22"/></g>'
        f'<g stroke="currentColor" stroke-width="3" stroke-linecap="round" opacity="0.8">'
        f'<path d="M8 24h6M50 24h6M13 9l5 4M51 9l-5 4"/></g>'
        f'<circle cx="32" cy="24" r="7" fill="currentColor"/>'
        f'<path d="M26 34h12l3 22H23z" fill="none" stroke="#9AA9BD" stroke-width="3" stroke-linejoin="round"/>'
        f'<path d="M21 56h22" stroke="#9AA9BD" stroke-width="3" stroke-linecap="round"/></svg>')
    st.markdown(
        f'<div class="sw-head" style="--sw-beacon-now:{colour}">{svg}'
        f'<div><div class="sw-title">Signal Watch</div>'
        f'<div class="sw-sub">Learn to read the market. Every trade you make is your own call.</div></div></div>',
        unsafe_allow_html=True)


def practice_banner():
    import streamlit as st
    st.markdown("<div class='sw-practice'><b>Practice mode.</b> This is fake money. Trades you record here are "
                "kept apart from your real ones.</div>", unsafe_allow_html=True)


# ---- chart theme: the same dark Plotly look, but on the app's own blue-night background
CHART = "plotly_dark"
try:
    import copy
    import plotly.io as pio

    _t = copy.deepcopy(pio.templates["plotly_dark"])
    _t.layout.update(paper_bgcolor=NIGHT, plot_bgcolor=NIGHT, font=dict(color=FOG),
                     xaxis=dict(gridcolor=TIDE, zerolinecolor=TIDE, linecolor=TIDE),
                     yaxis=dict(gridcolor=TIDE, zerolinecolor=TIDE, linecolor=TIDE))
    pio.templates["signal_dark"] = _t
    CHART = "signal_dark"
except Exception:
    pass
