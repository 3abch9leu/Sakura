"""
INBETWEEN / ROOTCODE smoke test: every engine and every endpoint, PASS/FAIL + timing.

    python smoke_test.py                      # uses http://localhost:8000 if up, else runs the API in-process
    python smoke_test.py --url http://192.168.1.20:8000
    python smoke_test.py --no-llm             # skip /chat (no Groq / Ollama available)
    python smoke_test.py --no-render          # skip the Stage 2 AI render (slowest check)
"""
import argparse
import json
import sys
import time
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS = []


def check(name, fn):
    t = time.perf_counter()
    try:
        info = fn()
        ok = True
    except Exception as e:
        info, ok = f"{type(e).__name__}: {e}"[:300], False
        if "--verbose" in sys.argv:
            traceback.print_exc()
    ms = (time.perf_counter() - t) * 1000
    RESULTS.append((name, ok, ms))
    print(f"[{'PASS' if ok else 'FAIL'}] {name:<28} {ms:8.0f} ms  {info or ''}")


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------- engines (direct calls)
def engines(include_vision=True):
    from rootcode.evaluate import Context, evaluate
    from rootcode.hydro import distribute
    from rootcode.optimizer import run
    from rootcode.solar import facade_sun, peak_hour
    from rootcode.tile import baseline

    ctx = Context(plants=["mint", "basil", "strawberry", "lettuce"])

    def solar():
        s = facade_sun(36.81, 10.18, 270.0)
        need(2 < s["daily_kwh_m2"] < 8, "implausible W facade irradiation")
        return f"W facade {s['daily_kwh_m2']:.2f} kWh/m2/day, peak {peak_hour(s)}"

    def hydro():
        h = distribute(baseline(ctx.plants, 1.0))
        need(abs(sum(h["litres"].values()) - 1.0) < 1e-6, "mass not conserved")
        return f"drain {h['drain_time_min']:.1f} min, Re {h['reynolds_max']:.0f}, laminar={h['laminar']}"

    def optimizer():
        out = run(ctx, n_gen=40)
        b = out["designs"]["balanced"]["result"]
        need(all(b["constraints"].values()), f"balanced infeasible: {b['constraints']}")
        o = b["objectives"]
        return (f"balanced: {o['water_l_day']:.2f} L/d, {float(o['heat_kwh_day']):.2f} kWh/d, "
                f"deficit {o['plant_deficit']:.1%}, Pareto size {len(out['F'])}")

    def vision():
        import numpy as np
        from rootcode.facade import analyze, load_rgb
        img, s = load_rgb("samples/test.jpg")
        r = analyze(img, [(265 * s, 300 * s), (375 * s, 300 * s), (265 * s, 530 * s), (375 * s, 530 * s)], 1.0)
        need(r["backend"] == "sam2", f"fell back to {r['backend']}: {r['backend_errors']}")
        import torch
        dev = "GPU" if torch.cuda.is_available() else "CPU"
        return f"sam2 on {dev}, score {r['sam_score']:.2f}, window {r['window_w_m']}x{r['window_h_m']} m"

    check("engine: SolarEngine", solar)
    check("engine: HydroEngine", hydro)
    check("engine: ROOTOptimizer", optimizer)
    if include_vision:
        check("engine: FacadeVision SAM2", vision)
    else:   # a live server already holds SAM 2 on the GPU; /facade below tests it without a 2nd copy
        print("[SKIP] engine: FacadeVision SAM2      (covered by POST /facade on the live server)")


# ---------------------------------------------------------------- API
def make_client(url):
    """Returns (client, live). Live server if it answers /health, else the API in-process."""
    import httpx
    try:
        httpx.get(url + "/health", timeout=3).raise_for_status()
        return httpx.Client(base_url=url, timeout=600), True
    except Exception:
        import os
        os.environ["ROOTCODE_WARMUP"] = "0"
        from fastapi.testclient import TestClient
        import api
        return TestClient(api.app), False


def endpoints(c, llm, render=True):
    def health():
        r = c.get("/health"); r.raise_for_status(); j = r.json()
        return f"cuda={j['gpu'].get('cuda_available')}, llm={[b['name'] for b in j['llm_backends']]}"

    def plants():
        r = c.get("/plants"); r.raise_for_status()
        return f"{len(r.json())} plants"

    def sun():
        r = c.get("/sun", params={"facade": "S"}); r.raise_for_status(); j = r.json()
        need(len(j["hourly"]) == 24, "hourly profile missing")
        return f"S facade {j['kwh_per_m2_day']:.2f} kWh/m2/day, peak {j['peak_hour']}"

    def evaluate():
        # balanced design found by the optimizer for the default context (feasible)
        body = {"design": {"widths_mm": [0.68, 0.62, 1.47, 1.08], "cool_width_mm": 0, "water_l_day": 0.95,
                           "porosity": 0.27, "aperture_mm": 8.1, "layers": 3}}
        r = c.post("/evaluate", json=body); r.raise_for_status(); j = r.json()
        return f"feasible={j['feasible']}, heat {j['result']['objectives']['heat_kwh_day']:.2f} kWh/d"

    def design_fast():
        r = c.post("/design", json={"fast": True}); r.raise_for_status(); j = r.json()
        need(set(j["designs"]) >= {"water_saver", "shade_maximizer", "balanced", "baseline"}, "designs missing")
        need(j["n_gen"] == 40, "fast mode not applied")
        b = j["designs"]["balanced"]["result"]
        need(all(b["constraints"].values()), "balanced infeasible")
        return f"n_gen 40, heat cut {b['panel']['heat_reduction_pct']:.0f} %, deficit {b['objectives']['plant_deficit']:.1%}"

    def design_full():
        r = c.post("/design", json={"facade": "S", "plants": ["mint", "chili", "basil"]}); r.raise_for_status()
        j = r.json(); need(j["n_gen"] == 120, "default n_gen changed")
        return f"n_gen 120, Pareto {len(j['pareto'])} points, plant_safe={j['plant_safe_found']}"

    def facade():
        with open("samples/test.jpg", "rb") as f:
            r = c.post("/facade", files={"image": ("test.jpg", f, "image/jpeg")},
                       data={"points": "[[265,300],[375,300],[265,530],[375,530]]", "real_width_m": "1.0"})
        r.raise_for_status(); j = r.json()
        need(j["backend"] == "sam2", f"backend {j['backend']}: {j['backend_errors']}")
        need(len(j["mask_png_base64"]) > 100, "no mask")
        return f"sam2 score {j['sam_score']:.2f}, {j['window_w_m']}x{j['window_h_m']} m, {j['tiles']['total']} tiles"

    corners = "[[208,248],[430,248],[435,596],[205,596]]"     # window of samples/test.jpg

    def tryon():
        with open("samples/test.jpg", "rb") as f:
            r = c.post("/tryon", files={"image": ("test.jpg", f, "image/jpeg")},
                       data={"corners": corners, "real_width_m": "1.0", "plants": "mint,basil,strawberry,chili"})
        r.raise_for_status(); j = r.json()
        need(len(j["tryon_png_base64"]) > 1000, "no try-on image")
        return f"{j['tiles']['total']} tiles, heat cut {j['metrics']['heat_reduction_pct']:.0f} %"

    def render():
        with open("samples/test.jpg", "rb") as f:
            r = c.post("/render", files={"image": ("test.jpg", f, "image/jpeg")},
                       data={"corners": corners, "real_width_m": "1.0", "plants": "mint,basil,strawberry,chili"})
        r.raise_for_status(); j = r.json()
        need(j["enhanced"], j["message"])
        return f"AI render {j['render_seconds']:.1f} s, peak VRAM {j['peak_vram_mb']} MB, strength {j['strength']}"

    def chat():
        msg = ("Design tiles for my west-facing window in Tunis, 1.2 x 1.4 m, plants mint and basil, "
               "RH 0.55, 4 root tiles, 6 litres a day available.")
        r = c.post("/chat", json={"messages": [{"role": "user", "content": msg}]}); r.raise_for_status()
        j = r.json()
        need(j["design"] is not None, "agent did not call the optimizer")
        return f"via {j['llm']}, reply {len(j['reply'])} chars"

    check("GET  /health", health)
    check("GET  /plants", plants)
    check("GET  /sun", sun)
    check("POST /evaluate", evaluate)
    check("POST /design (fast)", design_fast)
    print("       ... default design runs 120 generations, ~5 s, please wait")
    check("POST /design (default)", design_full)
    check("POST /facade", facade)
    check("POST /tryon", tryon)
    if render:
        print("       ... AI render: ~30-60 s the first time (model load), then ~10-20 s, please wait")
        check("POST /render (SD+ControlNet)", render)
    else:
        print("[SKIP] POST /render")
    if llm:
        print("       ... agent test: ~10 s on Groq, ~60 s on local Ollama, please wait")
        check("POST /chat (agent)", chat)
    else:
        print("[SKIP] POST /chat (agent)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-render", action="store_true", help="skip the Stage 2 diffusion render")
    ap.add_argument("--no-engines", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    client, live = make_client(a.url)
    where = f"live server at {a.url}" if live else f"in-process (no server at {a.url})"
    print(f"API under test: {where}\n")
    if not a.no_engines:
        engines(include_vision=not live)
        print()
    endpoints(client, not a.no_llm, not a.no_render)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed" + (f"  FAILED: {failed}" if failed else ""))
    sys.exit(1 if failed else 0)
