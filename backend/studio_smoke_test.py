"""
HTTP smoke test for the connected studio + digital twin endpoints (real requests, running API needed).

    uvicorn api:app --port 8000
    python studio_smoke_test.py --url http://127.0.0.1:8000 [--realistic]
"""
import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

ROWS = []


def call(base, method, path, body=None, files=None, timeout=300):
    url = base + path
    headers = {}
    data = None
    if files:
        b = uuid.uuid4().hex
        parts = []
        for k, (name, content, ctype) in files.items():
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                         f'Content-Type: {ctype}\r\n\r\n'.encode() + content + b"\r\n")
        for k, v in (body or {}).items():
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        data = b"".join(parts) + f"--{b}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    t = time.perf_counter()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r), time.perf_counter() - t
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), time.perf_counter() - t


def check(name, ok, secs, detail=""):
    ROWS.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name:42s} {secs:6.1f}s  {detail}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--image", default="samples/test.jpg")
    ap.add_argument("--realistic", action="store_true")
    a = ap.parse_args()
    B = a.url.rstrip("/")
    try:
        urllib.request.urlopen(B + "/plants", timeout=5)
    except Exception as e:
        sys.exit(f"API not reachable at {B} ({e}). Start it: uvicorn api:app --port 8000")

    img = open(a.image, "rb").read()
    s, up, t = call(B, "POST", "/space/upload", {"suggest": "true"}, {"image": ("wall.jpg", img, "image/jpeg")})
    regs = (up.get("suggestions") or {}).get("regions", [])
    check("POST /space/upload + suggestions", s == 200 and up.get("image_id") and len(regs) > 0, t,
          f"{len(regs)} regions: {[r['kind'] for r in regs]}")
    iid, W, H = up["image_id"], up["width"], up["height"]
    surf = next((r for r in regs if r["kind"] == "surface"), regs[0] if regs else {"seed": [W * 0.5, H * 0.1]})

    s, seg, t = call(B, "POST", "/space/segment", {"image_id": iid, "points": [surf["seed"]], "labels": [1]})
    check("POST /space/segment include click", s == 200 and seg["area_frac"] > 0.2, t,
          f"backend={seg.get('backend')} area={seg.get('area_frac', 0):.2f} obstacles={len(seg.get('obstacles', []))}")
    s, seg2, t = call(B, "POST", "/space/segment", {"image_id": iid, "points": [surf["seed"], [W * 0.95, H * 0.5]], "labels": [1, 0]})
    check("POST /space/segment + exclude click", s == 200 and seg2["area_frac"] <= seg["area_frac"] + 1e-6, t,
          f"area {seg['area_frac']:.3f} -> {seg2['area_frac']:.3f}")
    s, rect, t = call(B, "POST", "/space/segment", {"image_id": iid, "mode": "rect", "rect": [20, 20, W * 0.45, H * 0.9]})
    check("POST /space/segment rectangle fallback", s == 200 and rect["backend"] == "manual", t, f"area={rect.get('area_frac', 0):.2f}")
    s, bad, t = call(B, "POST", "/space/segment", {"image_id": iid, "points": [[10, 10]], "labels": [0]})
    check("POST /space/segment only exclude -> 422", s == 422, t)

    obstacles = [o["polygon"] for o in seg["obstacles"]]
    ref = {"p1": [153, 640], "p2": [492, 640], "length_m": 1.3}            # left window surround, ~1.3 m
    s, area, t = call(B, "POST", "/space/area", {"image_id": iid, "selection": seg["polygons"], "obstacles": obstacles,
                                                 "reference": ref})
    check("POST /space/area (reference measurement)", s == 200 and area["usable_area_m2"] > 0, t,
          f"{area.get('width_m')} x {area.get('height_m')} m, usable {area.get('usable_area_m2')} m², obstacles {len(area.get('obstacles_m', []))}")

    s, sun, t = call(B, "GET", "/solar/day?azimuth=270&date=2026-06-21")
    check("GET /solar/day summer", s == 200 and sun["sunrise"] < sun["sunset"], t,
          f"{sun.get('sunrise')}-{sun.get('sunset')} {sun.get('daily_kwh_m2')} kWh/m²")

    # a 1.8 x 1.5 m part of the wall keeps the test fast
    small = {"width_m": 1.8, "height_m": 1.5}
    s, st, t = call(B, "POST", "/studio/styles", {"area": small, "plants": ["mint", "basil", "cherry_tomato"], "facade_azimuth": 270})
    ok = s == 200 and all("error" not in d for d in st["designs"]) and len(st["designs"]) == 8
    check("POST /studio/styles (8 styles, NSGA-II each)", ok, t,
          ", ".join(f"{d['style']}:{d['metrics']['planting_cells']}p/{d['metrics']['open_fraction']:.2f}" for d in st.get("designs", [])))
    feas = [d for d in st["designs"] if d.get("optimisation", {}).get("feasible")]
    check("  every style optimised + SVG preview", len(feas) == 8 and all(d["svg"].startswith("<svg") for d in st["designs"]), 0,
          f"exposure={st.get('exposure_class')} recs={len(st.get('recommendations', []))}")

    s, st_area, t = call(B, "POST", "/studio/styles", {"area": area, "plants": ["mint", "strawberry"], "styles": ["mashrabiya", "honeycomb"]})
    check("POST /studio/styles on the selected wall", s == 200 and all("cells" in d for d in st_area["designs"]), t,
          ", ".join(f"{d['style']}:{d['metrics']['cells']} cells" for d in st_area.get("designs", []) if "metrics" in d))

    design = st_area["designs"][0]
    s, pv, t = call(B, "POST", "/studio/preview", {"image_id": iid, "area": area, "design": design, "realistic": a.realistic})
    check("POST /studio/preview (layers)", s == 200 and pv.get("geometry_png_base64"), t,
          f"realistic={pv.get('realistic')} {pv.get('message') or ''}"[:90])
    if s == 200:
        open("studio_preview_geometry.png", "wb").write(base64.b64decode(pv["geometry_png_base64"]))
        if pv.get("realistic_png_base64"):
            open("studio_preview_realistic.png", "wb").write(base64.b64decode(pv["realistic_png_base64"]))

    s, demo, t = call(B, "GET", "/installation/demo")
    check("GET /installation/demo", s == 200 and demo.get("demo") and demo["branches"], t, f"{len(demo.get('branches', []))} branches")

    s, _, t = call(B, "POST", "/sensors", {"source": "simulated", "branch": demo["branches"][0]["id"], "level_raw": 120, "temp_c": 34})
    check("POST /sensors (simulated potentiometer)", s == 200, t)
    wx = [{"date": "d0", "tmax_c": 35, "rh": 0.4, "rain_mm": 0}, {"date": "d1", "tmax_c": 36, "rh": 0.4, "rain_mm": 0},
          {"date": "d2", "tmax_c": 30, "rh": 0.5, "rain_mm": 0}]
    s, w, t = call(B, "POST", "/water/status", {"branches": demo["branches"], "levels": {}, "weather": wx, "hours_to_refill": 48})
    b0 = w["branches"][0] if s == 200 else {}
    check("POST /water/status (dynamic threshold)", s == 200 and b0.get("level_source", "").startswith("sensor"), t,
          f"B0 {b0.get('remaining_l')} L, threshold {b0.get('dynamic_threshold_frac')}, alerts {[x['code'] for x in b0.get('alerts', [])]}")
    s, w2, t = call(B, "POST", "/water/status", {"branches": demo["branches"], "weather": [dict(d, tmax_c=22) for d in wx], "hours_to_refill": 48})
    b0c = w2["branches"][0] if s == 200 else {}
    check("  cooler forecast lowers the threshold", s == 200 and b0c["dynamic_threshold_frac"] < b0["dynamic_threshold_frac"], t,
          f"{b0['dynamic_threshold_frac']} -> {b0c.get('dynamic_threshold_frac')}")
    s, dev, t = call(B, "GET", "/sensors/device")
    check("GET /sensors/device (LCD + buzzer)", s == 200 and dev.get("line1"), t, f"{dev.get('line1')} | {dev.get('line2')} buzz={dev.get('buzz')}")
    s, w3, t = call(B, "POST", "/water/status", {"branches": demo["branches"]}, timeout=30)
    check("POST /water/status (live forecast or fallback)", s == 200, t, w3.get("weather_source", ""))

    print(f"\n{sum(ROWS)}/{len(ROWS)} passed")
    sys.exit(0 if all(ROWS) else 1)


if __name__ == "__main__":
    main()
