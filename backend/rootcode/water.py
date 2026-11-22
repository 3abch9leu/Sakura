"""
Water budget for the integrated reservoirs (one reservoir group per hidden branch).

A transparent daily balance, not a prediction model:

    need(day)   = sum over the branch's plants of  PLANT_DEMAND_L_DAY[plant]      (HydroEngine table)
                  x sun factor (0.6 + 0.4 * cell exposure / 4 kWh/m2)              (same rule as evaluate.py)
                  x heat factor 1 + 0.04 * (Tmax - 28 C), clipped 0.7..1.6        (ASSUMPTION, stated in the UI)
                  x humidity factor 1 + 0.5 * (0.55 - RH), clipped 0.85..1.2      (ASSUMPTION)
                  / (1 - losses)                                                  (evaporation, overflow, leaks)
    rain(day)   = forecast rain (mm = L/m2) x collector area x efficiency, only when a collector exists
    required    = sum of net need until the next planned refill, x (1 + safety margin)

The warning threshold is therefore DYNAMIC: required / capacity, recomputed with the plants, the sun, the
forecast, the losses, the rain and the refill plan - never a fixed "20 % low" level.
"""
import json
import math
import threading
import time
import urllib.request

from . import config as C

HEAT_COEF = 0.04
HEAT_REF_C = 28.0


def factors(tmax_c, rh):
    heat = min(1.6, max(0.7, 1 + HEAT_COEF * ((tmax_c if tmax_c is not None else HEAT_REF_C) - HEAT_REF_C)))
    hum = min(1.2, max(0.85, 1 + 0.5 * (0.55 - (rh if rh is not None else 0.55))))
    return heat, hum


def branch_budget(branch, level_frac, days, losses=0.15, safety=0.2, hours_to_refill=48.0,
                  collector_m2=0.0, collector_eff=0.8, level_source="estimated"):
    """
    branch: {"id", "capacity_l", "need_l_day" (sun-scaled base need), "plants": [...]}.
    days: forecast list [{"date", "tmax_c", "rh", "rain_mm"}] starting today.
    """
    cap = float(branch["capacity_l"])
    remaining = max(0.0, min(1.0, float(level_frac))) * cap
    base = float(branch["need_l_day"])
    timeline, req, left, t_out = [], 0.0, remaining, None
    hours_left = hours_to_refill
    for i, d in enumerate(days[:4] or [{"date": None, "tmax_c": None, "rh": None, "rain_mm": 0}]):
        heat, hum = factors(d.get("tmax_c"), d.get("rh"))
        gross = base * heat * hum / (1 - losses)
        rain = (d.get("rain_mm") or 0) * collector_m2 * collector_eff
        net = max(0.0, gross - rain)
        timeline.append({"date": d.get("date"), "need_l": round(gross, 3), "rain_gain_l": round(rain, 3),
                         "net_l": round(net, 3), "heat_factor": round(heat, 2), "humidity_factor": round(hum, 2),
                         "tmax_c": d.get("tmax_c"), "rain_mm": d.get("rain_mm")})
        frac = min(1.0, hours_left / 24) if hours_left > 0 else 0.0
        req += net * frac
        hours_left -= 24
        if t_out is None:
            if net > 0 and left < net:
                t_out = i * 24 + 24 * left / net
            left -= net
    req_safe = req * (1 + safety)
    today = timeline[0]["net_l"]
    tomorrow = timeline[1]["net_l"] if len(timeline) > 1 else today
    autonomy_h = t_out if t_out is not None else len(timeline) * 24.0
    threshold = min(1.0, req_safe / cap) if cap > 0 else 1.0

    alerts = []
    if remaining <= 0.02 * cap or (today > 0 and remaining < today * 0.25):
        alerts.append({"level": "critical", "code": "INTERRUPT", "title": "Possible irrigation interruption",
                       "text": f"Only {remaining:.2f} L left: the plants of this branch may stop receiving water within hours."})
    elif remaining < today + tomorrow:
        alerts.append({"level": "warning", "code": "TOMORROW", "title": "Insufficient water for tomorrow",
                       "text": f"{remaining:.2f} L left, about {today + tomorrow:.2f} L needed for today and tomorrow."})
    if remaining < req_safe and not any(a["code"] == "INTERRUPT" for a in alerts):
        alerts.append({"level": "warning" if remaining >= req else "critical", "code": "REFILL",
                       "title": "Reservoir refill recommended",
                       "text": f"Until the planned refill in {hours_to_refill:.0f} h the plants need about {req:.2f} L "
                               f"(+{int(safety * 100)} % margin = {req_safe:.2f} L); {remaining:.2f} L are available. "
                               f"Add at least {max(0.0, req_safe - remaining):.2f} L."})
    hot = [d for d in timeline[:2] if (d["tmax_c"] or 0) >= 32]
    if hot:
        alerts.append({"level": "info", "code": "HEAT", "title": "Hot weather may increase water requirements",
                       "text": f"Up to {max(d['tmax_c'] for d in hot):.0f} °C expected: the plants' need rises by about "
                               f"{(max(d['heat_factor'] for d in hot) - 1) * 100:.0f} % in this model."})
    if any((d["rain_mm"] or 0) > 2 for d in timeline[:2]) and collector_m2 > 0:
        alerts.append({"level": "info", "code": "RAIN", "title": "Rain expected",
                       "text": "The collector should add water: the refill can wait if the forecast holds."})
    status = "critical" if any(a["level"] == "critical" for a in alerts) else \
             "warning" if any(a["level"] == "warning" for a in alerts) else "ok"
    return {
        "id": branch["id"], "plants": branch.get("plants", []), "capacity_l": round(cap, 3),
        "level_frac": round(remaining / cap, 4) if cap else 0.0, "remaining_l": round(remaining, 3),
        "level_source": level_source, "need_today_l": round(today, 3), "need_tomorrow_l": round(tomorrow, 3),
        "required_until_refill_l": round(req_safe, 3), "dynamic_threshold_frac": round(threshold, 4),
        "autonomy_hours": round(autonomy_h, 1), "status": status, "alerts": alerts, "timeline": timeline,
        "refill_l": round(max(0.0, min(cap, req_safe) - remaining), 3),
    }


# ---------------------------------------------------------------- sensors (Arduino bridge or simulation)
_SENS = {"reading": None, "history": []}
_LOCK = threading.Lock()


def put_reading(r):
    r = dict(r)
    r["ts"] = time.time()
    if r.get("level_frac") is None and r.get("level_raw") is not None:      # potentiometer 0..1023
        lo, hi = float(r.get("raw_min", 0)), float(r.get("raw_max", 1023))
        r["level_frac"] = max(0.0, min(1.0, (float(r["level_raw"]) - lo) / max(1.0, hi - lo)))
    with _LOCK:
        _SENS["reading"] = r
        _SENS["history"] = (_SENS["history"] + [r])[-500:]
    return r


def get_reading(max_age_s=120):
    with _LOCK:
        r = _SENS["reading"]
        hist = list(_SENS["history"][-120:])
    if r and time.time() - r["ts"] > max_age_s:
        r = dict(r, stale=True)
    return r, hist


# ---------------------------------------------------------------- weather (Open-Meteo, no key, cached)
_WX = {}


def forecast(lat, lon, days=4):
    """Daily Tmax / mean RH / rain for the next days. Only the rounded coordinates leave the server."""
    key = (round(lat, 2), round(lon, 2))
    hit = _WX.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%.2f&longitude=%.2f"
           "&daily=temperature_2m_max,precipitation_sum,relative_humidity_2m_mean&timezone=auto&forecast_days=%d"
           % (key[0], key[1], days))
    with urllib.request.urlopen(url, timeout=6) as r:
        d = json.load(r)["daily"]
    out = [{"date": d["time"][i], "tmax_c": d["temperature_2m_max"][i],
            "rh": (d.get("relative_humidity_2m_mean") or [None] * len(d["time"]))[i] / 100
            if (d.get("relative_humidity_2m_mean") or [None])[i] is not None else None,
            "rain_mm": d["precipitation_sum"][i]} for i in range(len(d["time"]))]
    _WX[key] = (time.time(), out)
    return out


def alert_for_device(statuses):
    """Most severe alert -> what the Arduino LCD (16x2) and buzzer should show."""
    order = {"critical": 0, "warning": 1, "info": 2}
    alerts = [(order[a["level"]], a, s) for s in statuses for a in s["alerts"]]
    if not alerts:
        best = min(statuses, key=lambda s: s["autonomy_hours"]) if statuses else None
        return {"code": "OK", "buzz": False, "line1": "INBETWEEN  OK",
                "line2": (f"Autonomy {best['autonomy_hours']:.0f}h" if best else "")[:16]}
    _, a, s = min(alerts, key=lambda t: t[0])
    short = {"INTERRUPT": "WATER: EMPTY!", "TOMORROW": "Low for tomorrow", "REFILL": "Refill advised",
             "HEAT": "Hot: more water", "RAIN": "Rain expected"}.get(a["code"], a["code"])
    return {"code": a["code"], "buzz": a["level"] == "critical", "line1": short[:16],
            "line2": f"B{s['id'] + 1} {s['remaining_l']:.1f}L {s['autonomy_hours']:.0f}h"[:16]}
