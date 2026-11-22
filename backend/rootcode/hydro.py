"""
HydroEngine - gravity-fed water distribution through the tile channels.

Model
-----
A tank above the tile drains through one channel per pocket (+ an optional cooling branch).
Each channel is a laminar rectangular duct (Hagen-Poiseuille with the standard
rectangular-section correction):

    R_i = 12 * mu * L_i / (a * b^3 * (1 - 0.63 b/a)),  a = max(w, d), b = min(w, d)
    Q_i(t) = k_i * rho * g * (h(t) + z_i) / R_i

h(t) is the water height in the tank (it falls as the tank drains), z_i is the vertical
drop from the manifold to outlet i and k_i is an optional calibration factor measured
on the real prototype (default 1). Because every Q_i is linear in h, the drain-down
integral has a closed form, so one evaluation costs microseconds - no surrogate needed.

Limits (say these out loud if a juror asks): mm-scale channels can run partly full,
trap air bubbles and lose energy at bends and entrances. That is why `calibration`
exists: pour a known volume, weigh what each pocket receives, fit k_i.
"""
import math
import numpy as np
from . import config as C
from .tile import pocket_layout, cooling_route


def channel_resistance(width_m, depth_m, length_m):
    a, b = max(width_m, depth_m), min(width_m, depth_m)
    return 12.0 * C.MU_WATER * length_m / (a * b ** 3 * (1.0 - 0.63 * b / a))


def _route_len(route):
    return sum(math.dist(p, q) for p, q in zip(route, route[1:]))


def branches(design, calibration=None):
    """Return list of dicts (name, conductance G=k/R, drop z, width, depth) for every open branch."""
    calibration = calibration or {}
    out = []
    for i, (p, w_mm) in enumerate(zip(pocket_layout(design.plants), design.widths_mm)):
        R = channel_resistance(w_mm / 1000, C.CHANNEL_DEPTH, p.length)
        k = calibration.get(f"pocket_{i}", 1.0)
        out.append(dict(name=f"pocket_{i}", plant=p.plant, G=k / R, z=p.drop,
                        w=w_mm / 1000, length=p.length))
    if design.cooling_open:
        route = cooling_route()
        L = _route_len(route)
        R = channel_resistance(design.cool_width_mm / 1000, C.CHANNEL_DEPTH, L)
        k = calibration.get("cooling", 1.0)
        out.append(dict(name="cooling", plant=None, G=k / R, z=route[-1][1] - route[0][1],
                        w=design.cool_width_mm / 1000, length=L))
    return out


def distribute(design, calibration=None):
    """
    Pour `design.water_l_day` litres into the tank and let it drain.
    Returns litres received by each branch, the drain time and a laminar-flow check.
    """
    br = branches(design, calibration)
    A = C.TANK_AREA_PER_TILE
    V0 = design.water_l_day / 1000.0          # m3
    u0 = V0 / A                                # initial water height in tank (m)
    rg = C.RHO_WATER * C.G
    G = np.array([b["G"] for b in br]) * rg    # m3/s per metre of head
    c = np.array([C.TANK_BASE_HEAD + b["z"] for b in br])
    S, B = G.sum(), (G * c).sum()

    # closed-form integral of Q_i over the whole drain-down
    #   vol_i = A*G_i * [ u0/S + (c_i - B/S)/S * ln((B + S u0)/B) ]
    log_term = math.log((B + S * u0) / B)
    vol = A * G * (u0 / S + (c - B / S) / S * log_term)
    vol = np.clip(vol, 0, None)
    vol *= V0 / vol.sum()                      # remove rounding drift, conserve mass
    drain_time_s = (A / S) * log_term

    # laminar check at the start (highest flow)
    q0 = G * (c + u0)
    re_max = 0.0
    for b, q in zip(br, q0):
        area = b["w"] * C.CHANNEL_DEPTH
        dh = 2 * area / (b["w"] + C.CHANNEL_DEPTH)
        re_max = max(re_max, (q / area) * dh / C.NU_WATER)

    litres = {b["name"]: float(v * 1000) for b, v in zip(br, vol)}
    return {
        "litres": litres,
        "plants": {b["name"]: b["plant"] for b in br if b["plant"]},
        "drain_time_min": float(drain_time_s / 60),
        "reynolds_max": float(re_max),
        "laminar": bool(re_max < 2000),
    }


def evenness(received, demand):
    """Coefficient of variation of (received / demand) across pockets. 0 = perfectly matched."""
    r = np.array(received) / np.array(demand)
    return float(r.std() / r.mean()) if r.mean() > 0 else float("inf")
