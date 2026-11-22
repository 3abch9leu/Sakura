"""
FacadeVision - from one phone photo to the window dimensions the optimizer needs.

Pipeline
  1. Segmentation: the user taps the window (1+ points). Backends, tried in order:
       sam2    SAM 2.1 via Hugging Face transformers (best)
       sam     SAM ViT-B via transformers (very stable API)
       classic OpenCV flood fill from the tap (no deep learning, last-resort fallback)
  2. Geometry: largest contour -> 4 corners -> homography -> perspective-corrected aspect ratio.
  3. Scale: the user gives ONE real measurement (window width in metres). A single photo cannot
     know absolute size; asking for it is honest and takes 5 seconds with a tape measure.
  4. Placement: 30 x 30 cm tile grid projected back onto the photo; bottom row = root tiles.

    python -m rootcode.facade photo.jpg --click 640 410 --width 1.2 --out facade_out.png
"""

import argparse
import base64
import math
import cv2
import numpy as np
from . import config as C

_MODELS = {}


# ---------------------------------------------------------------- segmentation backends
def _device():
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _seg_sam2(img_rgb, points, labels=None):
    import torch
    from PIL import Image
    from transformers import Sam2Model, Sam2Processor

    name = "facebook/sam2.1-hiera-small"
    if name not in _MODELS:
        _MODELS[name] = (
            Sam2Processor.from_pretrained(name),
            Sam2Model.from_pretrained(name).to(_device()).eval(),
        )
    proc, model = _MODELS[name]
    inputs = proc(
        images=Image.fromarray(img_rgb),
        input_points=[[[list(p) for p in points]]],
        input_labels=[[list(labels or [1] * len(points))]],
        return_tensors="pt",
    ).to(_device())
    with torch.no_grad():
        out = model(**inputs, multimask_output=True)
    masks = proc.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"])[
        0
    ]  # (1, 3, H, W)
    best = int(out.iou_scores[0, 0].argmax())
    return masks[0, best].numpy().astype(np.uint8), float(out.iou_scores[0, 0, best])


def _seg_sam(img_rgb, points, labels=None):
    import torch
    from PIL import Image
    from transformers import SamModel, SamProcessor

    name = "facebook/sam-vit-base"
    if name not in _MODELS:
        _MODELS[name] = (
            SamProcessor.from_pretrained(name),
            SamModel.from_pretrained(name).to(_device()).eval(),
        )
    proc, model = _MODELS[name]
    inputs = proc(
        Image.fromarray(img_rgb),
        input_points=[[list(p) for p in points]],
        input_labels=[list(labels or [1] * len(points))],
        return_tensors="pt",
    ).to(_device())
    with torch.no_grad():
        out = model(**inputs)
    masks = proc.image_processor.post_process_masks(
        out.pred_masks.cpu(),
        inputs["original_sizes"].cpu(),
        inputs["reshaped_input_sizes"].cpu(),
    )[0]
    best = int(out.iou_scores[0, 0].argmax())
    return masks[0, best].numpy().astype(np.uint8), float(out.iou_scores[0, 0, best])


def _seg_classic(img_rgb, points, labels=None, tol=30):
    """Flood fill from each tap in a smoothed image. No deep learning: emergency fallback only."""
    smooth = cv2.bilateralFilter(img_rgb, 9, 50, 50)
    h, w = smooth.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    labels = list(labels or [1] * len(points))
    neg = np.zeros((h, w), np.uint8)
    for (x, y), lab in zip(points, labels):
        ff = np.zeros((h + 2, w + 2), np.uint8)
        cv2.floodFill(
            smooth.copy(),
            ff,
            (int(x), int(y)),
            0,
            (tol,) * 3,
            (tol,) * 3,
            4 | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8),
        )
        region = (ff[1:-1, 1:-1] > 0).astype(np.uint8)
        if lab:
            mask |= region
        else:
            neg |= region
    mask &= 1 - neg
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    return mask, None


BACKENDS = {"sam2": _seg_sam2, "sam": _seg_sam, "classic": _seg_classic}


def segment(img_rgb, points, backend="auto", labels=None):
    """points: taps in image pixels. labels: 1 = include (default), 0 = exclude (refinement clicks)."""
    order = ["sam2", "sam", "classic"] if backend == "auto" else [backend]
    errors = {}
    for b in order:
        try:
            mask, score = BACKENDS[b](img_rgb, points, labels)
            if mask.sum() > 0.002 * mask.size:
                return mask, b, score, errors
            errors[b] = "empty mask"
        except (
            Exception
        ) as e:  # missing package, no internet for weights, API change...
            errors[b] = f"{type(e).__name__}: {e}"[:200]
    raise RuntimeError(f"All segmentation backends failed: {errors}")


# ---------------------------------------------------------------- geometry
def _order_corners(pts):
    pts = np.array(pts, np.float32).reshape(-1, 2)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        np.float32,
    )


def window_quad(mask):
    """4 corners (tl, tr, br, bl) of the window region, robust to ragged masks."""
    cnts, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cnt = max(cnts, key=cv2.contourArea)
    hull = cv2.convexHull(cnt)
    peri = cv2.arcLength(hull, True)
    for eps in (0.01, 0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            return _order_corners(approx), cv2.contourArea(cnt)
    return _order_corners(cv2.boxPoints(cv2.minAreaRect(cnt))), cv2.contourArea(cnt)


def true_aspect(quad, img_shape):
    """
    Real height/width ratio of a rectangle seen in perspective (Zhang & He, "Whiteboard scanning
    and image enhancement"). The focal length is estimated from the quad itself; if that is
    ill-conditioned (near-frontal photo) we assume a typical phone main camera (~26 mm equiv.).
    """
    h_img, w_img = img_shape[:2]
    u0, v0 = w_img / 2, h_img / 2
    tl, tr, br, bl = [np.array([p[0] - u0, p[1] - v0, 1.0]) for p in quad]
    m1, m2, m3, m4 = tl, tr, bl, br
    k2 = np.dot(np.cross(m1, m4), m3) / np.dot(np.cross(m2, m4), m3)
    k3 = np.dot(np.cross(m1, m4), m2) / np.dot(np.cross(m3, m4), m2)
    n2, n3 = k2 * m2 - m1, k3 * m3 - m1

    f_phone = 26 / 36 * max(w_img, h_img)
    f, f_source = f_phone, "assumed phone lens"
    if abs(n2[2] * n3[2]) > 1e-9:
        f2 = -(n2[0] * n3[0] + n2[1] * n3[1]) / (n2[2] * n3[2])
        if f2 > 0 and 0.4 * max(w_img, h_img) < math.sqrt(f2) < 4 * max(w_img, h_img):
            f, f_source = math.sqrt(f2), "estimated from the window"

    def norm2(n):
        return (n[0] ** 2 + n[1] ** 2) / f**2 + n[2] ** 2

    w_over_h = math.sqrt(norm2(n2) / norm2(n3))
    return 1.0 / w_over_h, f, f_source


def rectify(quad, img_shape):
    """Perspective-corrected aspect ratio (height/width) and the homography photo -> rectified."""
    tl, tr, br, bl = quad
    w = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    aspect, f, f_source = true_aspect(quad, img_shape)
    h = w * aspect
    dst = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
    H = cv2.getPerspectiveTransform(quad, dst)
    return aspect, H, (w, h), f_source


# ---------------------------------------------------------------- main entry point
def analyze(
    img_rgb, points, real_width_m, root_tiles=4, backend="auto", real_height_m=None
):
    mask, used, score, errors = segment(img_rgb, points, backend)
    quad, cnt_area = window_quad(mask)
    aspect, H, (wp, hp), f_source = rectify(quad, img_rgb.shape)
    window_w = float(real_width_m)
    window_h = float(real_height_m) if real_height_m else float(real_width_m * aspect)

    quad_area = cv2.contourArea(quad.reshape(-1, 1, 2))
    fill = float(cnt_area / quad_area) if quad_area > 0 else 0.0
    tl, tr, br, bl = quad
    skew = math.degrees(abs(math.atan2(tr[1] - tl[1], tr[0] - tl[0])))
    warnings = []
    if fill < 0.85:
        warnings.append(
            "Mask is irregular (curtains, bars or reflections?). Tap again or add a second point."
        )
    if skew > 12:
        warnings.append(
            "Photo is strongly tilted; dimensions are perspective-corrected but less precise."
        )
    left, right = np.linalg.norm(bl - tl), np.linalg.norm(br - tr)
    if (
        f_source != "estimated from the window"
        and abs(left - right) / max(left, right) > 0.1
        and not real_height_m
    ):
        warnings.append(
            "Side view with unknown lens: height may be off by ~10 cm. "
            "Retake from the front, or type the real height too."
        )
    if not 0.3 < aspect < 3.5:
        warnings.append(
            "Unusual window proportions - check the tap landed on the glass."
        )

    nx = max(1, math.ceil(window_w / C.TILE_W))
    ny = max(1, math.ceil(window_h / C.TILE_H))
    return {
        "backend": used,
        "sam_score": score,
        "backend_errors": errors,
        "window_w_m": round(window_w, 3),
        "window_h_m": round(window_h, 3),
        "height_source": (
            "measured by user" if real_height_m else "estimated from photo"
        ),
        "area_m2": round(window_w * window_h, 3),
        "tiles": {
            "columns": nx,
            "rows": ny,
            "total": nx * ny,
            "root_tiles": min(root_tiles, nx),
        },
        "focal_length": f_source,
        "quad_px": quad.round(1).tolist(),
        "mask_fill": round(fill, 3),
        "tilt_deg": round(skew, 1),
        "warnings": warnings,
        "_mask": mask,
        "_H": H,
        "_rect_px": (wp, hp),
    }


def overlay(img_rgb, res):
    """Photo + window mask + projected tile grid (root tiles green, shade tiles terracotta)."""
    out = img_rgb.copy()
    tint = out.copy()
    tint[res["_mask"] > 0] = (59, 130, 196)
    out = cv2.addWeighted(tint, 0.35, out, 0.65, 0)

    wp, hp = res["_rect_px"]
    Hinv = np.linalg.inv(res["_H"])
    nx, ny = res["tiles"]["columns"], res["tiles"]["rows"]
    tile_w_px = wp / (res["window_w_m"] / C.TILE_W)
    tile_h_px = hp / (res["window_h_m"] / C.TILE_H)
    n_root = res["tiles"]["root_tiles"]
    for j in range(ny):
        for i in range(nx):
            x0, y0 = i * tile_w_px, j * tile_h_px
            sq = np.array(
                [
                    [x0, y0],
                    [x0 + tile_w_px, y0],
                    [x0 + tile_w_px, y0 + tile_h_px],
                    [x0, y0 + tile_h_px],
                ],
                np.float32,
            ).reshape(-1, 1, 2)
            poly = cv2.perspectiveTransform(sq, Hinv).astype(np.int32)
            is_root = (j == ny - 1) and (i < n_root)
            color = (78, 125, 58) if is_root else (200, 105, 63)
            fill = out.copy()
            cv2.fillPoly(fill, [poly], color)
            out = cv2.addWeighted(fill, 0.25, out, 0.75, 0)
            cv2.polylines(out, [poly], True, color, 2, cv2.LINE_AA)
    cv2.polylines(
        out, [np.array(res["quad_px"], np.int32)], True, (255, 255, 255), 3, cv2.LINE_AA
    )
    label = f'{res["window_w_m"]:.2f} x {res["window_h_m"]:.2f} m | {res["tiles"]["total"]} tiles ({res["backend"]})'
    cv2.putText(
        out, label, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 4, cv2.LINE_AA
    )
    cv2.putText(
        out,
        label,
        (12, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return out


def public(res):
    """JSON-safe result (drops numpy internals)."""
    return {k: v for k, v in res.items() if not k.startswith("_")}


def png_b64(img_rgb):
    ok, buf = cv2.imencode(".png", cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR))
    return base64.b64encode(buf.tobytes()).decode()


def load_rgb(path_or_bytes, max_side=1600):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        img = cv2.imdecode(np.frombuffer(path_or_bytes, np.uint8), cv2.IMREAD_COLOR)
    else:
        import os

        if not os.path.isfile(path_or_bytes):
            raise FileNotFoundError(
                f"No image at '{os.path.abspath(path_or_bytes)}'. Put the photo in this folder "
                f"or give its full path. Try: samples/test_window.jpg"
            )
        # np.fromfile + imdecode also works with Windows paths containing accents or spaces
        img = cv2.imdecode(np.fromfile(path_or_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(
            "The file exists but is not a readable image (use .jpg or .png; "
            "iPhone .heic photos must be converted first)"
        )
    s = max_side / max(img.shape[:2])
    if s < 1:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (s if s < 1 else 1.0)


if __name__ == "__main__":
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument(
        "--click",
        nargs="+",
        type=float,
        required=True,
        help="x y [x2 y2 ...] in ORIGINAL image pixels",
    )
    ap.add_argument(
        "--width", type=float, required=True, help="real window width in metres"
    )
    ap.add_argument(
        "--height",
        type=float,
        default=None,
        help="optional real window height in metres",
    )
    ap.add_argument(
        "--backend", default="auto", choices=["auto", "sam2", "sam", "classic"]
    )
    ap.add_argument("--root-tiles", type=int, default=4)
    ap.add_argument("--out", default="facade_out.png")
    a = ap.parse_args()
    img, s = load_rgb(a.image)
    pts = [(a.click[i] * s, a.click[i + 1] * s) for i in range(0, len(a.click), 2)]
    res = analyze(img, pts, a.width, a.root_tiles, a.backend, a.height)
    cv2.imwrite(a.out, cv2.cvtColor(overlay(img, res), cv2.COLOR_RGB2BGR))
    print(json.dumps(public(res), indent=2))
    print(f"Overlay saved to {a.out}")
