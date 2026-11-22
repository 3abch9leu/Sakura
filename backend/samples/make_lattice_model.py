"""
INBETWEEN lattice prototype: geometry + HydroEngine + SolarEngine numbers for the 3D viewer.

Geometry: an asanoha-based triangular lattice, 4 rows x 6 cells = 24 cells, side 0.30 m.
  - upward cells (flat floor) can hold a planting insert, with a water compartment in their floor beam
  - downward cells stay open or carry an asanoha / sakura shading insert
Water: a supply tube enters at the top. Internal channels follow only downward or level struts
(gravity) to each planting cell's floor compartment. Each compartment inlet is a small moulded
micro-channel whose width is tuned so every plant receives its daily need.

Hydraulics reuse rootcode.hydro.channel_resistance (Hagen-Poiseuille, rectangular section) and the
same closed-form header drain-down used by HydroEngine.distribute.
Writes front/public/data/lattice-model.json for the landing-page prototype (app/home/lattice.ts).

    python samples/make_lattice_model.py
"""
import heapq
import os
import sys
import json
import math

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rootcode import config as C  # noqa: E402
from rootcode.hydro import channel_resistance
from rootcode.solar import facade_sun

S = 0.30
H = S * math.sqrt(3) / 2
ROWS, PER = 4, 3
BASE_Y = 0.30
X_SHIFT = -0.525

# ---------------------------------------------------------------- geometry
verts, vindex = [], {}


def vid(x, y):
    key = (round(x, 4), round(y, 4))
    if key not in vindex:
        vindex[key] = len(verts)
        verts.append([round(x + X_SHIFT, 4), round(y, 4)])
    return vindex[key]


cells, edges = [], set()
for r in range(ROWS):
    yb, yt = BASE_Y + r * H, BASE_Y + (r + 1) * H
    off = 0 if r % 2 == 0 else S / 2
    B = lambda i: vid(off + i * S, yb)
    if off == 0:
        T = lambda j: vid(S / 2 + j * S, yt)
        ups = [(B(i), B(i + 1), T(i)) for i in range(PER)]
        downs = [(T(i), T(i + 1), B(i + 1)) for i in range(PER)]
    else:
        T = lambda j: vid(j * S, yt)
        ups = [(B(i), B(i + 1), T(i + 1)) for i in range(PER)]
        downs = [(T(i), T(i + 1), B(i)) for i in range(PER)]
    for i in range(PER):
        for kind, tri in (("up", ups[i]), ("down", downs[i])):
            cells.append({"id": len(cells), "row": r, "kind": kind, "v": list(tri)})
            a, b, c = tri
            for e in ((a, b), (b, c), (c, a)):
                edges.add(tuple(sorted(e)))
edges = sorted(edges)

# roles (deterministic): 10 planted up-cells, 2 open up-cells, down-cells: asanoha / sakura / open
PLANTS = ["basil", "strawberry", "mint", "lettuce", "rosemary", "mint", "strawberry", "basil", "lettuce", "rosemary"]
up_cells = [c for c in cells if c["kind"] == "up"]
open_up = {up_cells[4]["id"], up_cells[9]["id"]}
k = 0
for c in cells:
    if c["kind"] == "up":
        if c["id"] in open_up:
            c["role"] = "open"
        else:
            c["role"] = "plant"; c["plant"] = PLANTS[k]; k += 1
    else:
        n = c["id"]
        c["role"] = "sakura" if n in (3, 19) else ("asanoha" if (n // 2) % 2 == 0 else "open")

# ---------------------------------------------------------------- gravity paths (Dijkstra on non-rising edges)
adj = {i: [] for i in range(len(verts))}
for a, b in edges:
    adj[a].append(b); adj[b].append(a)
top_y = max(v[1] for v in verts)
top_vs = sorted([i for i, v in enumerate(verts) if abs(v[1] - top_y) < 1e-6], key=lambda i: verts[i][0])
SUPPLY = min(top_vs, key=lambda i: abs(verts[i][0] - 0.0))


def descend(src, dst):
    dist, prev, pq = {src: 0.0}, {}, [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            break
        if d > dist[u]:
            continue
        for w in adj[u]:
            if verts[w][1] > verts[u][1] + 1e-6:      # never climb
                continue
            nd = d + math.dist(verts[u], verts[w])
            if nd < dist.get(w, 1e9):
                dist[w], prev[w] = nd, u
                heapq.heappush(pq, (nd, w))
    if dst not in dist:
        return None, None
    path, u = [dst], dst
    while u != src:
        u = prev[u]; path.append(u)
    return path[::-1], dist[dst]


bottom_y = min(v[1] for v in verts)
for c in cells:
    if c["role"] != "plant":
        continue
    a, b = sorted(c["v"][:2], key=lambda i: verts[i][0])   # floor beam endpoints
    best = None
    for tgt in (a, b):
        p, L = descend(SUPPLY, tgt)
        if p and (best is None or L < best[1]):
            best = (p, L, tgt)
    c["path"], c["path_len"], c["inlet_v"] = best[0], round(best[1], 3), best[2]
    c["floor"] = [a, b]
    other = b if best[2] == a else a
    # overflow / drainage: from the far end of the compartment straight down to the base
    lows = [i for i, v in enumerate(verts) if abs(v[1] - bottom_y) < 1e-6]
    dp = min((descend(other, t) for t in lows), key=lambda r: r[1] if r[1] is not None else 1e9)
    c["drain"] = dp[0]

# ---------------------------------------------------------------- SolarEngine (pvlib)
ORIENT = {"W": 270.0, "S": 180.0, "E": 90.0}
solar = {}
for key, az in ORIENT.items():
    sun = facade_sun(C.DEFAULT_LAT, C.DEFAULT_LON, az, "2026-07-15", freq="30min")
    times = sun["times"]
    hours = []
    import pvlib
    loc = pvlib.location.Location(C.DEFAULT_LAT, C.DEFAULT_LON, C.DEFAULT_TZ)
    sp = loc.get_solarposition(times)
    for i, t in enumerate(times):
        h = t.hour + t.minute / 60
        if 5 <= h <= 20.5:
            hours.append({"h": h, "az": round(float(sp["azimuth"].iloc[i]), 2),
                          "el": round(float(90 - sp["apparent_zenith"].iloc[i]), 2),
                          "beam": round(float(sun["beam"][i]), 1), "diffuse": round(float(sun["diffuse"][i]), 1)})
    solar[key] = {"azimuth": az, "daily_kwh_m2": round(sun["daily_kwh_m2"], 2), "hours": hours}

# ---------------------------------------------------------------- HydroEngine allocation
EXTRA_DEMAND = {"rosemary": 0.15}   # ASSUMPTION: not in config.PLANT_DEMAND_L_DAY
COMP = {"len": S - 0.07, "h": 0.045, "d": 0.10}          # inner size of a floor-beam compartment (m)
COMP_L = COMP["len"] * COMP["h"] * COMP["d"] * 1000
HEADER = {"area": 0.008, "bottom": top_y + 0.20}          # small covered header bottle above the top
INLET_LEN, INLET_DEPTH = 0.30, 0.0004                     # labyrinth micro-channel moulded in each compartment inlet (like a drip emitter)
TUBE_D = 0.004                                            # 4 mm internal channel / tubing


def tube_R(L):
    return 128 * C.MU_WATER * L / (math.pi * TUBE_D ** 4)


def allocate(plant_cells, demand, widths_mm, V):
    """HydroEngine closed-form drain-down of a header through parallel branches."""
    rg = C.RHO_WATER * C.G
    R = np.array([channel_resistance(w / 1000, INLET_DEPTH, INLET_LEN) + tube_R(c["path_len"])
                  for c, w in zip(plant_cells, widths_mm)])
    G = rg / R
    cvec = np.array([HEADER["bottom"] - verts[c["inlet_v"]][1] for c in plant_cells])
    A, u0 = HEADER["area"], V / 1000 / HEADER["area"]
    Ssum, Bsum = G.sum(), (G * cvec).sum()
    logt = math.log((Bsum + Ssum * u0) / Bsum)
    vol = A * G * (u0 / Ssum + (cvec - Bsum / Ssum) / Ssum * logt)
    vol = np.clip(vol, 0, None); vol *= (V / 1000) / vol.sum()
    q0 = G * (cvec + u0)
    re = max(q / (w / 1000 * INLET_DEPTH) * (2 * w / 1000 * INLET_DEPTH / (w / 1000 + INLET_DEPTH)) / C.NU_WATER
             for q, w in zip(q0, widths_mm))
    return vol * 1000, (A / Ssum) * logt / 60, re, cvec


models = {}
for key in ORIENT:
    scale = 0.6 + 0.4 * solar[key]["daily_kwh_m2"] / C.REF_FACADE_IRRADIATION
    pcs = [c for c in cells if c["role"] == "plant"]
    need = np.array([C.PLANT_DEMAND_L_DAY.get(c["plant"], EXTRA_DEMAND.get(c["plant"])) * scale for c in pcs])
    V = float(need.sum() * 1.10)                               # 10 % margin goes on to drainage
    equal = [1.5] * len(pcs)
    vol_eq, _, _, _ = allocate(pcs, need, equal, V)
    w = np.full(len(pcs), 1.5)
    for _ in range(200):                                       # tune inlet widths to match demand
        vol, tmin, re, head = allocate(pcs, need, w, V)
        w = np.clip(w * (need * 1.10 / vol) ** 0.6, C.W_MIN_MM, C.W_MAX_MM)
    vol, tmin, re, head = allocate(pcs, need, w, V)
    models[key] = {
        "scale": round(scale, 3), "supply_l_day": round(V, 3), "drip_minutes": round(tmin, 1),
        "reynolds_max": round(float(re), 1), "max_head_m": round(float(head.max()), 3),
        "max_pressure_kpa": round(float(C.RHO_WATER * C.G * (head.max() + V / 1000 / HEADER["area"]) / 1000), 2),
        "cells": [{"id": c["id"], "plant": c["plant"], "need_l_day": round(float(n), 3),
                   "alloc_l_day": round(float(a), 3), "alloc_equal_l_day": round(float(e), 3),
                   "inlet_mm": round(float(wi), 2), "path_len_m": c["path_len"], "head_m": round(float(hd), 3),
                   "autonomy_days": round(COMP_L / float(n), 1)}
                  for c, n, a, e, wi, hd in zip(pcs, need, vol, vol_eq, w, head)],
    }

out = {
    "S": S, "H": round(H, 5), "verts": verts, "edges": [list(e) for e in edges], "cells": cells,
    "supply_vertex": SUPPLY, "compartment": {**COMP, "litres": round(COMP_L, 3)}, "header": HEADER,
    "inlet": {"length_m": INLET_LEN, "depth_mm": INLET_DEPTH * 1000}, "tube_d_mm": TUBE_D * 1000,
    "solar": solar, "hydro": models,
    "notes": {"rosemary_demand": "assumption 0.15 L/day (not in config)",
              "demand_source": "config.PLANT_DEMAND_L_DAY scaled by facade irradiance (evaluate.plant_demand)"},
}
OUT = os.path.join(os.path.dirname(__file__), "..", "front", "public", "data", "lattice-model.json")
with open(OUT, "w") as f:
    json.dump(out, f, separators=(",", ":"))
for k2, m in models.items():
    print(k2, "supply", m["supply_l_day"], "L/day  drip", m["drip_minutes"], "min  Re", m["reynolds_max"],
          "P", m["max_pressure_kpa"], "kPa")
    for c in m["cells"]:
        print("   ", c["plant"].ljust(10), "need", c["need_l_day"], "tuned", c["alloc_l_day"], "equal", c["alloc_equal_l_day"],
              "inlet", c["inlet_mm"], "mm  head", c["head_m"], "auto", c["autonomy_days"], "d")
print("cells", len(cells), "edges", len(edges), "compartment L", round(COMP_L, 2))
