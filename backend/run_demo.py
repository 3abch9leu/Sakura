"""
ROOTCODE demo: optimise a tile for one apartment window and export everything.

    python run_demo.py                       # west window in Tunis, 4 plants
    python run_demo.py --facade S --rh 0.3 --plants mint basil chili strawberry
"""
import argparse
import json
import os
import time

from rootcode.evaluate import Context
from rootcode.optimizer import run, pick_three
from rootcode.export import laser_layers, preview_svg, plot_pareto, plot_comparison


def summary(name, d, r):
    o, p, h = r["objectives"], r["panel"], r["hydraulics"]
    return (f"{name:16s} water {o['water_l_day']:5.2f} L/day | heat {o['heat_kwh_day']:4.2f} kWh/day "
            f"(-{p['heat_reduction_pct']:.0f}% vs no screen) | plant deficit {100 * o['plant_deficit']:4.1f}% | "
            f"evenness CV {r['distribution_cv']:.2f} | cooling {'ON ' if d.cooling_open else 'OFF'} | "
            f"drip {h['drain_time_min']:.0f} min")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plants", nargs="+", default=["mint", "basil", "strawberry", "lettuce"])
    ap.add_argument("--facade", default="W")
    ap.add_argument("--rh", type=float, default=0.55, help="daytime relative humidity 0-1")
    ap.add_argument("--window", nargs=2, type=float, default=[1.2, 1.4], metavar=("W", "H"))
    ap.add_argument("--root-tiles", type=int, default=4)
    ap.add_argument("--water", type=float, default=6.0, help="litres/day available for this window")
    ap.add_argument("--lat", type=float, default=36.81)
    ap.add_argument("--lon", type=float, default=10.18)
    ap.add_argument("--out", default="output")
    ap.add_argument("--gens", type=int, default=150)
    ap.add_argument("--photo", help="photo of the window: FacadeVision measures it")
    ap.add_argument("--click", nargs="+", type=float, help="tap(s) on the glass: x y [x2 y2]")
    ap.add_argument("--real-width", type=float, help="real window width in metres (for scale)")
    ap.add_argument("--real-height", type=float, default=None)
    a = ap.parse_args()

    if a.photo:
        import cv2
        from rootcode.facade import analyze, overlay, load_rgb, public
        img, sc = load_rgb(a.photo)
        pts = [(a.click[i] * sc, a.click[i + 1] * sc) for i in range(0, len(a.click), 2)]
        fv = analyze(img, pts, a.real_width, a.root_tiles, real_height_m=a.real_height)
        os.makedirs(a.out, exist_ok=True)
        cv2.imwrite(os.path.join(a.out, "facade_overlay.png"), cv2.cvtColor(overlay(img, fv), cv2.COLOR_RGB2BGR))
        a.window = [fv["window_w_m"], fv["window_h_m"]]
        print(f"FacadeVision [{fv['backend']}]: window {a.window[0]} x {a.window[1]} m, "
              f"{fv['tiles']['total']} tiles. {' '.join(fv['warnings'])}")

    ctx = Context(plants=a.plants, facade=a.facade, rh=a.rh, window_w=a.window[0],
                  window_h=a.window[1], root_tiles=a.root_tiles, water_available_l_day=a.water,
                  lat=a.lat, lon=a.lon)
    os.makedirs(a.out, exist_ok=True)

    t = time.time()
    out = run(ctx, n_gen=a.gens)
    print(f"NSGA-II finished in {time.time() - t:.1f}s, {len(out['F'])} Pareto designs, "
          f"plant-safe found: {out['plant_safe_found']}\n")

    report = {"context": {k: v for k, v in ctx.__dict__.items() if k != "calibration"}, "designs": {}}
    for name, v in out["designs"].items():
        d, r = v["design"], v["result"]
        print(summary(name, d, r))
        report["designs"][name] = {"design": d.to_dict(), "result": r}
        with open(os.path.join(a.out, f"preview_{name}.svg"), "w") as f:
            f.write(preview_svg(d, name.replace("_", " ").title()))
        if name != "baseline":
            laser_layers(d, os.path.join(a.out, "laser", name), prefix=f"rootcode_{name}")
    laser_layers(out["designs"]["baseline"]["design"], os.path.join(a.out, "laser", "baseline"),
                 prefix="rootcode_baseline")

    picks, _ = pick_three(out["X"], out["F"])
    bF = out["designs"]["baseline"]["result"]["objectives"]
    plot_pareto(out["F"], picks, [bF["water_l_day"], bF["heat_kwh_day"]], os.path.join(a.out, "pareto.png"))
    plot_comparison(out["designs"]["baseline"]["result"], out["designs"]["balanced"]["result"],
                    os.path.join(a.out, "comparison.png"))
    with open(os.path.join(a.out, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=float)
    print(f"\nSaved previews, laser files, plots and report.json to ./{a.out}/")


if __name__ == "__main__":
    main()
