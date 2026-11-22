"""
Cultural generative design - geometry library + per-style optimisation inside the user's selected area.

Every style is a real cell geometry, not a pattern printed on a planter:
  * some cells of the geometry become PLANTING cells (a pocket in the cell, its lower section is an
    integrated water compartment),
  * the other cells stay OPEN (the cultural motif cut through a thin screen: airflow, light, balance),
  * the frame members (or the branches of the organic style) carry hidden gravity channels,
  * a discreet supply tube enters from above; there is no large reservoir on top.

Style selection is separate from performance: the same context (area, sun, plants, water) is applied to
every style; the style fixes the screen geometry (open fraction, aperture, depth) and NSGA-II
(the existing ROOTOptimizer machinery) optimises only the hydraulic variables for that geometry.
"""
import math

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import ElementwiseProblem
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.optimize import minimize
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from . import config as C
from . import sunpath
from .evaluate import Context, evaluate
from .optimizer import pick_three
from .tile import TileDesign

DEPTH_M = 0.10              # cell depth (frame member depth)
FRAME_M = 0.022             # frame member width
POCKET_PROTRUSION_M = 0.12  # foliage + pocket lip in front of the frame (self-shading of the cells below)
RES_FRACTION = 0.30         # lower share of a planting cell that is a water compartment
RES_FILL = 0.85             # usable share of that compartment
CHANNEL_SECTION_M2 = 0.012 * 0.018   # hollow channel inside a frame member / branch

SUN_LOVING = {"cherry_tomato", "chili", "strawberry", "basil"}
SHADE_TOLERANT = {"mint", "parsley", "lettuce"}

STYLES = {
    "mashrabiya": dict(name="Tunisian mashrabiya", culture="Tunisia", lattice="square", cell=0.30,
                       motif="mashrabiya",
                       text="Square timber grid with eight-point star openings, after the Tunisian mashrabiya screens."),
    "arabic_star": dict(name="Arabic geometric stars", culture="Tunisia / Arab world", lattice="square", cell=0.30,
                        motif="khatam",
                        text="Khatam pattern: eight-point stars between small crosses, a classic of Arab tilework."),
    "asanoha": dict(name="Japanese asanoha", culture="Japan", lattice="hex", cell=0.17, motif="asanoha",
                    text="Hemp-leaf lattice: each hexagon divided into six leaves; used in kumiko screens."),
    "sakura": dict(name="Sakura floral geometry", culture="Japan", lattice="hex", cell=0.17, motif="sakura",
                   text="Five-petal cherry blossom openings in a hexagonal frame."),
    "seigaiha": dict(name="Japanese seigaiha waves", culture="Japan", lattice="fan", cell=0.17, motif="seigaiha",
                     text="Rows of wave scales; the hollow of each scale is a pocket or a crescent opening."),
    "tree": dict(name="Organic branching", culture="Nature", lattice="tree", cell=0.085, motif="ring",
                 text="An artificial root system: hollow branches descend from the supply point and carry pods."),
    "honeycomb": dict(name="Honeycomb", culture="Nature", lattice="hex", cell=0.17, motif="hexring",
                      text="Hexagonal cells: the most material-efficient tessellation."),
    "hybrid": dict(name="Tunisian-Japanese hybrid", culture="Tunisia × Japan", lattice="hex", cell=0.17,
                   motif="hybrid",
                   text="Hexagonal frame alternating asanoha leaves and Tunisian eight-point stars."),
}


# ================================================================ geometry primitives (metres, y downward)
def _regular(cx, cy, r, n, start):
    return [(cx + r * math.cos(start + 2 * math.pi * k / n), cy + r * math.sin(start + 2 * math.pi * k / n))
            for k in range(n)]


def _star(cx, cy, ro, ri, tips, start=-math.pi / 2):
    return [(cx + (ro if k % 2 == 0 else ri) * math.cos(start + k * math.pi / tips),
             cy + (ro if k % 2 == 0 else ri) * math.sin(start + k * math.pi / tips)) for k in range(2 * tips)]


def _shrink(poly, cx, cy, k):
    return [(cx + (x - cx) * k, cy + (y - cy) * k) for x, y in poly]


def _ellipse(cx, cy, rx, ry, rot, n=14):
    c, s = math.cos(rot), math.sin(rot)
    return [(cx + rx * math.cos(t) * c - ry * math.sin(t) * s, cy + rx * math.cos(t) * s + ry * math.sin(t) * c)
            for t in np.linspace(0, 2 * math.pi, n, endpoint=False)]


def _arc(cx, cy, r, a0, a1, n=16):
    return [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in np.linspace(a0, a1, n)]


# ---------------------------------------------------------------- lattices -> candidate cells
def _cells_square(W, H, s):
    out = []
    nx, ny = int(W // s) + 2, int(H // s) + 2
    for j in range(ny):
        for i in range(nx):
            cx, cy = s / 2 + i * s, s / 2 + j * s
            out.append(dict(cx=cx, cy=cy, row=j, col=i,
                            poly=[(cx - s / 2, cy - s / 2), (cx + s / 2, cy - s / 2), (cx + s / 2, cy + s / 2), (cx - s / 2, cy + s / 2)],
                            w=s, h=s))
    return out


def _cells_hex(W, H, r):
    out = []
    dx, dy = math.sqrt(3) * r, 1.5 * r
    for j in range(int(H // dy) + 2):
        for i in range(int(W // dx) + 2):
            cx = dx / 2 + i * dx + (dx / 2 if j % 2 else 0)
            cy = r + j * dy
            out.append(dict(cx=cx, cy=cy, row=j, col=i, poly=_regular(cx, cy, r, 6, -math.pi / 2), w=dx, h=2 * r))
    return out


def _cells_fan(W, H, r):
    """Seigaiha: semicircular scales (flat base at the bottom), rows offset by half a scale."""
    out = []
    for j in range(int(H // r) + 2):
        for i in range(int(W // (2 * r)) + 2):
            cx = r + i * 2 * r + (r if j % 2 else 0)
            base = (j + 1) * r
            poly = _arc(cx, base, r * 0.98, math.pi, 2 * math.pi, 18)          # upper half (y down)
            out.append(dict(cx=cx, cy=base - 0.42 * r, row=j, col=i, poly=poly, w=2 * r, h=r))
    return out


def _cells_tree(W, H, r_pod, geom=None):
    """Organic 'artificial root system' grown by space colonisation inside the selected area.

    Attractor points cover the usable area; branches grow from the supply point (top) toward them in
    small steps. Every step descends (the water inside the hollow branches flows by gravity), never leaves
    the area or crosses a window, and pods hang at the branch nodes without overlapping."""
    from shapely.geometry import LineString
    if geom is None:
        geom = Polygon([(0, 0), (W, 0), (W, H), (0, H)])
    from shapely.prepared import prep
    inside = prep(geom.buffer(1e-6))
    step = max(0.05, r_pod * 0.85)
    rng = np.random.default_rng(7)
    sp = 2.3 * r_pod
    att = []
    for j in range(int(H / sp) + 1):
        for i in range(int(W / sp) + 1):
            x = (i + 0.5 + rng.uniform(-0.3, 0.3)) * sp
            y = (j + 0.5 + rng.uniform(-0.3, 0.3)) * sp
            if y > 0.15 and inside.contains(Point(x, y).buffer(r_pod)):
                att.append((x, y))
    att = np.array(att) if att else np.zeros((0, 2))

    def seg_ok(a, b, w):
        return inside.contains(LineString([a, b]).buffer(w / 2 + 0.004))

    def try_root(x0):
        from scipy.spatial import cKDTree
        nodes = [(x0, 0.03)]
        parent = [None]
        alive = np.ones(len(att), bool)
        g = step * 0.5                                   # spatial grid: "no node closer than step/2" in O(1)
        grid = {(int(x0 // g), int(0.03 // g)): [nodes[0]]}

        def free(q):
            gx, gy = int(q[0] // g), int(q[1] // g)
            return all(math.dist(q, r) >= g for dx in (-1, 0, 1) for dy in (-1, 0, 1) for r in grid.get((gx + dx, gy + dy), ()))

        for _ in range(400):
            if not alive.any():
                break
            pts = att[alive]
            nd = np.array(nodes)
            dist, near = cKDTree(nd).query(pts)
            ok = dist < max(W, H) * 0.6
            pull = {}
            for k in np.where(ok)[0]:
                v = (pts[k] - nd[near[k]]) / max(dist[k], 1e-9)
                pull.setdefault(int(near[k]), []).append(v)
            grown = False
            for ni, vs in pull.items():
                v0 = np.mean(vs, 0)
                base = math.atan2(v0[1], v0[0])
                p = None
                for da in (0, 0.45, -0.45, 0.9, -0.9, 1.3, -1.3):      # bend around windows and holes
                    v = np.array([math.cos(base + da), math.sin(base + da)])
                    v[1] = max(v[1], 0.28)                           # always descend (gravity)
                    v = v / np.linalg.norm(v)
                    q = tuple(nd[ni] + v * step)
                    if free(q) and seg_ok(nodes[ni], q, 0.02):
                        p = q
                        break
                if p is None:
                    continue
                grid.setdefault((int(p[0] // g), int(p[1] // g)), []).append(p)
                nodes.append(p)
                parent.append(ni)
                grown = True
            idx = np.where(alive)[0]
            dd, _ = cKDTree(np.array(nodes)).query(att[idx])
            alive[idx[dd < 1.4 * r_pod]] = False
            if not grown:
                break
        return nodes, parent

    best = None
    for fx in (0.5, 0.35, 0.65, 0.2, 0.8):
        if not inside.contains(Point(W * fx, 0.03).buffer(0.02)):  # prepared geometry
            continue
        nodes, parent = try_root(W * fx)
        if best is None or len(nodes) > len(best[0]):
            best = (nodes, parent, W * fx)
        if len(nodes) > 0.6 * max(1, len(att)):
            break
    nodes, parent, root_x = best if best else ([(W / 2, 0.03)], [None], W / 2)
    _cells_tree.root_x = root_x

    # pipe model: branch width grows with the number of tips it carries
    children = {i: [] for i in range(len(nodes))}
    for i, pa in enumerate(parent):
        if pa is not None:
            children[pa].append(i)
    load = [0] * len(nodes)
    for i in reversed(range(len(nodes))):
        load[i] = 1 if not children[i] else sum(load[c] for c in children[i])
    segs, seg_of = [], {}
    for i in range(1, len(nodes)):
        seg_of[i] = len(segs)
        segs.append(dict(a=nodes[parent[i]], b=nodes[i], w=min(0.05, 0.012 + 0.004 * math.sqrt(load[i])), parent=None))
    for i in range(1, len(nodes)):
        pa = parent[i]
        segs[seg_of[i]]["parent"] = seg_of.get(pa)

    # limb = which branch leaving the first fork a node belongs to
    fork = 0
    while len(children[fork]) == 1:
        fork = children[fork][0]
    limb_of = {}
    for li, c0 in enumerate(children[fork]):
        stack = [c0]
        while stack:
            n = stack.pop()
            limb_of[n] = li
            stack.extend(children[n])

    pods = []
    SA = np.array([s_["a"] for s_ in segs]) if segs else np.zeros((0, 2))
    SB = np.array([s_["b"] for s_ in segs]) if segs else np.zeros((0, 2))
    SW = np.array([s_["w"] for s_ in segs]) if segs else np.zeros(0)
    pg = 2.15 * r_pod
    pod_grid = {}

    def seg_clear(x, y):
        """Vectorised point-to-segment distance against every branch at once."""
        if not len(SA):
            return True
        P = np.array([x, y])
        AB = SB - SA
        t = np.clip(((P - SA) * AB).sum(1) / np.maximum((AB * AB).sum(1), 1e-12), 0, 1)
        d = np.linalg.norm(SA + AB * t[:, None] - P, axis=1)
        return bool((d >= r_pod * 0.95 + SW / 2).all())

    def pod_ok(x, y):
        gx, gy = int(x // pg), int(y // pg)
        if any(math.dist((x, y), q) < pg for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in pod_grid.get((gx + dx, gy + dy), ())):
            return False
        if not seg_clear(x, y):
            return False
        poly = Polygon(_ellipse(x, y, r_pod * 0.82, r_pod, 0, 18))
        return inside.contains(poly.buffer(-0.002))
    nodes_at = {}
    order = sorted(range(1, len(nodes)), key=lambda i: (len(children[i]) > 0, -nodes[i][1]))   # tips first
    for i in order:
        x, y = nodes[i]
        a = math.atan2(y - nodes[parent[i]][1], x - nodes[parent[i]][0])
        for off in ((0, 1.05), (math.cos(a + math.pi / 2), math.sin(a + math.pi / 2)), (-math.cos(a + math.pi / 2), -math.sin(a + math.pi / 2))):
            px, py = x + off[0] * r_pod * 1.05, y + off[1] * r_pod * 1.05
            if pod_ok(px, py):
                pods.append(dict(cx=px, cy=py, seg=seg_of[i], depth=1, limb=limb_of.get(i, 0)))
                pod_grid.setdefault((int(px // pg), int(py // pg)), []).append((px, py))
                break
    cells = []
    for k, p in enumerate(pods):
        cells.append(dict(cx=p["cx"], cy=p["cy"], row=int(p["cy"] // (2 * r_pod)), col=k, seg=p["seg"], limb=p["limb"],
                          poly=_ellipse(p["cx"], p["cy"], r_pod * 0.82, r_pod, 0, 18), w=1.64 * r_pod, h=2 * r_pod))
    return cells, segs


# ---------------------------------------------------------------- motifs = openings of an OPEN cell
def motif(kind, c, alt=False):
    cx, cy, w, h = c["cx"], c["cy"], c["w"], c["h"]
    s = min(w, h)
    if kind == "mashrabiya":
        return [_star(cx, cy, 0.39 * s, 0.26 * s, 8)] + [_regular(cx + dx * 0.36 * s, cy + dy * 0.36 * s, 0.045 * s, 4, math.pi / 4)
                                                         for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    if kind == "khatam":
        return [_star(cx, cy, 0.38 * s, 0.29 * s, 8, -math.pi / 2 + math.pi / 8)] + \
               [_star(cx + dx * 0.35 * s, cy + dy * 0.35 * s, 0.06 * s, 0.026 * s, 4) for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    if kind == "asanoha" or (kind == "hybrid" and not alt):
        r = h / 2 * 0.84
        hexp = _regular(cx, cy, r, 6, -math.pi / 2)
        leaves = []
        for k in range(6):                       # six kites: centre, vertex k, centre of edge... shrunk
            a, b = hexp[k], hexp[(k + 1) % 6]
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            tri = [(cx, cy), a, m]
            tx, ty = sum(p[0] for p in tri) / 3, sum(p[1] for p in tri) / 3
            leaves.append(_shrink(tri, tx, ty, 0.7))
            tri = [(cx, cy), m, b]
            tx, ty = sum(p[0] for p in tri) / 3, sum(p[1] for p in tri) / 3
            leaves.append(_shrink(tri, tx, ty, 0.7))
        return leaves
    if kind == "hybrid":
        return [_star(cx, cy, 0.38 * h, 0.24 * h, 8)]
    if kind == "sakura":
        r = h * 0.2
        petals = [_ellipse(cx + r * math.cos(a), cy + r * math.sin(a), 0.16 * h, 0.09 * h, a)
                  for a in np.linspace(-math.pi / 2, 1.5 * math.pi, 5, endpoint=False)]
        return petals + [_regular(cx, cy, 0.04 * h, 10, 0)]
    if kind == "seigaiha":
        R = w / 2
        base = c["poly"][0][1]
        bands = []
        for r_out, r_in in ((0.80, 0.62), (0.48, 0.30)):
            outer = _arc(cx, base, R * r_out, math.pi, 2 * math.pi, 16)
            inner = _arc(cx, base, R * r_in, 2 * math.pi, math.pi, 16)
            bands.append(outer + inner)
        return bands
    if kind == "hexring":
        return [_regular(cx, cy, h / 2 * 0.72, 6, -math.pi / 2)]
    if kind == "ring":
        return [_ellipse(cx, cy, w / 2 * 0.62, h / 2 * 0.62, 0, 16)]
    return []


def _area(poly):
    return abs(Polygon(poly).area) if len(poly) >= 3 else 0.0


# ================================================================ generator
def _region_geom(region):
    polys = []
    for p in region.get("region_polygons_m") or []:
        try:
            g = Polygon(p["outer"], p.get("holes") or []).buffer(0)
            if not g.is_empty:
                polys.append(g)
        except Exception:
            continue
    if not polys:
        W, H = region["width_m"], region["height_m"]
        polys = [Polygon([(0, 0), (W, 0), (W, H), (0, H)])]
    return unary_union(polys)


def _fps(cands, k, start):
    """Farthest-point sampling: k evenly spread cells among candidates."""
    chosen = [start]
    d = np.array([math.dist((c["cx"], c["cy"]), (start["cx"], start["cy"])) for c in cands])
    while len(chosen) < k:
        i = int(np.argmax(d))
        if d[i] <= 0:
            break
        chosen.append(cands[i])
        d = np.minimum(d, [math.dist((c["cx"], c["cy"]), (cands[i]["cx"], cands[i]["cy"])) for c in cands])
    return chosen


def _frame_graph(cells):
    """Frame members = polygon edges of the cells (shared edges merged). Nodes are rounded vertices."""
    import heapq
    key = lambda p: (round(p[0], 3), round(p[1], 3))
    adj = {}
    for c in cells:
        pts = [key(p) for p in c["poly"]]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            if a == b:
                continue
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    # joints where cells touch without sharing an exact vertex (wave scales, pods) are connected too
    eps = 0.18 * min(c["h"] for c in cells)
    grid = {}
    for v in adj:
        grid.setdefault((int(v[0] // eps), int(v[1] // eps)), []).append(v)
    for (gx, gy), vs in list(grid.items()):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for v in vs:
                    for w in grid.get((gx + dx, gy + dy), []):
                        if v != w and w not in adj[v] and math.dist(v, w) <= eps:
                            adj[v].add(w)
                            adj[w].add(v)
    top = min(v[1] for v in adj)
    band = min(c["h"] for c in cells) * 0.55
    sources = [v for v in adj if v[1] <= top + band]
    # Dijkstra from the top manifold. Going down costs only length; a rise is allowed (closed channel fed from
    # above, still below the supply level) but costs 4x its height, so paths stay downhill wherever possible.
    dist, prev = {v: 0.0 for v in sources}, {v: None for v in sources}
    pq = [(0.0, v) for v in sources]
    heapq.heapify(pq)
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1e18):
            continue
        for w in adj[u]:
            nd = d + math.dist(u, w) + 4.0 * max(0.0, u[1] - w[1])
            if nd < dist.get(w, 1e18):
                dist[w], prev[w] = nd, u
                heapq.heappush(pq, (nd, w))
    return key, dist, prev, top


def plant_demand_l(plant, exposure_kwh):
    """HydroEngine's demand table, scaled by the cell's own sun exposure (same rule as evaluate.plant_demand)."""
    return C.PLANT_DEMAND_L_DAY[plant] * (0.6 + 0.4 * exposure_kwh / C.REF_FACADE_IRRADIATION)


# share of the cells that carry a planting pocket (the rest show the cultural motif as an open screen)
MAX_CELLS = 110          # cells per design at most (cell size grows on big walls)
GREENERY = {"pattern": None, "balanced": 0.55, "full": 1.0}   # None = previous sun-based rule (26-42 %)


def generate(style_id, region, plants, sun, water_available_l_day=None, exposure_class="moderate", greenery="full"):
    """water_available_l_day: an optional limit (L/day). None = no limit: the design reports the water it needs."""
    st = STYLES[style_id]
    W, H = float(region["width_m"]), float(region["height_m"])
    geom = _region_geom(region)
    segs = []
    from shapely.prepared import prep
    import shapely
    inside = prep(geom.buffer(1e-6))
    shrunk = geom.buffer(-0.002)

    def fits(c):
        return inside.contains(Polygon(c["poly"]).buffer(-0.002))

    # large walls get larger cells (like a building-scale lattice): about MAX_CELLS cells at most, so a whole
    # facade stays readable and generates in seconds
    cell = st["cell"]
    if st["lattice"] == "tree":
        one = 1.2 * cell * cell * 4                 # wall area served by one pod (empirical)
    else:
        sample = {"square": _cells_square, "hex": _cells_hex, "fan": _cells_fan}[st["lattice"]](cell * 4, cell * 4, cell)
        one = _area(sample[0]["poly"])
    n_est = geom.area / max(one, 1e-9)
    if n_est > MAX_CELLS:
        cell *= math.sqrt(n_est / MAX_CELLS)
    if st["lattice"] == "tree":
        raw, segs = _cells_tree(W, H, cell, geom)
        cells = [c for c in raw if fits(c)]
    else:
        make = {"square": _cells_square, "hex": _cells_hex, "fan": _cells_fan}[st["lattice"]]
        base = make(W + cell * 2, H + cell * 2, cell)
        # slide the lattice: keep the offset that fits most cells. Scoring = all vertices (+ centre) inside, for all
        # 16 offsets in one vectorised call; full polygon tests only for the winning offset.
        V = np.array([[(x, y) for x, y in c["poly"]] + [(c["cx"], c["cy"])] for c in base])   # (n, k+1, 2)
        best_n, best_o = -1, (0.0, 0.0)
        for fx in (0, 0.25, 0.5, 0.75):
            for fy in (0, 0.25, 0.5, 0.75):
                ox, oy = -fx * base[0]["w"], -fy * base[0]["h"]
                ok = shapely.contains_xy(shrunk, V[..., 0] + ox, V[..., 1] + oy).all(1)
                if ok.sum() > best_n:
                    best_n, best_o = int(ok.sum()), (ox, oy)
        ox, oy = best_o
        moved = [dict(c, cx=c["cx"] + ox, cy=c["cy"] + oy, poly=[(x + ox, y + oy) for x, y in c["poly"]]) for c in base]
        cells = [c for c in moved if fits(c)]
    if st["lattice"] == "tree":           # keep only branches leading to kept pods
        keep = set()
        for c in cells:
            s = c["seg"]
            while s is not None and s not in keep:
                keep.add(s)
                s = segs[s]["parent"]
        segs = [dict(s, id=i) for i, s in enumerate(segs) if i in keep]
    if len(cells) < 2:
        raise ValueError("the selected area is too small for this geometry")
    for i, c in enumerate(cells):
        c["id"] = i

    # ---- how many planting cells: limited by the water budget and by the sun (shade vs. light)
    plant_frac = GREENERY.get(greenery) or {"high": 0.42, "moderate": 0.34, "low": 0.26}[exposure_class]
    mean_need = float(np.mean([C.PLANT_DEMAND_L_DAY[p] for p in plants])) * (0.6 + 0.4 * sun["daily_kwh_m2"] / C.REF_FACADE_IRRADIATION)
    n_water = (int(water_available_l_day * 0.85 // max(mean_need, 1e-6))       # keep 15% for losses
               if water_available_l_day else len(cells))
    keep_open = 0 if greenery == "full" else 1          # "full": every pocket planted, the frame carries the pattern
    n_plant = max(1, min(int(round(len(cells) * plant_frac)), n_water, len(cells) - keep_open))
    # spread them (farthest-point sampling) starting from the bottom-centre cell: easy to reach and refill
    graph = None
    cand = cells
    if st["lattice"] != "tree":
        graph = _frame_graph(cells)
        key, dist = graph[0], graph[1]
        cand = [c for c in cells if any(key(p) in dist for p in c["poly"])] or cells
        if greenery == "full":
            cand = cells        # islands the channels cannot reach are planted too, watered by hand (flagged)
        n_plant = min(n_plant, max(1, len(cand) - keep_open))
    start = min(cand, key=lambda c: (abs(c["cx"] - W / 2) + (H - c["cy"]) * 0.8))
    chosen = {c["id"] for c in _fps(cand, n_plant, start)}

    # ---- self-shading per cell: frame depth + foliage of the planting cells above (profile-angle method)
    tv, th = np.array(sun["tan_v"]), np.array(sun["tan_h"])
    beam, dif = np.array(sun["beam_w_m2"]), np.array(sun["diffuse_w_m2"])
    dt = sun["dt_h"]
    for c in cells:
        f = np.clip(1 - DEPTH_M * tv / c["h"], 0, 1) * np.clip(1 - DEPTH_M * np.abs(th) / c["w"], 0, 1)
        for o in cells:
            if o["id"] not in chosen or o["id"] == c["id"] or o["cy"] >= c["cy"]:
                continue
            overlap = max(0.0, min(o["cx"] + o["w"] / 2, c["cx"] + c["w"] / 2) - max(o["cx"] - o["w"] / 2, c["cx"] - c["w"] / 2)) / c["w"]
            if overlap <= 0:
                continue
            gap = (c["cy"] - c["h"] / 2) - (o["cy"] + o["h"] / 2)
            shade = np.clip((POCKET_PROTRUSION_M * tv - max(gap, 0)) / c["h"], 0, 1) * min(1.0, overlap)
            f = f * (1 - shade)
        c["direct_fraction"] = f.round(3).tolist()
        c["exposure_kwh_m2"] = float(((beam * f + dif * 0.85) * dt).sum() / 1000)

    exps = np.array([c["exposure_kwh_m2"] for c in cells])
    q1, q2 = np.quantile(exps, [0.33, 0.66]) if len(exps) > 2 else (exps.min(), exps.max())
    for c in cells:
        c["zone"] = "high" if c["exposure_kwh_m2"] >= q2 else ("low" if c["exposure_kwh_m2"] <= q1 else "medium")

    # ---- plants: sun-loving species in the most exposed planting cells, shade-tolerant in the least
    pcells = sorted([c for c in cells if c["id"] in chosen], key=lambda c: -c["exposure_kwh_m2"])
    order = sorted(plants, key=lambda p: (0 if p in SUN_LOVING else 1, plants.index(p)))
    per = [len(pcells) // len(order) + (1 if i < len(pcells) % len(order) else 0) for i in range(len(order))]
    k = 0
    for p, n in zip(order, per):
        for c in pcells[k:k + n]:
            c["plant"] = p
        k += n

    # ---- roles, motifs, reservoirs
    open_area = 0.0
    total_area = sum(_area(c["poly"]) for c in cells)
    for c in cells:
        if c["id"] in chosen:
            c["role"] = "plant"
            c["motif"] = []
            top = c["cy"] + c["h"] / 2 - RES_FRACTION * c["h"]
            inner_w = c["w"] * 0.72
            cap = inner_w * RES_FRACTION * c["h"] * (DEPTH_M - 0.02) * RES_FILL * 1000
            c["reservoir"] = {"capacity_l": round(cap, 3), "top_y": round(top, 4), "bottom_y": round(c["cy"] + c["h"] / 2 * 0.9, 4)}
            c["need_l_day"] = round(plant_demand_l(c["plant"], c["exposure_kwh_m2"]), 3)
        else:
            c["role"] = "open"
            alt = (c["row"] + c["col"]) % 2 == 1
            c["motif"] = [[(round(x, 4), round(y, 4)) for x, y in m] for m in motif(st["motif"], c, alt)]
            open_area += sum(_area(m) for m in c["motif"])
            c["reservoir"] = None
    bbox_area = W * H
    open_cells_area = sum(_area(c["poly"]) for c in cells if c["role"] == "open")
    if open_cells_area > 0:
        screen_porosity = open_area / open_cells_area
    else:                                    # every cell planted: porosity of the style's motif, for the heat model
        c0 = cells[0]
        screen_porosity = sum(_area(m) for m in motif(st["motif"], c0)) / max(_area(c0["poly"]), 1e-9)
    gaps = max(0.0, geom.area - total_area) if st["lattice"] == "tree" else 0.0
    open_fraction = (open_area + gaps) / max(geom.area if st["lattice"] == "tree" else total_area, 1e-9)

    # ---- branches (hidden gravity channels) and storage per branch
    branches = []
    if st["lattice"] == "tree":
        for c in cells:
            c["branch"] = 0
        # one branch per limb leaving the first fork
        for c in cells:
            c["branch"] = c.get("limb", 0) if c["id"] in chosen else None
        channels = []
        for s in segs:
            channels.append({"branch": None, "points": [list(s["a"]), list(s["b"])], "w": s["w"]})
        chan_len = sum(math.dist(s["a"], s["b"]) for s in segs)
        frame_len = chan_len
    else:
        # every planting cell is fed along the frame members from the top manifold (no channel crosses a
        # window or empty space); cells sharing the same entry point form one branch
        key, dist, prev, top_y = graph
        entries, channels, used = {}, [], set()
        for c in sorted([c for c in cells if c["role"] == "plant"], key=lambda c: c["cx"]):
            tops = sorted((key(p) for p in c["poly"] if key(p) in dist), key=lambda v: (v[1], dist[v]))
            if not tops:
                c["branch"] = None
                continue
            v = min(tops[:2], key=lambda v: dist[v])
            path = [v]
            while prev[path[-1]] is not None:
                path.append(prev[path[-1]])
            path.reverse()                                   # manifold -> ... -> cell
            for a, b in zip(path, path[1:]):
                used.add(tuple(sorted((a, b))))
            entries.setdefault(path[0], []).append(c)
            pts = [[path[0][0], top_y]] + [list(p) for p in path] + [[c["cx"], c["reservoir"]["top_y"]]]
            channels.append({"branch": None, "points": pts, "w": 0.012, "cell": c["id"]})
        order = sorted(entries, key=lambda v: v[0])
        for bi, e in enumerate(order):
            for c in entries[e]:
                c["branch"] = bi
        by_id = {c["id"]: c for c in cells}
        for ch in channels:
            ch["branch"] = by_id[ch["cell"]]["branch"]
        hand = [c for c in cells if c["role"] == "plant" and c.get("branch") is None]
        for c in hand:                       # no frame path from the manifold: a hand-watered group of its own
            c["branch"] = len(order)
            c["hand_watered"] = True
        for c in cells:
            if c["role"] != "plant":
                c["branch"] = None
        xs = [v[0] for v in order] + [W / 2]
        if order:
            channels.insert(0, {"branch": None, "points": [[min(xs), top_y], [max(xs), top_y]], "w": 0.014})
        chan_len = sum(math.dist(a, b) for a, b in used) + (max(xs) - min(xs) if order else 0.0)
        frame_len = sum(Polygon(c["poly"]).length for c in cells) / 2
    supply = {"x": getattr(_cells_tree, "root_x", W / 2) if st["lattice"] == "tree" else W / 2, "y_top": -0.25, "y_in": 0.0}

    groups = {}
    for c in cells:
        if c["role"] == "plant":
            groups.setdefault(c["branch"], []).append(c)
    for bi, cs in sorted(groups.items(), key=lambda t: (t[0] is None, t[0])):
        branches.append({
            "id": int(bi or 0), "cells": [c["id"] for c in cs],
            "hand_watered": any(c.get("hand_watered") for c in cs),
            "plants": [c["plant"] for c in cs],
            "capacity_l": round(sum(c["reservoir"]["capacity_l"] for c in cs) + chan_len / max(1, len(groups)) * CHANNEL_SECTION_M2 * 1000, 3),
            "need_l_day": round(sum(c["need_l_day"] for c in cs), 3),
        })

    # ---- materials
    wood_m3 = frame_len * FRAME_M * DEPTH_M
    screen_m2 = sum(_area(c["poly"]) for c in cells if c["role"] == "open")
    motif_sizes = [math.sqrt(_area(m)) for c in cells for m in c["motif"] if _area(m) > 0]
    return {
        "style": style_id, **{k: st[k] for k in ("name", "culture", "text")},
        "width_m": round(W, 3), "height_m": round(H, 3), "depth_m": DEPTH_M,
        "cells": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items()
                   if k not in ("seg",)} | {"poly": [[round(x, 4), round(y, 4)] for x, y in c["poly"]]} for c in cells],
        "segments": [{"a": [round(v, 4) for v in s["a"]], "b": [round(v, 4) for v in s["b"]], "w": s["w"]} for s in segs],
        "channels": channels, "supply": supply, "branches": branches,
        "metrics": {
            "cells": len(cells), "planting_cells": len(pcells), "open_cells": len(cells) - len(pcells),
            "open_fraction": round(float(open_fraction), 3),
            "screen_porosity": round(float(screen_porosity if st["lattice"] != "tree" else open_fraction), 3),
            "aperture_mm": round(float(np.median(motif_sizes) * 1000), 1) if motif_sizes else 20.0,
            "storage_l": round(sum(b["capacity_l"] for b in branches), 2),
            "plant_need_l_day": round(sum(c["need_l_day"] for c in pcells), 3),
            "frame_length_m": round(frame_len, 2), "wood_m3": round(wood_m3, 4), "screen_m2": round(screen_m2, 3),
            "hidden_channel_m": round(chan_len, 2), "area_m2": round(float(geom.area), 3), "bbox_m2": round(bbox_area, 3),
            "water_limited": bool(water_available_l_day) and n_plant == n_water,
            "greenery": greenery,
        },
    }


# ================================================================ optimisation per style (shared engine)
class _FixedScreen(ElementwiseProblem):
    """ROOTOptimizer's objectives and constraints, with the screen fixed by the cultural geometry."""

    def __init__(self, ctx, porosity, aperture_mm, layers):
        self.ctx, self.fixed = ctx, (porosity, aperture_mm, layers)
        n = len(ctx.plants)
        xl = [C.W_MIN_MM] * n + [C.WC_MIN_MM, C.V_MIN_L]
        xu = [C.W_MAX_MM] * n + [C.WC_MAX_MM, C.V_MAX_L]
        super().__init__(n_var=n + 2, n_obj=3, n_ieq_constr=4, xl=np.array(xl), xu=np.array(xu))

    def design(self, x):
        n = len(self.ctx.plants)
        p, a, l = self.fixed
        return TileDesign(plants=list(self.ctx.plants), widths_mm=[float(v) for v in x[:n]], cool_width_mm=float(x[n]),
                          water_l_day=float(x[n + 1]), porosity=p, aperture_mm=a, layers=l)

    def _evaluate(self, x, out, *args, **kwargs):
        r = evaluate(self.design(x), self.ctx)
        o = r["objectives"]
        out["F"] = [o["water_l_day"], o["heat_kwh_day"], o["plant_deficit"]]
        out["G"] = [C.MIN_EFFECTIVE_POROSITY - r["panel"]["effective_porosity"],
                    o["water_l_day"] - self.ctx.water_available_l_day,
                    C.MIN_DRAIN_MIN - r["hydraulics"]["drain_time_min"],
                    (r["hydraulics"]["reynolds_max"] - C.MAX_REYNOLDS) / 100.0]


def optimise(gen, plants, facade, lat, lon, date, water_available_l_day, rh=0.55, n_gen=30):
    m = gen["metrics"]
    porosity = float(np.clip(m["screen_porosity"], C.P_MIN, C.P_MAX))
    aperture = float(np.clip(m["aperture_mm"], C.A_MIN_MM, C.A_MAX_MM))
    ctx = Context(plants=list(plants), lat=lat, lon=lon, facade=facade, date=date, rh=rh,
                  window_w=gen["width_m"], window_h=gen["height_m"],
                  root_tiles=max(1, math.ceil(m["planting_cells"] / len(plants))),
                  water_available_l_day=water_available_l_day if water_available_l_day else 1e6)
    prob = _FixedScreen(ctx, porosity, aperture, C.LAYERS_MAX)
    res = minimize(prob, NSGA2(pop_size=60, crossover=SBX(prob=0.9, eta=15), mutation=PM(eta=20),
                               eliminate_duplicates=True), ("n_gen", n_gen), seed=1, verbose=False)
    if res.X is None:
        return {"feasible": False, "message": "No hydraulic design meets the water budget and drip constraints "
                                              "for this geometry: raise the water limit, plant fewer pockets or choose fewer plants."}
    X, F = np.atleast_2d(res.X), np.atleast_2d(res.F)
    picks, safe = pick_three(X, F)
    d = prob.design(X[picks["balanced"]])
    r = evaluate(d, ctx)
    return {"feasible": True, "plant_safe": safe, "design": d.to_dict(), "result": r,
            "engine_note": "Heat estimate: ROOTOptimizer's perforated-screen model with this geometry's open fraction "
                           f"({porosity:.2f}) and aperture ({aperture:.0f} mm). Clear-sky model, not a measurement."}


# ================================================================ solar recommendations
def recommendations(sun_summer, sun_winter, region, plants):
    s, w = sun_summer["daily_kwh_m2"], sun_winter["daily_kwh_m2"]
    cls = sunpath.exposure_class(s)
    rec = []
    if cls == "high":
        rec.append({"topic": "density", "text": f"High summer exposure ({s:.1f} kWh/m²/day, clear sky): prefer denser geometry "
                    "(open fraction about 25-40 %) to shade the wall and window behind it."})
    elif cls == "moderate":
        rec.append({"topic": "density", "text": f"Moderate summer exposure ({s:.1f} kWh/m²/day): a balanced geometry "
                    "(open fraction about 35-50 %) keeps light for the plants and still shades."})
    else:
        rec.append({"topic": "density", "text": f"Low exposure ({s:.1f} kWh/m²/day): keep the geometry open (above 50 %) "
                    "so plants receive enough light; shading is not the priority here."})
    if w > s * 0.9:
        rec.append({"topic": "season", "text": f"This wall receives as much or more sun in winter ({w:.1f} kWh/m²/day) "
                    "as in summer (typical of south-facing walls): a deeper frame shades the high summer sun "
                    "and lets the low winter sun through."})
    elif w < s * 0.4:
        rec.append({"topic": "season", "text": f"Winter sun is weak here ({w:.1f} kWh/m²/day): plants that need sun all year "
                    "will grow slowly in winter; leafy herbs are safer."})
    sun_l = [p for p in plants if p in SUN_LOVING]
    shade_l = [p for p in plants if p in SHADE_TOLERANT]
    if cls == "low" and sun_l:
        rec.append({"topic": "plants", "text": f"{', '.join(sun_l)} need a lot of sun; on this wall they may fruit poorly. "
                    "They are placed in the most exposed cells."})
    if cls == "high" and shade_l:
        rec.append({"topic": "plants", "text": f"{', '.join(shade_l)} prefer partial shade: they are placed in the cells "
                    "shaded by the plants above."})
    if region.get("obstacles_m"):
        rec.append({"topic": "open", "text": "Windows and doors you marked stay outside the structure, with a 5 cm "
                    "clearance, so daylight, view and opening are kept."})
    rec.append({"topic": "limits", "text": "Surrounding buildings and trees are not modelled: the sun hours are a "
                "clear-sky upper bound. Mark nearby obstacles or check the wall at different times to confirm."})
    return cls, rec


def fit_label(cls, open_fraction):
    lo, hi = {"high": (0.25, 0.40), "moderate": (0.35, 0.50), "low": (0.50, 0.80)}[cls]
    if open_fraction < lo:
        return "denser than recommended"
    if open_fraction > hi:
        return "more open than recommended"
    return "suits this wall's sun"


def direct_fractions(gen, sun):
    """Per-cell unshaded fraction of the opening over a (possibly different) day: frame depth + foliage above."""
    tv, th = np.array(sun["tan_v"]), np.array(sun["tan_h"])
    beam, dif, dt = np.array(sun["beam_w_m2"]), np.array(sun["diffuse_w_m2"]), sun["dt_h"]
    cells = gen["cells"]
    out = {}
    for c in cells:
        f = np.clip(1 - DEPTH_M * tv / c["h"], 0, 1) * np.clip(1 - DEPTH_M * np.abs(th) / c["w"], 0, 1)
        for o in cells:
            if o["role"] != "plant" or o["id"] == c["id"] or o["cy"] >= c["cy"]:
                continue
            overlap = max(0.0, min(o["cx"] + o["w"] / 2, c["cx"] + c["w"] / 2) - max(o["cx"] - o["w"] / 2, c["cx"] - c["w"] / 2)) / c["w"]
            if overlap <= 0:
                continue
            gap = (c["cy"] - c["h"] / 2) - (o["cy"] + o["h"] / 2)
            f = f * (1 - np.clip((POCKET_PROTRUSION_M * tv - max(gap, 0)) / c["h"], 0, 1) * min(1.0, overlap))
        out[c["id"]] = {"direct_fraction": f.round(3).tolist(),
                        "exposure_kwh_m2": round(float(((beam * f + dif * 0.85) * dt).sum() / 1000), 3)}
    return out
