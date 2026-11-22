"""
Solar Intelligence - sun on the facade and how much of it passes through the tile screen.

pvlib gives sun position and clear-sky irradiance on the vertical facade. Clear sky is an
upper bound (the worst hot day), which is what a shading design should be sized for.

Screen model: a perforated screen of depth t with apertures of size a. Direct sun passes
only where the aperture is not shadowed by its own walls, in both the vertical and the
horizontal direction (profile-angle method used for louvres and egg-crate shading):

    tau_beam    = p * max(0, 1 - t*tan(profile_v)/a) * max(0, 1 - t*tan(|gamma|)/a)
    tau_diffuse = p * a / (a + t)          (crude view-factor approximation)
"""
from functools import lru_cache
import numpy as np
import pandas as pd
import pvlib
from . import config as C


@lru_cache(maxsize=32)
def facade_sun(lat=C.DEFAULT_LAT, lon=C.DEFAULT_LON, facade_azimuth=270.0,
               date="2026-07-15", tz=C.DEFAULT_TZ, freq="10min"):
    """Precompute everything the screen model needs for one design day (cached)."""
    loc = pvlib.location.Location(lat, lon, tz)
    times = pd.date_range(f"{date} 00:00", f"{date} 23:59", freq=freq, tz=tz)
    sp = loc.get_solarposition(times)
    cs = loc.get_clearsky(times, model="ineichen")
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=90, surface_azimuth=facade_azimuth,
        solar_zenith=sp["apparent_zenith"], solar_azimuth=sp["azimuth"],
        dni=cs["dni"], ghi=cs["ghi"], dhi=cs["dhi"], albedo=0.25,
    )
    beam = poa["poa_direct"].fillna(0).clip(lower=0).to_numpy()
    diffuse = poa["poa_diffuse"].fillna(0).clip(lower=0).to_numpy()

    alt = np.radians(np.clip(90 - sp["apparent_zenith"].to_numpy(), 0, 90))
    gamma = np.radians(((sp["azimuth"].to_numpy() - facade_azimuth + 180) % 360) - 180)
    cosg = np.cos(gamma)
    facing = (cosg > 1e-3) & (alt > 0)
    tan_v = np.where(facing, np.tan(alt) / np.where(facing, cosg, 1), 0.0)
    tan_h = np.where(facing, np.abs(np.tan(gamma)), 0.0)
    beam = np.where(facing, beam, 0.0)

    dt_h = pd.Timedelta(freq).total_seconds() / 3600
    return {
        "times": times, "beam": beam, "diffuse": diffuse,
        "tan_v": tan_v, "tan_h": tan_h, "dt_h": dt_h,
        "daily_kwh_m2": float((beam + diffuse).sum() * dt_h / 1000),
    }


def screen_transmission(sun, porosity, aperture_m, depth_m):
    """Return (transmitted, incident) irradiance time series in W/m2 for the open screen area."""
    fv = np.clip(1 - depth_m * sun["tan_v"] / aperture_m, 0, 1)
    fh = np.clip(1 - depth_m * sun["tan_h"] / aperture_m, 0, 1)
    tau_beam = porosity * fv * fh
    tau_diff = porosity * aperture_m / (aperture_m + depth_m)
    transmitted = sun["beam"] * tau_beam + sun["diffuse"] * tau_diff
    incident = sun["beam"] + sun["diffuse"]
    return transmitted, incident


def peak_hour(sun):
    i = int(np.argmax(sun["beam"] + sun["diffuse"]))
    return sun["times"][i].strftime("%H:%M")
