"""
Generate a SYNTHETIC STEG-style bill for testing the bill reader (not a real invoice, fake personal data).
Amounts are computed with rootcode.tariff so the end-to-end check should report "match".

    python samples/make_specimen_bill.py            -> samples/bill_specimen.png / .pdf
    python samples/make_specimen_bill.py --estimated --old-taxes
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rootcode.tariff import compute  # noqa: E402

FONT = "C:/Windows/Fonts/arial.ttf"
BOLD = "C:/Windows/Fonts/arialbd.ttf"


def fmt(x):
    return f"{x:,.3f}".replace(",", " ").replace(".", ",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kwh", type=int, default=412)
    ap.add_argument("--old-index", type=int, default=18734)
    ap.add_argument("--kva", type=float, default=2)
    ap.add_argument("--estimated", action="store_true")
    ap.add_argument("--old-taxes", action="store_true", help="print taxes of the 2022 PDF (to test mismatch causes)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "bill_specimen"))
    a = ap.parse_args()

    c = compute(a.kwh, 2, a.kva, taxes_variant="pdf_2022" if a.old_taxes else "current")["lines"]
    rtt, gas = 1.000, 0.0
    total = c["electricity_total_tnd"] + rtt + gas

    W, H = 1240, 1754
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f = lambda s, b=False: ImageFont.truetype(BOLD if b else FONT, s)  # noqa: E731
    ar = lambda: ImageFont.truetype(FONT, 26, layout_engine=ImageFont.Layout.RAQM)  # noqa: E731

    d.rectangle([40, 40, W - 40, 150], outline="#1b4f8a", width=3)
    d.text((70, 62), "Société Tunisienne de l'Electricité et du Gaz", font=f(32, True), fill="#1b4f8a")
    d.text((70, 106), "SPECIMEN - FACTURE DE TEST SYNTHETIQUE (données fictives)", font=f(22), fill="#b4412b")
    d.text((W - 70, 70), "الشركة التونسية للكهرباء والغاز", font=ar(), fill="#1b4f8a", anchor="ra", direction="rtl")

    y = 190
    for left in ["Nom : M. Test Exemple", "Adresse : 12 rue Fictive, 1000 Tunis",
                 "Référence client : 000 000 000 0", "N° compteur : 00000000"]:
        d.text((70, y), left, font=f(26), fill="black")
        y += 42

    y += 20
    d.line([40, y, W - 40, y], fill="#999", width=2)
    y += 25
    d.text((70, y), "Période de consommation : du 10/05/2026 au 09/07/2026", font=f(27, True), fill="black")
    y += 50
    d.text((70, y), "Puissance souscrite : " + fmt(a.kva).split(",")[0] + " kVA", font=f(26), fill="black")
    d.text((W - 70, y), "القدرة المكتتبة", font=ar(), fill="black", anchor="ra", direction="rtl")
    y += 46
    d.text((70, y), "Type de relevé : " + ("Estimé" if a.estimated else "Relevé réel"), font=f(26), fill="black")
    d.text((W - 70, y), "قراءة تقديرية" if a.estimated else "قراءة حقيقية", font=ar(), fill="black", anchor="ra",
           direction="rtl")
    y += 70

    rows = [
        ("Ancien index", f"{a.old_index}", "المؤشر القديم"),
        ("Nouvel index", f"{a.old_index + a.kwh}", "المؤشر الجديد"),
        ("Consommation (kWh)", f"{a.kwh}", "الاستهلاك"),
        ("Montant consommation HT", fmt(c["energy_tnd"]) + " DT", "مبلغ الاستهلاك"),
        ("Redevance de puissance", fmt(c["fixed_charges_tnd"]) + " DT", "معلوم القدرة"),
        ("Total taxes (TVA, FTE, CL)", fmt(c["taxes_tnd"]) + " DT", "الأداءات"),
        ("Total électricité", fmt(c["electricity_total_tnd"]) + " DT", "مجموع الكهرباء"),
        ("Contribution RTT", fmt(rtt) + " DT", ""),
    ]
    d.rectangle([60, y - 10, W - 60, y + 54 * len(rows) + 10], outline="#bbb", width=2)
    for lab, val, arl in rows:
        d.text((80, y), lab, font=f(27), fill="black")
        d.text((760, y), val, font=f(27, True), fill="black", anchor="ra")
        if arl:
            d.text((W - 80, y), arl, font=ar(), fill="black", anchor="ra", direction="rtl")
        y += 54
    y += 40
    d.rectangle([60, y, W - 60, y + 80], fill="#eef3fa", outline="#1b4f8a", width=2)
    d.text((80, y + 22), "Net à payer : " + fmt(total) + " DT", font=f(32, True), fill="#1b4f8a")
    d.text((W - 80, y + 24), "المبلغ الصافي للدفع", font=ar(), fill="#1b4f8a", anchor="ra", direction="rtl")
    d.text((70, H - 80), "Document généré pour les tests INBETWEEN. Ne correspond à aucun client réel.",
           font=f(20), fill="#777")

    img.save(a.out + ".png")
    img.save(a.out + ".pdf", resolution=150)
    print("wrote", a.out + ".png", "and .pdf;", "electricity", c["electricity_total_tnd"], "total", round(total, 3))


if __name__ == "__main__":
    main()
