"""
HTTP test of the leaf-health model (team DeepLabV3) and the phone-camera relay, including interference with
the other AI services. Needs a running API:

    uvicorn api:app --port 8000
    python leaf_smoke_test.py --url http://127.0.0.1:8000 leaf1.jpg leaf2.jpg ...
"""
import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

ROWS = []


def multipart(fields, files):
    b = uuid.uuid4().hex
    parts = []
    for k, (name, content, ctype) in files.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
                     + content + b"\r\n")
    for k, v in fields.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    return b"".join(parts) + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def call(base, method, path, fields=None, files=None, js=None, timeout=300):
    data, headers = None, {}
    if files is not None or fields:
        data, ct = multipart(fields or {}, files or {})
        headers["Content-Type"] = ct
    elif js is not None:
        data, headers["Content-Type"] = json.dumps(js).encode(), "application/json"
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers, method=method), timeout=timeout) as r:
            return r.status, json.load(r), time.perf_counter() - t
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), time.perf_counter() - t


def check(name, ok, secs, detail=""):
    ROWS.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name:44s} {secs * 1000:8.0f} ms  {detail}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--wall", default="samples/test.jpg", help="photo used to exercise SAM 2 in the interference test")
    ap.add_argument("--bill", default="samples/bill_specimen.png")
    ap.add_argument("images", nargs="+")
    a = ap.parse_args()
    B = a.url.rstrip("/")
    try:
        urllib.request.urlopen(B + "/plants", timeout=5)
    except Exception as e:
        sys.exit(f"API not reachable at {B} ({e})")

    s, st, t = call(B, "GET", "/leaf/status")
    check("GET /leaf/status (lazy: not loaded yet)", s == 200 and st["model_present"], t, f"loaded={st.get('loaded')} device={st.get('device')}")

    imgs = [(p, open(p, "rb").read()) for p in a.images]
    for i, (p, data) in enumerate(imgs):
        s, r, t = call(B, "POST", "/leaf/analyze", {"plant": "basil", "cell": "3"}, {"file": (p.split("/")[-1].split("\\")[-1], data, "image/jpeg")})
        ok = s == 200 and r.get("overlay_jpg_base64") and 0 <= r.get("affected_share", -1) <= 1
        check(f"POST /leaf/analyze {p.split('/')[-1].split(chr(92))[-1][:22]}", ok, t,
              f"{r.get('label')} {r.get('affected_share', 0) * 100:.1f}% device={r.get('model', {}).get('device')} "
              f"server {r.get('timing_ms', {}).get('total')} ms{' (incl. load)' if r.get('timing_ms', {}).get('includes_model_load') else ''}")

    # warm latency
    data = imgs[0][1]
    ts = []
    for _ in range(10):
        s, r, t = call(B, "POST", "/leaf/analyze", {}, {"file": ("leaf.jpg", data, "image/jpeg")})
        ts.append(r["timing_ms"]["inference"])
    check("warm inference latency (10 runs)", statistics.median(ts) < 1000, statistics.median(ts) / 1000,
          f"median {statistics.median(ts):.1f} ms, max {max(ts):.1f} ms (model only)")

    s, r, t = call(B, "POST", "/leaf/analyze", {}, {"file": ("notes.txt", b"not an image", "text/plain")})
    check("POST /leaf/analyze not an image -> 422", s == 422, t)

    # phone camera relay (same contract as the camera page)
    s, r, t = call(B, "POST", "/api/camera/photos", {"takenAtMs": str(int(time.time() * 1000)), "fileName": "photo.jpg", "cell": "3"},
                   {"photo": ("photo.jpg", data, "image/jpeg")})
    pid = r.get("id")
    check("POST /api/camera/photos (camera page)", s == 200 and pid, t, f"id={pid}")
    s, lst, t = call(B, "GET", "/api/camera/photos?cell=3")
    check("GET /api/camera/photos?cell=3", s == 200 and any(p["id"] == pid for p in lst), t, f"{len(lst)} photo(s)")
    s, r, t = call(B, "POST", f"/api/camera/photos/{pid}/analyze", {"plant": "basil"})
    check("POST /api/camera/photos/{id}/analyze", s == 200 and r.get("camera_photo", {}).get("id") == pid, t, r.get("label", ""))

    # interference: SAM 2 (GPU) and bill OCR (CPU) alone, then while leaf analyses run in parallel
    wall, bill = open(a.wall, "rb").read(), open(a.bill, "rb").read()
    s, up, _ = call(B, "POST", "/space/upload", {"suggest": "false"}, {"image": ("wall.jpg", wall, "image/jpeg")})
    iid = up["image_id"]

    def sam():
        return call(B, "POST", "/space/segment", js={"image_id": iid, "points": [[640, 90]], "labels": [1]})

    def ocr():
        return call(B, "POST", "/bill/read", files={"file": ("bill.png", bill + uuid.uuid4().bytes, "image/png")})  # unique bytes: no result cache

    sam(); ocr()
    base_sam = statistics.median([sam()[2] for _ in range(3)])
    base_ocr = statistics.median([ocr()[2] for _ in range(2)])
    stop = threading.Event()
    leaf_runs = []

    def leaf_loop():
        while not stop.is_set():
            s_, r_, _ = call(B, "POST", "/leaf/analyze", {}, {"file": ("leaf.jpg", data, "image/jpeg")})
            leaf_runs.append(s_)

    th = [threading.Thread(target=leaf_loop) for _ in range(2)]
    [x.start() for x in th]
    res_sam = [sam() for _ in range(3)]
    res_ocr = [ocr() for _ in range(2)]
    stop.set()
    [x.join() for x in th]
    con_sam = statistics.median([x[2] for x in res_sam])
    con_ocr = statistics.median([x[2] for x in res_ocr])
    ok = all(x[0] == 200 for x in res_sam + res_ocr) and all(x == 200 for x in leaf_runs)
    check("other AI services keep working in parallel", ok, con_sam,
          f"SAM 2 {base_sam * 1000:.0f} -> {con_sam * 1000:.0f} ms, OCR {base_ocr * 1000:.0f} -> {con_ocr * 1000:.0f} ms, "
          f"{len(leaf_runs)} leaf runs meanwhile")
    s, st, t = call(B, "GET", "/leaf/status")
    check("GET /leaf/status (cached instance)", s == 200 and st["loaded"], t, f"device={st['device']} load {st['load_seconds']} s, runs {st['runs']}")
    print(f"\n{sum(ROWS)}/{len(ROWS)} passed")
    sys.exit(0 if all(ROWS) else 1)


if __name__ == "__main__":
    main()
