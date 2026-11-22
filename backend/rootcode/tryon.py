"""
Stage 1 try-on - paint the optimized tiles onto a photo of the wall / window.

Geometry, not AI: every star aperture, plant pocket and channel comes from the real optimized
design (same functions as the laser files), drawn in a rectified "wall plane" texture and warped
onto the photo with the homography of the 4 corners the user marked.

    from rootcode.tryon import tryon
    res = tryon(img_rgb, corners=[(x,y)*4 tl,tr,br,bl], real_width_m=1.2, design=TileDesign(...))
    res["image"]  -> RGB try-on,   res["mask"] -> uint8 0/1 area covered by tiles

Corners can come straight from POST /facade (`quad_px`).
"""
import math
import cv2
import numpy as np

from . import config as C
from .export import MM, aperture_stars
from .facade import rectify, _order_corners
from .tile import pocket_layout, cooling_route

TILE_PX = 180                     # texture resolution of one 30 x 30 cm tile
TERRACOTTA = (200, 105, 63)       # RGB, same colour as the dashboard preview
GROUT = (120, 70, 48)
SOIL = (74, 52, 38)
PLANT_COLORS = {                  # leaf colour, fruit colour (None = no fruit)
    "mint": ((70, 140, 60), None), "basil": ((60, 125, 45), None), "parsley": ((80, 150, 55), None),
    "lettuce": ((130, 180, 80), None), "strawberry": ((70, 130, 55), (200, 30, 40)),
    "chili": ((65, 120, 50), (210, 40, 25)), "cherry_tomato": ((75, 130, 55), (220, 50, 35)),
}


def _px(v_m, s):
    return int(round(v_m * MM * s))


def _tile_texture(design, root, rng):
    """One tile: RGB + alpha (alpha 0 inside the star perforations, wall shows through)."""
    s = TILE_PX / (C.TILE_W * MM)                 # px per mm
    n = TILE_PX
    rgb = np.zeros((n, n, 3), np.uint8)
    rgb[:] = TERRACOTTA
    # subtle clay texture
    noise = rng.normal(0, 6, (n, n, 1)).astype(np.int16)
    rgb = np.clip(rgb.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    alpha = np.full((n, n), 255, np.uint8)

    for star in aperture_stars(design, root=root):
        pts = np.array([[x * s, y * s] for x, y in star], np.int32)
        cv2.fillPoly(alpha, [pts], 0)
        # shadow on the lower edge of each hole: the screen has real depth (layers x 3 mm)
        cv2.polylines(rgb, [pts + [0, max(1, design.layers)]], True, GROUT, 1, cv2.LINE_AA)

    if root:
        if design.cooling_open:
            (x0, y0), (x1, y1) = cooling_route()
            cv2.rectangle(rgb, (_px(0.015, s), _px(C.COOL_STRIP_Y - 0.015, s)),
                          (_px(C.TILE_W - 0.015, s), _px(C.COOL_STRIP_Y + 0.015, s)), (150, 120, 95), -1)
        for p in pocket_layout(design.plants):
            x0, y0 = _px(p.cx - C.POCKET_W / 2, s), _px(p.cy - C.POCKET_H / 2, s)
            x1, y1 = _px(p.cx + C.POCKET_W / 2, s), _px(p.cy + C.POCKET_H / 2, s)
            cv2.rectangle(rgb, (x0, y0), (x1, y1), SOIL, -1)
            cv2.rectangle(rgb, (x0, y0), (x1, y1), GROUT, 2)
            leaf, fruit = PLANT_COLORS.get(p.plant, ((70, 140, 60), None))
            w, h = x1 - x0, y1 - y0
            for _ in range(14):                     # leaves spilling out of the pocket
                cx = int(rng.uniform(x0, x1)); cy = int(rng.uniform(y0 - 0.35 * h, y1 - 0.2 * h))
                r = int(rng.uniform(0.10, 0.18) * w)
                shade = tuple(int(np.clip(c + rng.normal(0, 12), 0, 255)) for c in leaf)
                cv2.ellipse(rgb, (cx, cy), (r, int(r * 0.6)), rng.uniform(0, 180), 0, 360, shade, -1, cv2.LINE_AA)
                cv2.ellipse(alpha, (cx, cy), (r, int(r * 0.6)), 0, 0, 360, 255, -1)  # leaves are opaque
            if fruit:
                for _ in range(4):
                    cx = int(rng.uniform(x0 + 0.15 * w, x1 - 0.15 * w)); cy = int(rng.uniform(y0, y1))
                    cv2.circle(rgb, (cx, cy), max(2, int(0.07 * w)), fruit, -1, cv2.LINE_AA)

    # grout line around each tile
    cv2.rectangle(rgb, (0, 0), (n - 1, n - 1), GROUT, 2)
    return rgb, alpha


def tryon(img_rgb, corners, real_width_m, design, root_tiles=4, real_height_m=None, seed=0):
    """
    corners: 4 (x, y) points in img_rgb pixels around the area to cover (any order).
    Returns dict(image, mask, window_w_m, window_h_m, tiles{columns, rows, total, root_tiles}).
    """
    quad = _order_corners(corners)
    aspect, H, (wp, hp), f_source = rectify(quad, img_rgb.shape)
    w_m = float(real_width_m)
    h_m = float(real_height_m) if real_height_m else w_m * aspect
    nx, ny = max(1, math.ceil(w_m / C.TILE_W)), max(1, math.ceil(h_m / C.TILE_H))
    n_root = min(root_tiles, nx * ny)

    rng = np.random.default_rng(seed)
    root_tex = _tile_texture(design, True, rng)
    shade_tex = _tile_texture(design, False, rng)

    # rectified wall plane, cropped to the real covered size (edge tiles are cut, like on site)
    Wt, Ht = nx * TILE_PX, ny * TILE_PX
    tex = np.zeros((Ht, Wt, 3), np.uint8)
    alp = np.zeros((Ht, Wt), np.uint8)
    for j in range(ny):
        for i in range(nx):
            # root tiles: bottom row first (closest to the sill, easy to refill and harvest)
            k = (ny - 1 - j) * nx + i
            rgb, a = root_tex if k < n_root else shade_tex
            tex[j * TILE_PX:(j + 1) * TILE_PX, i * TILE_PX:(i + 1) * TILE_PX] = rgb
            alp[j * TILE_PX:(j + 1) * TILE_PX, i * TILE_PX:(i + 1) * TILE_PX] = a
    cw = max(1, int(round(w_m / C.TILE_W * TILE_PX)))
    ch = max(1, int(round(h_m / C.TILE_H * TILE_PX)))
    tex, alp = tex[Ht - ch:, :cw], alp[Ht - ch:, :cw]   # grid starts at the sill: cut the TOP row

    # rectified texture -> photo
    src = np.array([[0, 0], [cw, 0], [cw, ch], [0, ch]], np.float32)
    M = cv2.getPerspectiveTransform(src, quad.astype(np.float32))
    h_img, w_img = img_rgb.shape[:2]
    warped = cv2.warpPerspective(tex, M, (w_img, h_img), flags=cv2.INTER_AREA)
    a_w = cv2.warpPerspective(alp, M, (w_img, h_img), flags=cv2.INTER_LINEAR).astype(np.float32) / 255
    cover = cv2.warpPerspective(np.full((ch, cw), 255, np.uint8), M, (w_img, h_img)) > 127

    # perforations: the photo shows through, darkened by the screen's shadow
    behind = img_rgb.astype(np.float32) * 0.55
    out = img_rgb.astype(np.float32)
    a3 = a_w[..., None]
    blended = warped.astype(np.float32) * a3 + behind * (1 - a3)
    out[cover] = blended[cover]
    return {
        "image": np.clip(out, 0, 255).astype(np.uint8),
        "mask": cover.astype(np.uint8),
        "window_w_m": round(w_m, 3), "window_h_m": round(h_m, 3),
        "height_source": "measured by user" if real_height_m else f"estimated from photo ({f_source})",
        "tiles": {"columns": nx, "rows": ny, "total": nx * ny, "root_tiles": n_root},
        "corners_px": quad.round(1).tolist(),
    }
