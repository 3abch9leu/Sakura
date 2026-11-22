"""
Export: laser-cutting SVG layers, a colour preview, and result plots.

Laser convention (works with LightBurn, RDWorks, Inkscape):
  red  hairline stroke (#FF0000, 0.01 mm) = CUT
  blue filled shapes   (#0000FF)          = ENGRAVE (raster, set power for ~0.6 mm depth)
Units: millimetres, 1 SVG unit = 1 mm.
"""
import math
import os
import numpy as np
from . import config as C
from .tile import pocket_layout, cooling_route

MM = 1000.0
CUT = 'fill="none" stroke="#FF0000" stroke-width="0.01"'
ENGRAVE = 'fill="#0000FF" stroke="none"'


# ---------------------------------------------------------------- geometry helpers
def star_points(cx, cy, R, r_ratio=0.62, n=8, rot=math.pi / 8):
    """8-point zellige-style star (16 vertices alternating outer/inner radius)."""
    pts = []
    for k in range(2 * n):
        rad = R if k % 2 == 0 else R * r_ratio
        ang = rot + k * math.pi / n
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return pts


def star_area(R, r_ratio=0.62, n=8):
    return 2 * n * 0.5 * R * (R * r_ratio) * math.sin(math.pi / n)


def _poly(pts, attrs):
    d = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    return f'<polygon points="{d}" {attrs}/>'


def _rect(x, y, w, h, attrs, rx=0):
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx}" {attrs}/>'


def _svg(body, w=C.TILE_W * MM, h=C.TILE_H * MM, extra=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" '
            f'viewBox="0 0 {w} {h}" {extra}>\n' + "\n".join(body) + "\n</svg>\n")


def _blocked_rects(design, root=True):
    """Regions (mm) where no aperture may be cut."""
    rects = [(0, 0, C.TILE_W * MM, (C.MANIFOLD_Y + 0.012) * MM)]  # manifold band
    if root:
        for p in pocket_layout(design.plants):
            rects.append(((p.cx - C.POCKET_W / 2) * MM - 4, (p.cy - C.POCKET_H / 2) * MM - 4,
                          C.POCKET_W * MM + 8, C.POCKET_H * MM + 8))
            for (x0, y0), (x1, y1) in zip(p.route, p.route[1:]):
                rects.append((min(x0, x1) * MM - 4, min(y0, y1) * MM - 4,
                              abs(x1 - x0) * MM + 8, abs(y1 - y0) * MM + 8))
        if design.cooling_open:
            rects.append((10, C.COOL_STRIP_Y * MM - 20, C.TILE_W * MM - 20, 34))
            (x0, y0), (x1, y1) = cooling_route()
            rects.append((x0 * MM - 5, y0 * MM, 10, (y1 - y0) * MM + 5))
    return rects


def _free(cx, cy, R, rects, margin=8):
    W, H = C.TILE_W * MM, C.TILE_H * MM
    if cx - R < margin or cy - R < margin or cx + R > W - margin or cy + R > H - margin:
        return False
    for x, y, w, h in rects:
        if cx + R > x and cx - R < x + w and cy + R > y and cy - R < y + h:
            return False
    return True


def aperture_stars(design, root=True):
    """Stars on a square grid whose pitch gives the requested porosity."""
    R = design.aperture_mm / 2
    pitch = max(math.sqrt(star_area(R) / design.porosity), 2 * R + 1.5)  # keep >= 1.5 mm bridges
    rects = _blocked_rects(design, root)
    stars = []
    W, H = C.TILE_W * MM, C.TILE_H * MM
    for j in range(int(H // pitch) + 1):
        for i in range(int(W // pitch) + 1):
            cx, cy = pitch / 2 + i * pitch, pitch / 2 + j * pitch
            if _free(cx, cy, R, rects):
                stars.append(star_points(cx, cy, R))
    return stars


# ---------------------------------------------------------------- laser layers
def laser_layers(design, out_dir, prefix="rootcode"):
    """Write back / channel / front-screen SVGs ready for a laser cutter. Returns file paths."""
    os.makedirs(out_dir, exist_ok=True)
    W, H = C.TILE_W * MM, C.TILE_H * MM
    outline = _rect(0, 0, W, H, CUT, rx=4)
    mount = [f'<circle cx="{x}" cy="{y}" r="2.5" {CUT}/>' for x in (8, W - 8) for y in (8, H - 8)]
    files = {}

    # 1. back plate
    files["back"] = os.path.join(out_dir, f"{prefix}_1_back.svg")
    open(files["back"], "w").write(_svg([outline, *mount]))

    # 2. channel plate: engraved manifold + channels, cut wick holes at each outlet
    body = [outline, *mount,
            _rect(10, (C.MANIFOLD_Y - 0.008) * MM, W - 20, 8, ENGRAVE),           # manifold
            f'<circle cx="{W / 2}" cy="{(C.MANIFOLD_Y - 0.004) * MM}" r="3" {CUT}/>']  # tank inlet
    for p, w in zip(pocket_layout(design.plants), design.widths_mm):
        pts = " ".join(f"{x * MM:.2f},{y * MM:.2f}" for x, y in p.route)
        body.append(f'<polyline points="{pts}" fill="none" stroke="#0000FF" '
                    f'stroke-width="{w:.2f}" stroke-linejoin="round"/>')
        ex, ey = p.route[-1]
        body.append(f'<circle cx="{ex * MM:.2f}" cy="{ey * MM:.2f}" r="1.5" {CUT}/>')  # wick hole
        body.append(f'<text x="{p.cx * MM:.1f}" y="{p.cy * MM:.1f}" font-size="4" fill="#0000FF" '
                    f'text-anchor="middle">{p.plant} {w:.2f}mm</text>')
    if design.cooling_open:
        pts = " ".join(f"{x * MM:.2f},{y * MM:.2f}" for x, y in cooling_route())
        body.append(f'<polyline points="{pts}" fill="none" stroke="#0000FF" '
                    f'stroke-width="{design.cool_width_mm:.2f}"/>')
        body.append(_rect(15, C.COOL_STRIP_Y * MM - 15, W - 30, 30, ENGRAVE))
    files["channels"] = os.path.join(out_dir, f"{prefix}_2_channels_ENGRAVE.svg")
    open(files["channels"], "w").write(_svg(body))

    # 3. front screen (cut this file `layers` times and stack)
    body = [outline, *mount]
    for p in pocket_layout(design.plants):
        body.append(_rect((p.cx - C.POCKET_W / 2) * MM, (p.cy - C.POCKET_H / 2) * MM,
                          C.POCKET_W * MM, C.POCKET_H * MM, CUT, rx=3))
    if design.cooling_open:
        body.append(_rect(15, C.COOL_STRIP_Y * MM - 15, W - 30, 30, CUT, rx=3))
    body += [_poly(s, CUT) for s in aperture_stars(design)]
    files["front"] = os.path.join(out_dir, f"{prefix}_3_front_x{design.layers}.svg")
    open(files["front"], "w").write(_svg(body))

    # 4. shade-only tile screen (no pockets, full star pattern)
    body = [outline, *mount] + [_poly(s, CUT) for s in aperture_stars(design, root=False)]
    files["shade"] = os.path.join(out_dir, f"{prefix}_4_shade_tile_x{design.layers}.svg")
    open(files["shade"], "w").write(_svg(body))
    return files


# ---------------------------------------------------------------- preview for the dashboard
def preview_svg(design, title=""):
    """Colour preview of a root tile (what the user sees on screen)."""
    W, H = C.TILE_W * MM, C.TILE_H * MM
    body = [f'<rect width="{W}" height="{H}" rx="6" fill="#C8693F"/>',      # terracotta
            _rect(10, (C.MANIFOLD_Y - 0.010) * MM, W - 20, 10, 'fill="#3B82C4"', rx=3)]
    body += [_poly(s, 'fill="#F4EDE4"') for s in aperture_stars(design)]
    for p, w in zip(pocket_layout(design.plants), design.widths_mm):
        pts = " ".join(f"{x * MM:.1f},{y * MM:.1f}" for x, y in p.route)
        body.append(f'<polyline points="{pts}" fill="none" stroke="#3B82C4" '
                    f'stroke-width="{max(w * 1.6, 1.2):.2f}" stroke-linecap="round" stroke-linejoin="round"/>')
        body.append(_rect((p.cx - C.POCKET_W / 2) * MM, (p.cy - C.POCKET_H / 2) * MM,
                          C.POCKET_W * MM, C.POCKET_H * MM, 'fill="#4E7D3A"', rx=5))
        body.append(f'<text x="{p.cx * MM:.1f}" y="{p.cy * MM + 2:.1f}" font-size="8" fill="#fff" '
                    f'font-family="sans-serif" text-anchor="middle">{p.plant}</text>')
    if design.cooling_open:
        pts = " ".join(f"{x * MM:.1f},{y * MM:.1f}" for x, y in cooling_route())
        body.append(f'<polyline points="{pts}" fill="none" stroke="#3B82C4" '
                    f'stroke-width="{design.cool_width_mm * 1.6:.2f}"/>')
        body.append(_rect(15, C.COOL_STRIP_Y * MM - 15, W - 30, 30, 'fill="#8FB8DE"', rx=4))
    if title:
        body.append(f'<text x="{W / 2}" y="{H - 4}" font-size="9" fill="#fff" '
                    f'font-family="sans-serif" text-anchor="middle">{title}</text>')
    return _svg(body)


# ---------------------------------------------------------------- plots
def plot_pareto(F, picks, baseline_F, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 5))
    sc = ax.scatter(F[:, 0], F[:, 1], c=F[:, 2], cmap="viridis_r", s=28, alpha=.85)
    fig.colorbar(sc, label="Plant water deficit (0 = all plants satisfied)")
    marks = {"water_saver": ("o", "Water Saver"), "shade_maximizer": ("s", "Shade Maximizer"),
             "balanced": ("D", "Balanced")}
    for k, i in picks.items():
        m, lab = marks[k]
        ax.scatter(F[i, 0], F[i, 1], marker=m, s=160, facecolors="none", edgecolors="#C8693F",
                   linewidths=2.2, label=lab)
    ax.scatter(*baseline_F[:2], marker="X", s=160, color="#B23B3B", label="Conventional tile")
    ax.set_xlabel("Water used (L/day per window)")
    ax.set_ylabel("Heat gain into the room (kWh/day)")
    ax.set_title("ROOTCODE Pareto front (NSGA-II)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_comparison(base_res, opt_res, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plants = [p["plant"] for p in opt_res["pockets"]]
    x = np.arange(len(plants))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x - .2, [p["ratio"] for p in base_res["pockets"]], .4, color="#B23B3B", label="Conventional tile")
    ax.bar(x + .2, [p["ratio"] for p in opt_res["pockets"]], .4, color="#4E7D3A", label="ROOTCODE (balanced)")
    ax.axhline(1, color="k", lw=1, ls="--")
    ax.set_xticks(x, plants)
    ax.set_ylabel("Water received / water needed")
    ax.set_title("Same water budget, different geometry")
    ax.legend()
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
