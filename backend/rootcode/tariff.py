"""
STEG low-voltage residential tariff calculator (deterministic, no LLM arithmetic).

All prices, fees and taxes come from data/steg_tariff.json, which cites the official STEG pages.
Money is computed with Decimal in millimes and returned in TND with 3 decimals (1 TND = 1000 millimes).

    from rootcode.tariff import compute, verify
    compute(consumption_kwh=420, months=2, power_kva=2)
    verify({"consumption_kwh": 420, "period_months": 2, "subscribed_power_kva": 2, "total_tnd": 101.2})

Status values returned by verify():
    "match"        the printed amount agrees with the official tariff (within tolerance)
    "mismatch"     it does not, with the identified possible causes
    "partial"      some lines could be checked, the total could not
    "unavailable"  essential data or tariff rules are missing: nothing is claimed
"""
import json
import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

TARIFF_PATH = os.getenv("ROOTCODE_TARIFF",
                        os.path.join(os.path.dirname(__file__), "..", "data", "steg_tariff.json"))

TOL_ABS = Decimal("0.100")     # TND: printed bills round each line to the millime
TOL_REL = Decimal("0.005")     # 0.5 %


def load_tariff(path=TARIFF_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


TARIFF = load_tariff()


def _d(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _tnd(millimes):
    """Decimal millimes -> float TND rounded to the millime."""
    return float((_d(millimes) / 1000).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def months_between(start, end):
    """Billing months from two ISO dates (rounded to the nearest whole month, >= 1)."""
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    days = (d1 - d0).days
    if days <= 0:
        raise ValueError("period end must be after period start")
    return max(1, round(days / 30.44)), days


def _band(monthly_kwh, category, t):
    for b in t["residential"]["bands"]:
        lo, hi = b["min_kwh_month"], b["max_kwh_month"]
        if monthly_kwh > lo and (hi is None or monthly_kwh <= hi) or (monthly_kwh == 0 and lo == 0):
            return b if category in b["applies_to"] else None
    return None


def _vat_rate(monthly_kwh, taxes):
    for r in taxes["vat_residential"]:
        if r["max_kwh_month"] is None or monthly_kwh <= r["max_kwh_month"]:
            return _d(r["rate"])
    return None


def compute(consumption_kwh, months=None, power_kva=None, taxes_variant="current",
            pricing_rule=None, tariff=None):
    """
    Electricity part of a residential STEG bill.
    Returns dict(status, lines{...} in TND, monthly_kwh, band, category, assumptions, missing, sources).
    status: "complete" | "partial" (some lines need missing inputs) | "unavailable".
    """
    t = tariff or TARIFF
    res = t["residential"]
    taxes = t["taxes"] if taxes_variant == "current" else t["previous_taxes_pdf_2022"]
    rule = pricing_rule or res["pricing_rule"]
    assumptions, missing, notes = [], [], []

    if consumption_kwh is None or consumption_kwh < 0:
        return {"status": "unavailable", "reason": "consumption (kWh) is missing", "missing": ["consumption_kwh"]}
    C = _d(consumption_kwh)
    if not months:
        months = t["billing"]["default_period_months"]
        assumptions.append(f"Billing period not given: assumed {months} months (STEG: \"{t['billing']['period_text']}\").")
    m = _d(months)
    monthly = C / m
    assumptions.append(t["billing"]["monthly_split_assumption"])

    if power_kva is None:
        missing.append("subscribed_power_kva")
        category = None
    else:
        category = "economic" if power_kva <= res["economic_max_kva"] else "normal"

    # ---- energy price
    if category is None:
        # bands above 100 kWh/month are identical for both categories
        category_for_price = "normal" if monthly > 100 else None
    else:
        category_for_price = category
    band = _band(monthly, category_for_price, t) if category_for_price else None
    lines = {}
    if band is None:
        reason = ("subscribed power (kVA) is needed to choose the tariff band below 100 kWh/month"
                  if category_for_price is None else res["unsupported_cases"][0])
        return {"status": "unavailable", "reason": reason, "missing": missing, "monthly_kwh": float(monthly),
                "assumptions": assumptions}

    if rule == "selective":
        energy_m = C * _d(band["price_mill_per_kwh"])
    else:   # band-by-band (used only to explain mismatches)
        energy_m = Decimal(0)
        for b in res["bands"]:
            if category_for_price not in b["applies_to"]:
                continue
            lo, hi = _d(b["min_kwh_month"]), b["max_kwh_month"]
            hi = monthly if hi is None else min(monthly, _d(hi))
            if hi > lo:
                energy_m += (hi - lo) * m * _d(b["price_mill_per_kwh"])
    lines["energy_tnd"] = energy_m

    # ---- power fee
    if power_kva is not None:
        lines["fixed_charges_tnd"] = _d(res["power_fee_mill_per_kva_month"]) * _d(power_kva) * m

    # ---- taxes
    vat = _vat_rate(monthly, taxes)
    lines["vat_tnd"] = energy_m * vat
    lines["municipal_tnd"] = C * _d(taxes["municipal_mill_per_kwh"])
    fte_exempt = category == "economic" and monthly <= 100
    if category is None and monthly <= 100:
        missing.append("subscribed_power_kva (FTE exemption)")
    lines["fte_tnd"] = Decimal(0) if fte_exempt else C * _d(taxes["fte_mill_per_kwh"])
    lines["taxes_tnd"] = lines["vat_tnd"] + lines["municipal_tnd"] + lines["fte_tnd"]

    complete = "fixed_charges_tnd" in lines
    if complete:
        lines["electricity_total_tnd"] = energy_m + lines["fixed_charges_tnd"] + lines["taxes_tnd"]
    out_lines = {k: _tnd(v) for k, v in lines.items()}
    return {
        "status": "complete" if complete else "partial",
        "lines": out_lines,
        "consumption_kwh": float(C), "months": float(m), "monthly_kwh": round(float(monthly), 1),
        "category": category, "band": {"price_mill_per_kwh": band["price_mill_per_kwh"], "footnote": band["footnote"]},
        "vat_rate": float(vat), "fte_exempt": fte_exempt, "pricing_rule": rule, "taxes_variant": taxes_variant,
        "assumptions": assumptions, "missing": missing, "notes": notes,
        "sources": [t["sources"]["steg_web"]["url"], t["sources"]["steg_pdf"]["url"]],
    }


def _close(a, b):
    a, b = _d(a), _d(b)
    return abs(a - b) <= max(TOL_ABS, TOL_REL * abs(b))


LINE_LABELS = {"energy_tnd": "Energy (consumption) amount", "fixed_charges_tnd": "Fixed charges (power fee)",
               "taxes_tnd": "Taxes", "electricity_total_tnd": "Electricity total"}


def verify(bill, tariff=None):
    """
    bill: corrected fields (plain numbers), any of
        consumption_kwh, index_previous, index_current, period_start, period_end, period_months,
        subscribed_power_kva, reading_type ('actual'|'estimated'), energy_amount_tnd, fixed_charges_tnd,
        taxes_tnd, electricity_total_tnd, other_charges_tnd, total_tnd
    Returns dict(status, summary, calculation, checks[], causes[], warnings[], ...).
    """
    t = tariff or TARIFF
    warnings, checks, causes = [], [], []

    C = bill.get("consumption_kwh")
    ip, ic = bill.get("index_previous"), bill.get("index_current")
    if ip is not None and ic is not None:
        diff = ic - ip
        if diff < 0:
            warnings.append("The new index is lower than the old one: check both readings (meter rollover or typo).")
        elif C is None:
            C = diff
        elif abs(diff - C) > 0.5:
            warnings.append(f"Index difference ({diff:g} kWh) differs from the printed consumption ({C:g} kWh). "
                            "Some bills add an estimated or regularised quantity; check the consumption line.")

    months = bill.get("period_months")
    days = None
    if bill.get("period_start") and bill.get("period_end"):
        try:
            mm, days = months_between(bill["period_start"], bill["period_end"])
            months = months or mm
        except ValueError as e:
            warnings.append(f"Billing period: {e}.")

    reading = bill.get("reading_type")
    if reading == "estimated":
        warnings.append("This bill uses an ESTIMATED reading: STEG computes it from your last 24 months "
                        "and corrects it on the next actual reading (" + t["sources"]["steg_bill_guide"]["url"] + ").")

    if C is None:
        return {"status": "unavailable", "summary": "Verification unavailable: the consumption in kWh is missing.",
                "checks": [], "causes": [], "warnings": warnings, "calculation": None}

    calc = compute(C, months, bill.get("subscribed_power_kva"), tariff=t)
    if calc["status"] == "unavailable":
        return {"status": "unavailable", "summary": f"Verification unavailable: {calc['reason']}.",
                "checks": [], "causes": [], "warnings": warnings, "calculation": calc}

    printed = {"energy_tnd": bill.get("energy_amount_tnd"), "fixed_charges_tnd": bill.get("fixed_charges_tnd"),
               "taxes_tnd": bill.get("taxes_tnd"), "electricity_total_tnd": bill.get("electricity_total_tnd")}
    if printed["electricity_total_tnd"] is None and bill.get("total_tnd") is not None:
        if bill.get("other_charges_tnd") is not None:
            printed["electricity_total_tnd"] = round(bill["total_tnd"] - bill["other_charges_tnd"], 3)
        else:
            warnings.append("The bill total may also include gas, the RTT contribution or arrears, which we cannot "
                            "verify. Enter those 'other charges' to compare the electricity part.")

    for key, val in printed.items():
        if val is None or key not in calc["lines"]:
            continue
        ok = _close(calc["lines"][key], val)
        checks.append({"line": key, "label": LINE_LABELS[key], "printed_tnd": val,
                       "calculated_tnd": calc["lines"][key], "difference_tnd": round(val - calc["lines"][key], 3),
                       "match": ok})

    if not checks:
        return {"status": "unavailable", "calculation": calc, "checks": [], "causes": [], "warnings": warnings,
                "summary": "Verification unavailable: no printed amount to compare with. Enter at least the "
                           "energy amount or the electricity total from your bill."}

    if all(c["match"] for c in checks):
        status = "match" if any(c["line"] == "electricity_total_tnd" for c in checks) and calc["status"] == "complete" \
            else "partial"
    else:
        status = "mismatch"
        causes = explain_mismatch(C, months, bill.get("subscribed_power_kva"), printed, t)
        if reading == "estimated":
            causes.append("The reading is estimated, so the quantity itself may differ from your real use; "
                          "the next actual reading corrects it.")
        if not causes:
            causes.append("We could not identify the cause. It may come from an item not covered by the published "
                          "tariff (regularisation, gas, other fees) or from a value read incorrectly. "
                          "Check the fields, or contact STEG.")

    summary = {
        "match": "The amounts on your bill agree with the official STEG tariff.",
        "partial": "The lines we could check agree with the official tariff; the total could not be fully verified.",
        "mismatch": "Some amounts differ from our calculation with the official tariff.",
    }[status]
    return {"status": status, "summary": summary, "calculation": calc, "checks": checks, "causes": causes,
            "warnings": warnings, "consumption_kwh": C, "period_days": days}


def explain_mismatch(C, months, power_kva, printed, t):
    """Try documented alternative hypotheses deterministically; report those that reproduce the bill."""
    hyps = [
        ("taxes of the 2022 tariff PDF (FTE 1 mill/kWh, VAT 13 %)", dict(taxes_variant="pdf_2022")),
        ("band-by-band pricing instead of a single band price", dict(pricing_rule="progressive")),
    ]
    if months and months != 1:
        hyps.append(("a one-month period for the band", dict(months=1)))
    if months != 2:
        hyps.append(("a two-month period (STEG bills are usually bimonthly)", dict(months=2)))
    found = []
    for label, kw in hyps:
        args = dict(consumption_kwh=C, months=months, power_kva=power_kva, tariff=t)
        args.update(kw)
        try:
            alt = compute(**args)
        except Exception:
            continue
        if alt["status"] == "unavailable":
            continue
        agree = [k for k, v in printed.items() if v is not None and k in alt["lines"]]
        if agree and all(_close(alt["lines"][k], printed[k]) for k in agree):
            found.append(f"The printed amounts are reproduced with {label}.")
    return found
