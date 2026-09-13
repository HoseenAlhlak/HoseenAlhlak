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
for f in (ROOT / "assets" / "fonts").glob("*.ttf"):
    font_manager.fontManager.addfont(str(f))
plt.rcParams.update({
    "font.family": "Amiri",
    "figure.dpi": 140,
    "savefig.dpi": 140,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.6,
    "axes.titlesize": 15,
    "axes.titleweight": "bold",
    "axes.labelsize": 11.5,
    "xtick.labelsize": 10.5,
    "ytick.labelsize": 10.5,
    "legend.fontsize": 10.5,
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
# الرسوم البيانية
# ----------------------------------------------------------------------------
def fmt_k(n):
    return f"{int(n):,}"


def chart_totals(mx):
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.4))
    order = ["OSDI", "OSAP", "OSLK"]
    names = [ar(AIRPORTS[c]["short"]) for c in order]
    vals = [mx[c]["total"] for c in order]
    cols = [AP_COLOR[c] for c in order]
    ax = axes[0]
    b = ax.bar(names, vals, color=cols, width=0.62)
    for r, v in zip(b, vals):
        ax.text(r.get_x() + r.get_width() / 2, v * 1.02, fmt_k(v), ha="center", fontsize=12, fontweight="bold")
    ax.set_title(ar("إجمالي الحركات المسجلة (يناير 2025 – سبتمبر 2026)"))
    ax.set_ylim(0, max(vals) * 1.14)
    ax.set_ylabel(ar("عدد الحركات"))
    ax.margins(x=0.02)

    ax = axes[1]
    x = np.arange(3)
    dep = [mx[c]["departures"] for c in order]
    arr = [mx[c]["arrivals"] for c in order]
    ax.bar(x - 0.19, dep, 0.38, label=ar("مغادرات"), color="#334155")
    ax.bar(x + 0.19, arr, 0.38, label=ar("وصولات"), color="#94a3b8")
    for i in range(3):
        ax.text(x[i] - 0.19, dep[i] * 1.02, fmt_k(dep[i]), ha="center", fontsize=9.5)
        ax.text(x[i] + 0.19, arr[i] * 1.02, fmt_k(arr[i]), ha="center", fontsize=9.5)
    ax.set_xticks(x); ax.set_xticklabels(names)
    ax.set_title(ar("المغادرات مقابل الوصولات"))
    ax.legend(frameon=False)
    ax.set_ylim(0, max(dep + arr) * 1.15)
    fig.tight_layout()
    fig.savefig(CHARTS / "c01_totals.png", bbox_inches="tight")
    plt.close(fig)


def chart_monthly(mx):
    fig, ax = plt.subplots(figsize=(11.5, 4.8))
    for icao in ["OSDI", "OSAP", "OSLK"]:
        ms = [x for x in mx[icao]["monthly"] if x["month"] >= "2025-01"]
        idx = pd.period_range("2025-01", "2026-09", freq="M")
        s = pd.Series({x["month"]: x["n"] for x in ms}).reindex(idx.astype(str), fill_value=0)
        ax.plot(idx.to_timestamp(), s.values, marker="o", ms=3.6,
                color=AP_COLOR[icao], label=ar(AIRPORTS[icao]["short"]), linewidth=2)
    # منطقة فجوة بيانات دمشق (مارس 2026) + الشهر الأخير غير المكتمل
    ymax = max(max([x["n"] for x in mx[i]["monthly"]] or [1]) for i in AIRPORTS)
    ax.axvspan(pd.Timestamp("2026-02-27"), pd.Timestamp("2026-04-03"),
               color="#fbbf24", alpha=0.22, zorder=0)
    ax.annotate(ar("فجوة تسجيل في بيانات دمشق"),
                xy=(pd.Timestamp("2026-03-16"), ymax * 1.05), ha="center",
                fontsize=10, color="#92400e")
    ax.axvspan(pd.Timestamp("2026-08-31"), pd.Timestamp("2026-09-30"),
               color="#64748b", alpha=0.14, zorder=0)
    ax.annotate(ar("سبتمبر 2026 غير مكتمل"),
                xy=(pd.Timestamp("2026-09-15"), ymax * 1.05), ha="center",
                fontsize=9.5, color="#475569")
    ax.set_ylim(0, ymax * 1.2)
    ax.set_title(ar("تطور الحركة الشهرية للمطارات الثلاثة"))
    ax.set_ylabel(ar("عدد الحركات في الشهر"))
    ax.legend(frameon=False)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    fig.savefig(CHARTS / "c02_monthly.png", bbox_inches="tight")
    plt.close(fig)


def chart_categories(mx):
    fig, ax = plt.subplots(figsize=(10.6, 4.2))
    order = ["OSDI", "OSAP", "OSLK"][::-1]
    cat_order = ["رحلات ركاب", "شحن جوي", "طيران أعمال", "عسكري وحكومي",
                 "طيران عام", "مروحيات", "خدمات أخرى", "غير مصنّف"]
    left = np.zeros(3)
    y = np.arange(3)
    for cat in cat_order:
        vals = np.array([next((c["share"] for c in mx[i]["categories"] if c["name"] == cat), 0)
                         for i in order])
        if vals.sum() == 0:
            continue
        ax.barh(y, vals, left=left, color=CAT_COLOR[cat], label=ar(cat), height=0.58)
        for j, (v, l) in enumerate(zip(vals, left)):
            if v >= 4.5:
                ax.text(l + v / 2, y[j], f"{v:.0f}%", ha="center", va="center",
                        color="white", fontsize=10, fontweight="bold")
        left += vals
    ax.set_yticks(y)
    ax.set_yticklabels([ar(AIRPORTS[i]["short"]) for i in order])
    ax.set_xlim(0, 100)
    ax.set_xlabel(ar("النسبة من إجمالي حركات المطار (%)"))
    ax.set_title(ar("تركيب الحركة حسب الفئة (نِسَب مئوية)"))
    ax.legend(frameon=False, ncol=4, loc="lower center", bbox_to_anchor=(0.5, -0.34))
    fig.tight_layout()
    fig.savefig(CHARTS / "c03_categories.png", bbox_inches="tight")
    plt.close(fig)


def chart_airlines(df, mx):
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ops = df["op"].value_counts().head(12)
    y = np.arange(len(ops))[::-1]
    left = np.zeros(len(ops))
    for icao in ["OSDI", "OSAP", "OSLK"]:
        vals = np.array([int(((df["op"] == k) & (df["airport"] == icao)).sum()) for k in ops.index])
        ax.barh(y, vals, left=left, color=AP_COLOR[icao],
                label=ar(AIRPORTS[icao]["short"]), height=0.62)
        left += vals
    labels = []
    for k in ops.index:
        nm, iata, _ = AIRLINES.get(k, (k, "—", "—"))
        labels.append(ar(f"{nm} ({k})"))
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=11)
    for j, k in enumerate(ops.index):
        ax.text(ops[k] * 1.01, y[j], fmt_k(ops[k]), va="center", fontsize=9.5)
    ax.set_xlim(0, ops.iloc[0] * 1.12)
    ax.set_title(ar("أكبر 12 شركة تشغيل عبر المطارات الثلاثة (إجمالي الحركات)"))
    ax.set_xlabel(ar("عدد الحركات"))
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "c04_airlines.png", bbox_inches="tight")
    plt.close(fig)


def chart_share_donuts(mx):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    for ax, icao in zip(axes, ["OSDI", "OSAP"]):
        ops = mx[icao]["top_airlines"][:7]
        other = mx[icao]["total"] - sum(o["n"] for o in ops)
        vals = [o["n"] for o in ops] + [other]
        labels = [ar(o["name"]) for o in ops] + [ar("آخرون")]
        colors = plt.cm.Blues if icao == "OSDI" else plt.cm.Greens
        cs = [colors(0.85 - 0.07 * i) for i in range(len(ops))] + ["#cbd5e1"]
        wedges, _, autotexts = ax.pie(
            vals, labels=labels, colors=cs, autopct=lambda p: f"{p:.0f}%" if p >= 4 else "",
            startangle=90, counterclock=False,
            textprops={"fontsize": 9.6}, wedgeprops={"edgecolor": "white", "linewidth": 1.4})
        for t in autotexts:
            t.set_color("white"); t.set_fontweight("bold"); t.set_fontsize(9)
        ax.set_title(ar(f"حصة شركات التشغيل — {AIRPORTS[icao]['short']}"), pad=12)
    fig.suptitle(ar("توزّع السوق بين شركات التشغيل (أكبر 7 شركات)"), fontsize=15, fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "c05_shares.png", bbox_inches="tight")
    plt.close(fig)


def chart_destinations(mx):
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.4))
    for ax, icao in zip(axes, ["OSDI", "OSAP"]):
        dst = mx[icao]["top_destinations"][:10][::-1]
        names = [ar(f"{d['city']} ({d['iata']})") for d in dst]
        vals = [d["n"] for d in dst]
        ax.barh(np.arange(len(dst)), vals, color=AP_COLOR[icao], height=0.62)
        ax.set_yticks(np.arange(len(dst))); ax.set_yticklabels(names, fontsize=10.5)
        for j, v in enumerate(vals):
            ax.text(v * 1.01, j, fmt_k(v), va="center", fontsize=9)
        ax.set_xlim(0, max(vals) * 1.13)
        ax.set_title(ar(f"أهم 10 وجهات مغادرة — {AIRPORTS[icao]['short']}"))
        ax.set_xlabel(ar("عدد الرحلات المغادرة"))
    fig.suptitle(ar("خريطة الوجهات الأكثر تكراراً (مغادرات)"), fontsize=15, fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "c06_destinations.png", bbox_inches="tight")
    plt.close(fig)


def chart_hourly(mx):
    fig, ax = plt.subplots(figsize=(11, 4.4))
    hours = np.arange(24)
    for icao in ["OSDI", "OSAP", "OSLK"]:
        h = np.array(mx[icao]["hourly"], dtype=float)
        h = 100 * h / h.sum()
        ax.plot(hours, h, marker="o", ms=3.5, color=AP_COLOR[icao],
                label=ar(AIRPORTS[icao]["short"]), linewidth=2)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel(ar("الساعة (بتوقيت دمشق المحلي)"))
    ax.set_ylabel(ar("% من الحركات"))
    ax.set_title(ar("التوزيع الساعي للحركة — إيقاع اليوم التشغيلي"))
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "c07_hourly.png", bbox_inches="tight")
    plt.close(fig)


def chart_dow(mx):
    fig, ax = plt.subplots(figsize=(11, 4.4))
    x = np.arange(7)
    w = 0.27
    for i, icao in enumerate(["OSDI", "OSAP", "OSLK"]):
        cnts = np.array(mx[icao]["dow_counts"], dtype=float)
        cnts = 100 * cnts / cnts.sum()
        ax.bar(x + (i - 1) * w, cnts, w, color=AP_COLOR[icao],
               label=ar(AIRPORTS[icao]["short"]))
    ax.set_xticks(x)
    ax.set_xticklabels([ar(d) for d in DOW_AR])
    ax.set_ylabel(ar("% من الحركات"))
    ax.set_title(ar("توزيع الحركة على أيام الأسبوع"))
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "c08_dow.png", bbox_inches="tight")
    plt.close(fig)


def chart_types(df):
    fig, ax = plt.subplots(figsize=(11, 5.2))
    types = df["type"].value_counts().head(10)
    y = np.arange(len(types))[::-1]
    left = np.zeros(len(types))
    for icao in ["OSDI", "OSAP", "OSLK"]:
        vals = np.array([int(((df["type"] == k) & (df["airport"] == icao)).sum()) for k in types.index])
        ax.barh(y, vals, left=left, color=AP_COLOR[icao],
                label=ar(AIRPORTS[icao]["short"]), height=0.62)
        left += vals
    ax.set_yticks(y); ax.set_yticklabels(list(types.index), fontsize=11)
    for j, v in enumerate(types.values):
        ax.text(v * 1.01, y[j], fmt_k(v), va="center", fontsize=9.5)
    ax.set_xlim(0, types.iloc[0] * 1.12)
    ax.set_title(ar("أكثر 10 أنواع طائرات تشغيلاً (حسب المطار)"))
    ax.set_xlabel(ar("عدد الحركات"))
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "c09_types.png", bbox_inches="tight")
    plt.close(fig)


def chart_profile(mx):
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    order = ["OSDI", "OSAP", "OSLK"]
    names = [ar(AIRPORTS[c]["short"]) for c in order]
    cols = [AP_COLOR[c] for c in order]

    ax = axes[0]
    v = [mx[c]["ft_median"] or 0 for c in order]
    ax.bar(names, v, color=cols, width=0.6)
    for i, val in enumerate(v):
        ax.text(i, val * 1.03, f"{val:.0f}", ha="center", fontweight="bold", fontsize=11)
    ax.set_title(ar("وسيط زمن الرحلة (دقيقة)"))
    ax.set_ylim(0, max(v) * 1.18)

    ax = axes[1]
    v = [mx[c]["dist_median"] or 0 for c in order]
    ax.bar(names, v, color=cols, width=0.6)
    for i, val in enumerate(v):
        ax.text(i, val * 1.03, f"{val:,.0f}", ha="center", fontweight="bold", fontsize=11)
    ax.set_title(ar("وسيط المسافة المقطوعة (كم)"))
    ax.set_ylim(0, max(v) * 1.18)

    ax = axes[2]
    v = [mx[c]["widebody_share"] for c in order]
    ax.bar(names, v, color=cols, width=0.6)
    for i, val in enumerate(v):
        ax.text(i, val + 0.35, f"{val:.1f}%", ha="center", fontweight="bold", fontsize=11)
    ax.set_title(ar("حصة الطائرات العريضة البدن"))
    ax.set_ylim(0, max(max(v) * 1.25, 2))
    fig.suptitle(ar("بصمة التشغيل: زمن الرحلة، المسافة، وحجم الطائرات"), fontsize=14.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "c10_profile.png", bbox_inches="tight")
    plt.close(fig)


def chart_growth(mx):
    fig, ax = plt.subplots(figsize=(10.2, 4.6))
    order = ["OSDI", "OSAP", "OSLK"]
    x = np.arange(3)
    v25 = [mx[c]["jan_aug_2025"] for c in order]
    v26 = [mx[c]["jan_aug_2026"] for c in order]
    ax.bar(x - 0.19, v25, 0.38, label=ar("يناير–أغسطس 2025"), color="#93c5fd")
    ax.bar(x + 0.19, v26, 0.38, label=ar("يناير–أغسطس 2026"), color="#1d4ed8")
    for i in range(3):
        ax.text(x[i] - 0.19, v25[i] * 1.02, fmt_k(v25[i]), ha="center", fontsize=9.5)
        ax.text(x[i] + 0.19, v26[i] * 1.02, fmt_k(v26[i]), ha="center", fontsize=9.5)
        g = mx[order[i]]["growth_pct"]
        if g is not None:
            ax.annotate(ar(f"نمو {g:+.0f}%"), (x[i], max(v25[i], v26[i]) * 1.13),
                        ha="center", fontsize=11, fontweight="bold",
                        color="#166534" if g >= 0 else "#991b1b")
    ax.set_xticks(x)
    ax.set_xticklabels([ar(AIRPORTS[c]["short"]) for c in order])
    ax.set_ylim(0, max(max(v25), max(v26)) * 1.28)
    ax.set_title(ar("مقارنة عادلة: الفترة يناير–أغسطس بين عامي 2025 و2026"))
    ax.set_ylabel(ar("عدد الحركات"))
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(CHARTS / "c11_growth.png", bbox_inches="tight")
    plt.close(fig)


def chart_latakia(df, mx):
    m = mx["OSLK"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6))

    ax = axes[0]
    ms = [x for x in m["monthly"]]
    idx = pd.period_range(ms[0]["month"], ms[-1]["month"], freq="M")
    s = pd.Series({x["month"]: x["n"] for x in ms}).reindex(idx.astype(str), fill_value=0)
    ax.bar(idx.to_timestamp(), s.values, color=AP_COLOR["OSLK"], width=22)
    ax.set_title(ar("الحركة الشهرية (اللاذقية)"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=45)

    ax = axes[1]
    d = df[df["airport"] == "OSLK"]
    ops = d["op"].value_counts().head(5)
    vals = list(ops.values)
    labels = [ar(airline_name(k)) for k in ops.index]
    colors = ["#b91c1c" if k in MIL_OPS else "#64748b" for k in ops.index]
    wedges, _, at = ax.pie(vals, labels=labels, colors=colors, autopct="%1.0f%%",
                           startangle=90, counterclock=False, textprops={"fontsize": 9.5},
                           wedgeprops={"edgecolor": "white", "linewidth": 1.3})
    for t in at:
        t.set_color("white"); t.set_fontweight("bold")
    ax.set_title(ar("المشغّلون (أحمر = عسكري روسي)"), fontsize=13)

    ax = axes[2]
    t = d["type"].value_counts().head(6)[::-1]
    ax.barh(np.arange(len(t)), t.values, color="#7f1d1d", height=0.6)
    ax.set_yticks(np.arange(len(t))); ax.set_yticklabels(list(t.index), fontsize=10.5)
    for j, v in enumerate(t.values):
        ax.text(v + 0.8, j, str(v), va="center", fontsize=9.5)
    ax.set_xlim(0, t.max() * 1.15)
    ax.set_title(ar("أنواع الطائرات"), fontsize=13)
    fig.suptitle(ar("اللاذقية: مطار بوجهة عسكرية — جسر جوي روسي (تشكالوفسكي)"),
                 fontsize=14.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "c12_latakia.png", bbox_inches="tight")
    plt.close(fig)


def chart_domestic(mx):
    fig, ax = plt.subplots(figsize=(10.2, 4.2))
    order = ["OSDI", "OSAP", "OSLK"]
    y = np.arange(3)
    dom = np.array([mx[c]["domestic_dep"] for c in order], dtype=float)
    intl = np.array([mx[c]["intl_dep"] for c in order], dtype=float)
    tot = dom + intl
    dom_p, intl_p = 100 * dom / tot, 100 * intl / tot
    ax.barh(y, dom_p, color="#f59e0b", label=ar("مغادرات داخلية"), height=0.55)
    ax.barh(y, intl_p, left=dom_p, color="#1e40af", label=ar("مغادرات دولية"), height=0.55)
    for j in range(3):
        if dom_p[j] >= 6:
            ax.text(dom_p[j] / 2, y[j], f"{dom_p[j]:.0f}%", ha="center", va="center",
                    color="white", fontweight="bold")
        ax.text(dom_p[j] + intl_p[j] / 2, y[j], f"{intl_p[j]:.0f}%", ha="center",
                va="center", color="white", fontweight="bold")
    ax.set_yticks(y)
    ax.set_yticklabels([ar(AIRPORTS[c]["short"]) for c in order])
    ax.set_xlim(0, 100)
    ax.set_xlabel(ar("النسبة من المغادرات المصنّفة (%)"))
    ax.set_title(ar("المغادرات: داخلية مقابل دولية"))
    ax.legend(frameon=False, ncol=2, loc="lower center", bbox_to_anchor=(0.5, -0.32))
    fig.tight_layout()
    fig.savefig(CHARTS / "c13_domestic.png", bbox_inches="tight")
    plt.close(fig)


def chart_network(df):
    """حجم الشبكة: عدد الوجهات والشركات لكل مطار"""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    order = ["OSDI", "OSAP", "OSLK"]
    names = [ar(AIRPORTS[c]["short"]) for c in order]
    cols = [AP_COLOR[c] for c in order]
    ax = axes[0]
    v = [df[(df["airport"] == c) & (df["movement"] == "مغادرة")]["dest_iata"].dropna().nunique()
         for c in order]
    ax.bar(names, v, color=cols, width=0.58)
    for i, val in enumerate(v):
        ax.text(i, val + 0.8, str(val), ha="center", fontweight="bold", fontsize=12)
    ax.set_title(ar("عدد وجهات المغادرة المختلفة"))
    ax.set_ylim(0, max(v) * 1.2)
    ax = axes[1]
    v = [df[df["airport"] == c]["reg"].nunique() for c in order]
    ax.bar(names, v, color=cols, width=0.58)
    for i, val in enumerate(v):
        ax.text(i, val + 6, fmt_k(val), ha="center", fontweight="bold", fontsize=12)
    ax.set_title(ar("عدد الطائرات الفريدة (بحسب التسجيل)"))
    ax.set_ylim(0, max(v) * 1.2)
    fig.suptitle(ar("اتساع الشبكة والتنوّع التشغيلي"), fontsize=14.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "c14_network.png", bbox_inches="tight")
    plt.close(fig)


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
            "متوسط شهري": m["avg_monthly"], "أعلى شهر": f'{m["peak_month"]["month"]} ({m["peak_month"]["n"]})',
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
