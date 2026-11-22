"""
Evaluate one tile design in one context -> the three objectives and readable metrics.

Objectives (all minimised, per window panel per day):
  W  water used (L/day)
  H  heat gain reaching the room through the window (kWh/day), after evaporative cooling
  D  plant water deficit (0 = every plant gets its need, 1 = no plant gets anything)
"""
from dataclasses import dataclass, field
import math
import numpy as np
from . import config as C
from .hydro import distribute, evenness
from .solar import facade_sun, screen_transmission
from .tile import effective_porosity, pocket_area_fraction


@dataclass
class Context:
    plants: list
    lat: float = C.DEFAULT_LAT
    lon: float = C.DEFAULT_LON
    facade: str = "W"                    # N, NE, E, SE, S, SW, W, NW or an azimuth in degrees
    date: str = "2026-07-15"
    rh: float = 0.55                     # daytime relative humidity (0-1)
    window_w: float = 1.2                # m
    window_h: float = 1.4                # m
    root_tiles: int = 4                  # tiles carrying plant pockets; the others are shade-only
    water_available_l_day: float = 6.0   # litres the household can spare per day for this window
    calibration: dict = field(default_factory=dict)

    @property
    def azimuth(self):
        return float(C.FACADE_AZIMUTHS.get(str(self.facade).upper(), self.facade))

    @property
    def n_tiles(self):
        return max(1, math.ceil(self.window_w / C.TILE_W) * math.ceil(self.window_h / C.TILE_H))

    def sun(self):
        return facade_sun(self.lat, self.lon, self.azimuth, self.date)


def plant_demand(ctx, sun):
    scale = 0.6 + 0.4 * sun["daily_kwh_m2"] / C.REF_FACADE_IRRADIATION
    return np.array([C.PLANT_DEMAND_L_DAY[p] * scale for p in ctx.plants])


def evaluate(design, ctx):
    sun = ctx.sun()
    n = ctx.n_tiles
    tile_area = C.TILE_W * C.TILE_H

    # ---- water distribution (HydroEngine)
    hyd = distribute(design, ctx.calibration)
    pocket_names = [f"pocket_{i}" for i in range(len(ctx.plants))]
    received = np.array([hyd["litres"].get(k, 0.0) for k in pocket_names])
    demand = plant_demand(ctx, sun)
    deficit = float(np.clip(demand - received, 0, None).sum() / demand.sum())
    drained = float(np.clip(received - C.POCKET_CAPACITY_FACTOR * demand, 0, None).sum())

    # ---- evaporative cooling (optional path)
    cool_water = hyd["litres"].get("cooling", 0.0)
    dryness = float(np.clip((1 - ctx.rh) / 0.5, 0, 1.6))
    sunfac = 0.5 + 0.5 * sun["daily_kwh_m2"] / C.REF_FACADE_IRRADIATION
    evap_cap = C.EVAP_RATE_REF * C.COOL_STRIP_AREA * dryness * sunfac       # L/day
    evaporated = min(cool_water, evap_cap)
    cooling_kwh = evaporated * C.LATENT_HEAT / 3.6e6 * C.COOLING_COUPLING  # 1 L = 1 kg
    drained += max(0.0, cool_water - evap_cap)

    # ---- solar heat gain (Solar Intelligence)
    tr, inc = screen_transmission(sun, design.porosity, design.aperture_mm / 1000, design.screen_depth)
    T = tr.sum() * sun["dt_h"] / 1000      # kWh/m2/day transmitted through open screen
    I = inc.sum() * sun["dt_h"] / 1000     # kWh/m2/day incident on facade

    def tile_gain(blocked):
        open_a, block_a = tile_area * (1 - blocked), tile_area * blocked
        return (C.WINDOW_SHGC * T * open_a
                + C.SECONDARY_GAIN * C.SCREEN_ABSORPTANCE * (I - T) * open_a
                + C.SECONDARY_GAIN * C.SCREEN_ABSORPTANCE * I * block_a)

    n_root = min(ctx.root_tiles, n)
    n_shade = n - n_root
    root_blocked = min(1.0, pocket_area_fraction(len(ctx.plants)) + C.COOL_STRIP_AREA / tile_area)
    heat_root = max(0.0, tile_gain(root_blocked) - cooling_kwh)
    heat_shade = tile_gain(0.0)
    unshaded_tile = C.WINDOW_SHGC * I * tile_area

    W = design.water_l_day * n_root
    H = heat_root * n_root + heat_shade * n_shade
    eff_p = effective_porosity(design)

    return {
        "objectives": {"water_l_day": W, "heat_kwh_day": H, "plant_deficit": deficit},
        "constraints": {
            "porosity_ok": eff_p >= C.MIN_EFFECTIVE_POROSITY,
            "water_ok": W <= ctx.water_available_l_day,
            "slow_drip_ok": hyd["drain_time_min"] >= C.MIN_DRAIN_MIN,
            "laminar_ok": hyd["reynolds_max"] <= C.MAX_REYNOLDS,
        },
        "panel": {
            "n_tiles": n,
            "root_tiles": n_root,
            "shade_tiles": n_shade,
            "heat_unshaded_kwh_day": unshaded_tile * n,
            "heat_reduction_pct": 100 * (1 - H / (unshaded_tile * n)) if unshaded_tile > 0 else 0.0,
            "evaporative_cooling_kwh_day": cooling_kwh * n_root,
            "water_drained_l_day": drained * n_root,
            "effective_porosity": eff_p,
        },
        "pockets": [
            {"plant": p, "received_l": float(r), "need_l": float(d), "ratio": float(r / d)}
            for p, r, d in zip(ctx.plants, received, demand)
        ],
        "distribution_cv": evenness(received, demand),
        "cooling_water_l_tile": cool_water,
        "hydraulics": {k: hyd[k] for k in ("drain_time_min", "reynolds_max", "laminar")},
        "litres_per_branch": hyd["litres"],
        "facade_irradiation_kwh_m2_day": sun["daily_kwh_m2"],
    }
