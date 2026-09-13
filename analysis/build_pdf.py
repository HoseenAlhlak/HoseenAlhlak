#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مولد نسخة PDF من التقرير العربي المقارن.
يعتمد fpdf2 مع محرك تشكيل النص (HarfBuzz) لدعم العربية RTL.
المدخلات: analysis/results/metrics.json + reports/charts/*.png
الناتج:  reports/تقرير_مطارات_سوريا_المقارن.pdf
"""

import io
import json
from pathlib import Path

from fpdf import FPDF
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "analysis" / "results"
CHARTS = ROOT / "reports" / "charts"
FONTS = ROOT / "assets" / "fonts"
OUT = ROOT / "reports" / "تقرير_مطارات_سوريا_المقارن.pdf"

PAGE_W = 210
MARGIN = 14
CONTENT_W = PAGE_W - 2 * MARGIN

DAM, ALP, LTK = "#1e5aa8", "#0e8a5f", "#c2571a"


class ReportPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.add_font("Amiri", "", str(FONTS / "Amiri-Regular.ttf"))
        self.add_font("Amiri", "B", str(FONTS / "Amiri-Bold.ttf"))
        self.add_font("Cairo", "", str(FONTS / "Cairo.ttf"))
        self.set_auto_page_break(auto=True, margin=16)
        self.set_text_shaping(True)
        self._in_footer = False

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Cairo", "", 9)
        self.set_text_color(120, 128, 140)
        self.cell(0, 8, "التقرير المقارن — حركة الطيران في مطارات سوريا الثلاثة", align="L")
        self.set_draw_color(229, 231, 235)
        self.line(MARGIN, 12, PAGE_W - MARGIN, 12)
        self.ln(12)

    def footer(self):
        self._in_footer = True
        self.set_y(-12)
        self.set_font("Cairo", "", 9)
        self.set_text_color(120, 128, 140)
        self.cell(0, 8, f"صفحة {self.page_no()} من {{nb}}", align="C")
        self._in_footer = False


def img_bytes_jpeg(png_path: Path, quality: int = 88, target_w: int = 1500) -> bytes:
    im = Image.open(png_path).convert("RGB")
    if im.width > target_w:
        im = im.resize((target_w, int(im.height * target_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def h1(pdf, txt, color=(15, 42, 92)):
    pdf.set_font("Cairo", "", 17)
    pdf.set_text_color(*color)
    pdf.multi_cell(CONTENT_W, 11, txt, align="R")
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.5)
    y = pdf.get_y() + 1
    pdf.line(PAGE_W - MARGIN - 40, y, PAGE_W - MARGIN, y)
    pdf.ln(4)


def h2(pdf, txt, color=(31, 41, 55)):
    pdf.set_font("Cairo", "", 13)
    pdf.set_text_color(*color)
    pdf.multi_cell(CONTENT_W, 9, txt, align="R")
    pdf.ln(1.5)


def para(pdf, txt, size=11, bold=False, color=(17, 24, 39), lh=7.2):
    pdf.set_font("Amiri", "B" if bold else "", size)
    pdf.set_text_color(*color)
    pdf.multi_cell(CONTENT_W, lh, txt, align="R")


def bullet(pdf, txt):
    pdf.set_font("Amiri", "", 11)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(6, 7, "◆", align="R")
    pdf.multi_cell(CONTENT_W - 6, 7, txt, align="R")
    pdf.ln(0.6)


def chart(pdf, png_path: Path, caption: str):
    data = img_bytes_jpeg(png_path)
    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
    draw_w = CONTENT_W
    draw_h = draw_w * h / w
    max_h = 118
    if draw_h > max_h:
        draw_h = max_h
        draw_w = draw_h * w / h
    if pdf.get_y() + draw_h + 14 > 280:
        pdf.add_page()
    x = (PAGE_W - draw_w) / 2
    pdf.image(io.BytesIO(data), x=x, w=draw_w, h=draw_h)
    pdf.ln(1.5)
    pdf.set_font("Amiri", "", 9.5)
    pdf.set_text_color(90, 98, 110)
    pdf.multi_cell(CONTENT_W, 5.6, caption, align="R")
    pdf.ln(2.5)


def table(pdf, headers, rows, widths, aligns=None, header_bg=(15, 42, 92)):
    aligns = aligns or ["R"] * len(headers)
    pdf.set_font("Cairo", "", 8.6)
    pdf.set_fill_color(*header_bg)
    pdf.set_text_color(255, 255, 255)
    for htxt, w, a in zip(headers, widths, aligns):
        pdf.cell(w, 8, htxt, border=1, align=a, fill=True)
    pdf.ln()
    pdf.set_text_color(30, 35, 45)
    pdf.set_font("Amiri", "", 9.6)
    fill = False
    for r in rows:
        if pdf.get_y() > 275:
            pdf.add_page()
            pdf.set_font("Cairo", "", 8.6)
            pdf.set_fill_color(*header_bg)
            pdf.set_text_color(255, 255, 255)
            for htxt, w, a in zip(headers, widths, aligns):
                pdf.cell(w, 8, htxt, border=1, align=a, fill=True)
            pdf.ln()
            pdf.set_text_color(30, 35, 45)
            pdf.set_font("Amiri", "", 9.6)
        max_h = 8
        for val, w, a in zip(r, widths, aligns):
            pdf.cell(w, max_h, str(val), border=1, align=a,
                     fill=fill and True or False)
        fill = not fill
        pdf.ln()
    pdf.ln(2)


def fmt(n):
    return f"{int(n):,}" if n is not None else "—"


def cat_share(ap, name):
    for c in ap["categories"]:
        if c["name"] == name:
            return c["share"]
    return 0


def main():
    m = json.loads((RESULTS / "metrics.json").read_text(encoding="utf-8"))
    meta, q = m["meta"], m["quality"]
    dam, alp, ltk = m["airports"]["OSDI"], m["airports"]["OSAP"], m["airports"]["OSLK"]

    pdf = ReportPDF()
    pdf.set_title("التقرير المقارن — حركة الطيران في مطارات سوريا الثلاثة (دمشق، حلب، اللاذقية)")
    pdf.set_author("تحليل آلي من مستودع HoseenAlhlak/HoseenAlhlak")
    pdf.set_creator("analysis/build_pdf.py — fpdf2 + HarfBuzz")
    pdf.set_subject("تحليل مقارن لحركة الطيران 2025-2026")
    pdf.add_page()

    # ============ الغلاف ============
    pdf.set_fill_color(15, 42, 92)
    pdf.rect(0, 0, PAGE_W, 88, "F")
    pdf.set_y(24)
    pdf.set_font("Cairo", "", 10.5)
    pdf.set_text_color(190, 210, 240)
    pdf.cell(0, 8, "تقرير تحليلي موثّق — بيانات رحلات فعلية من مستودع GitHub", align="C")
    pdf.ln(10)
    pdf.set_font("Cairo", "", 24)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 14, "حركة الطيران في مطارات سوريا الثلاثة", align="C")
    pdf.ln(13)
    pdf.set_font("Cairo", "", 15)
    pdf.cell(0, 10, "دمشق  ·  حلب  ·  اللاذقية", align="C")
    pdf.ln(12)
    pdf.set_font("Cairo", "", 10.5)
    pdf.cell(0, 7, f"الفترة: {meta['data_first']} حتى {meta['data_last']}   |   {fmt(meta['total_movements'])} حركة جوية   |   20 شهراً", align="C")

    pdf.set_y(100)
    kpis = [
        ("إجمالي الحركات", fmt(meta["total_movements"]), (51, 90, 168)),
        ("حركات دمشق", fmt(dam["total"]), (30, 90, 168)),
        ("حركات حلب", fmt(alp["total"]), (14, 138, 95)),
        ("حركات اللاذقية", fmt(ltk["total"]), (194, 87, 26)),
        ("شركات التشغيل", str(meta["unique_operators"]), (51, 65, 85)),
        ("وجهة مختلفة", str(meta["unique_destinations"]), (51, 65, 85)),
        ("طائرة فريدة", fmt(meta["unique_aircraft"]), (51, 65, 85)),
    ]
    cw = CONTENT_W / 3
    for i, (label, value, color) in enumerate(kpis):
        col = i % 3
        row = i // 3
        x = MARGIN + (2 - col) * cw
        y = 100 + row * 30
        pdf.set_xy(x, y)
        pdf.set_fill_color(246, 247, 249)
        pdf.set_draw_color(229, 231, 235)
        pdf.rect(x, y, cw - 3, 26, style="DF", round_corners=True, corner_radius=3)
        pdf.set_xy(x, y + 3)
        pdf.set_font("Cairo", "", 15)
        pdf.set_text_color(*color)
        pdf.cell(cw - 3, 9, value, align="C")
        pdf.set_font("Cairo", "", 9)
        pdf.set_text_color(107, 114, 128)
        pdf.cell(cw - 3, 7, label, align="C")
    pdf.set_y(170)

    para(pdf, "ملخص التقرير:", bold=True, size=12.5)
    para(pdf, "تحليل مقارن شامل لحركة الطيران المسجلة في مطارات دمشق وحلب واللاذقية خلال الفترة من يناير 2025 حتى سبتمبر 2026، "
              "يستخرج المؤشرات الكمية الرئيسية (الأحجام، الفئات، النمو، الشركات، الوجهات، الأسطول، الإيقاع التشغيلي) ويعرضها في رسوم بيانية عربية موثقة، "
              "مع توثيق كامل للمنهجية وجودة البيانات والمصادر. هذا الملف هو النسخة المطبوعة من التقرير التفاعلي (HTML) المرفق في المجلد نفسه.", size=11)
    pdf.ln(2)
    para(pdf, f"تاريخ الإعداد: {meta['generated_at']} (توقيت دمشق) — أُنتج آلياً من الملفات الخام في data/raw/.", size=10, color=(107, 114, 128))

    # ============ الملخص التنفيذي ============
    pdf.add_page()
    h1(pdf, "1. الملخص التنفيذي — أبرز النتائج")
    bullets = [
        f"دمشق هو المركز بلا منازع: {fmt(dam['total'])} حركة أي {round(100*dam['total']/meta['total_movements'],1)}% من الإجمالي، عبر {dam['n_operators']} شركة تشغيل و{dam['n_destinations_all']} وجهة مختلفة.",
        f"حلب هو قصة النمو: من {fmt(alp['jan_aug_2025'])} حركة (يناير–أغسطس 2025) إلى {fmt(alp['jan_aug_2026'])} في الفترة نفسها من 2026، بنمو +{alp['growth_pct']}%.",
        f"اللاذقية نمط مختلف كلياً: {fmt(ltk['total'])} حركة فقط، {cat_share(ltk,'عسكري وحكومي')}% منها عسكرية/حكومية، أغلبها جسر جوي روسي مع قاعدة تشكالوفسكي ({ltk['ckl_n']} رحلة) بطائرات An-124 وIL-76.",
        f"ممر الخليج يهيمن على دمشق: {dam['gulf_share_of_intl']}% من مغادراته الدولية تتجه إلى مطارات الخليج (الكويت، دبي، الشارقة، الدوحة...).",
        f"سوق دمشق متنافس (HHI={dam['hhi']}؛ أكبر شركة {dam['top_airline']['share']}%) مقابل تركّز أعلى في حلب (HHI={alp['hhi']}؛ الملكية الأردنية {alp['top_airline']['share']}%).",
        f"نمو مطّرد: دمشق +{dam['growth_pct']}% في الفترة المماثلة، واللاذقية تضاعفت أكثر من ثلاث مرات ({ltk['jan_aug_2025']} ← {ltk['jan_aug_2026']}).",
        f"عائلة A320 هي العمود الفقري للأسطول؛ الطائرات العريضة البدن {dam['widebody_share']}% من حركات دمشق مقابل {alp['widebody_share']}% في حلب.",
    ]
    for b in bullets:
        bullet(pdf, b)

    # ============ المنهجية ============
    pdf.add_page()
    h1(pdf, "2. المنهجية وجودة البيانات")
    h2(pdf, "2.1 مصدر البيانات")
    para(pdf, "ثلاثة ملفات CSV بنمط سجلات تتبّع الرحلات (25 حقلاً لكل سجل: رقم الرحلة، المشغّل، نوع الطائرة وتسجيلها، مطارا الانطلاق والوصول وأوقاتهما، المدة، المسافة، الفئة، المدرج)، من مستودع HoseenAlhlak/HoseenAlhlak:")
    table(pdf,
          ["الملف", "المطار", "السجلات", "أول رصد", "آخر رصد"],
          [["flights_damascus_OSDI.csv", "دمشق DAM/OSDI", fmt(q["rows_per_file"]["OSDI"]), dam["first_event"], dam["last_event"]],
           ["flights_aleppo_OSAP.csv", "حلب ALP/OSAP", fmt(q["rows_per_file"]["OSAP"]), alp["first_event"], alp["last_event"]],
           ["flights_latakia_OSLK.csv", "اللاذقية LTK/OSLK", fmt(q["rows_per_file"]["OSLK"]), ltk["first_event"], ltk["last_event"]]],
          [50, 42, 22, 29, 29])
    h2(pdf, "2.2 قواعد الاحتساب")
    for b in [
        "«الحركة» = كل سجل؛ مغادرة إذا كان المطار مطار الانطلاق، ووصولاً إذا كان مطار الوجهة.",
        "الطابع الزمني المرجعي = وقت أول رصد (الأكثر اكتمالاً)، محوّلاً إلى توقيت دمشق المحلي.",
        "مؤشر التركّز HHI = مجموع مربعات حصص المشغلين × 10,000 (دون 1,500: سوق غير مركّز).",
        "استُبعدت الوجهة الذاتية (حركات محلية) من جداول الوجهات.",
        "مقارنة النمو اعتمدت الفترات المتماثلة يناير–أغسطس 2025 مقابل 2026.",
    ]:
        bullet(pdf, b)
    h2(pdf, "2.3 حدود البيانات (توثيق شفاف)")
    for b in [
        "فجوة تسجيل في بيانات دمشق بين 28 فبراير و2 أبريل 2026 (12 حركة فقط في مارس مقابل وسيط ~1,200) — عولجت باستبعادها من المتوسطات وتظليلها في الرسوم.",
        "سبتمبر 2026 شهر غير مكتمل (ينتهي التسجيل في 7 سبتمبر)؛ آخر شهر مكتمل هو أغسطس 2026.",
        "بدايات حلب المنخفضة (يناير–مايو 2025) تمثل استئنافاً تدريجياً حقيقياً لا فجوة بيانات.",
        "سجلات ناقصة حقولاً: بلا وقت إقلاع (2.2% في دمشق، 9% في حلب)، وبلا مشغّل معلن (0.3% دمشق، 21% اللاذقية — أغلبها عسكري بنمط روسي).",
    ]:
        bullet(pdf, b)

    # ============ لوحة المؤشرات ============
    pdf.add_page()
    h1(pdf, "3. لوحة المؤشرات المقارنة")
    rows = [
        ["إجمالي الحركات", fmt(dam["total"]), fmt(alp["total"]), fmt(ltk["total"])],
        ["مغادرات / وصولات", f'{fmt(dam["departures"])} / {fmt(dam["arrivals"])}', f'{fmt(alp["departures"])} / {fmt(alp["arrivals"])}', f'{fmt(ltk["departures"])} / {fmt(ltk["arrivals"])}'],
        ["متوسط شهري (أشهر مكتملة)", dam["avg_monthly"], alp["avg_monthly"], ltk["avg_monthly"]],
        ["أعلى شهر", f'{dam["peak_month"]["month"]} ({fmt(dam["peak_month"]["n"])})', f'{alp["peak_month"]["month"]} ({fmt(alp["peak_month"]["n"])})', f'{ltk["peak_month"]["month"]} ({ltk["peak_month"]["n"]})'],
        ["متوسط يومي (أغسطس 2026)", dam["avg_daily_last_full_month"], alp["avg_daily_last_full_month"], ltk["avg_daily_last_full_month"]],
        ["حصة رحلات الركاب", f'{cat_share(dam,"رحلات ركاب")}%', f'{cat_share(alp,"رحلات ركاب")}%', f'{cat_share(ltk,"رحلات ركاب")}%'],
        ["حصة العسكري والحكومي", f'{cat_share(dam,"عسكري وحكومي")}%', f'{cat_share(alp,"عسكري وحكومي")}%', f'{cat_share(ltk,"عسكري وحكومي")}%'],
        ["عدد شركات التشغيل", dam["n_operators"], alp["n_operators"], ltk["n_operators"]],
        ["أكبر مشغّل (حصته)", f'{dam["top_airline"]["name"]} ({dam["top_airline"]["share"]}%)', f'{alp["top_airline"]["name"]} ({alp["top_airline"]["share"]}%)', f'{ltk["top_airline"]["name"]} ({ltk["top_airline"]["share"]}%)'],
        ["مؤشر التركّز HHI", dam["hhi"], alp["hhi"], ltk["hhi"]],
        ["عدد الوجهات", dam["n_destinations_all"], alp["n_destinations_all"], ltk["n_destinations_all"]],
        ["الوجهة الأولى", f'{dam["top_destinations"][0]["city"]} ({fmt(dam["top_destinations"][0]["n"])})', f'{alp["top_destinations"][0]["city"]} ({fmt(alp["top_destinations"][0]["n"])})', f'{ltk["top_destinations"][0]["city"]} ({ltk["top_destinations"][0]["n"]})'],
        ["حصة الخليج من الدولية", f'{dam["gulf_share_of_intl"]}%', f'{alp["gulf_share_of_intl"]}%', "—"],
        ["أنواع الطائرات / طائرات فريدة", f'{dam["n_types"]} / {dam["n_aircraft"]}', f'{alp["n_types"]} / {alp["n_aircraft"]}', f'{ltk["n_types"]} / {ltk["n_aircraft"]}'],
        ["حصة العريضة البدن", f'{dam["widebody_share"]}%', f'{alp["widebody_share"]}%', f'{ltk["widebody_share"]}%'],
        ["وسيط زمن الرحلة (دقيقة)", dam["ft_median"], alp["ft_median"], ltk["ft_median"]],
        ["وسيط المسافة (كم)", fmt(dam["dist_median"]), fmt(alp["dist_median"]), fmt(ltk["dist_median"])],
        ["ساعة الذروة (محلي)", f'{dam["peak_hour"]}:00', f'{alp["peak_hour"]}:00', f'{ltk["peak_hour"]}:00'],
        ["النمو يناير–أغسطس 2025←2026", f'+{dam["growth_pct"]}%', f'+{alp["growth_pct"]}%', f'+{ltk["growth_pct"]}%'],
    ]
    table(pdf, ["المؤشر", "دمشق", "حلب", "اللاذقية"], rows, [62, 44, 44, 36])

    # ============ الرسوم ============
    pdf.add_page()
    h1(pdf, "4. الاتجاه الزمني والنمو")
    chart(pdf, CHARTS / "c02_monthly.png",
          "الشكل 1 — التطور الشهري: ثبات دمشق حول 1,200–1,400 حركة، صعود حلب المتسارع حتى 694 في أغسطس 2026، ونشاط اللاذقية المتقطع. المظلل بالأصفر فجوة تسجيل دمشق (مارس 2026) وبالرمادي سبتمبر غير المكتمل.")
    chart(pdf, CHARTS / "c11_growth.png",
          "الشكل 2 — مقارنة عادلة (يناير–أغسطس): نمو دمشق +30.7%، حلب +358.1%، اللاذقية +235.1% عن قاعدة منخفضة.")

    pdf.add_page()
    h1(pdf, "5. تركيب الحركة")
    chart(pdf, CHARTS / "c01_totals.png",
          "الشكل 3 — إجمالي الحركات والمغادرات مقابل الوصولات: توازن مدني شبه تام في دمشق وحلب، ومغادرات تفوق الوصولات في اللاذقية.")
    chart(pdf, CHARTS / "c03_categories.png",
          "الشكل 4 — تركيب الفئات: دمشق وحلب مدنيان بامتياز (ركاب ~95%)، واللاذقية 96% عسكري وحكومي.")
    chart(pdf, CHARTS / "c13_domestic.png",
          "الشكل 5 — المغادرات الداخلية شبه غائبة: إعادة الإعمار الجوي تركّزت على الربط الدولي.")

    pdf.add_page()
    h1(pdf, "6. سوق شركات التشغيل")
    chart(pdf, CHARTS / "c04_airlines.png",
          "الشكل 6 — أكبر 12 شركة عبر المطارات الثلاثة: الخطوط السورية أولاً ثم فلاي شام الناشئة — شركتان سوريتان تتمثلان معاً نحو 29% من كل الحركات.")
    chart(pdf, CHARTS / "c05_shares.png",
          "الشكل 7 — حصص السوق: تنوّع خليجي-أردني-تركي في دمشق مقابل ريادة أردنية-تركية في حلب.")

    pdf.add_page()
    h1(pdf, "7. الشبكة والوجهات")
    chart(pdf, CHARTS / "c06_destinations.png",
          "الشكل 8 — أهم الوجهات: الكويت أولاً في دمشق، وعمّان أولاً في حلب — شبكتان متكاملتان أكثر منهما متنافستان.")
    chart(pdf, CHARTS / "c14_network.png",
          "الشكل 9 — اتساع الشبكة: 95 وجهة و546 طائرة فريدة في دمشق مقابل 26 وجهة و216 طائرة في حلب.")

    pdf.add_page()
    h1(pdf, "8. إيقاع التشغيل")
    chart(pdf, CHARTS / "c07_hourly.png",
          "الشكل 10 — التوزيع الساعي (توقيت دمشق): ذروة دمشق 14:00 بمنحنى مزدوج، وحلب صباحية مبكرة (07:00)، واللاذقية عصرية (17:00).")
    chart(pdf, CHARTS / "c08_dow.png",
          "الشكل 11 — أيام الأسبوع: تفاوت محدود يدل على خطوط منتظمة.")

    pdf.add_page()
    h1(pdf, "9. الأسطول وبصمة المسافات")
    chart(pdf, CHARTS / "c09_types.png",
          "الشكل 12 — عائلة A320 تتصدر، مع حضور عريض البدن في دمشق (A330/B777/B787).")
    chart(pdf, CHARTS / "c10_profile.png",
          "الشكل 13 — بصمة التشغيل: رحلات اللاذقية أطول وأبعد (روسيا وإفريقيا)، وحلب الأقصر جذرياً (شبكة إقليمية).")

    pdf.add_page()
    h1(pdf, "10. اللاذقية: جسر جوي عسكري")
    chart(pdf, CHARTS / "c12_latakia.png",
          "الشكل 14 — اللاذقية بالتفصيل: حركة شهرية متقطعة، مشغّلون عسكريون روس (93.3% ارتباط روسي)، وأسراب IL-76 وAn-124.")
    for b in [
        f"الوجهة الأولى قاعدة تشكالوفسكي العسكرية قرب موسكو ({ltk['ckl_n']} رحلة) — جسر إمداد لوجستي واضح.",
        "ذيل إفريقي: رحلات متفرقة نحو باماكو وبرازافيل ولومي ودار السلام بنمط نقل استراتيجي An-124.",
        "الطيران المدني المنتظم غائب عملياً خلال فترة البيانات.",
    ]:
        bullet(pdf, b)

    # ============ الخلاصة ============
    pdf.add_page()
    h1(pdf, "11. الخلاصة التحليلية")
    para(pdf, "دمشق — الاستقرار بعد الاستعادة:", bold=True, size=12)
    para(pdf, f"{fmt(dam['total'])} حركة عبر {dam['n_operators']} شركة و{dam['n_destinations_all']} وجهة، وسوق غير مركّز ونمو +{dam['growth_pct']}%. "
              f"ارتباط خليجي بنيوي ({dam['gulf_share_of_intl']}% من مغادراته الدولية) وجاهزية عالية لمزيد من النمو.")
    pdf.ln(1)
    para(pdf, "حلب — منحنى الإقلاع:", bold=True, size=12)
    para(pdf, f"من {fmt(alp['jan_aug_2025'])} إلى {fmt(alp['jan_aug_2026'])} حركة في الفترات المتماثلة (+{alp['growth_pct']}%)، وأعلى شهر تشغيل في أغسطس 2026. "
              f"التحدي: توسيع قاعدة المشغلين ودخول طائرات أكبر (العريضة البدن {alp['widebody_share']}% فقط).")
    pdf.ln(1)
    para(pdf, "اللاذقية — مطار بلا ركاب:", bold=True, size=12)
    para(pdf, f"{fmt(ltk['total'])} حركة، {cat_share(ltk,'عسكري وحكومي')}% عسكرية و{ltk['russian_mil_share']}% بارتباط روسي مباشر؛ منصة لوجستية لا بوابة مدنية.")
    pdf.ln(2)
    para(pdf, "بصيغة واحدة: أعادت سوريا بناء بوّابتيها المدنيتين — دمشق بحجم مستقر وحلب بنمو انفجاري — بينما بقيت اللاذقية منصة عسكرية شبه حصرية.", bold=True)

    # ============ المصادر ============
    pdf.add_page()
    h1(pdf, "12. المصادر والمراجع")
    h2(pdf, "البيانات الخام")
    para(pdf, "flights_damascus_OSDI.csv (19,743 سجلاً) · flights_aleppo_OSAP.csv (5,068) · flights_latakia_OSLK.csv (252) — مستودع HoseenAlhlak/HoseenAlhlak على GitHub، مجلد data/raw/.", size=10.5)
    h2(pdf, "مراجع التحقق من رموز شركات التشغيل")
    for s in [
        "Wikipedia — List of airlines of Syria: en.wikipedia.org/wiki/List_of_airlines_of_Syria",
        "Airhex — Fly Cham (FYC/XH): airhex.com/airlines/fly-cham",
        "Airhex — flyadeal (FAD/F3): airhex.com/airlines/flyadeal",
        "Airhex — Dan Air (DNA/DN): airhex.com/airlines/dan-air",
        "Plane Finder — Centrum Air (MFX/C6): planefinder.net/data/airline/MFX",
        "Airhex — Air Mediterranean (MAR/MV): airhex.com/airlines/air-mediterranean",
        "Airways Magazine — flynas والرحلات إلى دمشق (KNE/XY): airwaysmag.com/new-post/flynas-syria-lcc",
        "airliners.de — أسطول LEAV Aviation (NGN/KK): airliners.de (تقرير الأسطول 2025)",
    ]:
        bullet(pdf, s)
    h2(pdf, "أدوات التحليل")
    para(pdf, "analysis/analyze_airports.py (pandas + matplotlib + arabic-reshaper + python-bidi) · analysis/build_report.py (HTML) · analysis/build_pdf.py (PDF) · المؤشرات التفصيلية في analysis/results/metrics.json", size=10.5)
    pdf.ln(2)
    para(pdf, "تنويه: الأرقام تعكس حصراً ما ورد في الملفات الثلاثة وهي حساسة لاكتمال التسجيل (القسم 2.3). التسميات العربية للشركات والمدن اجتهاد توثيقي مبني على المصادر أعلاه. هذا الملف نسخة مطبوعة من التقرير التفاعلي ذاتي الاحتواء (HTML) المرفق في المجلد نفسه، والذي يتضمن الجداول التفصيلية الكاملة.", size=9.5, color=(107, 114, 128))

    pdf.output(str(OUT))
    print(f"PDF written: {OUT.name} ({OUT.stat().st_size/1e6:.2f} MB, {pdf.page_no()} pages)")


if __name__ == "__main__":
    main()
