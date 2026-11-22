"""
Space selection - FacadeVision generalised from "find the window" to "choose any unused surface".

Workflow (each step is a function, the API exposes them one by one):
  1. suggest(img)              automatic suggestions: SAM 2 prompted on a coarse grid, deduplicated and
                               classified as "surface" (large, calm: walls, balcony parapets...) or
                               "opening" (window / door-like rectangles). Suggestions only; the user decides.
  2. refine(img, pts, labels)  the user's include (1) / exclude (0) clicks -> mask (SAM 2 -> SAM -> flood fill)
     mask_from_polygon(...)    polygon or rectangle fallback, no model at all
  3. obstacles(mask)           holes inside the selection (windows, doors, pipes...) + suggested openings
  4. installation_area(...)    one reference measurement -> metres; perspective rectification; usable area =
                               selection minus obstacles (with clearance), returned in metres for the generator.

A photo cannot tell whether a wall can carry a load: every result says so (structural check is on the user).
"""
import base64
import math

import cv2
import numpy as np

from .facade import _order_corners, rectify, segment

import threading

_SAM_LOCK = threading.Lock()
RECT_RES = 200          # px per metre in the rectified wall plane
CLEARANCE_M = 0.05      # free margin kept around every obstacle
MAX_SIDE_M = 80.0       # larger than this = a wrong measurement (cm typed as m, line too short)
MAX_PLANE_PX = 4000     # longest side of the rectified plane in px (memory bound for big facades)


# ---------------------------------------------------------------- helpers
def mask_png_b64(mask, color=(183, 123, 89), alpha=105):
    """Translucent RGBA overlay (transparent outside the mask) for the browser."""
    h, w = mask.shape[:2]
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[mask > 0] = (*color[::-1], alpha)            # cv2 is BGR(A)
    ok, buf = cv2.imencode(".png", rgba)
    return base64.b64encode(buf.tobytes()).decode()


def polygons(mask, min_frac=0.0005, eps_frac=0.004):
    """Mask -> list of {outer: [[x,y]...], holes: [[[x,y]...]...]} (image pixels, simplified)."""
    m = (mask > 0).astype(np.uint8)
    cnts, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    if hier is None:
        return out
    min_area = min_frac * m.size
    hier = hier[0]
    for i, c in enumerate(cnts):
        if hier[i][3] != -1 or cv2.contourArea(c) < min_area:
            continue
        eps = eps_frac * cv2.arcLength(c, True)
        outer = cv2.approxPolyDP(c, eps, True).reshape(-1, 2).tolist()
        holes = []
        j = hier[i][2]
        while j != -1:
            if cv2.contourArea(cnts[j]) >= min_area:
                holes.append(cv2.approxPolyDP(cnts[j], 0.01 * cv2.arcLength(cnts[j], True), True).reshape(-1, 2).tolist())
            j = hier[j][0]
        out.append({"outer": outer, "holes": holes})
    return out


def mask_from_polygon(shape_hw, outer, holes=()):
    m = np.zeros(shape_hw, np.uint8)
    cv2.fillPoly(m, [np.array(outer, np.int32)], 1)
    for h in holes:
        cv2.fillPoly(m, [np.array(h, np.int32)], 0)
    return m


def _rectangularity(c):
    a = cv2.contourArea(c)
    (_, _), (w, h), _ = cv2.minAreaRect(c)
    return a / (w * h) if w * h > 0 else 0.0


# ---------------------------------------------------------------- 1. suggestions
def _sam2_many(img_rgb, pts):
    """One SAM 2 forward pass for many single-point prompts (one object per point)."""
    import torch
    from PIL import Image
    from .facade import _MODELS, _device, _seg_sam2

    name = "facebook/sam2.1-hiera-small"
    if name not in _MODELS:
        _seg_sam2(img_rgb, [pts[0]])                    # loads the model through the shared cache
    proc, model = _MODELS[name]
    inputs = proc(images=Image.fromarray(img_rgb), input_points=[[[list(p)] for p in pts]],
                  input_labels=[[[1] for _ in pts]], return_tensors="pt").to(_device())
    with torch.no_grad():
        out = model(**inputs, multimask_output=True)
    masks = proc.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"])[0]   # (N, 3, H, W)
    scores = out.iou_scores[0].cpu().numpy()                                           # (N, 3)
    res = []
    for i in range(len(pts)):
        # two candidates per tap: the most confident mask (often the object: a window) and the
        # largest confident one (often the surface around it: the wall)
        cand = [(float(scores[i, k]), int(masks[i, k].sum()), k) for k in range(masks.shape[1])]
        best = max(cand)[2]
        good = [c for c in cand if c[0] >= 0.75] or [max(cand)]
        large = max(good, key=lambda c: c[1])[2]
        for k in {best, large}:
            res.append((masks[i, k].numpy().astype(np.uint8), float(scores[i, k]), pts[i]))
    return res


def suggest(img_rgb, grid=(5, 4)):
    """Candidate regions, each {kind, score, area_frac, bbox, polygons}. Falls back to nothing (honestly)."""
    h, w = img_rgb.shape[:2]
    pts = [((i + 0.5) * w / grid[0], (j + 0.5) * h / grid[1]) for j in range(grid[1]) for i in range(grid[0])]
    raw, err = None, None
    for attempt in range(2):                                 # the model may still be loading at server start
        try:
            with _SAM_LOCK:
                raw = _sam2_many(img_rgb, pts)
            break
        except Exception as e:
            err = e
            import time
            time.sleep(2.0)
    if raw is None:                                          # no SAM 2: no automatic suggestions (honest)
        return {"backend": None, "regions": [], "note": f"automatic suggestions unavailable ({type(err).__name__})"}
    backend = "sam2"
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 60, 160) > 0
    kept = []
    for m, sc, p in sorted(raw, key=lambda t: -int(t[0].sum())):
        area = m.sum() / m.size
        if area < 0.01 or area > 0.97:
            continue
        if any((np.logical_and(m, k["_m"]).sum() / max(1, np.logical_or(m, k["_m"]).sum())) > 0.6 for k in kept):
            continue
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cnts, key=cv2.contourArea)
        rect = _rectangularity(c)
        edge_d = float(edges[m > 0].mean())
        x, y, bw, bh = cv2.boundingRect(c)
        if area >= 0.08 and edge_d < 0.08:
            kind = "surface"
        elif rect > 0.8 and area < 0.25:
            kind = "opening"
        else:
            kind = "other"
        kept.append({"_m": m, "kind": kind, "score": round(sc, 3), "area_frac": round(float(area), 4),
                     "rectangularity": round(rect, 3), "edge_density": round(edge_d, 3),
                     "bbox": [int(x), int(y), int(bw), int(bh)], "seed": [round(p[0], 1), round(p[1], 1)]})
    # holes in a suggested surface are its windows / doors: suggest them as openings
    for k in [k for k in kept if k["kind"] == "surface"]:
        for o in obstacles(k["_m"], min_frac=0.004):
            if o["kind"] != "opening":
                continue
            hm = mask_from_polygon((h, w), o["polygon"])
            if any((np.logical_and(hm, q["_m"]).sum() / max(1, np.logical_or(hm, q["_m"]).sum())) > 0.6 for q in kept):
                continue
            x, y, bw, bh = o["bbox"]
            kept.append({"_m": hm, "kind": "opening", "score": None, "area_frac": round(float(hm.mean()), 4),
                         "rectangularity": None, "edge_density": None, "bbox": [x, y, bw, bh],
                         "seed": [x + bw / 2, y + bh / 2]})
    order = {"surface": 0, "opening": 1, "other": 2}
    kept.sort(key=lambda k: (order[k["kind"]], -k["area_frac"]))
    regions = []
    for k in kept[:10]:
        m = k.pop("_m")
        k["polygons"] = polygons(m)
        regions.append(k)
    return {"backend": backend, "regions": regions,
            "note": "Suggestions only: a visible surface is not necessarily able to carry an installation."}


# ---------------------------------------------------------------- 2. refinement
def refine(img_rgb, points, labels, backend="auto"):
    if not any(labels):
        raise ValueError("at least one include click is needed")
    mask, used, score, errors = segment(img_rgb, points, backend, labels)
    # keep only the connected parts that contain an include click (SAM sometimes adds far islands)
    n, lab = cv2.connectedComponents(mask.astype(np.uint8))
    keep = np.zeros_like(mask)
    for (x, y), l in zip(points, labels):
        xi, yi = int(min(max(x, 0), mask.shape[1] - 1)), int(min(max(y, 0), mask.shape[0] - 1))
        if l and lab[yi, xi] > 0:
            keep |= (lab == lab[yi, xi]).astype(mask.dtype)
    if keep.sum() > 0:
        mask = keep
    return mask, used, score, errors


# ---------------------------------------------------------------- 3. obstacles
def obstacles(mask, suggestions=None, min_frac=0.002):
    """Holes inside the selection (window, door, pipe...) and suggested openings overlapping it."""
    m = (mask > 0).astype(np.uint8)
    out = []
    cnts, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    sel_area = max(1, int(m.sum()))
    if hier is not None:
        for i, c in enumerate(cnts):
            if hier[0][i][3] == -1:
                continue
            a = cv2.contourArea(c)
            if a < min_frac * sel_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            rect = _rectangularity(c)
            out.append({"kind": "opening" if rect > 0.75 else "obstacle",
                        "label": ("Window or door (likely)" if rect > 0.75 else "Obstacle inside the selection"),
                        "polygon": cv2.approxPolyDP(c, 0.01 * cv2.arcLength(c, True), True).reshape(-1, 2).tolist(),
                        "bbox": [int(x), int(y), int(w), int(h)], "source": "hole in selection"})
    for s in suggestions or []:
        if s.get("kind") != "opening":
            continue
        x, y, w, h = s["bbox"]
        sub = m[y:y + h, x:x + w]
        if sub.size and 0.05 < sub.mean() < 0.95:            # partly covered by the selection
            for p in s["polygons"]:
                out.append({"kind": "opening", "label": "Window or door (suggested)", "polygon": p["outer"],
                            "bbox": s["bbox"], "source": "suggestion"})
    return out


# ---------------------------------------------------------------- 4. metric installation area
def _quad_of(mask):
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea)
    hull = cv2.convexHull(c)
    peri = cv2.arcLength(hull, True)
    for eps in (0.01, 0.02, 0.03, 0.05, 0.08):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            return _order_corners(ap)
    return _order_corners(cv2.boxPoints(cv2.minAreaRect(c)))


def installation_area(shape_hw, selection, obstacle_polys, reference, height_m=None, quad=None):
    """
    selection: list of {outer, holes} polygons in image px (union = chosen area).
    obstacle_polys: polygons (image px) to exclude, e.g. windows the user wants to keep clear.
    reference: {"p1": [x, y], "p2": [x, y], "length_m": float} - any real distance on the wall plane.
    Returns metres + the transform the preview needs.
    """
    h_img, w_img = shape_hw
    sel = np.zeros(shape_hw, np.uint8)
    for p in selection:
        sel |= mask_from_polygon(shape_hw, p["outer"], p.get("holes", []))
    if sel.sum() < 0.002 * sel.size:
        raise ValueError("the selected area is empty or too small")
    obs = np.zeros(shape_hw, np.uint8)
    for p in obstacle_polys:
        cv2.fillPoly(obs, [np.array(p, np.int32)], 1)

    q = _order_corners(np.array(quad, np.float32)) if quad else _quad_of(sel)
    aspect, H, (wp, hp), f_source = rectify(q, (h_img, w_img))

    def to_rect(pt):
        v = H @ np.array([pt[0], pt[1], 1.0])
        return v[:2] / v[2]

    edge = reference.get("edge")
    if edge in ("width", "height"):
        # the user knows the real width (or height) of the area they selected: no line to draw
        ref_px = float(wp if edge == "width" else hp)
    else:
        ref_px = float(np.linalg.norm(to_rect(reference["p1"]) - to_rect(reference["p2"])))
    if ref_px < max(12.0, 0.03 * max(wp, hp)):
        raise ValueError("the measuring line is too short: click the two ends of something long enough "
                         "(a whole door or window), not two points next to each other")
    m_per_px = float(reference["length_m"]) / ref_px
    if edge == "height" and not height_m:
        height_m = float(reference["length_m"])
    sy = (float(height_m) / hp) if height_m else m_per_px          # optional measured height fixes vertical scale
    width_m, height_full_m = wp * m_per_px, hp * sy
    if not (0.05 <= min(width_m, height_full_m) and max(width_m, height_full_m) <= MAX_SIDE_M):
        raise ValueError(f"with this measurement the area would be {width_m:.1f} x {height_full_m:.1f} m, which is "
                         "not plausible: type the length in metres (2.6, not 260) and check the measuring line")
    res = min(RECT_RES, MAX_PLANE_PX / max(width_m, height_full_m))   # big facades: coarser plane, bounded memory

    # rectified plane in metres at res px/m: S @ H maps photo -> plane
    S = np.diag([m_per_px * res, sy * res, 1.0])
    M = S @ H
    Wr, Hr = int(math.ceil(width_m * res)) + 2, int(math.ceil(height_full_m * res)) + 2
    sel_r = cv2.warpPerspective(sel * 255, M, (Wr, Hr), flags=cv2.INTER_NEAREST) > 127
    obs_r = cv2.warpPerspective(obs * 255, M, (Wr, Hr), flags=cv2.INTER_NEAREST) > 127
    # holes of the selection are obstacles too (windows the click did not cover)
    k = max(1, int(CLEARANCE_M * res))
    obs_r = cv2.dilate((obs_r | _holes(sel_r)).astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0
    usable = sel_r & ~obs_r

    ys, xs = np.nonzero(usable)
    if len(xs) == 0:
        raise ValueError("no usable area left after removing obstacles")
    x0, y0 = xs.min() / res, ys.min() / res
    polys_m = []
    for p in polygons(usable.astype(np.uint8), min_frac=0.002, eps_frac=0.002):
        polys_m.append({"outer": [[x / res - x0, y / res - y0] for x, y in p["outer"]],
                        "holes": [[[x / res - x0, y / res - y0] for x, y in h] for h in p["holes"]]})
    obs_m = []
    for o in obstacle_polys:
        pts = cv2.perspectiveTransform(np.array(o, np.float32).reshape(-1, 1, 2), M).reshape(-1, 2) / res
        obs_m.append({"x": float(pts[:, 0].min() - x0), "y": float(pts[:, 1].min() - y0),
                      "w": float(np.ptp(pts[:, 0])), "h": float(np.ptp(pts[:, 1]))})

    # plane (metres, origin = usable bbox top-left) -> photo pixels, for the preview
    T = np.array([[1, 0, x0], [0, 1, y0], [0, 0, 1.0]])
    plane_to_photo = np.linalg.inv(M) @ np.diag([res, res, 1.0]) @ T
    bw = (xs.max() - xs.min() + 1) / res
    bh = (ys.max() - ys.min() + 1) / res
    warnings = ["Structural suitability is not assessed from a photo: check the wall can carry the load "
                "(about 25-40 kg/m² with wet substrate) before installing."]
    tl, tr, br, bl = q
    if abs(np.linalg.norm(bl - tl) - np.linalg.norm(br - tr)) / max(np.linalg.norm(bl - tl), 1) > 0.15 and not height_m:
        warnings.append("Strong perspective: add the real height for a more precise result.")
    if bw < 0.3 or bh < 0.3:
        warnings.append("The usable area is smaller than one 30 cm module.")
    return {
        "width_m": round(float(bw), 3), "height_m": round(float(bh), 3),
        "usable_area_m2": round(float(usable.sum()) / res ** 2, 3),
        "selected_area_m2": round(float(sel_r.sum()) / res ** 2, 3),
        "region_polygons_m": polys_m, "obstacles_m": obs_m,
        "quad_px": q.round(1).tolist(), "plane_to_photo": plane_to_photo.tolist(),
        "scale": {"m_per_px": m_per_px, "height_source": "measured by user" if height_m else f"perspective estimate ({f_source})"},
        "warnings": warnings,
    }


def _holes(mask_bool):
    m = mask_bool.astype(np.uint8)
    filled = m.copy()
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(filled, cnts, -1, 1, -1)
    return (filled > 0) & ~mask_bool


def exif_hints(data):
    """GPS position and compass direction from the photo metadata, when the phone stored them."""
    out = {"lat": None, "lon": None, "camera_heading_deg": None, "facade_azimuth_deg": None, "date": None}
    try:
        import io
        from PIL import Image, ExifTags
        ex = Image.open(io.BytesIO(data)).getexif()
        gps = ex.get_ifd(0x8825) or {}
        def deg(v):
            d, m, s = [float(x) for x in v]
            return d + m / 60 + s / 3600
        if 2 in gps and 4 in gps:
            out["lat"] = round(deg(gps[2]) * (-1 if gps.get(1) == "S" else 1), 5)
            out["lon"] = round(deg(gps[4]) * (-1 if gps.get(3) == "W" else 1), 5)
        if 17 in gps:                                   # GPSImgDirection: where the camera pointed
            hd = float(gps[17]) % 360
            out["camera_heading_deg"] = round(hd, 1)
            out["facade_azimuth_deg"] = round((hd + 180) % 360, 1)   # the wall faces the photographer
        dt = ex.get(306) or ex.get_ifd(0x8769).get(36867)
        if dt:
            out["date"] = str(dt)[:10].replace(":", "-")
        _ = ExifTags
    except Exception:
        pass
    return out
