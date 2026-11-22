"""
Energy & Comfort Advisor - connects a verified STEG bill to INBETWEEN.

  A. understand(bill, verification)   consumption, daily / monthly averages, actual vs estimated, history trend
  B. scenarios(appliances, bill)      appliance kWh (P x h x days, deterministic) and, when the tariff allows,
                                      the bill impact computed by rootcode.tariff (never by an LLM)
  C. shading(facade, lat, lon, ...)   SolarEngine exposure + INBETWEEN design shading (existing optimizer outputs)
  + retrieve(query)                   keyword retrieval over data/energy_kb.json (official sources with URLs)
  + explain(bill, verification, lang) deterministic plain-language explanation in fr / ar / darija / en

Electricity savings from shading are NEVER computed: no validated building-energy model exists.
"""
import json
import os
import re
import unicodedata

from . import config as C
from .tariff import TARIFF, compute, months_between

NOT_VALIDATED = "Electricity savings have not yet been measured or validated."
KB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "energy_kb.json")
with open(KB_PATH, encoding="utf-8") as _f:
    KB = json.load(_f)["docs"]

ANME_AC = next(d for d in KB if d["id"] == "anme_ac_26")


# ================================================================ A. consumption understanding
def understand(bill, verification=None, history=None):
    """
    bill: corrected fields. history: optional list of {"period_end": "YYYY-MM-DD", "consumption_kwh": n}
    from previous bills (oldest first). Returns metrics with explicit 'unknown' where data is missing.
    """
    out = {"consumption_kwh": None, "days": None, "months": None, "kwh_per_day": None, "kwh_per_month": None,
           "reading_type": bill.get("reading_type"), "changes": None, "notes": []}
    c = bill.get("consumption_kwh")
    if c is None and bill.get("index_current") is not None and bill.get("index_previous") is not None:
        c = bill["index_current"] - bill["index_previous"]
    out["consumption_kwh"] = c
    if c is None:
        out["notes"].append("Consumption is unknown: enter it, or the old and new meter indexes.")
        return out
    days = None
    if bill.get("period_start") and bill.get("period_end"):
        try:
            months, days = months_between(bill["period_start"], bill["period_end"])
            out["months"] = months
        except ValueError:
            pass
    if bill.get("period_months"):
        out["months"] = bill["period_months"]
    out["days"] = days
    if days:
        out["kwh_per_day"] = round(c / days, 2)
    if out["months"]:
        # same monthly split as the STEG tariff bands (consumption / billing months)
        out["kwh_per_month"] = round(c / out["months"], 1)
    elif days:
        out["kwh_per_month"] = round(c / days * 30.44, 1)
    if not days and out["months"]:
        out["kwh_per_month"] = round(c / out["months"], 1)
        out["notes"].append("Daily average unknown: the exact billing dates are missing.")
    else:
        out["notes"].append("Averages unknown: the billing period is missing.")

    if verification and verification.get("calculation") and verification["calculation"].get("band"):
        calc = verification["calculation"]
        out["band"] = {"price_mill_per_kwh": calc["band"]["price_mill_per_kwh"], "monthly_kwh": calc["monthly_kwh"],
                       "vat_rate": calc.get("vat_rate")}
        out["next_band"] = _band_headroom(calc["monthly_kwh"], calc.get("category") or "normal")

    if out["reading_type"] == "estimated":
        out["notes"].append("Estimated reading: based on your last 24 months, corrected at the next actual reading (STEG).")

    if history:
        pts = [h for h in history if h.get("consumption_kwh") is not None]
        if pts:
            prev = pts[-1]["consumption_kwh"]
            if prev:
                ch = (c - prev) / prev * 100
                out["changes"] = {"previous_kwh": prev, "change_pct": round(ch, 1),
                                  "significant": abs(ch) >= 20, "series": pts + [{"period_end": bill.get("period_end"),
                                                                                    "consumption_kwh": c}]}
    return out


def _band_headroom(monthly_kwh, category):
    """How many kWh/month remain before the whole consumption moves to a higher price band."""
    for b in TARIFF["residential"]["bands"]:
        hi = b["max_kwh_month"]
        if category in b["applies_to"] and hi is not None and monthly_kwh <= hi:
            nxt = next((x for x in TARIFF["residential"]["bands"] if x["min_kwh_month"] == hi), None)
            return {"limit_kwh_month": hi, "headroom_kwh_month": round(hi - monthly_kwh, 1),
                    "next_price_mill_per_kwh": nxt["price_mill_per_kwh"] if nxt else None}
    return None


# ================================================================ B. scenarios
def appliance_kwh(power_w, hours_per_day, days, quantity=1):
    """E [kWh] = P [W] x hours/day x days x quantity / 1000"""
    if min(power_w, hours_per_day, days, quantity) < 0:
        raise ValueError("power, hours, days and quantity must be >= 0")
    if hours_per_day > 24:
        raise ValueError("hours per day cannot exceed 24")
    return power_w * hours_per_day * days * quantity / 1000.0


def scenarios(appliances, bill=None, setpoint=None):
    """
    appliances: [{name, power_w (or power_kw), hours_per_day, days, quantity=1, reduce_hours_per_day=0}]
    setpoint: optional {"current_c": 22, "target_c": 26} for air conditioners (ANME rule of thumb, labelled).
    bill: verified fields (consumption_kwh, months / period, subscribed_power_kva) to price the impact.
    """
    rows, assumptions = [], []
    total = 0.0
    total_saved = 0.0
    for a in appliances:
        p = a.get("power_w")
        if p is None and a.get("power_kw") is not None:
            p = a["power_kw"] * 1000
        if p is None:
            raise ValueError(f"power missing for {a.get('name', 'appliance')}")
        q = a.get("quantity", 1) or 1
        kwh = appliance_kwh(p, a["hours_per_day"], a["days"], q)
        saved = 0.0
        if a.get("reduce_hours_per_day"):
            saved = appliance_kwh(p, min(a["reduce_hours_per_day"], a["hours_per_day"]), a["days"], q)
        rows.append({"name": a.get("name") or "Appliance", "power_w": p, "hours_per_day": a["hours_per_day"],
                     "days": a["days"], "quantity": q, "kwh": round(kwh, 1),
                     "formula": f"{p:g} W x {a['hours_per_day']:g} h/day x {a['days']:g} days x {q:g} / 1000",
                     "kwh_saved_by_fewer_hours": round(saved, 1)})
        total += kwh
        total_saved += saved

    ac_saving = None
    if setpoint and setpoint.get("current_c") is not None and setpoint.get("target_c") is not None:
        ac_kwh = sum(r["kwh"] for r in rows if re.search(r"clim|air|ac\b|مكيف|كليم", r["name"], re.I)) or None
        deg = setpoint["target_c"] - setpoint["current_c"]
        if ac_kwh and deg > 0:
            # ANME: "each degree below 26 °C increases consumption by about 7 %" -> applied only up to 26 °C
            usable = max(0.0, min(setpoint["target_c"], 26) - setpoint["current_c"])
            frac = 1 - (1 / 1.07) ** usable
            ac_saving = {"kwh": round(ac_kwh * frac, 1), "degrees": usable, "fraction": round(frac, 3),
                         "assumption": "ANME rule of thumb: about 7 % more consumption per degree below 26 °C "
                                       "(reported by La Presse / AllAfrica, July 2026). Real savings depend on the "
                                       "room and the appliance.",
                         "source": ANME_AC["url"]}
            total_saved += ac_saving["kwh"]
            assumptions.append(ac_saving["assumption"])

    if bill and bill.get("consumption_kwh") and total > bill["consumption_kwh"]:
        assumptions.append(f"Check the hours or days: these appliances alone ({total:.0f} kWh) use more than the whole "
                           f"bill ({bill['consumption_kwh']:g} kWh) for its period.")
    money = _price_impact(bill, total, total_saved) if bill else None
    if money is None:
        assumptions.append("Bill impact not priced: needs a verified consumption, period and subscribed power.")
    return {"appliances": rows, "total_kwh": round(total, 1), "setpoint": ac_saving,
            "total_kwh_saved": round(total_saved, 1), "money": money, "assumptions": assumptions}


def _price_impact(bill, scenario_kwh, saved_kwh):
    c = bill.get("consumption_kwh")
    if c is None:
        return None
    months = bill.get("period_months")
    if not months and bill.get("period_start") and bill.get("period_end"):
        months = months_between(bill["period_start"], bill["period_end"])[0]
    kva = bill.get("subscribed_power_kva")
    base = compute(c, months, kva)
    if base["status"] != "complete":
        return None
    out = {"base_total_tnd": base["lines"]["electricity_total_tnd"], "base_band_mill": base["band"]["price_mill_per_kwh"]}
    if saved_kwh > 0:
        less = compute(max(0.0, c - saved_kwh), months, kva)
        if less["status"] == "complete":
            out["with_savings_total_tnd"] = less["lines"]["electricity_total_tnd"]
            out["saving_tnd"] = round(base["lines"]["electricity_total_tnd"] - less["lines"]["electricity_total_tnd"], 3)
            out["band_after_mill"] = less["band"]["price_mill_per_kwh"]
            out["band_changes"] = less["band"]["price_mill_per_kwh"] != base["band"]["price_mill_per_kwh"]
    out["note"] = ("Computed with the official STEG tariff for the same billing period (electricity part only). "
                   "Because STEG prices the whole monthly consumption at one band price, crossing a band limit "
                   "changes the price of every kWh.")
    out["assumption"] = "Assumes the saved kWh fall inside this billing period."
    return out


# ================================================================ C. shading connection
def shading(facade="W", lat=C.DEFAULT_LAT, lon=C.DEFAULT_LON, designs=None, run_optimizer=False, context=None):
    """
    Solar exposure of the window + INBETWEEN shading performance.
    designs: optional output of POST /design (dict name -> {result: ...}); else run the fast optimizer if asked.
    """
    from .solar import facade_sun, peak_hour
    az = float(C.FACADE_AZIMUTHS.get(str(facade).upper(), facade))
    s = facade_sun(lat, lon, az)
    out = {"facade": str(facade).upper(), "kwh_per_m2_day": round(s["daily_kwh_m2"], 2), "peak_hour": peak_hour(s),
           "note": "Clear-sky hot July day (pvlib), an upper bound.", "designs": None,
           "electricity_savings": NOT_VALIDATED}
    if designs is None and run_optimizer:
        from .evaluate import Context
        from .optimizer import run
        kw = {"plants": ["mint", "basil", "strawberry", "lettuce"], **(context or {})}   # API default plants
        ctx = Context(facade=str(facade).upper(), lat=lat, lon=lon, **kw)
        res = run(ctx, n_gen=40)
        designs = {k: {"result": v["result"]} for k, v in res["designs"].items()}
    if designs:
        rows = []
        for name in ("balanced", "shade_maximizer", "water_saver", "baseline"):
            d = designs.get(name)
            if not d:
                continue
            r = d["result"]
            rows.append({"name": name, "heat_reduction_pct": round(r["panel"]["heat_reduction_pct"], 1),
                         "solar_heat_kwh_day": round(r["objectives"]["heat_kwh_day"], 2),
                         "unshaded_solar_heat_kwh_day": round(r["panel"]["heat_unshaded_kwh_day"], 2)})
        out["designs"] = rows
        out["designs_note"] = ("Solar heat reaching the room through the window (kWh of heat per day), "
                               "not electricity. " + NOT_VALIDATED)
    return out


# ================================================================ retrieval
def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[إأآا]", "ا", s)


def retrieve(query, k=3):
    """Keyword + token overlap scoring over the official snippets. Returns [{id,title,text,source,url,score}]."""
    q = _norm(query)
    toks = set(re.findall(r"[\w؀-ۿ]{3,}", q))
    scored = []
    for d in KB:
        score = 0.0
        for kw in d["keywords"]:
            if _norm(kw) in q:
                score += 2.0
        body = _norm(d["title"] + " " + d["text"])
        score += 0.3 * sum(1 for t in toks if t in body)
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    return [{"id": d["id"], "title": d["title"], "text": d["text"], "source": d["source"], "url": d["url"],
             "score": round(s, 2)} for s, d in scored[:k]]


def detect_language(text):
    """'ar' (Modern Standard Arabic), 'darija' (Tunisian, Arabic or Latin script), 'fr' or 'en'."""
    t = text.lower()
    darija_words = r"\b(chnowa|chnoua|chniya|kifech|kifach|9adech|qadech|3lech|3leh|barcha|mte3|mta3|ya3tik|n7eb|nheb|" \
                   r"famma|fama|tawa|chbih|lfatoura|el fatoura|sa7a|ki|bech|mouch|mich)\b"
    if re.search(r"[؀-ۿ]", text):
        if re.search(r"(شنوة|شنية|علاش|برشا|متاع|قداش|كيفاش|توة|باش|موش|فما|نحب|الفاتورة متاعي|ياسر)", text):
            return "darija"
        return "ar"
    if re.search(darija_words, t) or re.search(r"\b\w*[3795]\w*[a-z]\w*\b", t) and re.search(r"[a-z][3795][a-z]", t):
        return "darija"
    if re.search(r"\b(le|la|les|est|pourquoi|comment|facture|ma|mon|une|des|combien|je)\b", t):
        return "fr"
    return "en"


# ================================================================ deterministic explanation
T = {
    "fr": {
        "intro": "Voici votre facture d'électricité expliquée simplement.",
        "cons": "Vous avez consommé {c} kWh{per}.",
        "per": " sur {d} jours, soit environ {kd} kWh par jour et {km} kWh par mois",
        "band": "À {m} kWh par mois, toute votre consommation est facturée {p} millimes le kWh (hors taxes), "
                "avec une TVA de {v} %.",
        "head": "Il vous reste environ {h} kWh par mois avant de passer à la tranche suivante ({np} millimes/kWh "
                "sur toute la consommation).",
        "actual": "Le relevé est RÉEL : il vient de la lecture de votre compteur.",
        "estimated": "Le relevé est ESTIMÉ : la STEG n'a pas pu lire le compteur et a estimé votre consommation à "
                     "partir des 24 derniers mois. Elle sera corrigée au prochain relevé réel.",
        "unknown_reading": "Nous ne savons pas si le relevé est réel ou estimé.",
        "match": "Nos calculs avec le tarif officiel de la STEG donnent le même montant que votre facture.",
        "partial": "Les lignes vérifiables correspondent au tarif officiel, mais le total n'a pas pu être entièrement vérifié.",
        "mismatch": "Certains montants diffèrent de notre calcul avec le tarif officiel.",
        "unavailable": "La vérification n'est pas possible pour l'instant : {r}",
        "fixed": "Les frais fixes (redevance de puissance) sont de {f} DT : ils sont dus même sans consommation.",
        "tips": "Conseils : réglez la climatisation à 26 °C (ANME), évitez la pointe de 11 h à 16 h en été, et "
                "entretenez les filtres.",
        "shade": "Un écran INBETWEEN réduit la chaleur solaire qui entre par la fenêtre, mais les économies "
                 "d'électricité n'ont pas encore été mesurées ni validées.",
    },
    "ar": {
        "intro": "هذا شرح مبسّط لفاتورة الكهرباء.",
        "cons": "استهلكت {c} كيلوواط ساعة{per}.",
        "per": " خلال {d} يومًا، أي حوالي {kd} كيلوواط ساعة في اليوم و{km} في الشهر",
        "band": "باستهلاك {m} كيلوواط ساعة في الشهر، يُحتسب كامل استهلاكك بسعر {p} مليم للكيلوواط ساعة "
                "(دون أداءات)، مع أداء على القيمة المضافة بنسبة {v}٪.",
        "head": "يبقى لك حوالي {h} كيلوواط ساعة في الشهر قبل المرور إلى الشريحة الموالية ({np} مليم على كامل الاستهلاك).",
        "actual": "القراءة حقيقية: مأخوذة من عدّادك.",
        "estimated": "القراءة تقديرية: لم تتمكن الستاغ من قراءة العداد فقدّرت استهلاكك حسب آخر 24 شهرًا، "
                     "وسيتم تعديلها عند القراءة الحقيقية القادمة.",
        "unknown_reading": "لا نعرف إن كانت القراءة حقيقية أم تقديرية.",
        "match": "حساباتنا بالتعريفة الرسمية للستاغ تعطي نفس مبلغ فاتورتك.",
        "partial": "الأسطر التي أمكن التحقق منها مطابقة للتعريفة الرسمية، لكن لم يمكن التحقق من المجموع كاملًا.",
        "mismatch": "بعض المبالغ تختلف عن حسابنا بالتعريفة الرسمية.",
        "unavailable": "التحقق غير ممكن حاليًا: {r}",
        "fixed": "المعاليم القارة (معلوم القدرة) تساوي {f} دينار، وهي مستوجبة حتى دون استهلاك.",
        "tips": "نصائح: اضبط المكيّف على 26 درجة (الوكالة الوطنية للتحكم في الطاقة)، وتجنّب وقت الذروة من 11 إلى 16 صيفًا، "
                "ونظّف المصافي بانتظام.",
        "shade": "شاشة INBETWEEN تقلّل حرارة الشمس الداخلة من النافذة، لكن الاقتصاد في الكهرباء لم يُقَس ولم يُثبت بعد.",
    },
    "darija": {
        "intro": "هاو شرح فاتورة الضو متاعك بالساهل.",
        "cons": "استهلكت {c} كيلوواط{per}.",
        "per": " في {d} يوم، يعني تقريب {kd} كيلوواط في النهار و{km} في الشهر",
        "band": "بـ{m} كيلوواط في الشهر، الستاغ تحسبلك الاستهلاك الكل بـ{p} مليم الكيلوواط (بلا أداءات)، "
                "والـTVA {v}٪.",
        "head": "باقيلك تقريب {h} كيلوواط في الشهر قبل ما تتعدى للشريحة اللي بعدها ({np} مليم على الاستهلاك الكل).",
        "actual": "القراية حقيقية: خذاوها من الكونتور متاعك.",
        "estimated": "القراية تقديرية: الستاغ ما قراتش الكونتور، قدّرت الاستهلاك على حساب آخر 24 شهر، "
                     "وتتصلّح في القراية الحقيقية الجاية.",
        "unknown_reading": "ما نعرفوش إذا القراية حقيقية ولا تقديرية.",
        "match": "حسبناها بالتعريفة الرسمية متاع الستاغ وطلعت كيف الفاتورة متاعك.",
        "partial": "السطور اللي نجمنا نثبتو فيها مطابقة، أما المجموع ما نجمناش نثبتو فيه الكل.",
        "mismatch": "فما مبالغ موش كيف الحساب متاعنا بالتعريفة الرسمية.",
        "unavailable": "ما نجموش نثبتو توة: {r}",
        "fixed": "المعاليم القارة (معلوم القدرة) {f} دينار، تخلصها حتى كان ما استهلكتش.",
        "tips": "نصايح: حط الكليماتيزور على 26 درجة (ANME)، بعّد على وقت الذروة من 11 لـ16 في الصيف، ونظّف الفيلتر.",
        "shade": "شاشة INBETWEEN تنقّص سخانة الشمس اللي تدخل من الشباك، أما الربح في الضو مازال ما تقاسش وما تثبتش.",
    },
    "en": {
        "intro": "Here is your electricity bill, explained simply.",
        "cons": "You used {c} kWh{per}.",
        "per": " over {d} days, about {kd} kWh per day and {km} kWh per month",
        "band": "At {m} kWh per month, all of your consumption is billed at {p} millimes per kWh (before tax), "
                "with {v} % VAT.",
        "head": "You have about {h} kWh per month left before moving to the next band ({np} millimes/kWh on "
                "all consumption).",
        "actual": "The reading is ACTUAL: it comes from your meter.",
        "estimated": "The reading is ESTIMATED: STEG could not read the meter and estimated your use from the last "
                     "24 months. It will be corrected at the next actual reading.",
        "unknown_reading": "We don't know whether the reading is actual or estimated.",
        "match": "Our calculation with the official STEG tariff gives the same amount as your bill.",
        "partial": "The lines we could check match the official tariff, but the total could not be fully verified.",
        "mismatch": "Some amounts differ from our calculation with the official tariff.",
        "unavailable": "Verification is not possible yet: {r}",
        "fixed": "Fixed charges (power fee) are {f} TND: they are due even without consumption.",
        "tips": "Tips: set the air conditioner to 26 °C (ANME), avoid the 11:00-16:00 summer peak, and clean filters.",
        "shade": "An INBETWEEN screen reduces the solar heat entering through the window, but electricity savings "
                 "have not yet been measured or validated.",
    },
}


def explain(bill, verification=None, lang="fr"):
    """Deterministic explanation (no LLM): every number comes from the bill or the tariff calculator."""
    L = T.get(lang, T["fr"])
    u = understand(bill, verification)
    parts = [L["intro"]]
    if u["consumption_kwh"] is not None:
        per = ""
        if u["days"]:
            per = L["per"].format(d=u["days"], kd=_fmt(u["kwh_per_day"], 2), km=_fmt(u["kwh_per_month"]))
        parts.append(L["cons"].format(c=_fmt(u["consumption_kwh"]), per=per))
    if u.get("band"):
        b = u["band"]
        parts.append(L["band"].format(m=_fmt(b["monthly_kwh"]), p=b["price_mill_per_kwh"],
                                      v=_fmt((b["vat_rate"] or 0) * 100)))
        if u.get("next_band") and u["next_band"]["next_price_mill_per_kwh"]:
            nb = u["next_band"]
            parts.append(L["head"].format(h=_fmt(nb["headroom_kwh_month"]), np=nb["next_price_mill_per_kwh"]))
    parts.append(L.get(u["reading_type"] or "unknown_reading", L["unknown_reading"]))
    if verification:
        st = verification.get("status")
        if st == "unavailable":
            parts.append(L["unavailable"].format(r=verification.get("summary", "").split(": ", 1)[-1]))
        elif st in L:
            parts.append(L[st])
        calc = verification.get("calculation") or {}
        fc = (calc.get("lines") or {}).get("fixed_charges_tnd")
        if fc is not None:
            parts.append(L["fixed"].format(f=_fmt(fc, 3)))
    parts.append(L["tips"])
    parts.append(L["shade"])
    sources = [TARIFF["sources"]["steg_web"]["url"], TARIFF["sources"]["steg_bill_guide"]["url"], ANME_AC["url"]]
    return {"text": "\n\n".join(parts), "paragraphs": parts, "lang": lang, "sources": sources, "understanding": u}


def _fmt(x, nd=1):
    if x is None:
        return "?"
    if nd == 3:
        return f"{x:.3f}"
    return f"{x:.{nd}f}".rstrip("0").rstrip(".")
