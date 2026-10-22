"""
Signal Watch look and feel.

Idea: a lighthouse watching the market at night. A dark base, one accent colour (the "beacon"), and a beacon
in the header that takes the colour of the market weather (teal = sunny, amber = partly cloudy, coral = stormy).
Type is Atkinson Hyperlegible, a face made for easy reading at a glance.

The four colours (page, boxes, text, accent) can be changed from the sidebar under Colors. They are saved in
signal_settings.json. Streamlit itself only reads colours from .streamlit/config.toml, so that file is rewritten
too; after a colour change, close and reopen the app once so checkboxes and sliders pick it up.
"""
import json
from html import escape
from pathlib import Path

# ---- colour schemes: page, boxes (sidebar, cards), text, accent
DEFAULT_NAME = "Night harbor"
PRESETS = {
    "Night harbor":    {"bg": "#0F1722", "box": "#172233", "text": "#E6ECF4", "accent": "#F5B544"},
    "Plum and mint":   {"bg": "#17121F", "box": "#221A2E", "text": "#EFE9F7", "accent": "#7FE0C2"},
    "Graphite and orchid": {"bg": "#141415", "box": "#1F1F22", "text": "#EDEDF0", "accent": "#C792EA"},
    "Forest and sand": {"bg": "#101A16", "box": "#18261F", "text": "#E7EFE9", "accent": "#D9B88F"},
    "Ember":           {"bg": "#1A1311", "box": "#271C19", "text": "#F3EAE6", "accent": "#FF8F6B"},
}

# meaning colours stay fixed so "good" and "bad" always read the same
GAIN = "#3DBFA0"
LOSS = "#F07167"
SKY = "#7DB3F0"
CAUTION = "#F5B544"
WEATHER_COLOURS = {"success": GAIN, "info": SKY, "warning": CAUTION, "error": LOSS}


# ---- colour maths
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def mix(a, b, t):
    """Blend colour a toward colour b by fraction t (0 = a, 1 = b)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def _lum(h):
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check_palette(p):
    """Return a plain-English problem with this scheme, or None if it is readable."""
    if contrast(p["text"], p["bg"]) < 4.5 or contrast(p["text"], p["box"]) < 4.5:
        return "The text colour is too close to the background colours to read comfortably."
    if contrast(p["accent"], p["bg"]) < 3:
        return "The accent colour is too close to the background to stand out."
    if _lum(p["bg"]) > 0.25 or _lum(p["box"]) > 0.3:
        return "Pick darker page and box colours. The charts are built for a dark background."
    return None


def derive(p):
    """Everything else the design needs, worked out from the four chosen colours."""
    on_accent = p["bg"] if contrast(p["bg"], p["accent"]) >= contrast(p["text"], p["accent"]) else p["text"]
    return {
        "night": p["bg"], "harbor": p["box"], "fog": p["text"], "beacon": p["accent"],
        "tide": mix(p["box"], p["text"], 0.18),        # borders and grid lines
        "mist": mix(p["text"], p["box"], 0.38),        # quiet text
        "hover": mix(p["box"], p["text"], 0.06),
        "on_accent": on_accent,
    }


# ---- saved choice
def load_choice(settings_path):
    try:
        t = json.loads(Path(settings_path).read_text()).get("theme", {})
    except Exception:
        t = {}
    return t if isinstance(t, dict) else {}


def save_choice(settings_path, name, custom=None):
    try:
        data = json.loads(Path(settings_path).read_text())
    except Exception:
        data = {}
    data["theme"] = {"name": name, "custom": custom or {}}
    Path(settings_path).write_text(json.dumps(data))


def palette_for(choice):
    name = choice.get("name", DEFAULT_NAME)
    if name == "Custom":
        c = choice.get("custom", {})
        p = {k: c.get(k, PRESETS[DEFAULT_NAME][k]) for k in ("bg", "box", "text", "accent")}
        if check_palette(p) is None:
            return "Custom", p
        return DEFAULT_NAME, dict(PRESETS[DEFAULT_NAME])
    if name in PRESETS:
        return name, dict(PRESETS[name])
    return DEFAULT_NAME, dict(PRESETS[DEFAULT_NAME])


# ---- Streamlit's own theme file
def config_text(p):
    return ("[client]\ntoolbarMode = \"minimal\"\n\n[theme]\nbase = \"dark\"\n"
            f"primaryColor = \"{p['accent']}\"\nbackgroundColor = \"{p['bg']}\"\n"
            f"secondaryBackgroundColor = \"{p['box']}\"\ntextColor = \"{p['text']}\"\n")


def ensure_config(app_file, p=None):
    """
    Streamlit only reads colours from .streamlit/config.toml. Write it if it is missing or no longer matches the
    chosen colours. Returns True if it was just written (the app must be restarted once to pick it up).
    """
    cfg = Path(app_file).with_name(".streamlit") / "config.toml"
    want = config_text(p or _P)
    try:
        if cfg.exists() and cfg.read_text() == want:
            return False
        cfg.parent.mkdir(exist_ok=True)
        cfg.write_text(want)
        return True
    except Exception:
        return False


# ---- stylesheet
def build_css(p):
    d = derive(p)
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&display=swap');

:root {{
  --sw-night: {d['night']}; --sw-harbor: {d['harbor']}; --sw-tide: {d['tide']}; --sw-fog: {d['fog']};
  --sw-mist: {d['mist']}; --sw-beacon: {d['beacon']}; --sw-hover: {d['hover']}; --sw-on-accent: {d['on_accent']};
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
.sw-practice {{ background: {mix(d['harbor'], '#A98BFF', 0.22)}; color: var(--sw-fog); padding: 10px 14px;
  border-radius: 10px; border-left: 4px solid #A98BFF; margin-bottom: 10px; }}

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
  border-color: var(--sw-beacon); background: var(--sw-hover); color: var(--sw-fog);
}}
.stButton > button:focus-visible {{ outline: 2px solid var(--sw-beacon); outline-offset: 2px; }}
button[kind="primary"], [data-testid="stBaseButton-primary"] {{
  background: var(--sw-beacon); color: var(--sw-on-accent); border: 1px solid var(--sw-beacon);
  border-radius: 10px; font-weight: 700;
}}
button[kind="primary"] p, [data-testid="stBaseButton-primary"] p {{ color: var(--sw-on-accent); }}

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


# ---- the active scheme
_NAME, _P = DEFAULT_NAME, dict(PRESETS[DEFAULT_NAME])
CHART = "plotly_dark"


def apply(p):
    """Make `p` the active colour scheme: rebuilds the chart theme so figures match."""
    global _P, CHART
    _P = dict(p)
    d = derive(_P)
    try:
        import copy
        import plotly.io as pio

        t = copy.deepcopy(pio.templates["plotly_dark"])
        t.layout.update(paper_bgcolor=d["night"], plot_bgcolor=d["night"], font=dict(color=d["fog"]),
                        xaxis=dict(gridcolor=d["tide"], zerolinecolor=d["tide"], linecolor=d["tide"]),
                        yaxis=dict(gridcolor=d["tide"], zerolinecolor=d["tide"], linecolor=d["tide"]))
        pio.templates["signal_dark"] = t
        CHART = "signal_dark"
    except Exception:
        CHART = "plotly_dark"


def inject():
    """Add the stylesheet to the page. Call once, near the top of the app."""
    import streamlit as st
    st.markdown(f"<style>{build_css(_P)}</style>", unsafe_allow_html=True)


def header(weather_level=None, weather_label=None):
    """Wordmark with a beacon that takes the colour of the market weather."""
    import streamlit as st
    colour = WEATHER_COLOURS.get(weather_level, _P["accent"])
    d = derive(_P)
    title = f"Market weather: {escape(str(weather_label))}" if weather_label else "Market weather unavailable"
    svg = (
        f'<svg class="sw-beacon" viewBox="0 0 64 64" role="img" aria-label="{title}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<g class="glow" fill="currentColor"><circle cx="32" cy="24" r="14" opacity="0.22"/></g>'
        f'<g stroke="currentColor" stroke-width="3" stroke-linecap="round" opacity="0.8">'
        f'<path d="M8 24h6M50 24h6M13 9l5 4M51 9l-5 4"/></g>'
        f'<circle cx="32" cy="24" r="7" fill="currentColor"/>'
        f'<path d="M26 34h12l3 22H23z" fill="none" stroke="{d["mist"]}" stroke-width="3" stroke-linejoin="round"/>'
        f'<path d="M21 56h22" stroke="{d["mist"]}" stroke-width="3" stroke-linecap="round"/></svg>')
    st.markdown(
        f'<div class="sw-head" style="--sw-beacon-now:{colour}">{svg}'
        f'<div><div class="sw-title">Signal Watch</div>'
        f'<div class="sw-sub">Learn to read the market. Every trade you make is your own call.</div></div></div>',
        unsafe_allow_html=True)


def practice_banner():
    import streamlit as st
    st.markdown("<div class='sw-practice'><b>Practice mode.</b> This is fake money. Trades you record here are "
                "kept apart from your real ones.</div>", unsafe_allow_html=True)


def colors_ui(settings_path):
    """Sidebar box for choosing a colour scheme. Saves the choice and reruns the app so it takes effect."""
    import streamlit as st
    choice = load_choice(settings_path)
    cur_name, cur_p = palette_for(choice)
    names = list(PRESETS) + ["Custom"]
    with st.sidebar.expander("Colors"):
        picked = st.selectbox("Color scheme", names, index=names.index(cur_name), key="theme_pick",
                              help="Pick a ready-made scheme, or choose Custom to set your own four colors. "
                                   "Meaning colors stay the same: teal for gains and coral for losses.")
        new_custom = dict(choice.get("custom") or cur_p)
        if picked == "Custom":
            base = {k: new_custom.get(k, cur_p[k]) for k in ("bg", "box", "text", "accent")}
            c1, c2 = st.columns(2)
            base["bg"] = c1.color_picker("Page", base["bg"], key="theme_bg")
            base["box"] = c2.color_picker("Boxes and sidebar", base["box"], key="theme_box")
            base["text"] = c1.color_picker("Text", base["text"], key="theme_text")
            base["accent"] = c2.color_picker("Accent", base["accent"], key="theme_accent")
            problem = check_palette(base)
            if problem:
                st.warning(problem)
            new_custom = base
            new_p = base
        else:
            problem = None
            new_p = PRESETS[picked]
        if not problem and (picked != cur_name or (picked == "Custom" and new_p != cur_p)):
            save_choice(settings_path, picked, new_custom if picked == "Custom" else choice.get("custom"))
            st.rerun()
        if picked != DEFAULT_NAME and st.button("Back to the default colors", key="theme_reset"):
            save_choice(settings_path, DEFAULT_NAME, choice.get("custom"))
            st.rerun()
        st.caption("After changing colors, close Signal Watch and open it again once so every checkbox and "
                   "slider picks up the new accent.")


apply(PRESETS[DEFAULT_NAME])
