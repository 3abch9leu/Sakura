"""
Photo-like preview of a design on the user's photo, with no AI model and no GPU: about one second on a CPU.

What is drawn, in the wall plane (metres -> pixels), then warped onto the photo with the plane->photo homography:
  * a wooden lattice: every cell frame and every cultural motif as a rounded wooden strip (wood grain, bevel
    lighting from the light direction), a thicker outer frame;
  * a terracotta planter in each planting cell, and the plant itself, leaf by leaf (shaded leaf sprites with
    midrib and veins; the leaf shape, colour and fruits depend on the species: basil, mint, cherry tomato,
    strawberry, lettuce, chili, parsley); mint trails down over the cell below;
  * the shadow the lattice (standing ~12 cm off the wall) casts on the wall, plus contact occlusion;
  * a colour grade so the wood and leaves take the photo's own exposure and white balance, and a little grain.

It is a design visualization, not a photograph: the caption says so. Nothing outside the selected area changes.
"""
import functools
import math

import cv2
import numpy as np

STANDOFF_M = 0.12          # lattice distance from the wall (shadow offset)
FRAME_M = 0.034            # cell frame strip width
MOTIF_M = 0.017            # motif strip width
OUTER_M = 0.055            # outer frame width
LIGHT = np.array([-0.55, -0.75, 1.0])   # light from the upper left, towards the wall (x right, y down, z out)

# leaf colour (RGB 0-1), leaf shape (length/width ratio, serration, gloss), size factor, fruit
PLANTS = {
    "basil":         dict(leaf=(0.30, 0.52, 0.19), ratio=1.7, serr=0.00, gloss=0.22, n=34, size=0.42, habit="bush"),
    "mint":          dict(leaf=(0.25, 0.44, 0.20), ratio=1.8, serr=0.10, gloss=0.08, n=30, size=0.34, habit="trail"),
    "cherry_tomato": dict(leaf=(0.22, 0.42, 0.16), ratio=2.2, serr=0.12, gloss=0.05, n=30, size=0.40, habit="bush", fruit="tomato"),
    "strawberry":    dict(leaf=(0.24, 0.48, 0.18), ratio=1.25, serr=0.14, gloss=0.10, n=21, size=0.40, habit="trifoliate", fruit="strawberry"),
    "lettuce":       dict(leaf=(0.50, 0.66, 0.30), ratio=1.15, serr=0.07, gloss=0.06, n=18, size=0.50, habit="rosette"),
    "chili":         dict(leaf=(0.21, 0.45, 0.17), ratio=2.8, serr=0.00, gloss=0.15, n=28, size=0.40, habit="bush", fruit="chili"),
    "parsley":       dict(leaf=(0.18, 0.42, 0.14), ratio=1.3, serr=0.22, gloss=0.04, n=46, size=0.24, habit="bush"),
}
DEFAULT_PLANT = "basil"


# ================================================================ sprites (cached, built once)
SPR_L = 96          # sprite leaf length in px (stamped scaled)


@functools.lru_cache(maxsize=32)
def leaf_sprite(ratio, serr, gloss, seed=0):
    """RGBA float32 leaf, base at the left middle, tip at the right. RGB is a grey shading map (x leaf colour)."""
    ss = 3                                         # supersampling for clean edges
    L = SPR_L * ss
    Wd = L / ratio
    h = int(Wd) + 4 * ss
    y, x = np.mgrid[0:h, 0:L].astype(np.float32)
    t = x / L
    yc = (y - h / 2)
    half = Wd / 2 * np.power(np.clip(np.sin(np.pi * np.power(t, 0.85)), 0, 1), 0.85)
    if serr:
        rng = np.random.default_rng(seed)
        teeth = 9 + int(rng.integers(0, 4))
        half = half * (1 - serr * np.abs(np.sin(t * np.pi * teeth)) ** 1.5)
    r = np.abs(yc) / np.maximum(half, 1e-3)
    inside = (r < 1) & (t > 0.004) & (t < 0.996)
    a = inside.astype(np.float32)
    # shading: darker base, lighter tip; one half slightly darker (the leaf is folded along the midrib)
    sh = 0.78 + 0.30 * t - 0.10 * (yc > 0) - 0.10 * r ** 3
    vein = 0.04 * np.cos((t * 7 - r * 1.3) * 2 * np.pi) * (r < 0.92)
    mid = 0.22 * np.exp(-(yc / (1.1 * ss)) ** 2) * (t < 0.92)
    spec = gloss * np.exp(-((r - 0.38) / 0.22) ** 2) * np.sin(np.pi * t) * (yc < 0)
    g = np.clip(sh + vein + mid + spec, 0, 1.6)
    spr = np.dstack([g * a, g * a, g * a, a]).astype(np.float32)          # premultiplied while resizing
    spr = cv2.resize(spr, (SPR_L, max(3, h // ss)), interpolation=cv2.INTER_AREA)
    spr[..., :3] = np.where(spr[..., 3:4] > 1e-3, spr[..., :3] / np.maximum(spr[..., 3:4], 1e-3), 0)
    return spr


@functools.lru_cache(maxsize=8)
def fruit_sprite(kind):
    """RGBA float32 fruit/flower sprite, centred, RGB in colour (0-1)."""
    n = 64
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    u, v = (x - n / 2) / (n / 2), (y - n / 2) / (n / 2)
    if kind == "tomato":
        r = np.hypot(u, v * 1.05)
        a = np.clip((1 - r) * 18, 0, 1)
        base = np.array([0.80, 0.12, 0.08])
        light = np.clip(0.55 + 0.6 * (-(u * 0.55) - (v * 0.75)) * (1 - r * 0.3), 0.3, 1.25)
        hl = 0.9 * np.exp(-(((u + 0.35) / 0.16) ** 2 + ((v + 0.38) / 0.12) ** 2))
        rgb = base[None, None] * light[..., None] + hl[..., None]
        calyx = (np.hypot(u, v + 0.82) < 0.22)
        rgb[calyx] = (0.2, 0.42, 0.15)
        a = np.maximum(a, calyx.astype(np.float32))
    elif kind == "strawberry":
        w = np.clip(1 - (v + 0.2) / 1.2, 0, 1) * 0.85 + 0.05             # cone, wide at the top
        r = np.abs(u) / np.maximum(w, 1e-3)
        a = np.clip((1 - r) * 12, 0, 1) * (v > -0.75) * (v < 0.95)
        base = np.array([0.82, 0.10, 0.12])
        light = np.clip(0.6 + 0.5 * (-u * 0.6 - v * 0.4), 0.3, 1.2)
        rgb = base[None, None] * light[..., None]
        seeds = (np.sin(u * 22) * np.sin(v * 22) > 0.9) & (a > 0.5)
        rgb[seeds] = (0.95, 0.85, 0.35)
        top = (v < -0.6) & (np.abs(u) < 0.6)
        rgb[top] = (0.18, 0.45, 0.15)
        a = np.where(top, 1.0, a)
    elif kind == "chili":
        cv = u + 0.25 * (v + 1) ** 2 - 0.3                               # a curved pod hanging down
        w = 0.22 * np.clip(1 - (v + 0.8) / 1.8, 0, 1) + 0.02
        a = np.clip((1 - np.abs(cv) / w) * 6, 0, 1) * (v > -0.85) * (v < 0.95)
        base = np.array([0.80, 0.08, 0.05])
        light = np.clip(0.6 + 0.9 * (-cv / w * 0.4), 0.35, 1.25)
        rgb = base[None, None] * light[..., None]
        top = (v < -0.65) & (a > 0)
        rgb[top] = (0.22, 0.45, 0.16)
    else:                                                                # flower: five white petals, yellow heart
        ang = np.arctan2(v, u)
        rr = np.hypot(u, v)
        pet = 0.55 + 0.4 * np.abs(np.cos(ang * 2.5))
        a = np.clip((pet - rr) * 10, 0, 1)
        rgb = np.ones((n, n, 3)) * 0.97
        rgb[rr < 0.25] = (0.95, 0.8, 0.2)
    return np.dstack([np.clip(rgb, 0, 1.4), a]).astype(np.float32)


# ================================================================ canvas helpers
class Canvas:
    """Premultiplied RGBA float32 layer."""

    def __init__(self, h, w):
        self.rgb = np.zeros((h, w, 3), np.float32)
        self.a = np.zeros((h, w), np.float32)
        self.h, self.w = h, w

    def over(self, rgb, a, x0=0, y0=0):
        """Alpha-over a straight-alpha patch at (x0, y0)."""
        h, w = a.shape
        x1, y1 = min(self.w, x0 + w), min(self.h, y0 + h)
        sx, sy = max(0, -x0), max(0, -y0)
        x0c, y0c = max(0, x0), max(0, y0)
        if x1 <= x0c or y1 <= y0c:
            return
        pa = a[sy:sy + y1 - y0c, sx:sx + x1 - x0c]
        pr = rgb[sy:sy + y1 - y0c, sx:sx + x1 - x0c]
        dst_rgb = self.rgb[y0c:y1, x0c:x1]
        dst_a = self.a[y0c:y1, x0c:x1]
        dst_rgb *= (1 - pa)[..., None]
        dst_rgb += pr * pa[..., None]
        dst_a *= (1 - pa)
        dst_a += pa

    def line(self, p1, p2, color, width):
        """An opaque stroke (stems)."""
        wd = max(1, int(width))
        x0, y0 = int(min(p1[0], p2[0])) - wd - 1, int(min(p1[1], p2[1])) - wd - 1
        x1, y1 = int(max(p1[0], p2[0])) + wd + 2, int(max(p1[1], p2[1])) + wd + 2
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.line(m, (int(p1[0]) - x0, int(p1[1]) - y0), (int(p2[0]) - x0, int(p2[1]) - y0), 255, wd, cv2.LINE_AA)
        a = m.astype(np.float32) / 255
        self.over(np.ones(m.shape + (3,), np.float32) * np.asarray(color, np.float32), a, x0, y0)

    def stamp(self, spr, x, y, length, angle, color, anchor="base"):
        """Draw a sprite: anchor point at (x, y), scaled so its width is `length` px, rotated by `angle` (rad)."""
        sh, sw = spr.shape[:2]
        s = length / sw
        if s * sw < 2:
            return
        ca, sa = math.cos(angle) * s, math.sin(angle) * s
        ax, ay = (0.0, sh / 2) if anchor == "base" else (sw / 2, sh / 2)
        corners = np.array([[0, 0], [sw, 0], [0, sh], [sw, sh]], np.float32) - (ax, ay)
        pts = np.stack([corners[:, 0] * ca - corners[:, 1] * sa + x, corners[:, 0] * sa + corners[:, 1] * ca + y], 1)
        x0, y0 = int(math.floor(pts[:, 0].min())) - 1, int(math.floor(pts[:, 1].min())) - 1
        x1, y1 = int(math.ceil(pts[:, 0].max())) + 1, int(math.ceil(pts[:, 1].max())) + 1
        if x1 < 0 or y1 < 0 or x0 >= self.w or y0 >= self.h:
            return
        M = np.array([[ca, -sa, x - x0 - (ax * ca - ay * sa)], [sa, ca, y - y0 - (ax * sa + ay * ca)]], np.float32)
        warped = cv2.warpAffine(spr, M, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
        a = warped[..., 3]
        rgb = warped[..., :3] * np.asarray(color, np.float32)[None, None]
        self.over(rgb, a, x0, y0)


def _wood_texture(h, w, rng):
    """Teak-like wood albedo: long grain streaks and a little colour variation."""
    n = rng.random((max(8, h // 6), max(8, w // 2))).astype(np.float32)
    n = cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC)
    n = cv2.GaussianBlur(n, (0, 0), sigmaX=18, sigmaY=1.2)
    n = (n - n.mean()) / (n.std() + 1e-6)
    fine = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), sigmaX=6, sigmaY=0.6)
    fine = (fine - fine.mean()) / (fine.std() + 1e-6)
    g = 0.92 + 0.07 * n + 0.04 * fine
    base = np.array([0.66, 0.42, 0.22], np.float32)               # warm teak
    return np.clip(g[..., None] * base[None, None], 0, 1)


def _strip_shading(mask, half_px):
    """Rounded strip profile -> Lambert + a soft highlight, from the light direction."""
    m8 = (mask > 0.5).astype(np.uint8)
    d = cv2.distanceTransform(m8, cv2.DIST_L2, 3)
    hgt = np.sqrt(np.clip(1 - (1 - np.clip(d / max(half_px, 1), 0, 1)) ** 2, 0, 1))
    hgt = cv2.GaussianBlur(hgt, (0, 0), 0.6)
    gx = cv2.Sobel(hgt, cv2.CV_32F, 1, 0, ksize=3) / 8 * half_px
    gy = cv2.Sobel(hgt, cv2.CV_32F, 0, 1, ksize=3) / 8 * half_px
    nrm = np.dstack([-gx, -gy, np.ones_like(gx)])
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
    L = LIGHT / np.linalg.norm(LIGHT)
    lam = np.clip((nrm * L[None, None]).sum(2), 0, 1)
    spec = np.clip(lam, 0, 1) ** 24 * 0.18
    return 0.42 + 0.68 * lam, spec


def _poly_px(poly, res):
    return np.round(np.asarray(poly, np.float64) * res).astype(np.int32)


# ================================================================ plants
def _plant(cv, rng, kind, cx, base_y, size, light_mul):
    """One plant, rooted at (cx, base_y) in px, about `size` px tall."""
    p = PLANTS.get(kind) or PLANTS[DEFAULT_PLANT]
    leaf_col = np.array(p["leaf"], np.float32)
    spr = [leaf_sprite(p["ratio"], p["serr"], p["gloss"], s) for s in range(3)]
    L = size * p["size"] * 1.0
    n = p["n"]
    habit = p["habit"]

    def leaf(x, y, length, ang, depth):
        col = leaf_col * light_mul * (0.48 + 0.55 * depth) * rng.uniform(0.85, 1.1)
        col = col * (1 + rng.normal(0, 0.05, 3)) + rng.normal(0, 0.015)          # hue / value variation
        cv.stamp(spr[int(rng.integers(0, 3))], x, y, length, ang, col)

    # back to front: depth 0 = behind (darker), 1 = front
    if habit == "rosette":
        for i in range(n):
            depth = i / n
            ang = -math.pi / 2 + rng.normal(0, 0.75) * (1.1 - depth * 0.4)
            leaf(cx + rng.normal(0, size * 0.05), base_y, L * rng.uniform(0.7, 1.05), ang, depth)
    elif habit == "trifoliate":
        for i in range(n // 3):
            depth = i / (n // 3)
            ang = -math.pi / 2 + rng.normal(0, 0.7)
            stem = size * rng.uniform(0.25, 0.55)
            sx, sy = cx + math.cos(ang) * stem, base_y + math.sin(ang) * stem
            cv.line((cx, base_y), (sx, sy), np.array([0.20, 0.34, 0.14]) * light_mul, size * 0.014)
            for da in (-0.75, 0, 0.75):
                leaf(sx, sy, L * 0.55 * rng.uniform(0.85, 1.1), ang + da, depth)
    else:
        for i in range(n):
            depth = i / n
            # leaves rise from stems spread over a dome
            ang_stem = -math.pi / 2 + rng.normal(0, 0.62)
            reach = size * rng.uniform(0.05, 0.62) * (1.05 - depth * 0.3)
            x = cx + math.cos(ang_stem) * reach
            y = base_y + math.sin(ang_stem) * reach * 0.95
            ang = ang_stem + rng.normal(0, 0.55)
            leaf(x, y, L * rng.uniform(0.75, 1.15), ang, depth)

    if habit == "trail":                       # mint: stems falling over the planter's edge
        for _ in range(int(rng.integers(2, 4))):
            x, y = cx + rng.normal(0, size * 0.25), base_y
            side = 1 if rng.random() > 0.5 else -1
            for k in range(9):
                x += side * size * 0.04 * (1 - k / 10) + rng.normal(0, size * 0.01)
                y += size * 0.09
                for s in (-1, 1):
                    leaf(x, y, L * 0.55 * (1 - k * 0.05), math.pi / 2 + s * 1.0 + rng.normal(0, 0.3), 0.5 + 0.4 * rng.random())

    fruit = p.get("fruit")
    if fruit:
        spr_f = fruit_sprite(fruit)
        m = {"tomato": 7, "strawberry": 4, "chili": 5}[fruit]
        fs = {"tomato": 0.11, "strawberry": 0.14, "chili": 0.20}[fruit]
        for _ in range(m):
            fx = cx + rng.normal(0, size * 0.22)
            fy = base_y - size * rng.uniform(0.0, 0.45) if fruit != "strawberry" else base_y + size * rng.uniform(-0.05, 0.12)
            cv.stamp(spr_f, fx, fy, size * fs * rng.uniform(0.85, 1.15), rng.normal(0, 0.25), light_mul, anchor="centre")
        if fruit == "strawberry":
            for _ in range(2):
                cv.stamp(fruit_sprite("flower"), cx + rng.normal(0, size * 0.2), base_y - size * rng.uniform(0.15, 0.4),
                         size * 0.09, 0, light_mul, anchor="centre")


def _planter(cv, poly_px, cx, cy, w, h, light_mul):
    """Terracotta planter in the lower part of a cell, clipped to the cell."""
    pw, ph = w * 0.74, h * 0.30
    x0, x1 = int(cx - pw / 2), int(cx + pw / 2)
    y1 = int(cy + h / 2 - h * 0.08)
    y0 = int(y1 - ph)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return y0
    ww, hh = x1 - x0, y1 - y0
    u = (np.arange(ww, dtype=np.float32) + 0.5) / ww
    v = (np.arange(hh, dtype=np.float32) + 0.5) / hh
    shade = (0.62 + 0.48 * np.sin(np.pi * u)[None, :] ** 0.6) * (1.02 - 0.22 * v[:, None])
    shade[: max(1, hh // 7)] *= 1.18                                       # rim
    base = np.array([0.66, 0.38, 0.26], np.float32)                        # terracotta
    rgb = shade[..., None] * base[None, None] * light_mul
    clip = np.zeros((hh, ww), np.uint8)
    cv2.fillPoly(clip, [poly_px - (x0, y0)], 1)
    # contact shadow of the planter on the lattice behind it
    sh = cv2.GaussianBlur(clip.astype(np.float32), (0, 0), max(1, hh * 0.15)) * 0.35
    cv.over(np.zeros((hh, ww, 3), np.float32), sh, x0 + max(1, int(hh * 0.06)), y0 + max(1, int(hh * 0.08)))
    cv.over(rgb, clip.astype(np.float32), x0, y0)
    return y0 + hh * 0.12


# ================================================================ main
def _px_per_m(P, W, H):
    """Photo pixels per metre near the centre of the plane (homography plane metres -> photo px)."""
    def f(x, y):
        v = P @ np.array([x, y, 1.0])
        return v[:2] / v[2]
    c = f(W / 2, H / 2)
    return float((np.linalg.norm(f(W / 2 + 0.5, H / 2) - c) + np.linalg.norm(f(W / 2, H / 2 + 0.5) - c)))


def render(photo_rgb, gen, area, seed=7, motif_fn=None):
    """Return (image RGB uint8, cover mask uint8, region mask uint8)."""
    h_img, w_img = photo_rgb.shape[:2]
    W, H = float(gen["width_m"]), float(gen["height_m"])
    P0 = np.array(area["plane_to_photo"], float)
    ppm = _px_per_m(P0, W, H)
    res = float(np.clip(ppm * 1.15, 120, 800))
    res = min(res, 3400 / max(W, H))
    tw, th = int(math.ceil(W * res)) + 4, int(math.ceil(H * res)) + 4
    rng = np.random.default_rng(seed)
    cv = Canvas(th, tw)

    # ---- photo light: exposure and white balance from the brightest pixels
    lum = photo_rgb.astype(np.float32).mean(2)
    hi = photo_rgb[lum >= np.percentile(lum, 97)].astype(np.float32) / 255
    white = hi.mean(0) if len(hi) else np.array([0.9, 0.9, 0.9])
    gain = float(np.clip(white.mean() / 0.88, 0.45, 1.12))
    tint = 0.5 + 0.5 * white / max(white.mean(), 1e-3)
    light_mul = np.clip(gain * tint, 0.3, 1.3).astype(np.float32)

    # ---- lattice strips (frames + motifs), one mask, then wood material + bevel
    strips = np.zeros((th, tw), np.uint8)
    fw, mw = max(2, int(round(FRAME_M * res))), max(1, int(round(MOTIF_M * res)))
    cells = gen["cells"]
    for c in cells:
        poly = _poly_px(c["poly"], res)
        cv2.polylines(strips, [poly], True, 255, fw, cv2.LINE_AA)
        motifs = c.get("motif") or (motif_fn(c) if motif_fn else [])
        for m in motifs:
            cv2.polylines(strips, [_poly_px(m, res)], True, 255, mw, cv2.LINE_AA)
    for s in gen.get("segments", []):          # organic branches
        cv2.line(strips, tuple(int(v * res) for v in s["a"]), tuple(int(v * res) for v in s["b"]), 255,
                 max(2, int(s["w"] * res * 1.2)), cv2.LINE_AA)
    try:                                         # outer frame around the whole lattice
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        u = unary_union([Polygon(c["poly"]).buffer(0.004) for c in cells if len(c["poly"]) >= 3])
        for g in getattr(u, "geoms", [u]):
            if g.area > 0.05:
                cv2.polylines(strips, [_poly_px(list(g.exterior.coords), res)], True, 255,
                              max(2, int(round(OUTER_M * res))), cv2.LINE_AA)
    except Exception:
        pass
    m = strips.astype(np.float32) / 255
    tex = _wood_texture(th, tw, rng)
    depth_px = max(1, int(round(0.022 * res)))                   # visible thickness of the strips
    Ld = -LIGHT[:2] / np.linalg.norm(LIGHT[:2])
    side = np.zeros_like(m)
    for k in range(1, depth_px + 1):
        Mk = np.float32([[1, 0, Ld[0] * k], [0, 1, Ld[1] * k]])
        side = np.maximum(side, cv2.warpAffine(m, Mk, (tw, th)))
    lam, spec = _strip_shading(m, fw / 2)
    front = (tex * lam[..., None] + spec[..., None]) * light_mul[None, None]
    back = tex * (0.42 * light_mul)[None, None]
    # empty canvas: write directly (front strips over their own side faces)
    cv.rgb[:] = front * m[..., None] + back * (side * (1 - m))[..., None]
    cv.a[:] = m + side * (1 - m)

    # ---- planters and plants, from the top row down (lower plants overlap the trailing stems above)
    for c in sorted([c for c in cells if c.get("role") == "plant"], key=lambda c: c["cy"]):
        cx, cy, w, h = c["cx"] * res, c["cy"] * res, c["w"] * res, c["h"] * res
        top = _planter(cv, _poly_px(c["poly"], res), cx, cy, w, h, light_mul)
        _plant(cv, rng, c.get("plant") or DEFAULT_PLANT, cx, top, min(w, h) * 0.95, light_mul)

    # ---- grain, then warp onto the photo (texture px -> photo px)
    noise = rng.normal(0, 0.012, (th, tw, 1)).astype(np.float32)
    rgb_p = np.clip(cv.rgb + noise * cv.a[..., None], 0, 1.2)
    S = np.diag([1 / res, 1 / res, 1.0])
    # work only in the photo region around the installation (+ room for overhanging leaves and shadows)
    cor = np.array([[0, 0, 1], [W, 0, 1], [W, H, 1], [0, H, 1]], float) @ P0.T
    cor = cor[:, :2] / cor[:, 2:3]
    mg = int(0.4 * ppm) + 4
    X0, Y0 = max(0, int(cor[:, 0].min()) - mg), max(0, int(cor[:, 1].min()) - mg)
    X1, Y1 = min(w_img, int(cor[:, 0].max()) + mg), min(h_img, int(cor[:, 1].max()) + mg)
    full_shape = (h_img, w_img)
    photo_full = photo_rgb
    photo_rgb = photo_rgb[Y0:Y1, X0:X1]
    h_img, w_img = photo_rgb.shape[:2]
    P = np.array([[1, 0, -X0], [0, 1, -Y0], [0, 0, 1.0]]) @ P0 @ S
    sigma = max(0.0, 0.5 * res / max(ppm, 1e-6) - 0.5)          # pre-blur against aliasing when shrinking
    if sigma > 0.3:
        rgb_p = cv2.GaussianBlur(rgb_p, (0, 0), sigma)
        a_p = cv2.GaussianBlur(cv.a, (0, 0), sigma)
    else:
        a_p = cv.a
    warped = cv2.warpPerspective(rgb_p, P, (w_img, h_img), flags=cv2.INTER_LINEAR)
    alpha = cv2.warpPerspective(a_p, P, (w_img, h_img), flags=cv2.INTER_LINEAR)

    # selected area in the photo: nothing is drawn outside it
    usable = np.zeros((th, tw), np.uint8)
    holes = np.zeros((th, tw), np.uint8)
    for poly in area.get("region_polygons_m") or []:
        cv2.fillPoly(usable, [_poly_px(poly["outer"], res)], 255)
        for hole in poly.get("holes") or []:
            cv2.fillPoly(usable, [_poly_px(hole, res)], 0)
            cv2.fillPoly(holes, [_poly_px(hole, res)], 255)
    for o in area.get("obstacles_m") or []:
        cv2.rectangle(holes, (int(o["x"] * res), int(o["y"] * res)), (int((o["x"] + o["w"]) * res), int((o["y"] + o["h"]) * res)), 255, -1)
    if not area.get("region_polygons_m"):
        usable[:] = 255
    k = max(1, int(0.10 * res))
    draw = cv2.dilate(usable, np.ones((2 * k + 1, 2 * k + 1), np.uint8)) & ~holes
    region = cv2.warpPerspective(usable, P, (w_img, h_img), flags=cv2.INTER_NEAREST) > 127
    drawable = cv2.warpPerspective(draw, P, (w_img, h_img), flags=cv2.INTER_LINEAR).astype(np.float32) / 255
    alpha = alpha * drawable
    with np.errstate(invalid="ignore", divide="ignore"):
        col = np.where(alpha[..., None] > 1e-4, warped / np.maximum(alpha[..., None], 1e-4), 0)

    # ---- shadow on the wall (lattice stands off the wall) + contact occlusion
    off = STANDOFF_M * ppm
    Ln = LIGHT / np.linalg.norm(LIGHT[:2])
    M = np.float32([[1, 0, -Ln[0] * off * 0.8], [0, 1, -Ln[1] * off * 0.8]])
    cast = cv2.GaussianBlur(cv2.warpAffine(alpha, M, (w_img, h_img)), (0, 0), max(0.8, 0.03 * ppm))
    ao = cv2.GaussianBlur(alpha, (0, 0), max(0.8, 0.012 * ppm))
    shadow = np.clip(0.42 * cast + 0.22 * ao, 0, 0.6) * np.maximum(region, drawable > 0.5)
    base = photo_rgb.astype(np.float32) / 255 * (1 - shadow[..., None])
    out = col * alpha[..., None] + base * (1 - alpha[..., None])
    res_img = photo_full.copy()
    res_img[Y0:Y1, X0:X1] = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    cover_f = np.zeros(full_shape, np.uint8)
    region_f = np.zeros(full_shape, np.uint8)
    cover_f[Y0:Y1, X0:X1] = ((alpha > 0.02) | (shadow > 0.04))
    region_f[Y0:Y1, X0:X1] = region
    return res_img, cover_f, region_f
