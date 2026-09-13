#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تحليل مقارن لحركة الطيران في ثلاثة مطارات سورية:
  دمشق (OSDI/DAM) — حلب (OSAP/ALP) — اللاذقية (OSLK/LTK)

يقرأ ملفات data/raw/flights_*.csv وينتج:
  - analysis/results/metrics.json      (كل المؤشرات للتفريغ في التقرير)
  - analysis/results/*.csv             (جداول مقارنة)
  - reports/charts/c*.png              (الرسوم البيانية بالعربية)

ملاحظات منهجية:
  - الطابع الزمني المرجعي لكل حركة = first_seen (الأكثر اكتمالاً)،
    مع تحويله إلى التوقيت المحلي (آسيا/دمشق) قبل أي تجميع زمني.
  - تصنيف الحركة: مغادرة إذا كان مطار الانطلاق هو المطار، ووصول إذا كان مطار الوجهة.
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
import arabic_reshaper
from bidi.algorithm import get_display

# ----------------------------------------------------------------------------
# المسارات
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "analysis" / "results"
CHARTS = ROOT / "reports" / "charts"
OUT.mkdir(parents=True, exist_ok=True)
CHARTS.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------------
# إعداد الخط العربي والتنسيق العام
# ----------------------------------------------------------------------------
for _f in (ROOT / "assets" / "fonts").glob("NotoSansArabic-*.ttf"):
    font_manager.fontManager.addfont(str(_f))

# مكدس الخطوط: العربية من Noto Sans Arabic، والأرقام/اللاتيني من DejaVu Sans
# (القائمة تفعّل fallback لكل محرف داخل matplotlib)
plt.rcParams.update({
    "font.family": ["Noto Sans Arabic", "DejaVu Sans"],
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.alpha": 0.3,
    "grid.linewidth": 0.55,
    "grid.linestyle": "--",
    "axes.titlesize": 13.5,
    "axes.titleweight": "bold",
    "axes.titlepad": 11,
    "axes.titlecolor": "#0f2a5c",
    "axes.labelsize": 11,
    "axes.labelcolor": "#374151",
    "axes.edgecolor": "#9ca3af",
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "xtick.color": "#374151",
    "ytick.color": "#374151",
    "legend.fontsize": 10.5,
    "legend.frameon": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})


def ar(txt: str) -> str:
    """تهيئة النص العربي للعرض في matplotlib (إعادة تشكيل + اتجاه)."""
    return get_display(arabic_reshaper.reshape(str(txt)))


# ----------------------------------------------------------------------------
# ثوابت: المطارات، الشركات، الفئات، الطائرات، المدن
# ----------------------------------------------------------------------------
AIRPORTS = {
    "OSDI": dict(
        file="flights_damascus_OSDI.csv", ar="مطار دمشق الدولي", city="دمشق",
        short="دمشق", iata="DAM", icao="OSDI",
        note="البوابة الجوية الرئيسية لسوريا ومركز الخطوط السورية وفلاي شام"),
    "OSAP": dict(
        file="flights_aleppo_OSAP.csv", ar="مطار حلب الدولي", city="حلب",
        short="حلب", iata="ALP", icao="OSAP",
        note="بوابة الشمال؛ شهد أسرع وتيرة نمو بعد استئناف التشغيل"),
    "OSLK": dict(
        file="flights_latakia_OSLK.csv", ar="مطار باسل الأسد الدولي (اللاذقية)", city="اللاذقية",
        short="اللاذقية", iata="LTK", icao="OSLK",
        note="حركة شبه حصرية لعمليات عسكرية/حكومية (القوات الجوية الروسية أساساً)"),
}

AP_COLOR = {"OSDI": "#1e5aa8", "OSAP": "#0e8a5f", "OSLK": "#c2571a"}

CATEGORY_AR = {
    "Passenger": "رحلات ركاب",
    "Cargo": "شحن جوي",
    "Business_jets": "طيران أعمال",
    "Military_and_government": "عسكري وحكومي",
    "General_aviation": "طيران عام",
    "Helicopters": "مروحيات",
    "Gliders": "طائرات شراعية",
    "Other_service": "خدمات أخرى",
    "UNKNOWN": "غير مصنّف",
}
CAT_COLOR = {
    "رحلات ركاب": "#2563eb", "شحن جوي": "#7c3aed", "طيران أعمال": "#0891b2",
    "عسكري وحكومي": "#d64545", "طيران عام": "#64748b", "مروحيات": "#9333ea",
    "طائرات شراعية": "#94a3b8", "خدمات أخرى": "#a16207", "غير مصنّف": "#d1d5db",
}

# شركات التشغيل — تم التحقق من الرموز عبر ICAO/IATA ومراجع الطيران (انظر تقرير المصادر)
AIRLINES = {
    "SYR": ("الخطوط الجوية السورية", "RB", "سوريا"),
    "FYC": ("فلاي شام", "XH", "سوريا (تأسست 2025)"),
    "SAW": ("أجنحة الشام", "6Q", "سوريا"),
    "RJA": ("الملكية الأردنية", "RJ", "الأردن"),
    "THY": ("الخطوط التركية", "TK", "تركيا"),
    "TKJ": ("إيه جت (AJet)", "VF", "تركيا"),
    "PGT": ("بيغاسوس", "PC", "تركيا"),
    "SXS": ("صن إكسبرس", "XQ", "تركيا"),
    "KNE": ("فلاي ناس", "XY", "السعودية"),
    "FAD": ("فلاي ديل", "F3", "السعودية"),
    "SVA": ("الخطوط السعودية", "SV", "السعودية"),
    "QTR": ("الخطوط القطرية", "QR", "قطر"),
    "QQE": ("كاتار التنفيذية (طيران أعمال)", "QE", "قطر"),
    "UAE": ("طيران الإمارات", "EK", "الإمارات"),
    "ETD": ("الاتحاد للطيران", "EY", "الإمارات"),
    "ABY": ("العربية للطيران", "G9", "الإمارات"),
    "ADY": ("العربية لأبوظبي", "3L", "الإمارات"),
    "FDB": ("فلاي دبي", "FZ", "الإمارات"),
    "JZR": ("الجزيرة الكويتية", "J9", "الكويت"),
    "KAC": ("الخطوط الكويتية", "KU", "الكويت"),
    "MEA": ("طيران الشرق الأوسط", "ME", "لبنان"),
    "DNA": ("دان إير", "DN", "رومانيا"),
    "MFX": ("سنتم إير", "C6", "أوزبكستان"),
    "MAR": ("إير ميديترانيان", "MV", "اليونان"),
    "NGN": ("ليف أفييشن (شارتر/ACMI)", "KK", "ألمانيا"),
    "IGC": ("آي جي سي (تشغيل خاص CRJ-200)", "—", "سوريا"),
    # مشغلون عسكريون روس (تظهر جميعها تقريباً بلوحة RFF في البيانات)
    "RFF": ("القوات الجوية الروسية (نقل عسكري)", "—", "روسيا"),
    "CHD": ("القوات الجوية الروسية — تشكيل CHD", "—", "روسيا"),
    "TTF": ("القوات الجوية الروسية — تشكيل TTF", "—", "روسيا"),
    "RSD": ("القوات الجوية الروسية — تشكيل RSD", "—", "روسيا"),
    "RFR": ("القوات الجوية الروسية — تشكيل RFR", "—", "روسيا"),
    "KGB": ("شحن عسكري (إليوشن IL-76، تسجيل قيرغيزي)", "—", "قيرغيزستان/روسيا"),
}
MIL_OPS = {"RFF", "CHD", "TTF", "RSD", "RFR", "KGB", "RRR"}

# أسماء المدن/المطارات بالعربية لأهم الوجهات الظاهرة في البيانات
CITY_AR = {
    "AMM": "عمّان", "IST": "إسطنبول", "SAW": "إسطنبول (صبيحة)", "SHJ": "الشارقة",
    "DXB": "دبي", "DWC": "دبي (آل مكتوم)", "AUH": "أبوظبي", "JED": "جدة",
    "MED": "المدينة المنورة", "RUH": "الرياض", "DMM": "الدمام", "DOH": "الدوحة",
    "KWI": "الكويت", "BGW": "بغداد", "EBL": "أربيل", "BSR": "البصرة",
    "NJF": "النجف", "MCT": "مسقط", "BEY": "بيروت", "CAI": "القاهرة",
    "OTP": "بوخارست", "EVN": "يريفان", "TBS": "تبليسي", "TAS": "طشقند",
    "DAM": "دمشق", "ALP": "حلب", "LTK": "اللاذقية", "DEZ": "دير الزور",
    "CKL": "تشكالوفسكي (قاعدة عسكرية، روسيا)", "ZIA": "جوكوفسكي (روسيا)",
    "SVO": "موسكو (شيريميتيفو)", "MRV": "مينيرالنيه فودي", "ADA": "أضنة",
    "BKO": "باماكو", "BZV": "برازافيل", "DAR": "دار السلام", "SUI": "السويداء؟",
    "DBB": "الغردقة", "TOB": "طبرق", "LFW": "لومي", "KRR": "كراسنودار",
    "TBZ": "تبريز", "IKA": "طهران", "KRM": "كرمانشاه", "MSQ": "مينسك",
}

WIDEBODY = {"A332", "A333", "A340", "A343", "A346", "A359", "A35K", "A310", "A310",
            "B762", "B763", "B764", "B77L", "B77W", "B773", "B788", "B789", "B78X",
            "A124", "A225", "IL96"}

DOW_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

SYRIAN_AP = {"DAM", "ALP", "LTK", "DEZ", "QC", "ACO"}


def airline_name(code: str) -> str:
    if code in AIRLINES:
        return AIRLINES[code][0]
    if not code or str(code) == "nan" or code == "غير معروف":
        return "غير محدد المشغّل"
    return f"مشغّل آخر ({code})"


# ----------------------------------------------------------------------------
# التحميل والتنظيف
# ----------------------------------------------------------------------------
def load_all() -> pd.DataFrame:
    frames = []
    for icao, meta in AIRPORTS.items():
        df = pd.read_csv(RAW / meta["file"], low_memory=False)
        df["airport"] = icao
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    # الحدث المرجعي: وقت أول رصد، محوّل إلى التوقيت المحلي
    df["event"] = pd.to_datetime(df["first_seen"], errors="coerce", utc=True)
    df["event_local"] = df["event"].dt.tz_convert("Asia/Damascus")
    df["takeoff_dt"] = pd.to_datetime(df["datetime_takeoff"], errors="coerce", utc=True)
    df["landed_dt"] = pd.to_datetime(df["datetime_landed"], errors="coerce", utc=True)

    # تصنيف الحركة
    def movement(r):
        if r["orig_icao"] == r["airport"]:
            return "مغادرة"
        if r["dest_icao"] == r["airport"]:
            return "وصول"
        return "غير مصنّفة"
    df["movement"] = df.apply(movement, axis=1)

    df["category_ar"] = df["category"].map(CATEGORY_AR).fillna("غير مصنّف")
    df["month"] = df["event_local"].dt.to_period("M").astype(str)
    df["hour"] = df["event_local"].dt.hour
    df["dow"] = df["event_local"].dt.dayofweek  # 0=الاثنين
    df["dow_ar"] = df["dow"].map(dict(enumerate(DOW_AR)))
    df["date"] = df["event_local"].dt.date
    df["ft_min"] = pd.to_numeric(df["flight_time"], errors="coerce") / 60.0
    df["dist_km"] = pd.to_numeric(df["actual_distance"], errors="coerce")
    df["op"] = df["operating_as"].fillna("غير معروف")
    df["airline_ar"] = df["op"].map(airline_name)
    df["is_wide"] = df["type"].isin(WIDEBODY)
    return df


# ----------------------------------------------------------------------------
# مؤشرات مطار واحد
# ----------------------------------------------------------------------------
def airport_metrics(df: pd.DataFrame, icao: str) -> dict:
    d = df[df["airport"] == icao].copy()
    meta = AIRPORTS[icao]
    m = {"icao": icao, "iata": meta["iata"], "name_ar": meta["ar"],
         "city": meta["city"], "short": meta["short"], "note": meta["note"]}

    m["total"] = int(len(d))
    m["departures"] = int((d["movement"] == "مغادرة").sum())
    m["arrivals"] = int((d["movement"] == "وصول").sum())
    m["unclassified"] = int((d["movement"] == "غير مصنّفة").sum())
    m["first_event"] = str(d["event_local"].min().date())
    m["last_event"] = str(d["event_local"].max().date())

    # الفئات
    cats = d["category_ar"].value_counts()
    m["categories"] = [{"name": k, "n": int(v),
                        "share": round(100 * v / len(d), 1)}
                       for k, v in cats.items()]

    # السلاسل الشهرية + كشف فجوات البيانات
    monthly = d.groupby("month").size().sort_index()
    med = float(monthly.median())
    m["monthly"] = [{"month": k, "n": int(v),
                     "gap": bool(med > 0 and v < 0.25 * med)} for k, v in monthly.items()]
    m["gap_months"] = [x["month"] for x in m["monthly"] if x["gap"]]
    m["peak_month"] = {"month": str(monthly.idxmax()), "n": int(monthly.max())}
    full = [x for x in m["monthly"] if not x["gap"]]
    m["avg_monthly"] = round(float(np.mean([x["n"] for x in full])), 1) if full else 0

    # آخر شهر مكتمل (أغسطس 2026) — متوسط يومي
    aug26 = d[d["month"] == "2026-08"]
    m["avg_daily_last_full_month"] = round(len(aug26) / 31.0, 1) if len(aug26) else None
    m["last_full_month"] = "2026-08" if len(aug26) else None

    # مقارنة عادلة: يناير–أغسطس 2025 مقابل يناير–أغسطس 2026
    per = d[(d["month"] >= "2025-01") & (d["month"] <= "2025-08")]
    per26 = d[(d["month"] >= "2026-01") & (d["month"] <= "2026-08")]
    m["jan_aug_2025"] = int(len(per))
    m["jan_aug_2026"] = int(len(per26))
    m["growth_pct"] = round(100 * (len(per26) - len(per)) / len(per), 1) if len(per) else None

    # الشركات
    ops = d["op"].value_counts()
    m["n_operators"] = int(ops.size)
    shares = ops / ops.sum()
    hhi = float((shares ** 2).sum() * 10000)
    m["hhi"] = round(hhi)
    top3 = float(shares.head(3).sum() * 100)
    m["top3_share"] = round(top3, 1)
    m["top_airlines"] = []
    for code, n in ops.head(12).items():
        if code == "غير معروف":
            nm, iata, country = "غير محدد المشغّل", "—", "—"
        else:
            nm, iata, country = AIRLINES.get(code, (f"مشغّل آخر ({code})", "—", "—"))
        m["top_airlines"].append({
            "code": code, "name": nm, "iata": iata, "country": country,
            "n": int(n), "share": round(100 * n / ops.sum(), 1)})
    m["top_airline"] = m["top_airlines"][0] if m["top_airlines"] else None

    # الوجهات والمصادر (مع استبعاد الوجهة الذاتية = حركات محلية)
    self_iata = meta["iata"]
    dep = d[d["movement"] == "مغادرة"]
    arr = d[d["movement"] == "وصول"]
    dep_ext = dep[dep["dest_iata"] != self_iata]
    arr_ext = arr[arr["orig_iata"] != self_iata]
    dst = dep_ext["dest_iata"].dropna().value_counts()
    org = arr_ext["orig_iata"].dropna().value_counts()
    def city_rows(s):
        return [{"iata": k, "city": CITY_AR.get(k, k), "n": int(v)}
                for k, v in s.head(12).items()]
    m["top_destinations"] = city_rows(dst)
    m["top_origins"] = city_rows(org)
    all_ap = pd.concat([dep_ext["dest_iata"], arr_ext["orig_iata"]]).dropna()
    m["n_destinations_all"] = int(all_ap.nunique())
    intl = dep_ext[~dep_ext["dest_iata"].isin(SYRIAN_AP)]
    m["n_destinations_intl"] = int(intl["dest_iata"].nunique())
    m["domestic_dep"] = int(dep_ext["dest_iata"].isin(SYRIAN_AP).sum())
    m["intl_dep"] = int((~dep_ext["dest_iata"].isin(SYRIAN_AP)).sum())
    m["local_ops"] = int((dep["dest_iata"] == self_iata).sum())

    # ممر الخليج: حصة مغادرات المطارات الخليجية من الرحلات الدولية
    GULF = {"KWI", "DXB", "DWC", "SHJ", "AUH", "DOH", "RUH", "JED", "DMM", "MED", "MCT"}
    gulf = int(dep_ext["dest_iata"].isin(GULF).sum())
    m["gulf_dep"] = gulf
    m["gulf_share_of_intl"] = round(100 * gulf / max(m["intl_dep"], 1), 1)

    # الأسطول
    types = d["type"].value_counts()
    m["n_types"] = int(types.size)
    m["n_aircraft"] = int(d["reg"].nunique())
    m["widebody_n"] = int(d["is_wide"].sum())
    m["widebody_share"] = round(100 * d["is_wide"].sum() / max(len(d), 1), 1)
    m["top_types"] = [{"type": k, "n": int(v)} for k, v in types.head(10).items()]

    # الإيقاع اليومي/الساعي
    m["hourly"] = [int(x) for x in d.groupby("hour").size().reindex(range(24), fill_value=0)]
    m["peak_hour"] = int(d.groupby("hour").size().idxmax())
    m["dow_counts"] = [int(x) for x in d.groupby("dow").size().reindex(range(7), fill_value=0)]
    m["dow_ar_counts"] = [{"day": DOW_AR[i], "n": m["dow_counts"][i]} for i in range(7)]

    busiest = d.groupby("date").size().sort_values(ascending=False)
    m["busiest_day"] = {"date": str(busiest.index[0]), "n": int(busiest.iloc[0])}

    # زمن/مسافة الرحلة (حركات ذات بيانات مكتملة)
    ft = d["ft_min"].dropna()
    ds = d["dist_km"].dropna()
    m["ft_median"] = round(float(ft.median()), 0) if len(ft) else None
    m["ft_mean"] = round(float(ft.mean()), 0) if len(ft) else None
    m["dist_median"] = round(float(ds.median()), 0) if len(ds) else None
    m["dist_mean"] = round(float(ds.mean()), 0) if len(ds) else None
    m["ft_n"] = int(len(ft))

    # المدارج
    m["runways"] = {k: int(v) for k, v in
                    pd.concat([d["runway_takeoff"].dropna(), d["runway_landed"].dropna()])
                    .value_counts().head(8).items()}

    # اللاذقية: التركيز العسكري الروسي
    if icao == "OSLK":
        ru = d[d["op"].isin(MIL_OPS) | d["painted_as"].isin(["RFF", "RFR"])]
        m["russian_mil_n"] = int(len(ru))
        m["russian_mil_share"] = round(100 * len(ru) / len(d), 1)
        ckl = d[(d["dest_iata"] == "CKL") | (d["orig_iata"] == "CKL")]
        m["ckl_n"] = int(len(ckl))
    return m


# ----------------------------------------------------------------------------
# جودة البيانات
# ----------------------------------------------------------------------------
def data_quality(df: pd.DataFrame) -> dict:
    q = {"rows_per_file": {i: int((df["airport"] == i).sum()) for i in AIRPORTS},
         "columns": list(df.columns[:25]),
         "missing": {}}
    for icao in AIRPORTS:
        d = df[df["airport"] == icao]
        q["missing"][icao] = {
            "datetime_takeoff": int(d["takeoff_dt"].isna().sum()),
            "datetime_landed": int(d["landed_dt"].isna().sum()),
            "flight_time": int(d["ft_min"].isna().sum()),
            "distance": int(d["dist_km"].isna().sum()),
            "operator": int((d["op"] == "غير معروف").sum()),
            "registration": int(d["reg"].isna().sum()),
        }
    # فجوات شهرية مكتشفة (أقل من ربع الوسيط)
    gaps = {}
    for icao in AIRPORTS:
        d = df[df["airport"] == icao]
        monthly = d.groupby("month").size().sort_index()
        med = monthly.median()
        gaps[icao] = [{"month": k, "n": int(v)}
                      for k, v in monthly.items() if med > 0 and v < 0.25 * med]
    q["detected_gaps"] = gaps
    return q

# ----------------------------------------------------------------------------
# الرسوم البيانية — نظام تصميم موحّد (Noto Sans Arabic + DejaVu Sans)
# ----------------------------------------------------------------------------
from matplotlib.ticker import FuncFormatter

AP_ORDER = ["OSDI", "OSAP", "OSLK"]
THOUS = FuncFormatter(lambda x, _: f"{x:,.0f}")

AP_AR = {c: ar(AIRPORTS[c]["short"]) for c in AP_ORDER}


def fmt_k(n) -> str:
    return f"{int(n):,.0f}"


def _light(ax):
    """شبكة خفيفة على المحور العمودي فقط."""
    ax.grid(axis="y", alpha=0.3, linewidth=0.55, linestyle="--")
    ax.grid(axis="x", visible=False)


def _light_h(ax):
    """شبكة خفيفة على المحور الأفقي فقط (أشرطة أفقية)."""
    ax.grid(axis="x", alpha=0.3, linewidth=0.55, linestyle="--")
    ax.grid(axis="y", visible=False)


def _save(fig, name):
    fig.savefig(CHARTS / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------- 1) الأحجام الكلية + مغادرات/وصولات ----------
def chart_totals(mx):
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.5), layout="constrained")

    ax = axes[0]
    vals = [mx[c]["total"] for c in AP_ORDER]
    bars = ax.bar([AP_AR[c] for c in AP_ORDER], vals,
                  color=[AP_COLOR[c] for c in AP_ORDER], width=0.58, zorder=3)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + max(vals) * 0.017, fmt_k(v),
                ha="center", va="bottom", fontsize=11.5, fontweight="bold", color="#111827")
    ax.set_title(ar("إجمالي الحركات المسجلة (يناير 2025 – سبتمبر 2026)"))
    ax.set_ylabel(ar("عدد الحركات"))
    ax.yaxis.set_major_formatter(THOUS)
    ax.set_ylim(0, max(vals) * 1.14)
    _light(ax)

    ax = axes[1]
    x = np.arange(3)
    dep = [mx[c]["departures"] for c in AP_ORDER]
    arr = [mx[c]["arrivals"] for c in AP_ORDER]
    ax.bar(x - 0.19, dep, 0.37, label=ar("مغادرات"), color="#334155", zorder=3)
    ax.bar(x + 0.19, arr, 0.37, label=ar("وصولات"), color="#94a3b8", zorder=3)
    for i in range(3):
        ax.text(x[i] - 0.19, dep[i] + max(dep + arr) * 0.017, fmt_k(dep[i]),
                ha="center", va="bottom", fontsize=9, color="#334155")
        ax.text(x[i] + 0.19, arr[i] + max(dep + arr) * 0.017, fmt_k(arr[i]),
                ha="center", va="bottom", fontsize=9, color="#64748b")
    ax.set_xticks(x)
    ax.set_xticklabels([AP_AR[c] for c in AP_ORDER])
    ax.set_title(ar("المغادرات مقابل الوصولات"))
    ax.yaxis.set_major_formatter(THOUS)
    ax.set_ylim(0, max(dep + arr) * 1.2)
    ax.legend(loc="upper right")
    _light(ax)
    _save(fig, "c01_totals.png")


# ---------- 2) التطور الشهري ----------
def chart_monthly(mx):
    fig, ax = plt.subplots(figsize=(11.8, 5.0), layout="constrained")
    idx = pd.period_range("2025-01", "2026-09", freq="M")
    for icao in AP_ORDER:
        s = pd.Series({x["month"]: x["n"] for x in mx[icao]["monthly"]}) \
            .reindex(idx.astype(str), fill_value=0)
        ax.plot(idx.to_timestamp(), s.values, marker="o", ms=4, lw=2.2,
                color=AP_COLOR[icao], label=AP_AR[icao], zorder=3)

    ymax = max(max(x["n"] for x in mx[i]["monthly"]) for i in AP_ORDER)

    # فجوة تسجيل دمشق (مارس 2026) + الشهر الأخير غير المكتمل
    ax.axvspan(pd.Timestamp("2026-02-26"), pd.Timestamp("2026-04-04"),
               color="#f59e0b", alpha=0.16, zorder=1)
    ax.text(pd.Timestamp("2026-03-16"), ymax * 0.60, ar("فجوة تسجيل\nبيانات دمشق"),
            ha="center", va="center", fontsize=9, color="#92400e",
            bbox=dict(boxstyle="round,pad=0.32", fc="#fffbeb", ec="#fcd34d", lw=0.8))
    ax.axvspan(pd.Timestamp("2026-08-31"), pd.Timestamp("2026-09-30"),
               color="#64748b", alpha=0.14, zorder=1)
    ax.text(pd.Timestamp("2026-09-15"), ymax * 0.42, ar("سبتمبر غير مكتمل"),
            ha="center", va="center", fontsize=8.6, color="#475569",
            bbox=dict(boxstyle="round,pad=0.3", fc="#f8fafc", ec="#cbd5e1", lw=0.8))

    ax.set_title(ar("تطور الحركة الشهرية للمطارات الثلاثة"))
    ax.set_ylabel(ar("عدد الحركات في الشهر"))
    ax.yaxis.set_major_formatter(THOUS)
    ax.set_ylim(0, ymax * 1.12)
    ax.legend(loc="upper left")
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(45)
        lbl.set_ha("right")
    _light(ax)
    _save(fig, "c02_monthly.png")


# ---------- 3) تركيب الفئات ----------
def chart_categories(mx):
    fig, ax = plt.subplots(figsize=(10.8, 4.3), layout="constrained")
    minor = {"طيران عام", "مروحيات", "طائرات شراعية", "خدمات أخرى", "غير مصنّف"}

    def shares(icao):
        d = {c["name"]: c["share"] for c in mx[icao]["categories"]}
        other = sum(v for k, v in d.items() if k in minor)
        return [d.get("رحلات ركاب", 0), d.get("شحن جوي", 0), d.get("طيران أعمال", 0),
                d.get("عسكري وحكومي", 0), other]

    cats = ["رحلات ركاب", "شحن جوي", "طيران أعمال", "عسكري وحكومي", "أخرى/غير مصنّف"]
    colors = ["#2563eb", "#7c3aed", "#0891b2", "#d64545", "#cbd5e1"]

    y = np.arange(3)
    left = np.zeros(3)
    for j, (cat, col) in enumerate(zip(cats, colors)):
        vals = np.array([shares(c)[j] for c in AP_ORDER])
        ax.barh(y, vals, left=left, color=col, label=ar(cat), height=0.56, zorder=3)
        for i, (v, l) in enumerate(zip(vals, left)):
            if v >= 6:
                ax.text(l + v / 2, y[i], f"{v:.0f}%", ha="center", va="center",
                        color="white", fontsize=10, fontweight="bold")
        left += vals

    ax.set_yticks(y)
    ax.set_yticklabels([AP_AR[c] for c in AP_ORDER], fontsize=11.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel(ar("النسبة من إجمالي حركات المطار (%)"))
    ax.set_title(ar("تركيب الحركة حسب الفئة"))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=5, fontsize=9.6)
    _light_h(ax)
    _save(fig, "c03_categories.png")


# ---------- 4) أكبر الشركات ----------
def chart_airlines(df, mx):
    fig, ax = plt.subplots(figsize=(11.2, 5.8), layout="constrained")
    ops = df["op"].value_counts().head(12)
    y = np.arange(len(ops))[::-1]
    left = np.zeros(len(ops))
    for icao in AP_ORDER:
        vals = np.array([int(((df["op"] == k) & (df["airport"] == icao)).sum())
                         for k in ops.index])
        ax.barh(y, vals, left=left, color=AP_COLOR[icao],
                label=AP_AR[icao], height=0.62, zorder=3)
        left += vals
    labels = []
    for k in ops.index:
        nm = AIRLINES.get(k, (k, "—", "—"))[0]
        labels.append(ar(nm) if k == "غير معروف" else ar(f"{nm} ({k})"))
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10.5)
    for j, v in enumerate(ops.values):
        ax.text(v + ops.iloc[0] * 0.012, y[j], fmt_k(v), va="center",
                ha="left", fontsize=9, color="#374151")
    ax.set_xlim(0, ops.iloc[0] * 1.13)
    ax.set_title(ar("أكبر 12 شركة تشغيل عبر المطارات الثلاثة"))
    ax.set_xlabel(ar("عدد الحركات"))
    ax.xaxis.set_major_formatter(THOUS)
    ax.legend(loc="lower right")
    _light_h(ax)
    _save(fig, "c04_airlines.png")


# ---------- 5) حصص السوق (حلقات مع مفتاح أسفل) ----------
def chart_share_donuts(mx):
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 5.6), layout="constrained")

    def draw(ax, icao, palette):
        ops = mx[icao]["top_airlines"][:7]
        other = mx[icao]["total"] - sum(o["n"] for o in ops)
        vals = [o["n"] for o in ops] + [other]
        names = [o["name"] for o in ops] + ["آخرون"]
        shares = [o["share"] for o in ops] + [round(100 * other / mx[icao]["total"], 1)]
        colors = [palette(i) for i in range(len(ops))] + ["#cbd5e1"]
        wedges, _, autotexts = ax.pie(
            vals, colors=colors, startangle=90, counterclock=False,
            center=(0, 0.16), radius=0.72,
            autopct=lambda p: f"{p:.0f}%" if p >= 4 else "",
            wedgeprops={"edgecolor": "white", "linewidth": 1.6},
            textprops={"fontsize": 9.3})
        for t in autotexts:
            t.set_color("white")
            t.set_fontweight("bold")
        ax.set_ylim(-1.42, 1.06)
        leg_labels = [ar(f"{n} — {s}%") for n, s in zip(names, shares)]
        ax.legend(wedges, leg_labels, loc="lower center", ncol=2,
                  fontsize=9.2, handlelength=1.1, columnspacing=0.9,
                  bbox_to_anchor=(0.5, -0.04))
        ax.set_title(ar(f"{AIRPORTS[icao]['short']} — حصص السوق"))

    draw(axes[0], "OSDI", lambda i: plt.cm.Blues(0.92 - 0.10 * i))
    draw(axes[1], "OSAP", lambda i: plt.cm.Greens(0.90 - 0.10 * i))
    fig.suptitle(ar("توزّع السوق بين شركات التشغيل (أكبر 7 + آخرون)"),
                 fontsize=14, fontweight="bold", color="#0f2a5c")
    _save(fig, "c05_shares.png")


# ---------- 6) أهم الوجهات ----------
def chart_destinations(mx):
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 5.5), layout="constrained")
    for ax, icao in zip(axes, ["OSDI", "OSAP"]):
        dst = mx[icao]["top_destinations"][:10][::-1]
        names = [ar(f"{d['city']} ({d['iata']})") for d in dst]
        vals = [d["n"] for d in dst]
        ax.barh(np.arange(len(dst)), vals, color=AP_COLOR[icao], height=0.6, zorder=3)
        ax.set_yticks(np.arange(len(dst)))
        ax.set_yticklabels(names, fontsize=10.3)
        for j, v in enumerate(vals):
            ax.text(v + max(vals) * 0.012, j, fmt_k(v), va="center", ha="left",
                    fontsize=8.8, color="#374151")
        ax.set_xlim(0, max(vals) * 1.14)
        ax.set_title(ar(f"أهم 10 وجهات مغادرة — {AIRPORTS[icao]['short']}"))
        ax.set_xlabel(ar("عدد الرحلات المغادرة"))
        ax.xaxis.set_major_formatter(THOUS)
        _light_h(ax)
    _save(fig, "c06_destinations.png")


# ---------- 7) التوزيع الساعي ----------
def chart_hourly(mx):
    fig, ax = plt.subplots(figsize=(11.4, 4.6), layout="constrained")
    hours = np.arange(24)
    for icao in AP_ORDER:
        h = np.array(mx[icao]["hourly"], dtype=float)
        h = 100 * h / h.sum()
        ax.plot(hours, h, marker="o", ms=3.6, lw=2.1, color=AP_COLOR[icao],
                label=AP_AR[icao], zorder=3)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlim(-0.5, 23.5)
    ax.set_xlabel(ar("الساعة (بتوقيت دمشق المحلي)"))
    ax.set_ylabel(ar("% من الحركات"))
    ax.set_title(ar("التوزيع الساعي للحركة — إيقاع اليوم التشغيلي"))
    ax.legend(loc="upper left")
    _light(ax)
    _save(fig, "c07_hourly.png")


# ---------- 8) أيام الأسبوع ----------
def chart_dow(mx):
    fig, ax = plt.subplots(figsize=(11.4, 4.5), layout="constrained")
    x = np.arange(7)
    w = 0.27
    top = 0
    for i, icao in enumerate(AP_ORDER):
        cnts = np.array(mx[icao]["dow_counts"], dtype=float)
        cnts = 100 * cnts / cnts.sum()
        top = max(top, cnts.max())
        ax.bar(x + (i - 1) * w, cnts, w, color=AP_COLOR[icao],
               label=AP_AR[icao], zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels([ar(d) for d in DOW_AR], fontsize=10.3)
    ax.set_ylabel(ar("% من الحركات"))
    ax.set_ylim(0, top * 1.24)
    ax.set_title(ar("توزيع الحركة على أيام الأسبوع"))
    ax.legend(loc="upper right", ncol=3)
    _light(ax)
    _save(fig, "c08_dow.png")


# ---------- 9) أنواع الطائرات ----------
def chart_types(df):
    fig, ax = plt.subplots(figsize=(11.2, 5.5), layout="constrained")
    types = df["type"].value_counts().head(10)
    y = np.arange(len(types))[::-1]
    left = np.zeros(len(types))
    for icao in AP_ORDER:
        vals = np.array([int(((df["type"] == k) & (df["airport"] == icao)).sum())
                         for k in types.index])
        ax.barh(y, vals, left=left, color=AP_COLOR[icao],
                label=AP_AR[icao], height=0.62, zorder=3)
        left += vals
    ax.set_yticks(y)
    ax.set_yticklabels(list(types.index), fontsize=10.8)
    for j, v in enumerate(types.values):
        ax.text(v + types.iloc[0] * 0.012, y[j], fmt_k(v), va="center", ha="left",
                fontsize=9, color="#374151")
    ax.set_xlim(0, types.iloc[0] * 1.12)
    ax.set_title(ar("أكثر 10 أنواع طائرات تشغيلاً (حسب المطار)"))
    ax.set_xlabel(ar("عدد الحركات"))
    ax.xaxis.set_major_formatter(THOUS)
    ax.legend(loc="lower right")
    _light_h(ax)
    _save(fig, "c09_types.png")


# ---------- 10) بصمة التشغيل ----------
def chart_profile(mx):
    fig, axes = plt.subplots(1, 3, figsize=(12.4, 4.3), layout="constrained")
    names = [AP_AR[c] for c in AP_ORDER]
    cols = [AP_COLOR[c] for c in AP_ORDER]

    panels = [
        ([mx[c]["ft_median"] or 0 for c in AP_ORDER], "وسيط زمن الرحلة (دقيقة)", "{:.0f}", 1.16),
        ([mx[c]["dist_median"] or 0 for c in AP_ORDER], "وسيط المسافة المقطوعة (كم)", "{:,.0f}", 1.16),
        ([mx[c]["widebody_share"] for c in AP_ORDER], "حصة الطائرات العريضة البدن (%)", "{:.1f}", 1.3),
    ]
    for ax, (vals, title, fmtv, pad) in zip(axes, panels):
        ax.bar(names, vals, color=cols, width=0.56, zorder=3)
        for i, v in enumerate(vals):
            ax.text(i, v + max(vals) * (pad - 1) * 0.22, fmtv.format(v),
                    ha="center", va="bottom", fontsize=11, fontweight="bold", color="#111827")
        ax.set_title(ar(title), fontsize=12)
        ax.set_ylim(0, max(vals) * pad)
        _light(ax)
    fig.suptitle(ar("بصمة التشغيل: زمن الرحلة، المسافة، وحجم الطائرات"),
                 fontsize=14, fontweight="bold", color="#0f2a5c")
    _save(fig, "c10_profile.png")


# ---------- 11) النمو (مقارنة عادلة) ----------
def chart_growth(mx):
    fig, ax = plt.subplots(figsize=(10.6, 4.8), layout="constrained")
    x = np.arange(3)
    v25 = [mx[c]["jan_aug_2025"] for c in AP_ORDER]
    v26 = [mx[c]["jan_aug_2026"] for c in AP_ORDER]
    top = max(max(v25), max(v26))
    ax.bar(x - 0.19, v25, 0.37, label=ar("يناير–أغسطس 2025"), color="#93c5fd", zorder=3)
    ax.bar(x + 0.19, v26, 0.37, label=ar("يناير–أغسطس 2026"), color="#1d4ed8", zorder=3)
    for i in range(3):
        ax.text(x[i] - 0.19, v25[i] + top * 0.017, fmt_k(v25[i]), ha="center",
                va="bottom", fontsize=9, color="#64748b")
        ax.text(x[i] + 0.19, v26[i] + top * 0.017, fmt_k(v26[i]), ha="center",
                va="bottom", fontsize=9, color="#1e40af")
        g = mx[AP_ORDER[i]]["growth_pct"]
        if g is not None:
            ax.text(x[i], max(v25[i], v26[i]) + top * 0.115, ar(f"نمو +{g:.0f}%"),
                    ha="center", va="bottom", fontsize=10.5, fontweight="bold",
                    color="#166534",
                    bbox=dict(boxstyle="round,pad=0.3", fc="#ecfdf5", ec="#a7f3d0", lw=0.9))
    ax.set_xticks(x)
    ax.set_xticklabels([AP_AR[c] for c in AP_ORDER], fontsize=11.5)
    ax.set_title(ar("مقارنة عادلة: الفترة يناير–أغسطس بين عامي 2025 و2026"))
    ax.set_ylabel(ar("عدد الحركات"))
    ax.yaxis.set_major_formatter(THOUS)
    ax.set_ylim(0, top * 1.34)
    ax.legend(loc="upper right")
    _light(ax)
    _save(fig, "c11_growth.png")


# ---------- 12) اللاذقية ----------
def chart_latakia(df, mx):
    m = mx["OSLK"]
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.7), layout="constrained")

    ax = axes[0]
    ms = m["monthly"]
    idx = pd.period_range(ms[0]["month"], ms[-1]["month"], freq="M")
    s = pd.Series({x["month"]: x["n"] for x in ms}).reindex(idx.astype(str), fill_value=0)
    ax.bar(idx.to_timestamp(), s.values, color=AP_COLOR["OSLK"], width=20, zorder=3)
    ax.set_title(ar("الحركة الشهرية"), fontsize=12)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(45)
        lbl.set_ha("right")
        lbl.set_fontsize(8.6)
    _light(ax)

    ax = axes[1]
    d = df[df["airport"] == "OSLK"]
    ops = d["op"].value_counts().head(5)[::-1]
    colors = ["#b91c1c" if k in MIL_OPS or k == "غير معروف" else "#64748b"
              for k in ops.index]
    ax.barh(np.arange(len(ops)), ops.values, color=colors, height=0.58, zorder=3)
    ax.set_yticks(np.arange(len(ops)))
    ax.set_yticklabels([ar(airline_name(k)) for k in ops.index], fontsize=9.6)
    for j, v in enumerate(ops.values):
        ax.text(v + ops.max() * 0.015, j, str(v), va="center", ha="left",
                fontsize=9, color="#374151")
    ax.set_xlim(0, ops.max() * 1.16)
    ax.set_title(ar("المشغّلون (أحمر = عسكري روسي)"), fontsize=12)
    _light_h(ax)

    ax = axes[2]
    t = d["type"].value_counts().head(6)[::-1]
    ax.barh(np.arange(len(t)), t.values, color="#7f1d1d", height=0.58, zorder=3)
    ax.set_yticks(np.arange(len(t)))
    ax.set_yticklabels(list(t.index), fontsize=10)
    for j, v in enumerate(t.values):
        ax.text(v + t.max() * 0.015, j, str(v), va="center", ha="left",
                fontsize=9, color="#374151")
    ax.set_xlim(0, t.max() * 1.16)
    ax.set_title(ar("أنواع الطائرات"), fontsize=12)
    _light_h(ax)

    fig.suptitle(ar("اللاذقية: مطار بوجهة عسكرية — جسر جوي روسي (تشكالوفسكي)"),
                 fontsize=14, fontweight="bold", color="#0f2a5c")
    _save(fig, "c12_latakia.png")


# ---------- 13) داخلي مقابل دولي ----------
def chart_domestic(mx):
    fig, ax = plt.subplots(figsize=(10.6, 4.3), layout="constrained")
    y = np.arange(3)
    dom = np.array([mx[c]["domestic_dep"] for c in AP_ORDER], dtype=float)
    intl = np.array([mx[c]["intl_dep"] for c in AP_ORDER], dtype=float)
    tot = dom + intl
    dom_p, intl_p = 100 * dom / tot, 100 * intl / tot
    ax.barh(y, dom_p, color="#f59e0b", label=ar("مغادرات داخلية"), height=0.54, zorder=3)
    ax.barh(y, intl_p, left=dom_p, color="#1e40af", label=ar("مغادرات دولية"),
            height=0.54, zorder=3)
    for j in range(3):
        if dom_p[j] >= 6:
            ax.text(dom_p[j] / 2, y[j], f"{dom_p[j]:.0f}%", ha="center", va="center",
                    color="white", fontweight="bold", fontsize=10)
        ax.text(dom_p[j] + intl_p[j] / 2, y[j], f"{intl_p[j]:.0f}%", ha="center",
                va="center", color="white", fontweight="bold", fontsize=10)
    ax.set_yticks(y)
    ax.set_yticklabels([AP_AR[c] for c in AP_ORDER], fontsize=11.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel(ar("النسبة من المغادرات المصنّفة (%)"))
    ax.set_title(ar("المغادرات: داخلية مقابل دولية"))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2)
    _light_h(ax)
    _save(fig, "c13_domestic.png")


# ---------- 14) اتساع الشبكة ----------
def chart_network(df):
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.3), layout="constrained")
    names = [AP_AR[c] for c in AP_ORDER]
    cols = [AP_COLOR[c] for c in AP_ORDER]

    ax = axes[0]
    v = [df[(df["airport"] == c) & (df["movement"] == "مغادرة")]
         ["dest_iata"].dropna().nunique() for c in AP_ORDER]
    ax.bar(names, v, color=cols, width=0.56, zorder=3)
    for i, val in enumerate(v):
        ax.text(i, val + max(v) * 0.02, str(val), ha="center", va="bottom",
                fontsize=12, fontweight="bold", color="#111827")
    ax.set_title(ar("عدد وجهات المغادرة المختلفة"), fontsize=12.5)
    ax.set_ylim(0, max(v) * 1.18)
    _light(ax)

    ax = axes[1]
    v = [df[df["airport"] == c]["reg"].nunique() for c in AP_ORDER]
    ax.bar(names, v, color=cols, width=0.56, zorder=3)
    for i, val in enumerate(v):
        ax.text(i, val + max(v) * 0.02, fmt_k(val), ha="center", va="bottom",
                fontsize=12, fontweight="bold", color="#111827")
    ax.set_title(ar("عدد الطائرات الفريدة (بحسب التسجيل)"), fontsize=12.5)
    ax.set_ylim(0, max(v) * 1.18)
    _light(ax)

    fig.suptitle(ar("اتساع الشبكة والتنوّع التشغيلي"),
                 fontsize=14, fontweight="bold", color="#0f2a5c")
    _save(fig, "c14_network.png")


# ----------------------------------------------------------------------------
# التنفيذ الرئيسي
# ----------------------------------------------------------------------------
def main():
    df = load_all()
    print(f"Loaded {len(df):,} movements")

    mx = {icao: airport_metrics(df, icao) for icao in AIRPORTS}
    quality = data_quality(df)

    # جداول CSV للمقارنة
    rows = []
    for icao, m in mx.items():
        rows.append({
            "المطار": m["name_ar"], "الرمز": f'{m["iata"]}/{m["icao"]}',
            "إجمالي الحركات": m["total"], "مغادرات": m["departures"], "وصولات": m["arrivals"],
            "متوسط شهري": m["avg_monthly"],
            "أعلى شهر": f'{m["peak_month"]["month"]} ({m["peak_month"]["n"]})',
            "شركات التشغيل": m["n_operators"], "الوجهات": m["n_destinations_all"],
            "أنواع الطائرات": m["n_types"], "طائرات فريدة": m["n_aircraft"],
            "حصة الركاب %": next((c["share"] for c in m["categories"] if c["name"] == "رحلات ركاب"), 0),
            "حصة العسكري %": next((c["share"] for c in m["categories"] if c["name"] == "عسكري وحكومي"), 0),
            "وسيط زمن الرحلة (د)": m["ft_median"], "وسيط المسافة (كم)": m["dist_median"],
            "نمو يناير-أغسطس %": m["growth_pct"],
        })
    pd.DataFrame(rows).to_csv(OUT / "airports_comparison.csv", index=False)

    ops_matrix = pd.crosstab(df["op"], df["airport"])
    ops_matrix["الإجمالي"] = ops_matrix.sum(axis=1)
    ops_matrix = ops_matrix.sort_values("الإجمالي", ascending=False)
    ops_matrix.to_csv(OUT / "operators_matrix.csv")

    monthly_df = pd.DataFrame({
        icao: pd.Series({x["month"]: x["n"] for x in mx[icao]["monthly"]})
        for icao in AIRPORTS}).fillna(0).astype(int)
    monthly_df.to_csv(OUT / "monthly_series.csv")

    metrics = {
        "meta": {
            "generated_at": pd.Timestamp.now(tz="Asia/Damascus").strftime("%Y-%m-%d %H:%M"),
            "data_first": str(df["event_local"].min().date()),
            "data_last": str(df["event_local"].max().date()),
            "total_movements": int(len(df)),
            "n_airports": len(AIRPORTS),
            # إجماليات عبر المطارات (اتحاد القيم الفريدة)
            "unique_operators": int(df.loc[df["op"] != "غير معروف", "op"].nunique()),
            "unique_aircraft": int(df["reg"].nunique()),
            "unique_types": int(df["type"].nunique()),
            "unique_destinations": int(pd.concat([
                df.loc[df["movement"] == "مغادرة", "dest_iata"],
                df.loc[df["movement"] == "وصول", "orig_iata"]]).dropna()
                .loc[lambda s: ~s.isin(["DAM", "ALP", "LTK"])].nunique()),
        },
        "airports": mx,
        "quality": quality,
    }
    with open(OUT / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=1, default=str)
    print("metrics.json written")

    # الرسوم
    chart_totals(mx)
    chart_monthly(mx)
    chart_categories(mx)
    chart_airlines(df, mx)
    chart_share_donuts(mx)
    chart_destinations(mx)
    chart_hourly(mx)
    chart_dow(mx)
    chart_types(df)
    chart_profile(mx)
    chart_growth(mx)
    chart_latakia(df, mx)
    chart_domestic(mx)
    chart_network(df)
    print("charts written:", len(list(CHARTS.glob("c*.png"))))


if __name__ == "__main__":
    main()
