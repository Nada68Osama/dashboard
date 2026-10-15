"""
Junction Live View  —  عرض التقاطع (Streamlit, view-only)

تشغيل:  streamlit run app1.py
حطي كل ملفات الإكسيل في فولدر  data/  جنب الملف ده (أي عدد ملفات).
الشريط اللي تحت بيعرض كل فايل في صف: بدايته ونهايته، والأوقات اللي فيها عربيات (أصفر) واللي مفيهاش (رمادي).
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
VIEWER = HERE / "viewer8.html"

# كام عربية بتمثلها 1 vph — عدد العربيات المعروضة = volumePerHour / CARS_DIV
CARS_DIV = 30
# أقصى فرق (بالثواني) لمطابقة وقت TurnRatios مع أقرب وقت في Approaches
TURN_MATCH_SEC = 90

# ---- ترجمة أسماء الشوارع (ضيفي أي شارع جديد هنا) ----
STREETS_EN = {
    "طريق النصر": "Nasr Road",
    "شارع السلام": "El Salam St.",
    "السكة الحديد": "Railway St.",
    "نصر أبو الفرج": "Nasr Abu El Farag",
}
DIRS = {  # EN label, AR label
    "North": ("Northbound", "شمالًا"),
    "South": ("Southbound", "جنوبًا"),
    "East": ("Eastbound", "شرقًا"),
    "West": ("Westbound", "غربًا"),
}

st.set_page_config(page_title="Junction Live View", page_icon="🚦", layout="wide",
                   initial_sidebar_state="collapsed")

# شاشة كاملة بدون عناصر ستريمليت
st.markdown(
    """
    <style>
      header[data-testid="stHeader"], footer, [data-testid="stSidebar"],
      [data-testid="stToolbar"], #MainMenu {display:none !important;}
      .block-container {padding:0 !important; max-width:100% !important;}
      [data-testid="stAppViewContainer"] {background:#0b1020;}
      iframe {height:100vh !important; border:0; display:block;}
      [data-testid="stElementContainer"]:has(iframe) {height:100vh !important;}
      [data-testid="stElementContainer"]:has(style) {display:none !important;}
      [data-testid="stVerticalBlock"] {gap:0 !important;}
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_wkt(wkt):
    """MULTILINESTRING (lon lat) -> [[lat, lon], ...] متصلة وبدون تكرار."""
    pts = [[float(y), float(x)] for x, y in re.findall(r"(-?\d+\.\d+)\s+(-?\d+\.\d+)", str(wkt))]
    out = []
    for p in pts:
        if not out or out[-1] != p:
            out.append(p)
    return out


def split_name(name):
    """'<شارع> North Bound' أو 'North Bound' بس -> (EN, AR)."""
    s = str(name).strip()
    m = re.match(r"^(.*?)\s*(North|South|East|West)\s*Bound$", s, re.I)
    if not m:
        return s, s
    street, d = m.group(1).strip(), m.group(2).capitalize()
    en_dir, ar_dir = DIRS[d]
    if not street:
        return en_dir, f"متجه {ar_dir}"
    return f"{STREETS_EN.get(street, street)} {en_dir}", f"{street} ({ar_dir})"


def num(x):
    return None if pd.isna(x) else float(x)


def to_ms(ts):
    # نفس التوقيت المحلي بالظبط (بنعامله UTC في المتصفح عشان ما يتغيرش)
    return int(pd.Timestamp(ts).tz_localize("UTC").timestamp() * 1000)


def build_file(path: Path):
    xl = pd.ExcelFile(path)
    appr = xl.parse("Approaches")
    appr["time"] = pd.to_datetime(appr["time"])
    appr = appr.dropna(subset=["time"])
    turns = xl.parse("TurnRatios") if "TurnRatios" in xl.sheet_names else pd.DataFrame()

    times = sorted(appr["time"].unique())
    times_ms = [to_ms(t) for t in times]
    t_ns = np.array([pd.Timestamp(t).value for t in times], dtype="int64")
    tindex = {pd.Timestamp(t): i for i, t in enumerate(times)}

    def nearest(ts):
        v = pd.Timestamp(ts).value
        j = int(np.abs(t_ns - v).argmin())
        return j if abs(t_ns[j] - v) <= TURN_MATCH_SEC * 1e9 else None

    approaches = []
    for aid, g in appr.groupby("approachId", sort=False):
        en, ar = split_name(g["approachName"].iloc[0])
        n = len(times)
        ser = {k: [None] * n for k in ("vph", "tt", "delay", "ff")}
        for _, r in g.iterrows():
            i = tindex[pd.Timestamp(r["time"])]
            ser["vph"][i] = num(r["volumePerHour"])
            ser["tt"][i] = num(r["travelTimeSec"])
            ser["delay"][i] = num(r["delaySec"])
            ser["ff"][i] = num(r["freeFlowTravelTimeSec"])
        approaches.append({"id": int(aid), "name_en": en, "name_ar": ar, "raw": str(g["approachName"].iloc[0]),
                           "coords": parse_wkt(g["segmentGeometryWKT"].iloc[0]), **ser})

    # لو فيه أكتر من approach بنفس الاسم (مثلاً 2 North Bound) نرقّمهم
    for key in ("name_en", "name_ar"):
        names = [a[key] for a in approaches]
        seen = {}
        for a in approaches:
            if names.count(a[key]) > 1:
                seen[a[key]] = seen.get(a[key], 0) + 1
                a[key] = f"{a[key]} #{seen[a[key]]}"

    exits = {}
    if not turns.empty:
        turns["time"] = pd.to_datetime(turns["time"])
        for _, r in turns.iterrows():
            k = (int(r["approachId"]), int(r["exitId"]))
            if k not in exits:
                if pd.isna(r.get("segmentGeometryWKT")):
                    continue
                en, ar = split_name(r["exitName"])
                exits[k] = {"aid": k[0], "eid": k[1], "name_en": en, "name_ar": ar, "raw": str(r["exitName"]),
                            "coords": parse_wkt(r["segmentGeometryWKT"]),
                            "vol": [None] * len(times), "pct": [None] * len(times)}
            i = nearest(r["time"])
            if i is not None and k in exits:
                exits[k]["vol"][i] = num(r["volumePerExit"])
                exits[k]["pct"][i] = num(r["ratioPercent"])

    return {
        "name": path.stem,
        "junction": str(appr["junctionName"].iloc[0]),
        "start": times_ms[0], "end": times_ms[-1],
        "times": times_ms, "approaches": approaches, "exits": list(exits.values()),
    }


@st.cache_data(show_spinner=False)
def build_payload(paths: tuple, mtimes: tuple):
    files = [build_file(Path(p)) for p in paths]
    files.sort(key=lambda f: (f["start"], f["name"]))
    return {"carsDiv": CARS_DIV, "files": files}


files = sorted(p for p in (DATA_DIR.glob("*.xlsx") if DATA_DIR.exists() else HERE.glob("*.xlsx"))
               if not p.name.startswith("~$"))
if not files:
    st.error(f"مفيش ملفات xlsx جوه: {DATA_DIR}")
    st.stop()

payload = build_payload(tuple(map(str, files)), tuple(p.stat().st_mtime for p in files))
html = VIEWER.read_text(encoding="utf-8").replace(
    "__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
)
if hasattr(st, "iframe"):          # ستريمليت الجديد
    st.iframe(html, height=900)
else:                              # نسخ أقدم
    import streamlit.components.v1 as components
    components.html(html, height=900, scrolling=False)
