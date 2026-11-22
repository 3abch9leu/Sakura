"""
Sun path on a facade for one day: position of the sun (for the 3D light) and clear-sky irradiance on the
vertical surface (pvlib, same Ineichen model as solar.py). Used by the design studio's time slider,
the style generator (self-shading per cell) and the digital twin's environmental view.

Clear sky = no clouds and no surrounding buildings or trees: an upper bound, not a measurement.
"""
from functools import lru_cache

import numpy as np
import pandas as pd
import pvlib

from . import config as C

SEASONS = {"summer": "06-21", "winter": "12-21", "equinox": "03-20", "design": "07-15"}


@lru_cache(maxsize=64)
def day(lat=C.DEFAULT_LAT, lon=C.DEFAULT_LON, facade_azimuth=270.0, date="2026-07-15", tz=C.DEFAULT_TZ,
        step_min=15):
    loc = pvlib.location.Location(lat, lon, tz)
    times = pd.date_range(f"{date} 00:00", f"{date} 23:59", freq=f"{step_min}min", tz=tz)
    sp = loc.get_solarposition(times)
    cs = loc.get_clearsky(times, model="ineichen")
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=90, surface_azimuth=facade_azimuth, solar_zenith=sp["apparent_zenith"],
        solar_azimuth=sp["azimuth"], dni=cs["dni"], ghi=cs["ghi"], dhi=cs["dhi"], albedo=0.25)
    el = (90 - sp["apparent_zenith"]).to_numpy()
    az = sp["azimuth"].to_numpy()
    up = el > 0
    gamma = np.radians(((az - facade_azimuth + 180) % 360) - 180)        # sun vs. wall normal
    alt = np.radians(np.clip(el, 0, 90))
    cosg = np.cos(gamma)
    facing = up & (cosg > 1e-3)
    tan_v = np.where(facing, np.tan(alt) / np.where(facing, cosg, 1), 0.0)   # vertical profile angle
    tan_h = np.where(facing, np.tan(gamma), 0.0)                              # signed horizontal angle
    beam = np.where(facing, poa["poa_direct"].fillna(0).clip(lower=0).to_numpy(), 0.0)
    diffuse = np.where(up, poa["poa_diffuse"].fillna(0).clip(lower=0).to_numpy(), 0.0)
    idx = np.where(up)[0]
    if len(idx) == 0:
        raise ValueError("the sun does not rise on this date at this latitude")
    i0, i1 = max(0, idx[0] - 1), min(len(times) - 1, idx[-1] + 1)
    dt_h = step_min / 60
    sel = slice(i0, i1 + 1)
    return {
        "date": date, "azimuth_facade": facade_azimuth, "lat": lat, "lon": lon, "step_min": step_min,
        "times": [t.strftime("%H:%M") for t in times[sel]],
        "sun_azimuth": az[sel].round(2).tolist(), "sun_elevation": el[sel].round(2).tolist(),
        "facing": facing[sel].tolist(), "tan_v": tan_v[sel].round(4).tolist(), "tan_h": tan_h[sel].round(4).tolist(),
        "beam_w_m2": beam[sel].round(1).tolist(), "diffuse_w_m2": diffuse[sel].round(1).tolist(),
        "sunrise": times[idx[0]].strftime("%H:%M"), "sunset": times[idx[-1]].strftime("%H:%M"),
        "direct_hours": round(float(facing.sum() * dt_h), 2),
        "daily_kwh_m2": round(float((beam + diffuse).sum() * dt_h / 1000), 3),
        "daily_direct_kwh_m2": round(float(beam.sum() * dt_h / 1000), 3),
        "peak_w_m2": round(float((beam + diffuse).max()), 1),
        "dt_h": dt_h,
    }


def seasons(lat, lon, facade_azimuth, year=2026):
    out = {}
    for k in ("summer", "winter"):
        d = day(lat, lon, float(facade_azimuth), f"{year}-{SEASONS[k]}")
        out[k] = {x: d[x] for x in ("date", "sunrise", "sunset", "direct_hours", "daily_kwh_m2", "daily_direct_kwh_m2", "peak_w_m2")}
    return out


def exposure_class(summer_kwh):
    """Clear-sky summer irradiation on the facade -> design guidance class (thresholds stated in the UI)."""
    if summer_kwh >= 3.5:
        return "high"
    if summer_kwh >= 2.0:
        return "moderate"
    return "low"
