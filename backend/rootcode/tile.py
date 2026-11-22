"""
Parametric ROOTCODE tile: the design vector theta <-> a concrete tile geometry.

Layout (tile seen from the front, y measured downward from the top):
  - top manifold fed by an external tank (gravity)
  - plant pockets in 2 columns, up to 3 rows
  - one gravity channel per pocket (no shared pipes -> no cross-talk)
  - optional cooling branch down the middle to an evaporative strip at the bottom
  - the rest of the front screen is perforated with zellige-style 8-point stars
"""
from dataclasses import dataclass, asdict
import math
import numpy as np
from . import config as C


@dataclass
class Pocket:
    plant: str
    cx: float          # m, centre x
    cy: float          # m, centre y (from top)
    route: list        # list of (x, y) points of the feeding channel, inlet first

    @property
    def length(self):
        return sum(math.dist(a, b) for a, b in zip(self.route, self.route[1:]))

    @property
    def drop(self):
        return self.route[-1][1] - self.route[0][1]


@dataclass
class TileDesign:
    plants: list           # plant name per pocket
    widths_mm: list        # channel width per pocket
    cool_width_mm: float   # cooling branch width (closed if < WC_CLOSED_MM)
    water_l_day: float     # water poured per tile per day
    porosity: float        # aperture porosity of the front screen
    aperture_mm: float     # aperture characteristic size (star diameter)
    layers: int            # stacked front layers

    @property
    def screen_depth(self):
        return self.layers * C.LAYER_T

    @property
    def cooling_open(self):
        return self.cool_width_mm >= C.WC_CLOSED_MM

    def to_dict(self):
        d = asdict(self)
        d["screen_depth_mm"] = round(self.screen_depth * 1000, 1)
        d["cooling_open"] = self.cooling_open
        return d


# ---------------------------------------------------------------- layout
def pocket_layout(plants):
    """Place up to 6 pockets in 2 columns and compute non-overlapping channel routes."""
    n = len(plants)
    if not 1 <= n <= 6:
        raise ValueError("ROOTCODE tile supports 1 to 6 pockets")
    rows = math.ceil(n / 2)
    ys = np.linspace(0.095, 0.215, rows) if rows > 1 else [0.15]
    col_x = [0.075, 0.225]
    pockets = []
    for i, plant in enumerate(plants):
        r, c = divmod(i, 2)
        cx = 0.15 if (n % 2 == 1 and i == n - 1) else col_x[c]
        cy = float(ys[r])
        top = cy - C.POCKET_H / 2
        if r == 0 or cx == 0.15:
            route = [(cx, C.MANIFOLD_Y), (cx, top)]
        else:
            # bypass the pockets above on the outer side, then jog into this pocket
            side = -1 if cx < 0.15 else 1
            bx = cx + side * (C.POCKET_W / 2 + 0.006 + (r - 1) * 0.008)
            bx = min(max(bx, 0.012), C.TILE_W - 0.012)
            route = [(bx, C.MANIFOLD_Y), (bx, top - 0.008), (cx, top - 0.008), (cx, top)]
        pockets.append(Pocket(plant, cx, cy, route))
    return pockets


def cooling_route():
    return [(0.15, C.MANIFOLD_Y), (0.15, C.COOL_STRIP_Y - 0.015)]


def pocket_area_fraction(n):
    return n * C.POCKET_W * C.POCKET_H / (C.TILE_W * C.TILE_H)


def effective_porosity(design):
    """Open fraction of the whole tile (pockets and cooling strip are opaque)."""
    blocked = pocket_area_fraction(len(design.plants)) + C.COOL_STRIP_AREA / (C.TILE_W * C.TILE_H)
    return design.porosity * max(0.0, 1.0 - blocked)


# ---------------------------------------------------------------- theta <-> design
def n_vars(n_pockets):
    return n_pockets + 5


def bounds(n_pockets):
    xl = [C.W_MIN_MM] * n_pockets + [C.WC_MIN_MM, C.V_MIN_L, C.P_MIN, C.A_MIN_MM, C.LAYERS_MIN - 0.49]
    xu = [C.W_MAX_MM] * n_pockets + [C.WC_MAX_MM, C.V_MAX_L, C.P_MAX, C.A_MAX_MM, C.LAYERS_MAX + 0.49]
    return np.array(xl, float), np.array(xu, float)


def decode(theta, plants):
    n = len(plants)
    return TileDesign(
        plants=list(plants),
        widths_mm=[float(w) for w in theta[:n]],
        cool_width_mm=float(theta[n]),
        water_l_day=float(theta[n + 1]),
        porosity=float(theta[n + 2]),
        aperture_mm=float(theta[n + 3]),
        layers=int(round(theta[n + 4])),
    )


def baseline(plants, water_l_day):
    """A conventional tile: equal straight channels, standard thin perforated panel."""
    return TileDesign(
        plants=list(plants),
        widths_mm=[1.5] * len(plants),
        cool_width_mm=1.5,
        water_l_day=water_l_day,
        porosity=0.50,
        aperture_mm=20.0,
        layers=1,
    )
