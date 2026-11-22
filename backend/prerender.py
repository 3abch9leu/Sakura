"""
Pre-render the pitch images: wall photo -> optimizer -> Stage 1 try-on + Stage 2 AI render
for the three Pareto designs, plus a before/after image.

    python prerender.py samples/test.jpg --corners 208 248 430 248 435 596 205 596 --width 1.0
    python prerender.py photo.jpg --click 640 410 --width 1.2 --facade W --plants mint basil chili strawberry

Corners = the 4 corners (any order) of the area to cover, in ORIGINAL photo pixels.
Instead of corners you can tap the window (--click) and FacadeVision (SAM 2) finds them.
Writes output/renders/tryon_<design>.png, render_<design>.png, before_after.png, renders.json
"""
import argparse
import json
import os
import time

import cv2
import numpy as np

from rootcode.evaluate import Context
from rootcode.facade import load_rgb
from rootcode.optimizer import run
from rootcode.tryon import tryon
from rootcode import enhance as E

DESIGNS = ["water_saver", "shade_maximizer", "balanced"]


def save(path, rgb):
    cv2.imwrite(path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def label(img, text, scale=None):
    out = img.copy()
    scale = scale or max(0.45, img.shape[1] / 1100)
    (tw, th), b = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    cv2.rectangle(out, (0, 0), (tw + 24, th + b + 20), (0, 0, 0), -1)
    cv2.putText(out, text, (12, th + 10), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--corners", nargs=8, type=float, help="x1 y1 x2 y2 x3 y3 x4 y4 (original pixels)")
    ap.add_argument("--click", nargs="+", type=float, help="tap(s) on the glass instead of corners")
    ap.add_argument("--width", type=float, required=True, help="real width of the covered area (m)")
    ap.add_argument("--height", type=float, default=None, help="optional real height (m)")
    ap.add_argument("--plants", nargs="+", default=["mint", "basil", "strawberry", "lettuce"])
    ap.add_argument("--facade", default="W")
    ap.add_argument("--rh", type=float, default=0.55)
    ap.add_argument("--water", type=float, default=6.0)
    ap.add_argument("--root-tiles", type=int, default=4)
    ap.add_argument("--gens", type=int, default=120)
    ap.add_argument("--strength", type=float, default=E.DEFAULT_STRENGTH)
    ap.add_argument("--seed", type=int, default=E.DEFAULT_SEED)
    ap.add_argument("--no-ai", action="store_true", help="Stage 1 only (no diffusion)")
    ap.add_argument("--out", default=os.path.join("output", "renders"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    img, s = load_rgb(a.photo)
    if a.corners:
        corners = [(a.corners[i] * s, a.corners[i + 1] * s) for i in range(0, 8, 2)]
    elif a.click:
        from rootcode.facade import analyze
        fv = analyze(img, [(a.click[i] * s, a.click[i + 1] * s) for i in range(0, len(a.click), 2)],
                     a.width, a.root_tiles, real_height_m=a.height)
        corners = fv["quad_px"]
        print(f"FacadeVision [{fv['backend']}] corners {corners}")
    else:
        ap.error("give --corners or --click")

    # window size for the optimizer = the covered area
    from rootcode.facade import rectify, _order_corners
    aspect = rectify(_order_corners(corners), img.shape)[0]
    w_m, h_m = a.width, a.height or a.width * aspect
    ctx = Context(plants=a.plants, facade=a.facade, rh=a.rh, window_w=w_m, window_h=h_m,
                  root_tiles=a.root_tiles, water_available_l_day=a.water)
    t = time.time()
    out = run(ctx, n_gen=a.gens)
    print(f"Optimizer: {time.time() - t:.1f} s, window {w_m:.2f} x {h_m:.2f} m")

    report = {"photo": a.photo, "corners_px": [list(map(float, c)) for c in corners],
              "strength": a.strength, "seed": a.seed, "designs": {}}
    renders = {}
    mask = None
    for name in DESIGNS:
        d, r = out["designs"][name]["design"], out["designs"][name]["result"]
        st1 = tryon(img, corners, w_m, d, a.root_tiles, h_m)
        save(os.path.join(a.out, f"tryon_{name}.png"), st1["image"])
        mask = st1["mask"]
        entry = {"design": d.to_dict(), "heat_reduction_pct": round(r["panel"]["heat_reduction_pct"], 1),
                 "water_l_day": round(r["objectives"]["water_l_day"], 2),
                 "plant_deficit_pct": round(100 * r["objectives"]["plant_deficit"], 1)}
        if not a.no_ai:
            st2 = E.enhance(st1["image"], st1["mask"], strength=a.strength, seed=a.seed)
            save(os.path.join(a.out, f"render_{name}.png"), st2["image"])
            entry.update(enhanced=st2["enhanced"], message=st2["message"], render_seconds=st2["seconds"],
                         peak_vram_mb=st2["peak_vram_mb"])
            renders[name] = st2["image"]
            print(f"{name:16s} render {st2['seconds']:5.1f} s  {st2['message']}")
        else:
            renders[name] = st1["image"]
        report["designs"][name] = entry

    # before / after (balanced) for the pitch, cropped around the tiles (+60 % context)
    ys, xs = np.nonzero(mask)
    mx, my = int(0.6 * (xs.max() - xs.min())), int(0.25 * (ys.max() - ys.min()))
    x0, x1 = max(0, xs.min() - mx), min(img.shape[1], xs.max() + mx)
    y0, y1 = max(0, ys.min() - my), min(img.shape[0], ys.max() + my)
    img, renders["balanced"] = img[y0:y1, x0:x1], renders["balanced"][y0:y1, x0:x1]
    if not a.no_ai:      # the crop cut the caption off: put it back on the cropped render
        renders["balanced"] = E.caption(renders["balanced"])
    b = report["designs"]["balanced"]
    after = label(renders["balanced"], f"After: balanced design  -{b['heat_reduction_pct']:.0f}% heat, "
                                       f"{b['water_l_day']:.1f} L/day, plants {100 - b['plant_deficit_pct']:.0f}% fed")
    before = label(img, "Before")
    save(os.path.join(a.out, "before_after.png"), np.hstack([before, after]))
    json.dump(report, open(os.path.join(a.out, "renders.json"), "w"), indent=2)
    print(f"Saved to {a.out}")


if __name__ == "__main__":
    main()
