"""
One cultural style, end to end (geometry -> winter shading -> NSGA-II channels -> SVG), as a plain function so
the API can run the styles in parallel worker processes (each style is independent).
"""


def run_style(sid, area, plants, summer, winter, cls, water_l_day, az, lat, lon, rh, prices, greenery="full"):
    from . import styles as S
    from . import stylerender
    try:
        gen = S.generate(sid, area, plants, summer, water_l_day, cls, greenery)
    except ValueError as e:
        return {"style": sid, "name": S.STYLES[sid]["name"], "error": str(e)}
    wf = S.direct_fractions(gen, winter)
    for c in gen["cells"]:
        c["direct_fraction_winter"] = wf[c["id"]]["direct_fraction"]
        c["exposure_winter_kwh_m2"] = wf[c["id"]]["exposure_kwh_m2"]
    gen["water"] = water_summary(gen)
    opt = S.optimise(gen, plants, str(az), lat, lon, "2026-07-15", water_l_day, rh)
    m = gen["metrics"]
    cost = None
    if prices:
        try:
            cost = round(m["frame_length_m"] * float(prices["frame_tnd_per_m"]) + m["screen_m2"] * float(prices["screen_tnd_per_m2"])
                         + m["planting_cells"] * float(prices["pocket_tnd"]), 1)
        except (KeyError, TypeError, ValueError):
            cost = None
    summary = None
    if opt["feasible"]:
        r = opt["result"]
        summary = {"heat_reduction_pct": r["panel"]["heat_reduction_pct"], "water_l_day": r["objectives"]["water_l_day"],
                   "plant_deficit": r["objectives"]["plant_deficit"], "drain_time_min": r["hydraulics"]["drain_time_min"],
                   "reynolds_max": r["hydraulics"]["reynolds_max"], "widths_mm": opt["design"]["widths_mm"],
                   "water_per_root_tile_l": opt["design"]["water_l_day"], "plant_safe": opt["plant_safe"]}
    gen["svg"] = stylerender.svg(gen)
    gen["fit"] = (S.fit_label(cls, m["open_fraction"]) if greenery != "full"
                  else "full green wall: the sun chooses the plant of each pocket")
    gen["optimisation"] = {"feasible": opt["feasible"], "summary": summary,
                           "message": opt.get("message") or opt.get("engine_note")}
    gen["cost_tnd"] = cost
    gen["cost_note"] = None if cost is not None else "Cost not estimated: no reliable local prices given."
    gen["context"] = {"lat": lat, "lon": lon, "facade_azimuth": az}
    return gen


def water_summary(gen):
    """What the design asks of the owner, from its own plants and sun (HydroEngine demand table): the answer to
    "how much water will I have to give?", instead of asking it before the design exists."""
    from . import styles as S
    from .config import PLANT_DEMAND_L_DAY  # noqa: F401  (same table as plant_demand_l)
    pc = [c for c in gen["cells"] if c.get("role") == "plant"]
    summer = sum(c["need_l_day"] for c in pc)
    winter = sum(S.plant_demand_l(c["plant"], c.get("exposure_winter_kwh_m2", c["exposure_kwh_m2"])) for c in pc)
    losses = 1 / 0.85                       # same 15 % margin (drip, evaporation) as the planting rule
    storage = gen["metrics"]["storage_l"]
    per_plant = {}
    for c in pc:
        per_plant[c["plant"]] = per_plant.get(c["plant"], 0) + 1
    hand = sum(1 for c in pc if c.get("hand_watered"))
    out = {"hand_watered_pockets": hand, "summer_l_day": round(summer * losses, 2), "winter_l_day": round(winter * losses, 2),
           "storage_l": storage, "pockets": len(pc), "per_plant": per_plant,
           "refill_days_summer": round(storage / (summer * losses), 1) if summer > 0 else None,
           "refill_days_winter": round(storage / (winter * losses), 1) if winter > 0 else None,
           "basis": "Plant demand (HydroEngine table) scaled by each pocket's computed sun, +15 % for drip and "
                    "evaporation. Clear-sky model: a planning estimate, not a measurement."}
    return out


def ignore_ctrl_c():
    """Pool initializer: Ctrl+C stops the server (the parent); workers must not print a traceback each."""
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def ping():
    """Warm-up: imports pymoo, shapely, pvlib in the worker so the first real request does not pay for it."""
    from . import styles  # noqa: F401
    from . import stylerender  # noqa: F401
    return True
