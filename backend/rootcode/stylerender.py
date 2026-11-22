"""
Drawing a generated cultural design:
  * svg(gen)                  - vector preview for the gallery (frame, openings, planting cells, hidden channels)
  * texture(gen, res)         - RGBA raster of the same geometry in the wall plane (metres -> pixels)
  * install(photo, gen, area) - perspective-correct composite onto the user's photo, ONLY inside the selected
                                usable area; everything else stays the original photograph.
The realistic preview (optional) is the existing SD 1.5 + ControlNet step conditioned on this composite.
"""
import math

import cv2
import numpy as np

from .tryon import PLANT_COLORS

WOOD = (201, 160, 110)          # RGB light oak
WOOD_DARK = (150, 108, 66)
SCREEN = (222, 196, 150)
SOIL = (78, 58, 40)
WATER = (79, 143, 176)


def _pts(poly, s, ox=0, oy=0):
    return np.array([[(x + ox) * s, (y + oy) * s] for x, y in poly], np.int32)


def _plant_svg(cx, cy, r, plant, k):
    leaf, fruit = PLANT_COLORS.get(plant, ((70, 140, 60), None))
    out = []
    for i in range(7):
        a = i / 7 * 2 * math.pi + k
        x, y = cx + math.cos(a) * r * 0.45, cy - r * 0.2 + math.sin(a) * r * 0.35
        out.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{r*0.36:.1f}" ry="{r*0.22:.1f}" '
                   f'transform="rotate({math.degrees(a):.0f} {x:.1f} {y:.1f})" fill="rgb{tuple(min(255, c + (i % 3) * 12) for c in leaf)}"/>')
    if fruit:
        for i in range(3):
            out.append(f'<circle cx="{cx + (i - 1) * r * 0.3:.1f}" cy="{cy + r * 0.05:.1f}" r="{r*0.11:.1f}" fill="rgb{fruit}"/>')
    return "".join(out)


def svg(gen, show_channels=True, px_per_m=400, tight=False):
    """tight=True: crop to the structure (no supply tube margin), for small pattern thumbnails."""
    W, H = gen["width_m"], gen["height_m"]
    s = px_per_m
    if tight:
        xs = [x for c in gen["cells"] for x, _ in c["poly"]]
        ys = [y for c in gen["cells"] for _, y in c["poly"]]
        x0, y0 = min(xs) * s - 6, min(ys) * s - 6
        vw, vh = (max(xs) - min(xs)) * s + 12, (max(ys) - min(ys)) * s + 12
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {vw:.0f} {vh:.0f}" preserveAspectRatio="xMidYMid slice" '
             f'role="img" aria-label="{gen["name"]} pattern">']
        o.append(f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{vw:.0f}" height="{vh:.0f}" fill="#efe9dc"/>')
    else:
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-20 -130 {W*s+40:.0f} {H*s+150:.0f}" role="img" '
             f'aria-label="{gen["name"]}: {gen["metrics"]["planting_cells"]} planting cells">']
        o.append(f'<rect x="-20" y="-130" width="{W*s+40:.0f}" height="{H*s+150:.0f}" fill="#efe9dc"/>')
        # supply tube from above
        sx = gen["supply"]["x"] * s
        o.append(f'<path d="M{sx:.0f} -130 V0" stroke="#7d8a6a" stroke-width="5" stroke-linecap="round"/>')
    for seg in gen.get("segments", []):
        a, b = seg["a"], seg["b"]
        o.append(f'<line x1="{a[0]*s:.1f}" y1="{a[1]*s:.1f}" x2="{b[0]*s:.1f}" y2="{b[1]*s:.1f}" '
                 f'stroke="rgb{WOOD_DARK}" stroke-width="{seg["w"]*s:.1f}" stroke-linecap="round"/>')
    for c in gen["cells"]:
        outline = " ".join(f"{x*s:.1f},{y*s:.1f}" for x, y in c["poly"])
        if c["role"] == "open":
            d = "M" + " L".join(f"{x*s:.1f} {y*s:.1f}" for x, y in c["poly"]) + " Z"
            for m in c["motif"]:
                d += " M" + " L".join(f"{x*s:.1f} {y*s:.1f}" for x, y in m) + " Z"
            o.append(f'<path d="{d}" fill="rgb{SCREEN}" fill-rule="evenodd"/>')
        else:
            o.append(f'<polygon points="{outline}" fill="rgb{SOIL}"/>')
            r = c["reservoir"]
            if r:
                clip_id = f"{gen['style']}{'-t' if tight else ''}-c{c['id']}"
                o.append(f'<clipPath id="{clip_id}"><polygon points="{outline}"/></clipPath>')
                o.append(f'<rect class="hyd" clip-path="url(#{clip_id})" x="{(c["cx"]-c["w"])*s:.1f}" y="{r["top_y"]*s:.1f}" '
                         f'width="{c["w"]*2*s:.1f}" height="{c["h"]*s:.1f}" fill="rgb{WATER}" opacity=".55"/>')
            o.append(_plant_svg(c["cx"] * s, (c["cy"] - c["h"] * 0.1) * s, min(c["w"], c["h"]) * 0.5 * s, c.get("plant"), c["id"]))
        o.append(f'<polygon points="{outline}" fill="none" stroke="rgb{WOOD}" stroke-width="{0.022*s:.1f}" stroke-linejoin="round"/>')
    if show_channels:
        for ch in gen["channels"]:
            d = "M" + " L".join(f"{x*s:.1f} {y*s:.1f}" for x, y in ch["points"])
            o.append(f'<path class="hyd" d="{d}" fill="none" stroke="rgb{WATER}" stroke-width="3" stroke-dasharray="7 5" opacity=".9"/>')
    o.append("</svg>")
    return "".join(o)


def texture(gen, res=300, seed=0):
    """RGBA wall-plane texture of the design, res px per metre, plus a soft shadow alpha."""
    W, H = gen["width_m"], gen["height_m"]
    w, h = int(math.ceil(W * res)) + 2, int(math.ceil(H * res)) + 2
    rgb = np.zeros((h, w, 3), np.uint8)
    a = np.zeros((h, w), np.uint8)
    rng = np.random.default_rng(seed)
    for seg in gen.get("segments", []):
        p1 = tuple(int(v * res) for v in seg["a"])
        p2 = tuple(int(v * res) for v in seg["b"])
        cv2.line(rgb, p1, p2, WOOD_DARK, max(2, int(seg["w"] * res)), cv2.LINE_AA)
        cv2.line(a, p1, p2, 255, max(2, int(seg["w"] * res)), cv2.LINE_AA)
    for c in gen["cells"]:
        poly = _pts(c["poly"], res)
        if c["role"] == "open":
            cv2.fillPoly(rgb, [poly], SCREEN)
            cv2.fillPoly(a, [poly], 255)
            for m in c["motif"]:
                cv2.fillPoly(a, [_pts(m, res)], 0)
        else:
            cv2.fillPoly(rgb, [poly], SOIL)
            cv2.fillPoly(a, [poly], 255)
            leaf, fruit = PLANT_COLORS.get(c.get("plant"), ((70, 140, 60), None))
            r = min(c["w"], c["h"]) * res * 0.5
            for _ in range(22):
                x = int(c["cx"] * res + rng.normal(0, r * 0.4))
                y = int((c["cy"] - c["h"] * 0.12) * res + rng.normal(0, r * 0.32))
                rr = int(rng.uniform(0.14, 0.24) * r)
                col = tuple(int(np.clip(v + rng.normal(0, 14), 0, 255)) for v in leaf)
                cv2.ellipse(rgb, (x, y), (rr, int(rr * 0.6)), rng.uniform(0, 180), 0, 360, col, -1, cv2.LINE_AA)
                cv2.ellipse(a, (x, y), (rr, int(rr * 0.6)), 0, 0, 360, 255, -1)
            if fruit:
                for _ in range(4):
                    cv2.circle(rgb, (int(c["cx"] * res + rng.normal(0, r * 0.3)), int(c["cy"] * res + rng.normal(0, r * 0.2))),
                               max(2, int(r * 0.09)), fruit, -1, cv2.LINE_AA)
        cv2.polylines(rgb, [poly], True, WOOD, max(2, int(0.022 * res)), cv2.LINE_AA)
        cv2.polylines(a, [poly], True, 255, max(2, int(0.022 * res)), cv2.LINE_AA)
    # supply tube entering from above (drawn in the plane up to 0.25 m above the structure: clipped by the frame)
    return rgb, a


def install(photo_rgb, gen, area, res=300, light=(-0.6, -0.8)):
    """Warp the design onto the photo with the plane->photo homography; only inside the usable area."""
    h_img, w_img = photo_rgb.shape[:2]
    rgb, a = texture(gen, res)
    P = np.array(area["plane_to_photo"], float) @ np.diag([1 / res, 1 / res, 1.0])     # texture px -> photo px
    warped = cv2.warpPerspective(rgb, P, (w_img, h_img), flags=cv2.INTER_AREA)
    alpha = cv2.warpPerspective(a, P, (w_img, h_img), flags=cv2.INTER_LINEAR).astype(np.float32) / 255

    # usable area in the photo (the design never leaves the user's selection)
    usable = np.zeros((int(gen["height_m"] * res) + 2, int(gen["width_m"] * res) + 2), np.uint8)
    for p in area.get("region_polygons_m") or []:
        cv2.fillPoly(usable, [_pts(p["outer"], res)], 255)
        for hole in p.get("holes") or []:
            cv2.fillPoly(usable, [_pts(hole, res)], 0)
    if not area.get("region_polygons_m"):
        usable[:] = 255
    region = cv2.warpPerspective(usable, P, (w_img, h_img), flags=cv2.INTER_NEAREST) > 127
    alpha *= region

    # contact shadow cast on the wall (direction of the light in the photo plane)
    scale = math.sqrt(abs(np.linalg.det(P[:2, :2])))
    off = np.float32([[1, 0, light[0] * -0.03 * res * scale], [0, 1, light[1] * -0.03 * res * scale]])
    shadow = cv2.GaussianBlur(cv2.warpAffine(alpha, off, (w_img, h_img)), (0, 0), max(1.0, 0.012 * res * scale))
    out = photo_rgb.astype(np.float32) * (1 - 0.38 * shadow[..., None])
    out = warped.astype(np.float32) * alpha[..., None] + out * (1 - alpha[..., None])
    cover = (alpha > 0.02) | (shadow > 0.05)
    return np.clip(out, 0, 255).astype(np.uint8), cover.astype(np.uint8), region.astype(np.uint8)


STYLE_PROMPT = ("architectural photograph of a building wall with an installed handcrafted light oak wooden lattice "
                "structure in {name} geometry, edible herbs and small vegetables growing inside the cells, "
                "Mediterranean daylight, realistic materials and shadows, high detail")
