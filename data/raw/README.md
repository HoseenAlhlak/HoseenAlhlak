# مجلد بيانات المطارات الخام — `data/raw/`

ضع في هذا المجلد ملفات المطارات الثلاثة التي تريد تحليلها مقارنةً.

## 1) أسماء الملفات المطلوبة

الأسماء أدناه هي التي يبحث عنها سكربت التحليل تلقائيًا (يمكن أيضًا استخدام الأسماء العربية بين قوسين):

| # | الملف | الاسم العربي البديل |
|---|-------|---------------------|
| 1 | `damascus.txt` | `مطار دمشق.txt` |
| 2 | `aleppo.txt` | `مطار حلب.txt` |
| 3 | `latakia.txt` | `مطار اللاذقية.txt` |

> **ملاحظة:** السكربت يقبل أي اسم ملف ينتهي بـ `.txt` أو `.csv` أو `.json` داخل هذا المجلد،
> ويتعرّف على المطار من محتوى الملف (رمز IATA أو اسم المطار). الأسماء المقترحة أعلاه هي للترتيب فقط.
> الترميز المدعوم: **UTF-8** (ويتم اكتشاف `UTF-8 BOM` و`UTF-16` و`Windows-1256` تلقائيًا).

## 2) صيغة الملف المقترحة (سطر = حقل واحد)

```
# مطار دمشق الدولي
airport_name_ar = مطار دمشق الدولي
airport_name_en = Damascus International Airport
iata = DAM
icao = OSDI
city = دمشق
country = سوريا
elevation_m = 616
opened = 1973
status = operational
terminals = 2
capacity_mpassengers = 5.0
runway_count = 2
runway_max_length_m = 3600
runway_surface = asphalt
passengers_2024 = 1250000
passengers_2025 = 1392699
movements_2025 = 18000
cargo_t_2025 = 3200
destinations = 24
airlines = 9
# سلسلة تاريخية: سنة=عدد المسافرين (افصل بفاصلة)
passengers_series = 2019=1500000, 2022=400000, 2023=700000, 2024=1250000, 2025=1392699
```

- الأسطر التي تبدأ بـ `#` تُعدّ تعليقات وتُتجاهل.
- الفاصل بين الاسم والقيمة: `=` أو `:`.
- أي حقل غير متوفر: اتركه فارغًا أو اكتب `NA` — ولن يُحتسب في المقارنة.
- **صيغة CSV** مقبولة أيضًا: صف ترويسة بالإنجليزية، ثم صف لكل مطار.
- **صيغة JSON** مقبولة أيضًا: مصفوفة كائنات، كل كائن يمثل مطارًا.

## 3) الحقول التي يبني عليها التقرير مؤشرات المقارنة

| المحور | الحقول |
|--------|--------|
| الهوية والموقع | `airport_name_ar` `iata` `icao` `city` `country` `lat` `lon` `elevation_m` |
| البنية التحتية | `runway_count` `runway_max_length_m` `runway_surface` `terminals` `gates` `capacity_mpassengers` |
| الحركة | `passengers_<سنة>` `movements_<سنة>` `cargo_t_<سنة>` `passengers_series` |
| الشبكة | `destinations` `airlines` `hub_for` |
| التشغيل والجودة | `status` `opened` `closure_notes` `asq_score` `on_time_pct` `avg_delay_min` |
| الأثر الاقتصادي | `revenue_usd` `jobs` `gdp_impact_usd` |

## 4) كيف يصل الملف إلى بيئة التحليل؟

**الطريقة الأسهل — من متصفح GitHub مباشرة:**

1. افتح مجلد `data/raw/` في المستودع على GitHub.
2. اضغط **Add file → Upload files**، واسحب الملفات الثلاثة، ثم **Commit changes** إلى `main`.
3. اكتب في المحادثة: «رفعت الملفات» — وسيتم سحبها وتحليلها فورًا.

**أو من الطرفية على جهازك:**

```bash
git clone https://github.com/HoseenAlhlak/HoseenAlhlak.git
cd HoseenAlhlak
cp ~/Downloads/*.txt data/raw/
git add data/raw
git commit -m "data: إضافة ملفات المطارات الثلاثة"
git push origin main
```
