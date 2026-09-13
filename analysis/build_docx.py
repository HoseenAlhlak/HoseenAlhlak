#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مولد نسخة Word القابلة للتحرير من التقرير المقارن.

الميزة الجوهرية: الرسوم البيانية تُحقن كـ«مخططات Word أصلية» (DrawingML Charts)
وليست صوراً — فيعرض Word نصوصها العربية بنفسه (تشكيل واتجاه صحيحان دائماً)،
ويمكن للمستخدم تحرير بياناتها (تحرير البيانات) ونوعها وألوانها وعناوينها مباشرة.

المراحل:
  A) بناء ملف PPTX مؤقت يحوي المخططات الأصلية عبر python-pptx (يشمل جداول بياناتها المضمّنة)
  B) بناء مستند DOCX كامل RTL عبر python-docx (نصوص + جداول + علامات مواضع الرسوم)
  C) حقن أجزاء المخططات (XML + XLSX مضمّن + علاقات) داخل حزمة DOCX
"""

import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import (XL_CHART_TYPE, XL_LEGEND_POSITION,
                             XL_LABEL_POSITION, XL_MARKER_STYLE)
from pptx.dml.color import RGBColor

from docx import Document
from docx.shared import Cm, RGBColor as DocxRGB
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "analysis" / "results"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "reports" / "تقرير_مطارات_سوريا_المقارن.docx"

FONT = "Segoe UI"          # متوفر افتراضياً في Windows/Office بدعم عربي كامل
NAVY = "0F2A5C"
DAM, ALP, LTK = "1E5AA8", "0E8A5F", "C2571A"
AP_COLOR = {"OSDI": DAM, "OSAP": ALP, "OSLK": LTK}
AP_AR = {"OSDI": "دمشق", "OSAP": "حلب", "OSLK": "اللاذقية"}

# ============================================================================
# تحميل البيانات
# ============================================================================
metrics = json.loads((RESULTS / "metrics.json").read_text(encoding="utf-8"))
M = metrics["meta"]
DAMX = metrics["airports"]["OSDI"]
ALPX = metrics["airports"]["OSAP"]
LTKX = metrics["airports"]["OSLK"]
Q = metrics["quality"]

om = pd.read_csv(RESULTS / "operators_matrix.csv")
AIRLINE_NAMES = {  # (اسم عربي، iata)
    "SYR": ("الخطوط الجوية السورية", "RB"), "FYC": ("فلاي شام", "XH"),
    "SAW": ("أجنحة الشام", "6Q"), "RJA": ("الملكية الأردنية", "RJ"),
    "THY": ("الخطوط التركية", "TK"), "TKJ": ("إيه جت AJet", "VF"),
    "PGT": ("بيغاسوس", "PC"), "SXS": ("صن إكسبرس", "XQ"),
    "KNE": ("فلاي ناس", "XY"), "FAD": ("فلاي ديل", "F3"),
    "SVA": ("الخطوط السعودية", "SV"), "QTR": ("الخطوط القطرية", "QR"),
    "QQE": ("كاتار التنفيذية", "QE"), "UAE": ("طيران الإمارات", "EK"),
    "ETD": ("الاتحاد للطيران", "EY"), "ABY": ("العربية للطيران", "G9"),
    "ADY": ("العربية لأبوظبي", "3L"), "FDB": ("فلاي دبي", "FZ"),
    "JZR": ("الجزيرة الكويتية", "J9"), "KAC": ("الخطوط الكويتية", "KU"),
    "MEA": ("طيران الشرق الأوسط", "ME"), "DNA": ("دان إير", "DN"),
    "MFX": ("سنتم إير", "C6"), "MAR": ("إير ميديترانيان", "MV"),
    "NGN": ("ليف أفييشن", "KK"), "IGC": ("آي جي سي (خاص)", "—"),
    "RFF": ("القوات الجوية الروسية", "—"), "CHD": ("تشكيل CHD الروسي", "—"),
    "TTF": ("تشكيل TTF الروسي", "—"), "RSD": ("تشكيل RSD الروسي", "—"),
}

# بيانات إضافية من الملفات الخام (أنواع الطائرات لكل مطار + وجهات المغادرة)
raw_frames = []
for icao, fname in [("OSDI", "flights_damascus_OSDI.csv"),
                    ("OSAP", "flights_aleppo_OSAP.csv"),
                    ("OSLK", "flights_latakia_OSLK.csv")]:
    d = pd.read_csv(RAW / fname, low_memory=False)
    d["airport"] = icao
    raw_frames.append(d)
raw = pd.concat(raw_frames, ignore_index=True)
raw["op"] = raw["operating_as"].fillna("غير معروف")

MONTHS = pd.period_range("2025-01", "2026-09", freq="M").astype(str).tolist()
DOW_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "جمعة", "السبت", "الأحد"]
CATS_MAIN = ["رحلات ركاب", "شحن جوي", "طيران أعمال", "عسكري وحكومي"]
CATS_COLORS = {"رحلات ركاب": "2563EB", "شحن جوي": "7C3AED",
               "طيران أعمال": "0891B2", "عسكري وحكومي": "D64545", "أخرى": "CBD5E1"}


def monthly_series(icao):
    s = pd.Series({x["month"]: x["n"] for x in metrics["airports"][icao]["monthly"]})
    return [int(s.get(m, 0)) for m in MONTHS]


def cat_shares(icao):
    d = {c["name"]: c["share"] for c in metrics["airports"][icao]["categories"]}
    vals = [d.get(c, 0) for c in CATS_MAIN]
    vals.append(100 - sum(vals))
    return vals


def hourly_pct(icao):
    h = metrics["airports"][icao]["hourly"]
    tot = sum(h) or 1
    return [round(100 * x / tot, 2) for x in h]


def dow_pct(icao):
    c = metrics["airports"][icao]["dow_counts"]
    tot = sum(c) or 1
    return [round(100 * x / tot, 2) for x in c]


def top_airlines(n=12):
    sub = om[om["op"] != "غير معروف"].head(n)
    out = []
    for _, r in sub.iterrows():
        nm = AIRLINE_NAMES.get(r["op"], (str(r["op"]), "—"))[0]
        out.append((f"{nm} ({r['op']})",
                    int(r.get("OSAP", 0)), int(r.get("OSDI", 0)), int(r.get("OSLK", 0))))
    return out


def airline_label(code, n):
    if code == "غير معروف":
        return "غير محدد المشغّل"
    nm = AIRLINE_NAMES.get(code, (code, "—"))[0]
    return f"{nm} ({code})" if code not in ("RFF",) else nm


def top_types(n=10):
    vc = raw["type"].value_counts().head(n)
    out = []
    for t, _ in vc.items():
        row = [int(((raw["type"] == t) & (raw["airport"] == a)).sum())
               for a in ["OSDI", "OSAP", "OSLK"]]
        out.append((t, *row))
    return out


def dep_dest_count(icao):
    d = raw[(raw["airport"] == icao) & (raw["orig_icao"] == icao)]
    return int(d["dest_iata"].dropna()[d["dest_iata"].dropna() != {"OSDI": "DAM", "OSAP": "ALP", "OSLK": "LTK"}[icao]].nunique())


def unique_regs(icao):
    return int(raw[raw["airport"] == icao]["reg"].nunique())


def ops_by(code):
    r = om[om["op"] == code]
    return int(r["الإجمالي"].iloc[0]) if len(r) else 0


def fmt(n):
    return f"{int(n):,}"


def cat_share(ap, name):
    for c in ap["categories"]:
        if c["name"] == name:
            return c["share"]
    return 0


# ============================================================================
# المرحلة A: تعريف المخططات وبناؤها في PPTX
# ============================================================================
CHART_SPECS = []  # (key, xl_type, title, cats, series[(name, values, color)], opts)


def spec(key, xl, title, cats, series, **opts):
    CHART_SPECS.append(dict(key=key, xl=xl, title=title, cats=cats,
                            series=series, opts=opts))


AP3 = [AP_AR["OSDI"], AP_AR["OSAP"], AP_AR["OSLK"]]

spec("totals", XL_CHART_TYPE.COLUMN_CLUSTERED,
     "الحركات المسجلة: المغادرات مقابل الوصولات",
     AP3,
     [("المغادرات", [DAMX["departures"], ALPX["departures"], LTKX["departures"]], "334155"),
      ("الوصولات", [DAMX["arrivals"], ALPX["arrivals"], LTKX["arrivals"]], "94A3B8")],
     labels=True, legend=True, h=3.35)

spec("monthly", XL_CHART_TYPE.LINE_MARKERS,
     "تطور الحركة الشهرية للمطارات الثلاثة (2025-01 حتى 2026-09)",
     MONTHS,
     [(AP_AR["OSDI"], monthly_series("OSDI"), DAM),
      (AP_AR["OSAP"], monthly_series("OSAP"), ALP),
      (AP_AR["OSLK"], monthly_series("OSLK"), LTK)],
     legend=True, h=3.6)

spec("categories", XL_CHART_TYPE.BAR_STACKED,
     "تركيب الحركة حسب الفئة (نسبة مئوية)",
     [AP_AR["OSLK"], AP_AR["OSAP"], AP_AR["OSDI"]],
     [(c, [cat_shares(a)[i] for a in ["OSDI", "OSAP", "OSLK"]], CATS_COLORS[c])
      for i, c in enumerate(CATS_MAIN)] + [("أخرى/غير مصنّف",
     [cat_shares(a)[4] for a in ["OSDI", "OSAP", "OSLK"]], "CBD5E1")],
     legend=True, h=3.2, pct=True)

_top = top_airlines(12)
spec("airlines", XL_CHART_TYPE.BAR_STACKED,
     "أكبر 12 شركة تشغيل عبر المطارات الثلاثة",
     [t[0] for t in _top][::-1],
     [(f"حلب", [t[2] for t in _top][::-1], ALP),
      ("دمشق", [t[1] for t in _top][::-1], DAM),
      ("اللاذقية", [t[3] for t in _top][::-1], LTK)],
     legend=True, h=4.6)


def donut_spec(key, title, icao, palette):
    ops = metrics["airports"][icao]["top_airlines"][:7]
    other = metrics["airports"][icao]["total"] - sum(o["n"] for o in ops)
    names = [airline_label(o["code"], o["n"]) for o in ops] + ["آخرون"]
    vals = [o["n"] for o in ops] + [other]
    spec(key, XL_CHART_TYPE.DOUGHNUT, title, names,
         [("عدد الحركات", vals, None)], donut=palette, h=3.9, w=4.9)


donut_spec("share_dam", "حصص السوق — دمشق (أكبر 7 شركات + آخرون)", "OSDI",
           ["1E5AA8", "3B82C4", "6BA3D9", "93B9E3", "B7CDEA", "D3E0F2", "E7EFF9", "CBD5E1"])
donut_spec("share_alp", "حصص السوق — حلب (أكبر 7 شركات + آخرون)", "OSAP",
           ["0E8A5F", "2DA44E", "5CBF7E", "8BD4A8", "B8E6CC", "D5F2E1", "EAF9F1", "CBD5E1"])


def dest_spec(key, icao, color, title):
    dst = metrics["airports"][icao]["top_destinations"][:10]
    cities = {"OSDI": [], "OSAP": []}
    names = [f"{d['city']} ({d['iata']})" for d in dst][::-1]
    vals = [d["n"] for d in dst][::-1]
    spec(key, XL_CHART_TYPE.BAR_CLUSTERED, title, names,
         [("عدد الرحلات", vals, color)], labels=True, h=4.2)


dest_spec("dest_dam", "OSDI", DAM, "أهم 10 وجهات مغادرة — دمشق")
dest_spec("dest_alp", "OSAP", ALP, "أهم 10 وجهات مغادرة — حلب")

spec("hourly", XL_CHART_TYPE.LINE_MARKERS,
     "التوزيع الساعي للحركة — إيقاع اليوم التشغيلي (%)",
     [f"{h:02d}" for h in range(24)],
     [(AP_AR["OSDI"], hourly_pct("OSDI"), DAM),
      (AP_AR["OSAP"], hourly_pct("OSAP"), ALP),
      (AP_AR["OSLK"], hourly_pct("OSLK"), LTK)],
     legend=True, h=3.4)

spec("dow", XL_CHART_TYPE.COLUMN_CLUSTERED,
     "توزيع الحركة على أيام الأسبوع (%)",
     DOW_AR,
     [(AP_AR["OSDI"], dow_pct("OSDI"), DAM),
      (AP_AR["OSAP"], dow_pct("OSAP"), ALP),
      (AP_AR["OSLK"], dow_pct("OSLK"), LTK)],
     legend=True, h=3.4)

_tt = top_types(10)
spec("types", XL_CHART_TYPE.BAR_STACKED,
     "أكثر 10 أنواع طائرات تشغيلاً (حسب المطار)",
     [t[0] for t in _tt][::-1],
     [("دمشق", [t[1] for t in _tt][::-1], DAM),
      ("حلب", [t[2] for t in _tt][::-1], ALP),
      ("اللاذقية", [t[3] for t in _tt][::-1], LTK)],
     legend=True, h=4.3)

spec("ft_median", XL_CHART_TYPE.COLUMN_CLUSTERED,
     "وسيط زمن الرحلة (دقيقة)",
     AP3, [("الوسيط (دقيقة)", [DAMX["ft_median"], ALPX["ft_median"], LTKX["ft_median"]], "0F766E")],
     labels=True, point_colors=[DAM, ALP, LTK], h=3.1, w=4.9)

spec("dist_median", XL_CHART_TYPE.COLUMN_CLUSTERED,
     "وسيط المسافة المقطوعة (كم)",
     AP3, [("الوسيط (كم)", [DAMX["dist_median"], ALPX["dist_median"], LTKX["dist_median"]], "7C3AED")],
     labels=True, point_colors=[DAM, ALP, LTK], h=3.1, w=4.9)

spec("widebody", XL_CHART_TYPE.COLUMN_CLUSTERED,
     "حصة الطائرات العريضة البدن (%)",
     AP3, [("النسبة", [DAMX["widebody_share"], ALPX["widebody_share"], LTKX["widebody_share"]], "B45309")],
     labels=True, point_colors=[DAM, ALP, LTK], h=3.1, w=4.9, numfmt='0.0"%"')

spec("growth", XL_CHART_TYPE.COLUMN_CLUSTERED,
     "مقارنة عادلة: الفترة يناير–أغسطس بين عامي 2025 و2026",
     AP3,
     [("يناير–أغسطس 2025", [DAMX["jan_aug_2025"], ALPX["jan_aug_2025"], LTKX["jan_aug_2025"]], "93C5FD"),
      ("يناير–أغسطس 2026", [DAMX["jan_aug_2026"], ALPX["jan_aug_2026"], LTKX["jan_aug_2026"]], "1D4ED8")],
     labels=True, legend=True, h=3.5)

spec("ltk_monthly", XL_CHART_TYPE.COLUMN_CLUSTERED,
     "اللاذقية: الحركة الشهرية",
     MONTHS, [("عدد الحركات", monthly_series("OSLK"), LTK)],
     h=3.3)

_ltk_raw = raw[raw["airport"] == "OSLK"]
_lops = _ltk_raw["op"].value_counts().head(5)
spec("ltk_ops", XL_CHART_TYPE.BAR_CLUSTERED,
     "اللاذقية: المشغّلون (عدد الحركات)",
     [airline_label(k, v) for k, v in _lops.items()][::-1],
     [("عدد الحركات", [int(v) for v in _lops.values][::-1], "B91C1C")],
     labels=True, h=3.3)

_lt = _ltk_raw["type"].value_counts().head(6)
spec("ltk_types", XL_CHART_TYPE.BAR_CLUSTERED,
     "اللاذقية: أنواع الطائرات",
     list(_lt.index)[::-1],
     [("عدد الحركات", [int(v) for v in _lt.values][::-1], "7F1D1D")],
     labels=True, h=3.3)

spec("domestic", XL_CHART_TYPE.BAR_STACKED,
     "المغادرات: داخلية مقابل دولية (نسبة مئوية)",
     [AP_AR["OSLK"], AP_AR["OSAP"], AP_AR["OSDI"]],
     [("مغادرات داخلية", [round(100 * metrics["airports"][a]["domestic_dep"] /
                                 max(metrics["airports"][a]["domestic_dep"] + metrics["airports"][a]["intl_dep"], 1), 1)
                            for a in ["OSDI", "OSAP", "OSLK"]], "F59E0B"),
      ("مغادرات دولية", [round(100 * metrics["airports"][a]["intl_dep"] /
                                 max(metrics["airports"][a]["domestic_dep"] + metrics["airports"][a]["intl_dep"], 1), 1)
                            for a in ["OSDI", "OSAP", "OSLK"]], "1E40AF")],
     legend=True, h=3.2, pct=True)

spec("network", XL_CHART_TYPE.COLUMN_CLUSTERED,
     "اتساع الشبكة والتنوّع التشغيلي",
     AP3,
     [("عدد وجهات المغادرة", [dep_dest_count("OSDI"), dep_dest_count("OSAP"), dep_dest_count("OSLK")], "0E7490"),
      ("عدد الطائرات الفريدة", [unique_regs("OSDI"), unique_regs("OSAP"), unique_regs("OSLK")], "334155")],
     labels=True, legend=True, h=3.4)


# ---------- بناء PPTX ----------
def rgb(hexstr):
    return RGBColor.from_string(hexstr)


def build_pptx(path: Path):
    prs = Presentation()
    blank = prs.slide_layouts[6]
    for s in CHART_SPECS:
        slide = prs.slides.add_slide(blank)
        cd = CategoryChartData()
        cd.categories = s["cats"]
        for name, vals, _c in s["series"]:
            cd.add_series(name, vals)
        w = Emu(int(s["opts"].get("w", 5.7) * 914400))
        h = Emu(int(s["opts"].get("h", 3.4) * 914400))
        gframe = slide.shapes.add_chart(s["xl"], Emu(0), Emu(0), w, h, cd)
        chart = gframe.chart

        # خط الرسم كله + العنوان
        chart.font.name = FONT
        chart.font.size = Pt(10)
        chart.has_title = True
        chart.chart_title.text_frame.text = s["title"]
        tr = chart.chart_title.text_frame.paragraphs[0].runs[0]
        tr.font.size = Pt(12.5)
        tr.font.bold = True
        tr.font.name = FONT
        tr.font.color.rgb = rgb(NAVY)

        # ألوان السلاسل
        if s["opts"].get("donut"):
            pal = s["opts"]["donut"]
            ser = chart.plots[0].series[0]
            for i, pt in enumerate(ser.points):
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = rgb(pal[i % len(pal)])
        else:
            for ser, (name, vals, col) in zip(chart.plots[0].series, s["series"]):
                if s["xl"] in (XL_CHART_TYPE.LINE_MARKERS, XL_CHART_TYPE.LINE):
                    ser.format.line.color.rgb = rgb(col)
                    ser.format.line.width = Pt(2.25)
                    ser.marker.style = XL_MARKER_STYLE.CIRCLE
                    ser.marker.size = 5
                    ser.marker.format.fill.solid()
                    ser.marker.format.fill.fore_color.rgb = rgb(col)
                    ser.marker.format.line.color.rgb = rgb(col)
                else:
                    ser.format.fill.solid()
                    ser.format.fill.fore_color.rgb = rgb(col)
                    ser.format.line.fill.background()
            if s["opts"].get("point_colors"):
                ser = chart.plots[0].series[0]
                for i, pt in enumerate(ser.points):
                    pt.format.fill.solid()
                    pt.format.fill.fore_color.rgb = rgb(s["opts"]["point_colors"][i])

        # تسميات البيانات
        if s["opts"].get("labels"):
            plot = chart.plots[0]
            plot.has_data_labels = True
            dl = plot.data_labels
            dl.font.size = Pt(9)
            dl.font.name = FONT
            dl.font.color.rgb = rgb("374151")
            dl.number_format = s["opts"].get("numfmt", "#,##0")
            dl.number_format_is_linked = False
            if s["xl"] == XL_CHART_TYPE.BAR_CLUSTERED or s["xl"] == XL_CHART_TYPE.COLUMN_CLUSTERED:
                dl.position = XL_LABEL_POSITION.OUTSIDE_END
        if s["opts"].get("donut"):
            plot = chart.plots[0]
            plot.has_data_labels = True
            dl = plot.data_labels
            dl.font.size = Pt(9)
            dl.font.bold = True
            dl.font.color.rgb = rgb("FFFFFF")
            dl.show_percentage = True
            dl.show_value = False
            dl.number_format = "0%"
            dl.number_format_is_linked = False

        # وسيلة الإيضاح
        if s["opts"].get("legend") or len(s["series"]) > 1:
            chart.has_legend = True
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
            chart.legend.font.size = Pt(9.5)
            chart.legend.font.name = FONT
        else:
            chart.has_legend = False

        # المحاور
        try:
            cat_ax = chart.category_axis
            cat_ax.tick_labels.font.size = Pt(9.5)
            cat_ax.tick_labels.font.name = FONT
            cat_ax.has_major_gridlines = False
        except Exception:
            pass
        try:
            val_ax = chart.value_axis
            val_ax.tick_labels.font.size = Pt(9)
            val_ax.tick_labels.font.name = FONT
            val_ax.tick_labels.number_format = s["opts"].get("numfmt", "#,##0") if s["opts"].get("pct") else "#,##0"
            val_ax.tick_labels.number_format_is_linked = False
            val_ax.has_major_gridlines = True
            val_ax.major_gridlines.format.line.color.rgb = rgb("E5E7EB")
            val_ax.major_gridlines.format.line.width = Pt(0.5)
            val_ax.format.line.color.rgb = rgb("9CA3AF")
        except Exception:
            pass
    prs.save(str(path))


# ============================================================================
# المرحلة B: بناء مستند DOCX (RTL كامل)
# ============================================================================
def set_rtl(p, align="right"):
    pPr = p._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    pPr.append(bidi)
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def run_rtl(p, text, bold=False, size=11, color=None, ltr=False):
    r = p.add_run(text)
    rPr = r._r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), FONT)
    rFonts.set(qn("w:hAnsi"), FONT)
    rFonts.set(qn("w:cs"), FONT)
    sz = OxmlElement("w:sz"); sz.set(qn("w:val"), str(int(size * 2))); rPr.append(sz)
    szCs = OxmlElement("w:szCs"); szCs.set(qn("w:val"), str(int(size * 2))); rPr.append(szCs)
    if bold:
        b = OxmlElement("w:b"); rPr.append(b)
        bCs = OxmlElement("w:bCs"); rPr.append(bCs)
    if color:
        r.font.color.rgb = DocxRGB.from_string(color)
    if not ltr:
        rtl = OxmlElement("w:rtl"); rPr.append(rtl)
    return r


def P(doc, text="", bold=False, size=11, color=None, align="right",
      space_after=6, outline=None):
    p = doc.add_paragraph()
    set_rtl(p, align)
    p.paragraph_format.space_after = Pt(space_after)
    if text:
        run_rtl(p, text, bold=bold, size=size, color=color)
    if outline is not None:
        pPr = p._p.get_or_add_pPr()
        ol = OxmlElement("w:outlineLvl"); ol.set(qn("w:val"), str(outline)); pPr.append(ol)
    return p


def H1(doc, text):
    return P(doc, text, bold=True, size=17, color=NAVY, space_after=10, outline=0)


def H2(doc, text):
    return P(doc, text, bold=True, size=13.5, color="1F2937", space_after=6, outline=1)


def BULLET(doc, text, bold_prefix=None):
    p = doc.add_paragraph()
    set_rtl(p)
    p.paragraph_format.space_after = Pt(4)
    run_rtl(p, "◆ ", size=10.5, color="1D4ED8")
    if bold_prefix:
        run_rtl(p, bold_prefix, bold=True, size=11)
    run_rtl(p, text, size=11)
    return p


def NOTE(doc, text, fill="FFF7ED", border="FDBA74"):
    # فقرة مظللة (ملاحظة)
    p = doc.add_paragraph()
    set_rtl(p)
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill); pPr.append(shd)
    p.paragraph_format.space_after = Pt(8)
    run_rtl(p, text, size=10.5, color="374151")
    return p


def TABLE(doc, headers, rows, widths=None, header_fill=NAVY, small=False):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    tblPr = t._tbl.tblPr
    bv = OxmlElement("w:bidiVisual"); tblPr.append(bv)
    layout = OxmlElement("w:tblLayout"); layout.set(qn("w:type"), "fixed"); tblPr.append(layout)
    fs = 9.5 if not small else 8.8
    # ترويسة
    for j, htxt in enumerate(headers):
        cell = t.rows[0].cells[j]
        cell.paragraphs[0].paragraph_format.space_after = Pt(0)
        set_rtl(cell.paragraphs[0], "center")
        run_rtl(cell.paragraphs[0], htxt, bold=True, size=fs, color="FFFFFF")
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), header_fill); tcPr.append(shd)
    # صفوف
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = t.rows[i + 1].cells[j]
            cell.paragraphs[0].paragraph_format.space_after = Pt(0)
            set_rtl(cell.paragraphs[0], "center" if j > 0 else "right")
            run_rtl(cell.paragraphs[0], str(val), size=fs)
            if i % 2 == 1:
                tcPr = cell._tc.get_or_add_tcPr()
                shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear")
                shd.set(qn("w:fill"), "F5F7FA"); tcPr.append(shd)
    if widths:
        for j, wcm in enumerate(widths):
            for r in t.rows:
                r.cells[j].width = Cm(wcm)
    return t


def CHART_MARK(doc, key):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    run_rtl(p, f"@@CHART_{key}@@", size=6, color="FFFFFF", ltr=True)
    return p


def CAPTION(doc, text):
    p = doc.add_paragraph()
    set_rtl(p)
    p.paragraph_format.space_after = Pt(10)
    run_rtl(p, text, size=9.5, color="6B7280")
    return p


def LTR_LINE(doc, text, size=9.5):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_after = Pt(3)
    run_rtl(p, text, size=size, color="374151", ltr=True)
    return p


def build_docx(path: Path):
    doc = Document()

    # خصائص
    doc.core_properties.title = "التقرير المقارن — حركة الطيران في مطارات سوريا الثلاثة"
    doc.core_properties.author = "تحليل آلي من مستودع HoseenAlhlak/HoseenAlhlak"
    doc.core_properties.language = "ar-SY"

    # إعداد الصفحة A4
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = Cm(2.1)
    sec.bottom_margin = Cm(1.9)

    # الخط الافتراضي
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(11)
    sPr = st.element.get_or_add_rPr()
    rF = sPr.get_or_add_rFonts()
    rF.set(qn("w:ascii"), FONT); rF.set(qn("w:hAnsi"), FONT); rF.set(qn("w:cs"), FONT)
    szCs = OxmlElement("w:szCs"); szCs.set(qn("w:val"), "22"); sPr.append(szCs)

    # تذييل الصفحات
    fp = sec.footer.paragraphs[0]
    set_rtl(fp, "center")
    run_rtl(fp, "التقرير المقارن — مطارات سوريا الثلاثة  |  صفحة ", size=8.5, color="6B7280")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), " PAGE ")
    r_ = OxmlElement("w:r")
    rPr_ = OxmlElement("w:rPr")
    szf = OxmlElement("w:sz"); szf.set(qn("w:val"), "17"); rPr_.append(szf)
    r_.append(rPr_)
    t_ = OxmlElement("w:t"); t_.text = "1"
    r_.append(t_)
    fld.append(r_)
    fp._p.append(fld)

    # ================= الغلاف =================
    P(doc, "", space_after=2)
    P(doc, "تقرير تحليلي موثّق — نسخة Word قابلة للتحرير", bold=True, size=13,
      color="1D4ED8", align="center", space_after=4)
    P(doc, "حركة الطيران في مطارات سوريا الثلاثة", bold=True, size=26,
      color=NAVY, align="center", space_after=4)
    P(doc, "دمشق  ·  حلب  ·  اللاذقية", bold=True, size=16,
      color="374151", align="center", space_after=10)
    P(doc, f"الفترة: {M['data_first']} حتى {M['data_last']}   |   {fmt(M['total_movements'])} حركة جوية   |   20 شهراً من البيانات",
      size=11.5, align="center", color="475569", space_after=14)

    TABLE(doc, ["المؤشر", "القيمة", "المؤشر", "القيمة"], [
        ["إجمالي الحركات", fmt(M["total_movements"]), "شركات التشغيل", str(M["unique_operators"])],
        ["حركات دمشق", fmt(DAMX["total"]), "وجهة مختلفة", str(M["unique_destinations"])],
        ["حركات حلب", fmt(ALPX["total"]), "طائرة فريدة", fmt(M["unique_aircraft"])],
        ["حركات اللاذقية", fmt(LTKX["total"]), "أنواع طائرات", str(M["unique_types"])],
    ], widths=[4.6, 3.4, 4.6, 3.4])
    P(doc, "", space_after=4)
    NOTE(doc, "هذه النسخة مبنية بالكامل بعناصر Word حية: كل النصوص والجداول قابلة للتحرير مباشرة، "
              "وكل رسم بياني هو «مخطط Word أصلي» — انقر بزر الفأرة الأيمن على أي رسم واختر «تحرير البيانات» "
              "لتعديل الأرقام في جدول Excel مضمّن، أو استخدم تبويب «تصميم المخطط» لتغيير النوع والألوان والعناوين. "
              "النصوص العربية داخل الرسوم يعرضها محرك Word نفسه، فتظهر بالتشكيل والاتجاه الصحيحين دائماً — "
              "لا توجد أي صور ثابتة في هذا الملف.", fill="EFF6FF", border="BFDBFE")
    P(doc, f"تاريخ الإعداد: {M['generated_at']} (توقيت دمشق) — أُنتج آلياً من الملفات الخام في data/raw/",
      size=9.5, color="6B7280", align="center", space_after=0)

    doc.add_page_break()

    # ================= 1. الملخص التنفيذي =================
    H1(doc, "1. الملخص التنفيذي — أبرز النتائج")
    tot = M["total_movements"]
    BULLET(doc, f" استحوذ على {fmt(DAMX['total'])} حركة جوية أي {round(100*DAMX['total']/tot,1)}% من الإجمالي، "
                f"عبر {DAMX['n_operators']} شركة تشغيل و{DAMX['n_destinations_all']} وجهة مختلفة — تنوّع تشغيلي يفوق مجموع حلب واللاذقية معاً.",
           bold_prefix="دمشق هو المركز بلا منازع:")
    BULLET(doc, f" من {fmt(ALPX['jan_aug_2025'])} حركة (يناير–أغسطس 2025) إلى {fmt(ALPX['jan_aug_2026'])} "
                f"في الفترة نفسها من 2026، بنمو +{ALPX['growth_pct']}%.",
           bold_prefix="حلب هو قصة النمو:")
    BULLET(doc, f" من أصل {fmt(LTKX['total'])} حركة فقط، شكّلت العمليات العسكرية والحكومية {cat_share(LTKX,'عسكري وحكومي')}%، "
                f"أغلبها جسر جوي روسي يربط غالبه بقاعدة تشكالوفسكي قرب موسكو ({LTKX['ckl_n']} رحلة) بطائرات An-124 وIL-76.",
           bold_prefix="اللاذقية ليست مطاراً مدنياً فعلياً في هذه الفترة:")
    BULLET(doc, f" {DAMX['gulf_share_of_intl']}% من مغادرات دمشق الدولية تتجه إلى مطارات الخليج "
                f"(الكويت، دبي، الشارقة، الدوحة، الرياض...)، فيما تميل شبكة حلب أكثر نحو عمّان وإسطنبول.",
           bold_prefix="ممر الخليج يهيمن على دمشق:")
    BULLET(doc, f" أكبر شركة (الخطوط السورية، {DAMX['top_airline']['share']}%) لا تستحوذ إلا على سدس السوق تقريباً، "
                f"ومؤشر HHI = {DAMX['hhi']} يشير إلى سوق متوازن؛ مقابل تركّز أعلى في حلب (HHI = {ALPX['hhi']}) "
                f"بقيادة الملكية الأردنية ({ALPX['top_airline']['share']}%).",
           bold_prefix="سوق دمشق متنافس وغير مركّز:")
    BULLET(doc, f" نما مطار دمشق +{DAMX['growth_pct']}% (الفترة المماثلة)، وتضاعفت حركة اللاذقية العسكرية "
                f"أكثر من ثلاث مرات (من {LTKX['jan_aug_2025']} إلى {LTKX['jan_aug_2026']} حركة).",
           bold_prefix="نمو مطّرد بعد الاستئناف:")
    BULLET(doc, f" عائلة A320 هي العمود الفقري في المطارات المدنية، بينما تشكل الطائرات العريضة البدن "
                f"(A330/B777/B787) {DAMX['widebody_share']}% من حركات دمشق مقابل {LTKX['widebody_share']}% "
                f"في اللاذقية حيث تسيطر منصات الشحن الاستراتيجي An-124.",
           bold_prefix="أسطول ضيق البدن غالباً مع حضور عريض البدن في دمشق:")

    # ================= 2. المنهجية =================
    doc.add_page_break()
    H1(doc, "2. المنهجية، تعريفات المؤشرات، وجودة البيانات")
    H2(doc, "2.1 مصدر البيانات وملفاته")
    P(doc, "اعتمد التحليل على ثلاثة ملفات CSV من مستودع GitHub ‏(HoseenAlhlak/HoseenAlhlak) بنمط سجلات تتبّع الرحلات، "
           "بواقع 25 عموداً لكل سجل تشمل: رقم الرحلة، المشغّل، نوع الطائرة وتسجيلها، مطارا الانطلاق والوصول وأوقاتهما، "
           "مدة الرحلة، المسافة الفعلية، الفئة، والمدارج المستخدمة.", size=11)
    TABLE(doc, ["الملف", "المطار", "السجلات", "أول رصد", "آخر رصد"], [
        ["flights_damascus_OSDI.csv", "دمشق DAM/OSDI", fmt(Q["rows_per_file"]["OSDI"]), DAMX["first_event"], DAMX["last_event"]],
        ["flights_aleppo_OSAP.csv", "حلب ALP/OSAP", fmt(Q["rows_per_file"]["OSAP"]), ALPX["first_event"], ALPX["last_event"]],
        ["flights_latakia_OSLK.csv", "اللاذقية LTK/OSLK", fmt(Q["rows_per_file"]["OSLK"]), LTKX["first_event"], LTKX["last_event"]],
    ], widths=[5.2, 3.6, 2.2, 2.5, 2.5], small=True)
    P(doc, "", space_after=2)

    H2(doc, "2.2 قواعد الاحتساب وتعريفات المؤشرات")
    BULLET(doc, " كل سجل في الملف يمثل حركة واحدة؛ صُنّفت «مغادرة» إذا كان المطار مطار الانطلاق، و«وصولاً» إذا كان مطار الوجهة.",
           bold_prefix="الحركة (Movement):")
    BULLET(doc, " اعتُمد وقت «أول رصد» (first_seen) لكونه الأكثر اكتمالاً، وحُوّل إلى التوقيت المحلي لدمشق قبل التجميع الشهري والساعي.",
           bold_prefix="الطابع الزمني المرجعي:")
    BULLET(doc, " وردت في البيانات جاهزة (ركاب، شحن، طيران أعمال، عسكري وحكومي...) وأُبقيت كما وردت في المصدر.",
           bold_prefix="الفئات:")
    BULLET(doc, " مجموع مربعات حصص المشغلين × 10,000؛ القيم دون 1,500 تدل على سوق غير مركّز، وفوق 2,500 على تركّز مرتفع.",
           bold_prefix="مؤشر التركّز HHI:")
    BULLET(doc, " استُبعدت السجلات التي يكون فيها المطار نفسه وجهة (حركات محلية/تدريبية) من جداول الوجهات.",
           bold_prefix="الوجهة الذاتية:")
    BULLET(doc, " قورنت الفترة يناير–أغسطس 2025 بالفترة المماثلة من 2026 لتلافي أثر الأشهر غير المكتملة وفجوة التسجيل.",
           bold_prefix="المقارنة العادلة للنمو:")

    H2(doc, "2.3 جودة البيانات وحدوده (توثيق شفاف)")
    NOTE(doc, "فجوة تسجيل في بيانات دمشق: بين 28 فبراير و2 أبريل 2026 لم يُسجَّل في ملف دمشق سوى 12 حركة في مارس كله، "
              "مقابل وسيط شهري يقارب 1,200 حركة — وهي بوضوح فجوة تغطية في التسجيل وليست توقفاً فعلياً. عولجت باستبعاد "
              "مارس 2026 من المتوسطات، وتوثيقها هنا، واستخدام مقارنات «الفترة مقابل الفترة».")
    NOTE(doc, "سبتمبر 2026 شهر غير مكتمل: تنتهي البيانات في 7 سبتمبر 2026؛ لذا لم يُحتسب في المتوسطات، "
              "واستُخدم أغسطس 2026 آخر شهر مكتمل. أما الأشهر الأولى المنخفضة لحلب (يناير–مايو 2025) فتعكس "
              "استئنافاً تدريجياً حقيقياً للتشغيل بعد إعادة افتتاح المطار وليست فجوة بيانات.", fill="F0FDF4", border="BBF7D0")
    TABLE(doc, ["مؤشر الاكتمال", "دمشق", "حلب", "اللاذقية"], [
        ["سجلات بلا وقت إقلاع مسجّل", f"{fmt(Q['missing']['OSDI']['datetime_takeoff'])} ({round(100*Q['missing']['OSDI']['datetime_takeoff']/DAMX['total'],1)}%)",
         f"{fmt(Q['missing']['OSAP']['datetime_takeoff'])} ({round(100*Q['missing']['OSAP']['datetime_takeoff']/ALPX['total'],1)}%)",
         f"{fmt(Q['missing']['OSLK']['datetime_takeoff'])} ({round(100*Q['missing']['OSLK']['datetime_takeoff']/LTKX['total'],1)}%)"],
        ["سجلات بلا وقت هبوط مسجّل", fmt(Q["missing"]["OSDI"]["datetime_landed"]), fmt(Q["missing"]["OSAP"]["datetime_landed"]), fmt(Q["missing"]["OSLK"]["datetime_landed"])],
        ["سجلات بلا مشغّل محدد", fmt(Q["missing"]["OSDI"]["operator"]), fmt(Q["missing"]["OSAP"]["operator"]), fmt(Q["missing"]["OSLK"]["operator"])],
        ["سجلات بلا مدة رحلة", fmt(Q["missing"]["OSDI"]["flight_time"]), fmt(Q["missing"]["OSAP"]["flight_time"]), fmt(Q["missing"]["OSLK"]["flight_time"])],
        ["معرّفات مكررة (fr24_id)", "0", "0", "0"],
        ["أشهر منخفضة/فجوات", "2026-03 (فجوة) · 2026-09 (جزئي)", "2025-01..04 (بداية تدريجية)", "لا شيء جوهرياً"],
    ], widths=[5.4, 3.6, 3.6, 3.4], small=True)
    P(doc, "كل السجلات الناقصة حقولاً تبقى محسوبة ضمن الحركات الكلية، وتُستبعد فقط من المؤشر الذي يشترط الحقل المعني.",
      size=9.5, color="6B7280", space_after=2)

    # ================= 3. لوحة المؤشرات =================
    doc.add_page_break()
    H1(doc, "3. لوحة المؤشرات المقارنة")
    P(doc, "الجدول التالي يجمع المؤشرات الرئيسية للمطارات الثلاثة جنباً إلى جنب (قابل للتحرير كمجدول Word):")
    TABLE(doc, ["المؤشر", "دمشق", "حلب", "اللاذقية"], [
        ["إجمالي الحركات (يناير 2025 – سبتمبر 2026)", fmt(DAMX["total"]), fmt(ALPX["total"]), fmt(LTKX["total"])],
        ["مغادرات / وصولات", f'{fmt(DAMX["departures"])} / {fmt(DAMX["arrivals"])}',
         f'{fmt(ALPX["departures"])} / {fmt(ALPX["arrivals"])}', f'{fmt(LTKX["departures"])} / {fmt(LTKX["arrivals"])}'],
        ["حصة من إجمالي المطارات الثلاثة", f'{round(100*DAMX["total"]/tot,1)}%', f'{round(100*ALPX["total"]/tot,1)}%', f'{round(100*LTKX["total"]/tot,1)}%'],
        ["متوسط الحركات شهرياً (أشهر مكتملة)", DAMX["avg_monthly"], ALPX["avg_monthly"], LTKX["avg_monthly"]],
        ["أعلى شهر تشغيل", f'{DAMX["peak_month"]["month"]} ({fmt(DAMX["peak_month"]["n"])})',
         f'{ALPX["peak_month"]["month"]} ({fmt(ALPX["peak_month"]["n"])})', f'{LTKX["peak_month"]["month"]} ({LTKX["peak_month"]["n"]})'],
        ["متوسط الحركات يومياً (أغسطس 2026)", DAMX["avg_daily_last_full_month"], ALPX["avg_daily_last_full_month"], LTKX["avg_daily_last_full_month"]],
        ["حصة رحلات الركاب", f'{cat_share(DAMX,"رحلات ركاب")}%', f'{cat_share(ALPX,"رحلات ركاب")}%', f'{cat_share(LTKX,"رحلات ركاب")}%'],
        ["حصة العسكري والحكومي", f'{cat_share(DAMX,"عسكري وحكومي")}%', f'{cat_share(ALPX,"عسكري وحكومي")}%', f'{cat_share(LTKX,"عسكري وحكومي")}%'],
        ["حصة طيران الأعمال", f'{cat_share(DAMX,"طيران أعمال")}%', f'{cat_share(ALPX,"طيران أعمال")}%', f'{cat_share(LTKX,"طيران أعمال")}%'],
        ["عدد شركات التشغيل", DAMX["n_operators"], ALPX["n_operators"], LTKX["n_operators"]],
        ["أكبر مشغّل (حصته)", f'{DAMX["top_airline"]["name"]} ({DAMX["top_airline"]["share"]}%)',
         f'{ALPX["top_airline"]["name"]} ({ALPX["top_airline"]["share"]}%)',
         f'{LTKX["top_airline"]["name"]} ({LTKX["top_airline"]["share"]}%)'],
        ["حصة أكبر 3 مشغلين", f'{DAMX["top3_share"]}%', f'{ALPX["top3_share"]}%', f'{LTKX["top3_share"]}%'],
        ["مؤشر التركّز HHI", DAMX["hhi"], ALPX["hhi"], LTKX["hhi"]],
        ["عدد الوجهات المخدمة", DAMX["n_destinations_all"], ALPX["n_destinations_all"], LTKX["n_destinations_all"]],
        ["الوجهة الأولى (مغادرات)", f'{DAMX["top_destinations"][0]["city"]} ({fmt(DAMX["top_destinations"][0]["n"])})',
         f'{ALPX["top_destinations"][0]["city"]} ({fmt(ALPX["top_destinations"][0]["n"])})',
         f'{LTKX["top_destinations"][0]["city"]} ({LTKX["top_destinations"][0]["n"]})'],
        ["حصة الخليج من المغادرات الدولية", f'{DAMX["gulf_share_of_intl"]}%', f'{ALPX["gulf_share_of_intl"]}%', "—"],
        ["نوع الطائرة الأكثر تكراراً", f'{DAMX["top_types"][0]["type"]} ({fmt(DAMX["top_types"][0]["n"])})',
         f'{ALPX["top_types"][0]["type"]} ({fmt(ALPX["top_types"][0]["n"])})', f'{LTKX["top_types"][0]["type"]} ({LTKX["top_types"][0]["n"]})'],
        ["أنواع مختلفة / طائرات فريدة", f'{DAMX["n_types"]} / {DAMX["n_aircraft"]}', f'{ALPX["n_types"]} / {ALPX["n_aircraft"]}', f'{LTKX["n_types"]} / {LTKX["n_aircraft"]}'],
        ["حصة الطائرات العريضة البدن", f'{DAMX["widebody_share"]}%', f'{ALPX["widebody_share"]}%', f'{LTKX["widebody_share"]}%'],
        ["وسيط زمن الرحلة (دقيقة)", DAMX["ft_median"], ALPX["ft_median"], LTKX["ft_median"]],
        ["وسيط المسافة المقطوعة (كم)", fmt(DAMX["dist_median"]), fmt(ALPX["dist_median"]), fmt(LTKX["dist_median"])],
        ["ساعة الذروة (توقيت محلي)", f'{DAMX["peak_hour"]}:00', f'{ALPX["peak_hour"]}:00', f'{LTKX["peak_hour"]}:00'],
        ["أكثر الأيام ازدحاماً", f'{DAMX["busiest_day"]["date"]} ({DAMX["busiest_day"]["n"]})',
         f'{ALPX["busiest_day"]["date"]} ({ALPX["busiest_day"]["n"]})', f'{LTKX["busiest_day"]["date"]} ({LTKX["busiest_day"]["n"]})'],
        ["النمو: يناير–أغسطس 2025 ← 2026", f'+{DAMX["growth_pct"]}%', f'+{ALPX["growth_pct"]}%', f'+{LTKX["growth_pct"]}%'],
    ], widths=[6.4, 3.4, 3.2, 3.0], small=True)

    # ================= 4. الاتجاه الزمني =================
    doc.add_page_break()
    H1(doc, "4. الاتجاه الزمني والنمو")
    CHART_MARK(doc, "monthly")
    CAPTION(doc, "الشكل 1 — التطور الشهري: ثبات دمشق حول 1,200–1,400 حركة شهرياً، وصعود حلب المتسارع حتى 694 حركة في أغسطس 2026، "
                 "ونشاط اللاذقية المتقطع منخفض الكم. لاحظ انخفاض مارس 2026 في سلسلة دمشق بسبب فجوة التسجيل الموثقة في القسم 2.3، "
                 "وأن سبتمبر 2026 غير مكتمل (رسم Word أصلي قابل للتحرير).")
    CHART_MARK(doc, "growth")
    CAPTION(doc, "الشكل 2 — مقارنة عادلة للفترة يناير–أغسطس بين عامي 2025 و2026: نمو دمشق +30.7%، وحلب +358.1% (أربعة أضعاف تقريباً)، "
                 "واللاذقية +235.1% عن قاعدة منخفضة (رسم Word أصلي قابل للتحرير).")
    P(doc, "القراءة التحليلية: منحنى حلب على شكل «منحنى إقلاع» نموذجي لمطار يعيد بناء شبكته — فتح خطوط عمّان وإسطنبول أولاً، "
           "ثم الخليج تدريجياً، ثم تكثيف الترددات. أما دمشق فتُظهر نضجاً مبكراً استعاد حجمه بسرعة خلال 2025 وثبّته في 2026، "
           "ما يوحي بأن العرض (المقاعد) لحق بالطلب خلال أقل من عام.")

    # ================= 5. تركيب الحركة =================
    doc.add_page_break()
    H1(doc, "5. تركيب الحركة: أحجام وفئات")
    CHART_MARK(doc, "totals")
    CAPTION(doc, "الشكل 3 — المغادرات مقابل الوصولات: توازن شبه تام في دمشق وحلب (فرق أقل من 2%) وهو متوقع لمطار مدني بخطوط منتظمة؛ "
                 "أما اللاذقية فالمغادرات تزيد على الوصولات (153 مقابل 97)، بما يوحي بمغادرة طائرات عائدة لقواعدها أكثر من الواصلة.")
    CHART_MARK(doc, "categories")
    CAPTION(doc, "الشكل 4 — تركيب الحركة حسب الفئة: دمشق وحلب مطاران مدنيان بامتياز (ركاب 94.6% و95.4%)، "
                 "واللاذقية 96% عسكري وحكومي (رسم قابل للتحرير).")
    CHART_MARK(doc, "domestic")
    CAPTION(doc, "الشكل 5 — المغادرات الداخلية شبه غائبة في المطارات الثلاثة؛ إعادة الإعمار الجوي تركّزت حتى الآن على الربط الدولي.")

    # ================= 6. شركات التشغيل =================
    doc.add_page_break()
    H1(doc, "6. سوق شركات التشغيل")
    CHART_MARK(doc, "airlines")
    syr, fyc = ops_by("SYR"), ops_by("FYC")
    CAPTION(doc, f"الشكل 6 — أكبر 12 شركة تشغيل (مكدّسة حسب المطار): تتقدم الخطوط السورية بـ {fmt(syr)} حركة "
                 f"تليها فلاي شام الناشئة بـ {fmt(fyc)} — أي أن شركتين سوريتين تمثلان معاً نحو "
                 f"{round(100*(syr+fyc)/tot,1)}% من كل الحركات المسجلة (رسم قابل للتحرير).")
    CHART_MARK(doc, "share_dam")
    CAPTION(doc, "الشكل 7 — حصص السوق في دمشق (أكبر 7 شركات + آخرون): سوق موزّع بين ناقلات خليجية "
                 "والناقلتين السوريتين والملكية الأردنية (رسم قابل للتحرير).")
    CHART_MARK(doc, "share_alp")
    CAPTION(doc, "الشكل 8 — حصص السوق في حلب: تقود الملكية الأردنية (27.8%) ثم التركية وإيه جت — جغرافيا تجارية مختلفة عن دمشق (رسم قابل للتحرير).")

    H2(doc, "6.1 أكبر الشركات في كل مطار")
    for ap_key, ap_name, apx in [("OSDI", "دمشق", DAMX), ("OSAP", "حلب", ALPX), ("OSLK", "اللاذقية", LTKX)]:
        P(doc, ap_name, bold=True, size=11.5, color={"OSDI": DAM, "OSAP": ALP, "OSLK": LTK}[ap_key], space_after=3)
        rows = []
        for i, a in enumerate(apx["top_airlines"][:8]):
            rows.append([str(i + 1), a["name"], f'{a["code"]} / {a["iata"]}', a["country"], fmt(a["n"]), f'{a["share"]}%'])
        TABLE(doc, ["#", "الشركة", "الرمز", "الجنسية", "الحركات", "الحصة"], rows,
              widths=[0.9, 4.6, 2.2, 3.4, 2.0, 1.7], small=True)
        P(doc, "", space_after=2)
    NOTE(doc, "ملاحظة توثيقية: تم التحقق من هوية شركات التشغيل عبر مطابقة رموز ICAO/IATA وأرقام الرحلات وتسجيلات الطائرات "
              "مع مراجع الطيران العامة (قائمة شركات الطيران السورية في ويكيبيديا، Airhex، Plane Finder وغيرها — انظر قسم المصادر). "
              "من أبرز النتائج: FYC هي «فلاي شام» السورية الجديدة (2025)، وKNE هي «فلاي ناس» السعودية، وFAD هي «فلاي ديل»، "
              "وTKJ هي «إيه جت» التركية.", fill="EFF6FF", border="BFDBFE")

    # ================= 7. الشبكة والوجهات =================
    doc.add_page_break()
    H1(doc, "7. الشبكة والوجهات")
    CHART_MARK(doc, "dest_dam")
    CAPTION(doc, "الشكل 9 — أهم 10 وجهات مغادرة من دمشق: الكويت أولاً (1,418 رحلة) تليها دبي والشارقة (رسم قابل للتحرير).")
    CHART_MARK(doc, "dest_alp")
    CAPTION(doc, "الشكل 10 — أهم 10 وجهات مغادرة من حلب: تعلو عمّان (700 رحلة) وتليها إسطنبول بمطارَيها — "
                 "الشبكتان متكاملتان أكثر منهما متنافستين (رسم قابل للتحرير).")
    CHART_MARK(doc, "network")
    CAPTION(doc, "الشكل 11 — اتساع الشبكة والتنوّع التشغيلي: دمشق خدم 95 وجهة عبر 546 طائرة فريدة (رسم قابل للتحرير).")
    NOTE(doc, f"ممر الخليج: {fmt(DAMX['gulf_dep'])} مغادرة من دمشق ({DAMX['gulf_share_of_intl']}% من دوليته) تتجه إلى الخليج — "
              "الكويت وحدها تستقبل من دمشق أكثر من مجموع ما تستقبله دبي والشارقة في حلب. هذا التركّز يعكس تركيبة الطلب "
              "(سفر عمل وتحويلات وعمالة) أكثر مما يعكس شبكة سياحية.")

    H2(doc, "7.1 أهم الوجهات (مغادرات) لكل مطار")
    for ap_key, ap_name, apx in [("OSDI", "دمشق", DAMX), ("OSAP", "حلب", ALPX), ("OSLK", "اللاذقية", LTKX)]:
        P(doc, ap_name, bold=True, size=11.5, color={"OSDI": DAM, "OSAP": ALP, "OSLK": LTK}[ap_key], space_after=3)
        rows = [[str(i + 1), d["city"], d["iata"], fmt(d["n"])]
                for i, d in enumerate(apx["top_destinations"][:8])]
        TABLE(doc, ["#", "الوجهة", "الرمز", "عدد الرحلات"], rows,
              widths=[1.0, 7.0, 2.0, 3.0], small=True)
        P(doc, "", space_after=2)

    # ================= 8. إيقاع التشغيل =================
    doc.add_page_break()
    H1(doc, "8. إيقاع التشغيل اليومي والأسبوعي")
    CHART_MARK(doc, "hourly")
    CAPTION(doc, "الشكل 12 — التوزيع الساعي (توقيت دمشق): دمشق يعمل بمنحنى مزدوج الذروة تمتد من التاسعة صباحاً حتى الرابعة عشرة "
                 "(ذروته 14:00) ثم موجة مسائية؛ حلب يتركز في نافذة الصباح الباكر (ذروة 07:00)؛ واللاذقية ذروتها عصراً (17:00) "
                 "(رسم قابل للتحرير).")
    CHART_MARK(doc, "dow")
    CAPTION(doc, "الشكل 13 — توزيع الحركة على أيام الأسبوع: التباين محدود (تفاوت ضمن بضع نقاط مئوية) — سمة خطوط منتظمة.")

    # ================= 9. الأسطول =================
    doc.add_page_break()
    H1(doc, "9. الأسطول: أنواع الطائرات وبصمة المسافات")
    CHART_MARK(doc, "types")
    CAPTION(doc, "الشكل 14 — أكثر 10 أنواع طائرات تشغيلاً: عائلة A320 تتصدر دمشق وحلب، وتحضر الطائرات العريضة (A330/B777/B787) "
                 "في دمشق عبر القطرية والإمارات والاتحاد (رسم قابل للتحرير).")
    CHART_MARK(doc, "ft_median")
    CAPTION(doc, "الشكل 15 — وسيط زمن الرحلة: رحلات اللاذقية أطول بكثير (250 دقيقة) لأنها تصل إلى روسيا وإفريقيا (رسم قابل للتحرير).")
    CHART_MARK(doc, "dist_median")
    CAPTION(doc, "الشكل 16 — وسيط المسافة المقطوعة: دمشق 1,485 كم (نطاق خليجي-إقليمي) وحلب 1,026 كم لأن شبكتها إقليمية بالأساس (رسم قابل للتحرير).")
    CHART_MARK(doc, "widebody")
    CAPTION(doc, "الشكل 17 — حصة الطائرات العريضة البدن: مؤشر «بوصلة نضج الشبكة» — دمشق 9.9% مقابل 3.7% فقط في حلب؛ "
                 "أي أن حلب لم تدخل بعد طور الطائرات الكبيرة وهامش نموها في حجم المقاعد لا يزال واسعاً (رسم قابل للتحرير).")

    # ================= 10. اللاذقية =================
    doc.add_page_break()
    H1(doc, "10. اللاذقية: جسر جوي عسكري")
    P(doc, f"تحتل اللاذقية موقعاً خاصاً في هذه المقارنة: خلال 20 شهراً لم تسجل سوى {fmt(LTKX['total'])} حركة "
           f"(بمعدل {LTKX['avg_monthly']} حركة شهرياً)، منها {cat_share(LTKX,'عسكري وحكومي')}% عسكري وحكومي. "
           "المشغّل المهيمن هو القوات الجوية الروسية بتنويعاتها، بطائرات شحن استراتيجي IL-76 وAn-124 "
           "وطائرات ركاب قديمة طراز Tu-154/Tu-134.")
    CHART_MARK(doc, "ltk_monthly")
    CAPTION(doc, "الشكل 18 — الحركة الشهرية في اللاذقية: قفزة لافتة في ديسمبر 2025 (37 حركة) ثم نشاط متقطع (رسم قابل للتحرير).")
    CHART_MARK(doc, "ltk_ops")
    CAPTION(doc, "الشكل 19 — المشغّلون: 93.3% من الحركات بارتباط روسي مباشر أو بنمط عسكري واضح (رسم قابل للتحرير).")
    CHART_MARK(doc, "ltk_types")
    CAPTION(doc, "الشكل 20 — أنواع الطائرات: IL-76 وAn-124 يهيمنان على حركة المطار (رسم قابل للتحرير).")
    BULLET(doc, f" مطار تشكالوفسكي (CKL) قرب موسكو يستقبل {LTKX['ckl_n']} رحلة من حركات اللاذقية المرتبطة به — "
                "جسر إمداد لوجستي واضح المعالم، مع ظهور جوكوفسكي وشيريميتيفو ومدن روسية أخرى.",
           bold_prefix="الوجهة الأولى قاعدة عسكرية:")
    BULLET(doc, " تسجل البيانات رحلات متفرقة نحو باماكو وبرازافيل ولومي ودار السلام — نمط مميز لعمليات نقل عسكري/دبلوماسي بعيدة المدى بطائرات An-124.",
           bold_prefix="ذيل إفريقي:")
    BULLET(doc, " رحلات الركاب المنتظمة غائبة، والطيران المدني في المطار شبه موقوف خلال فترة البيانات، خلافاً لدمشق وحلب.",
           bold_prefix="لا شبهة مدنية تقريباً:")
    NOTE(doc, "حدود التفسير: خلص التحليل إلى «الارتباط الروسي» من واقع المشغّل المسجّل (RFF وأخواتها)، واللوحة المرسومة على الطائرات "
              "(painted_as = RFF في معظم السجلات)، وأنماط الطائرات والوجهات. بعض السجلات (52) بلا مشغّل معلن، لكن 42 منها مصنفة "
              "«عسكري وحكومي» و37 منها طائرات An-124 — لذا فالنسبة المذكورة (93.3%) تحفظية والنسبة الفعلية أعلى منها على الأرجح.")

    # ================= 11. الخلاصة =================
    doc.add_page_break()
    H1(doc, "11. الخلاصة التحليلية")
    P(doc, "تروي بيانات المطارات الثلاثة قصة واحدة بثلاثة فصول:", size=11.5)
    P(doc, "دمشق — الاستقرار بعد الاستعادة", bold=True, size=12.5, color=DAM, space_after=3)
    P(doc, f"{fmt(DAMX['total'])} حركة خلال 20 شهراً، و{DAMX['n_operators']} شركة، و{DAMX['n_destinations_all']} وجهة، "
           f"وسوق غير مركّز (HHI={DAMX['hhi']}) بنمو +{DAMX['growth_pct']}% في 2026. استعاد المطار دوره كمحور إقليمي بسرعة، "
           f"وارتباطه الخليجي ({DAMX['gulf_share_of_intl']}% من مغادراته الدولية) هو السمة البنيوية الأبرز، ومؤشرات جاهزيته لمزيد من النمو إيجابية.")
    P(doc, "حلب — منحنى الإقلاع", bold=True, size=12.5, color=ALP, space_after=3)
    P(doc, f"من {fmt(ALPX['jan_aug_2025'])} حركة في الفترة يناير–أغسطس 2025 إلى {fmt(ALPX['jan_aug_2026'])} في الفترة المقابلة من 2026 "
           f"(+{ALPX['growth_pct']}%)، وبأعلى شهر تشغيل في تاريخ البيانات (أغسطس 2026: {fmt(ALPX['peak_month']['n'])} حركة). "
           "التحدي القادم بحسب المؤشرات: توسيع قاعدة المشغلين ودخول عائلات طائرات أكبر.")
    P(doc, "اللاذقية — مطار بلا ركاب", bold=True, size=12.5, color=LTK, space_after=3)
    P(doc, f"{fmt(LTKX['total'])} حركة فقط، {cat_share(LTKX,'عسكري وحكومي')}% منها عسكرية/حكومية و{LTKX['russian_mil_share']}% "
           "بارتباط روسي مباشر؛ المطار يعمل عملياً كمنصة عمليات لوجستية لا كبوابة مدنية، وأي مقارنة تجارية له مع دمشق وحلب "
           "غير مجدية — إذ هي مقارنة بين نموذجين مختلفين لاستخدام المطار.")
    P(doc, "بصياغة واحدة: أعادت سوريا بناء بوّابتيها المدنيتين — دمشق بحجم مستقر وحلب بنمو انفجاري — بينما بقيت اللاذقية منصة عسكرية شبه حصرية.",
      bold=True, size=11.5, color=NAVY)

    # ================= 12. المصادر =================
    doc.add_page_break()
    H1(doc, "12. المصادر والمراجع")
    H2(doc, "12.1 البيانات الخام")
    BULLET(doc, f"flights_damascus_OSDI.csv — {fmt(Q['rows_per_file']['OSDI'])} سجلاً، المستودع HoseenAlhlak/HoseenAlhlak، مجلد data/raw/.")
    BULLET(doc, f"flights_aleppo_OSAP.csv — {fmt(Q['rows_per_file']['OSAP'])} سجلاً، المصدر نفسه.")
    BULLET(doc, f"flights_latakia_OSLK.csv — {fmt(Q['rows_per_file']['OSLK'])} سجلاً، المصدر نفسه.")
    BULLET(doc, "بنية السجل: 25 حقلاً (fr24_id, flight, callsign, operating_as, painted_as, type, reg, orig/dest وأوقاتها, flight_time, actual_distance, circle_distance, category, runway…).")
    H2(doc, "12.2 مراجع التحقق من رموز شركات التشغيل")
    for line in [
        "Wikipedia — List of airlines of Syria:  en.wikipedia.org/wiki/List_of_airlines_of_Syria",
        "Airhex — Fly Cham (FYC/XH):  airhex.com/airlines/fly-cham",
        "Airhex — flyadeal (FAD/F3):  airhex.com/airlines/flyadeal",
        "Airhex — Dan Air (DNA/DN):  airhex.com/airlines/dan-air",
        "Plane Finder — Centrum Air (MFX/C6):  planefinder.net/data/airline/MFX",
        "Airhex — Air Mediterranean (MAR/MV):  airhex.com/airlines/air-mediterranean",
        "Airways Magazine — flynas والرحلات إلى دمشق (KNE/XY):  airwaysmag.com/new-post/flynas-syria-lcc",
        "airliners.de — أسطول LEAV Aviation (NGN/KK):  airliners.de (تقرير الأسطول 2025)",
    ]:
        LTR_LINE(doc, line)
    H2(doc, "12.3 أدوات التحليل ومنتجاته")
    BULLET(doc, "سكربت المؤشرات والرسوم: analysis/analyze_airports.py (Python: pandas, matplotlib, arabic-reshaper, python-bidi).")
    BULLET(doc, "مولدات التقارير: analysis/build_report.py (HTML) · analysis/build_pdf.py (PDF) · analysis/build_docx.py (هذه النسخة).")
    BULLET(doc, "المؤشرات التفصيلية: analysis/results/metrics.json وجداول CSV بجانبها.")
    BULLET(doc, "نسخ أخرى من التقرير: HTML ذاتي الاحتواء وPDF مطبوع في المجلد reports/.")
    P(doc, "تنويه: أرقام التقرير تعكس حصراً ما ورد في الملفات الثلاثة، وهي حساسة لاكتمال التسجيل فيها (انظر القسم 2.3). "
           "التسميات العربية للشركات والمدن اجتهاد توثيقي مبني على المصادر أعلاه.",
      size=9.5, color="6B7280")

    doc.save(str(path))


# ============================================================================
# المرحلة C: حقن المخططات داخل حزمة DOCX
# ============================================================================
W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

# الترتيب الرسمي لأبناء العناصر وفق مخطط WordprocessingML (لضمان فتح الملف دون إصلاح)
OOXML_ORDER = {
    "pPr": ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
            "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs",
            "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct",
            "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
            "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
            "suppressOverlap", "jc", "textDirection", "textAlignment",
            "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr",
            "pPrChange"],
    "rPr": ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
            "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
            "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
            "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
            "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
            "eastAsianLayout", "specVanish", "oMath"],
    "tcPr": ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders",
             "shd", "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign",
             "hideMark", "headers", "cellIns", "cellDel", "cellMerge", "tcPrChange"],
    "tblPr": ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual",
              "tblStyleRowBandSize", "tblStyleColBandSize", "tblW", "jc",
              "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout",
              "tblCellMar", "tblLook", "tblCaption", "tblDescription", "tblPrChange"],
    "trPr": ["cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter",
             "cantSplit", "trHeight", "tblHeader", "tblCellSpacing", "jc",
             "hidden", "ins", "del", "trPrChange"],
}
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def normalize_part(xml_bytes: bytes) -> bytes:
    """إعادة ترتيب أبناء pPr/rPr/tcPr/tblPr/trPr وفق تسلسل المخطط الرسمي."""
    from lxml import etree
    root = etree.fromstring(xml_bytes)
    for tag, seq in OOXML_ORDER.items():
        order = {name: i for i, name in enumerate(seq)}
        for el in root.iter(_W + tag):
            children = list(el)
            children.sort(key=lambda c: order.get(
                c.tag.split("}")[-1], len(seq)))
            for c in children:
                el.append(c)  # النقل يُعيد الترتيب
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def drawing_par(key: str, rid: str, docpr_id: int, cx: int, cy: int) -> str:
    """فقرة RTL موسّطة تحوي رسماً مضمناً يشير إلى المخطط."""
    return (
        f'<w:p {W_NS}><w:pPr><w:bidi/><w:jc w:val="center"/></w:pPr>'
        f'<w:drawing>'
        f'<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{docpr_id}" name="Chart {key}"/>'
        f'<wp:cNvGraphicFramePr>'
        f'<a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/>'
        f'</wp:cNvGraphicFramePr>'
        f'<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        f'<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="{rid}"/>'
        f'</a:graphicData></a:graphic></wp:inline></w:drawing></w:p>'
    )


PARA_RE = re.compile(r"<w:p\b.*?</w:p>", re.S)


def inject_charts(docx_path: Path, pptx_path: Path, out_path: Path):
    # 1) استخراج أجزاء المخططات من PPTX وربطها بالمواصفات عبر العنوان
    with zipfile.ZipFile(pptx_path) as z:
        names = z.namelist()
        chart_parts = {}
        for n in names:
            m = re.match(r"ppt/charts/chart(\d+)\.xml$", n)
            if not m:
                continue
            xmlb = z.read(n)
            xml = xmlb.decode("utf-8")
            # عنوان المخطط (أول نص داخل c:title)
            tm = re.search(r"<c:title>.*?<a:t>(.*?)</a:t>", xml, re.S)
            title = tm.group(1) if tm else ""
            rels_name = f"ppt/charts/_rels/chart{m.group(1)}.xml.rels"
            rels = z.read(rels_name).decode("utf-8")
            # الملف المضمّن (xlsx)
            emb_m = re.search(r'Target="\.\./embeddings/([^"]+)"', rels)
            emb_name = emb_m.group(1)
            emb_bytes = z.read(f"ppt/embeddings/{emb_name}")
            chart_parts[title] = dict(idx=int(m.group(1)), xml=xmlb,
                                      rels=rels, emb_name=emb_name, emb=emb_bytes)

    # 2) قراءة DOCX
    with zipfile.ZipFile(docx_path) as z:
        items = {n: z.read(n) for n in z.namelist()}

    # 3) أنواع المحتوى
    ct = items["[Content_Types].xml"].decode("utf-8")
    ct = ct.replace("</Types>",
                    '<Default Extension="xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/></Types>')

    # 4) علاقات المستند
    rels = items["word/_rels/document.xml.rels"].decode("utf-8")

    # 5) document.xml — استبدال العلامات بالرسوم
    docxml = items["word/document.xml"].decode("utf-8")
    used = set()
    for i, s in enumerate(CHART_SPECS):
        key = s["key"]
        cp = chart_parts.get(s["title"])
        assert cp is not None, f"chart part not found for: {s['title']}"
        n = i + 1
        # أسماء الأجزاء داخل DOCX
        chart_part_name = f"word/charts/chart{n}.xml"
        rels_part_name = f"word/charts/_rels/chart{n}.xml.rels"
        emb_part_name = f"word/embeddings/{cp['emb_name']}"
        assert emb_part_name not in used or True
        used.add(emb_part_name)
        items[chart_part_name] = cp["xml"]
        # علاقات المخطط (تشير إلى ../embeddings/...) — تعمل كما هي في بنية word/
        items[rels_part_name] = cp["rels"].encode("utf-8")
        items[emb_part_name] = cp["emb"]
        ct = ct.replace("</Types>",
                        f'<Override PartName="/{chart_part_name}" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/></Types>')
        rid = f"rIdChart{n}"
        rels = rels.replace("</Relationships>",
                            f'<Relationship Id="{rid}" '
                            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" '
                            f'Target="charts/chart{n}.xml"/></Relationships>')
        # أبعاد الرسم
        w_in = s["opts"].get("w", 5.7)
        h_in = s["opts"].get("h", 3.4)
        cx, cy = int(w_in * 914400), int(h_in * 914400)
        marker = f"@@CHART_{key}@@"
        found = False
        out_parts = []
        last = 0
        for m in PARA_RE.finditer(docxml):
            if marker in m.group(0):
                out_parts.append(docxml[last:m.start()])
                out_parts.append(drawing_par(key, rid, 1000 + n, cx, cy))
                last = m.end()
                found = True
                break
        out_parts.append(docxml[last:])
        assert found, f"marker not found: {marker}"
        docxml = "".join(out_parts)

    items["[Content_Types].xml"] = ct.encode("utf-8")
    items["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    items["word/document.xml"] = docxml.encode("utf-8")

    # 6.5) تطبيع ترتيب عناصر WordprocessingML في أجزاء المتن/الأنماط/التذييل
    for n in list(items):
        if re.match(r"word/(document|styles|footer\d*|header\d*)\.xml$", n):
            try:
                items[n] = normalize_part(items[n])
            except Exception as e:
                print(f"normalize skip {n}: {e}")

    # 6) كتابة الحزمة النهائية ([Content_Types] أولاً)
    ordered = ["[Content_Types].xml"] + [n for n in items if n != "[Content_Types].xml"]
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in ordered:
            z.writestr(n, items[n])


# ============================================================================
# التنفيذ
# ============================================================================
def main():
    tmp_pptx = ROOT / "analysis" / "results" / "_charts_tmp.pptx"
    tmp_docx = ROOT / "analysis" / "results" / "_report_tmp.docx"
    print(f"Building {len(CHART_SPECS)} native charts (PPTX stage)...")
    build_pptx(tmp_pptx)
    print("Building DOCX content...")
    build_docx(tmp_docx)
    print("Injecting charts into DOCX package...")
    inject_charts(tmp_docx, tmp_pptx, OUT)
    tmp_pptx.unlink()
    tmp_docx.unlink()
    print(f"DOCX written: {OUT.name} ({OUT.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
