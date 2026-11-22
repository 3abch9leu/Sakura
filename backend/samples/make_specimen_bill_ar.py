"""
SYNTHETIC Arabic STEG-style bill for testing the bill reader (fake personal data, not a real invoice).
Right-to-left layout: labels on the right, values on their left; ISO dates (2022-10-06) and amounts with a
decimal comma and "د.ت", as on Arabic STEG bills. Amounts come from rootcode.tariff (expected result: match).

    python samples/make_specimen_bill_ar.py      -> samples/bill_specimen_ar.png
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rootcode.tariff import compute  # noqa: E402

FONT = "C:/Windows/Fonts/arial.ttf"
BOLD = "C:/Windows/Fonts/arialbd.ttf"
KWH, OLD, KVA = 296, 41207, 2
START, END = "2022-08-07", "2022-10-06"


def fmt(x):
    return f"{x:.3f}".replace(".", ",")


def main():
    c = compute(KWH, 2, KVA)["lines"]
    rtt = 1.000
    total = c["electricity_total_tnd"] + rtt
    W, H = 1240, 1754
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    ar = lambda s, b=False: ImageFont.truetype(BOLD if b else FONT, s, layout_engine=ImageFont.Layout.RAQM)  # noqa: E731
    la = lambda s, b=False: ImageFont.truetype(BOLD if b else FONT, s)  # noqa: E731

    def rtl(x, y, text, size=28, bold=False, fill="black"):
        d.text((x, y), text, font=ar(size, bold), fill=fill, anchor="ra", direction="rtl", language="ar")

    def ltr(x, y, text, size=28, bold=False, fill="black"):
        d.text((x, y), text, font=la(size, bold), fill=fill, anchor="la")

    d.rectangle([40, 40, W - 40, 150], outline="#1b4f8a", width=3)
    rtl(W - 70, 58, "الشركة التونسية للكهرباء والغاز", 36, True, "#1b4f8a")
    rtl(W - 70, 106, "فاتورة تجريبية مصطنعة - بيانات وهمية", 24, False, "#b4412b")
    ltr(70, 70, "STEG", 40, True, "#1b4f8a")

    y = 200
    for line in ("الحريف : فلان الفلاني", "العنوان : نهج التجربة عدد 0 تونس", "مرجع الحريف : 000 000 000 0", "رقم العداد : 00000000"):
        rtl(W - 70, y, line, 26, False, "#444")
        y += 44

    # period: "من 2022-08-07 إلى 2022-10-06" (dates are left-to-right inside the Arabic line)
    rtl(W - 70, y + 20, "فترة الاستهلاك :", 28, True)
    ltr(150, y + 20, f"{START}   ←   {END}", 28, True)
    y += 90
    rtl(W - 70, y, "نوع القراءة : قراءة حقيقية", 26)
    y += 70

    rows = [
        ("المؤشر القديم", f"{OLD}"),
        ("المؤشر الجديد", f"{OLD + KWH}"),
        ("الاستهلاك (ك.و.س)", f"{KWH}"),
        ("القدرة المكتتبة (ك.ف.أ)", f"{KVA}"),
        ("مبلغ الاستهلاك", f"{fmt(c['energy_tnd'])} د.ت"),
        ("المعاليم القارة", f"{fmt(c['fixed_charges_tnd'])} د.ت"),
        ("الأداءات", f"{fmt(c['taxes_tnd'])} د.ت"),
        ("جملة الكهرباء", f"{fmt(c['electricity_total_tnd'])} د.ت"),
        ("مساهمة الإذاعة والتلفزة", f"{fmt(rtt)} د.ت"),
    ]
    d.line([60, y - 10, W - 60, y - 10], fill="#999", width=2)
    for label, value in rows:
        rtl(W - 70, y, label, 28)
        # the value sits on the left of its label, digits read left to right
        d.text((90, y), value, font=ar(28), fill="black", anchor="la", direction="rtl", language="ar")
        y += 62
    d.line([60, y, W - 60, y], fill="#999", width=2)
    y += 30
    rtl(W - 70, y, "المبلغ الجملي للدفع", 34, True)
    d.text((90, y), f"{fmt(total)} د.ت", font=ar(34, True), fill="black", anchor="la", direction="rtl", language="ar")
    y += 90
    rtl(W - 70, y, "آخر أجل للدفع : 2022-10-27", 24, False, "#444")

    out = os.path.join(os.path.dirname(__file__), "bill_specimen_ar.png")
    img.save(out)
    print(out, {k: round(v, 3) for k, v in c.items() if isinstance(v, (int, float))}, "total", round(total, 3))


if __name__ == "__main__":
    main()
