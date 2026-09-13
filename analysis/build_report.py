#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مولد التقرير العربي (HTML ذاتي الاحتواء)
يقرأ analysis/results/metrics.json + الرسوم من reports/charts/ وينتج:
  reports/تقرير_مطارات_سوريا_المقارن.html

كل الخطوط والصور تُضمَّن Base64 داخل الملف الواحد، فيعمل دون إنترنت وقابل للتنزيل مباشرة.
"""

import base64
import json
from pathlib import Path

from fontTools import subset
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "analysis" / "results"
CHARTS = ROOT / "reports" / "charts"
FONTS = ROOT / "assets" / "fonts"
OUT_HTML = ROOT / "reports" / "تقرير_مطارات_سوريا_المقارن.html"

# محارف التضمين: لاتينية أساسية + عربية + أشكال عرض + علامات ترقيم عربية
UNICODES = "U+0020-007E,U+00A0,U+060C-06FF,U+0750-077F,U+08A0-08FF,U+200C-200F,U+2010-2027,U+2030-2034,U+FB50-FDFF,U+FE70-FEFF,U+25CF,U+25A0"


def subset_font(src: Path, dst: Path) -> None:
    """تقليص ملف الخط للمحارف المستخدمة لتقليل حجم التقرير."""
    if dst.exists():
        return
    args = [
        str(src),
        f"--unicodes={UNICODES}",
        f"--output-file={dst}",
        "--layout-features=*",
        "--drop-tables+=FFTM",
    ]
    subset.main(args)


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def main() -> None:
    metrics = json.loads((RESULTS / "metrics.json").read_text(encoding="utf-8"))

    # تقليص الخطوط ثم تضمينها
    sub_dir = FONTS / "_subset"
    sub_dir.mkdir(exist_ok=True)
    amiri = FONTS / "Amiri-Regular.ttf"
    amiri_b = FONTS / "Amiri-Bold.ttf"
    cairo = FONTS / "Cairo.ttf"
    sub_amiri = sub_dir / "Amiri-Regular-sub.ttf"
    sub_amiri_b = sub_dir / "Amiri-Bold-sub.ttf"
    sub_cairo = sub_dir / "Cairo-sub.ttf"
    subset_font(amiri, sub_amiri)
    subset_font(amiri_b, sub_amiri_b)
    subset_font(cairo, sub_cairo)

    # الصور
    charts = sorted(CHARTS.glob("c*.png"))
    img = {p.stem: b64(p) for p in charts}

    # مصفوفة المشغلين (لأرقام "شركتان سوريتان معاً")
    ops_matrix = {}
    import pandas as pd
    om = pd.read_csv(RESULTS / "operators_matrix.csv")
    for _, row in om.iterrows():
        ops_matrix[str(row["op"])] = int(row["الإجمالي"])
    total_ops = metrics["meta"]["unique_operators"]
    total_dests = metrics["meta"]["unique_destinations"]
    total_aircraft = metrics["meta"]["unique_aircraft"]

    env = Environment(undefined=StrictUndefined)
    env.filters["fmt"] = lambda v: f"{int(v):,}" if v is not None else "—"
    template = env.from_string(
        (ROOT / "analysis" / "report_template.html").read_text(encoding="utf-8"))

    def cat_share(ap, name):
        for c in ap["categories"]:
            if c["name"] == name:
                return c["share"]
        return 0

    html = template.render(
        m=metrics["meta"],
        q=metrics["quality"],
        airports=metrics["airports"],
        dam=metrics["airports"]["OSDI"],
        alp=metrics["airports"]["OSAP"],
        ltk=metrics["airports"]["OSLK"],
        img=img,
        font_cairo=b64(sub_cairo),
        font_amiri=b64(sub_amiri),
        font_amiri_bold=b64(sub_amiri_b),
        cat_share=cat_share,
        pct=lambda part, whole: round(100 * part / max(whole, 1), 1),
        ops_total=lambda code: ops_matrix.get(code, 0),
        total_ops=total_ops,
        total_dests=total_dests,
        total_aircraft=total_aircraft,
    )
    OUT_HTML.write_text(html, encoding="utf-8")
    size_mb = OUT_HTML.stat().st_size / 1e6
    print(f"HTML written: {OUT_HTML.name} ({size_mb:.2f} MB), charts embedded: {len(img)}")


if __name__ == "__main__":
    main()
