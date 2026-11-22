"""
End-to-end HTTP test of the Energy & Comfort Companion endpoints (real requests, no mocks).

    uvicorn api:app --port 8000
    python samples/make_specimen_bill.py
    python bill_smoke_test.py --url http://localhost:8000
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = []


def check(name, fn):
    t = time.perf_counter()
    try:
        info = fn()
        RESULTS.append((name, True))
        print(f"PASS  {name:38} {time.perf_counter() - t:5.1f}s  {info or ''}")
    except Exception as e:
        RESULTS.append((name, False))
        print(f"FAIL  {name:38} {time.perf_counter() - t:5.1f}s  {type(e).__name__}: {e}")


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    a = ap.parse_args()
    B = a.url.rstrip("/").replace("//localhost", "//127.0.0.1")   # avoids a 2 s IPv6 lookup on Windows
    try:
        requests.get(B + "/plants", timeout=5)
    except requests.ConnectionError:
        print(f"The API is not running at {B}.\nStart it in another terminal, from the rootcode folder:\n"
              f"    python -m uvicorn api:app --port {B.rsplit(':', 1)[-1]}\nthen run this test again.")
        sys.exit(2)
    tmp = tempfile.mkdtemp()
    spec = os.path.join(HERE, "samples", "bill_specimen")
    if not os.path.exists(spec + ".png"):
        subprocess.run([sys.executable, os.path.join(HERE, "samples", "make_specimen_bill.py")], check=True)
    old = os.path.join(tmp, "old_taxes")
    subprocess.run([sys.executable, os.path.join(HERE, "samples", "make_specimen_bill.py"), "--old-taxes",
                    "--estimated", "--out", old], check=True, capture_output=True)
    state = {}

    def health():
        j = requests.get(B + "/health", timeout=60).json()
        need("bill_reader" in j and j["bill_reader"].get("rapidocr_installed"), "bill_reader / rapidocr missing")
        return "rapidocr installed"

    def read_png():
        with open(spec + ".png", "rb") as f:
            r = requests.post(B + "/bill/read", files={"file": ("bill.png", f, "image/png")}, timeout=180)
        need(r.ok, r.text[:200])
        j = r.json()
        F = {k: v["value"] for k, v in j["fields"].items()}
        need(F["consumption_kwh"] == 412, f"consumption {F['consumption_kwh']}")
        need(F["reading_type"] == "actual", "reading type")
        need("customer_name" in j["redacted"], "PII not detected")
        need("Test Exemple" not in r.text and "rue Fictive" not in r.text, "PII leaked in response")
        state["fields"] = F
        found = sum(v["status"] == "found" for v in j["fields"].values())
        return f"{found}/{len(F)} found, redacted={j['redacted']}"

    def read_pdf():
        with open(spec + ".pdf", "rb") as f:
            r = requests.post(B + "/bill/read", files={"file": ("bill.pdf", f, "application/pdf")}, timeout=180)
        need(r.ok, r.text[:200])
        F = {k: v["value"] for k, v in r.json()["fields"].items()}
        need(F["total_tnd"] is not None and F["consumption_kwh"] == 412, str(F))
        return f"source={r.json()['source']}"

    def read_arabic():
        """Arabic bill: right-to-left labels, ISO dates (2022-10-06), decimal comma, amounts in د.ت."""
        with open(os.path.join(os.path.dirname(spec), "bill_specimen_ar.png"), "rb") as f:
            r = requests.post(B + "/bill/read", files={"file": ("bill_ar.png", f, "image/png")}, timeout=180)
        need(r.ok, r.text[:200])
        F = {k: v["value"] for k, v in r.json()["fields"].items()}
        want = {"index_previous": 41207, "index_current": 41503, "consumption_kwh": 296, "energy_amount_tnd": 52.096,
                "taxes_tnd": 6.607, "electricity_total_tnd": 61.503, "total_tnd": 62.503,
                "period_start": "2022-08-07", "period_end": "2022-10-06"}
        bad = {k: (F.get(k), v) for k, v in want.items() if F.get(k) != v}
        need(not bad, f"wrong: {bad}")
        return "dates and amounts right-to-left OK"

    def read_bad():
        r = requests.post(B + "/bill/read", files={"file": ("x.png", b"not an image", "image/png")}, timeout=30)
        need(r.status_code == 422, f"expected 422, got {r.status_code}")
        r2 = requests.post(B + "/bill/read", files={"file": ("x.png", b"", "image/png")}, timeout=30)
        need(r2.status_code == 422, f"empty: expected 422, got {r2.status_code}")
        return r.json()["detail"][:60]

    def verify_match():
        r = requests.post(B + "/bill/verify", json={"bill": state["fields"]}, timeout=30)
        need(r.ok, r.text[:200])
        v = r.json()["verification"]
        need(v["status"] == "match", f"{v['status']}: {v['summary']} {v.get('checks')}")
        return f"match, {len(v['checks'])} lines checked"

    def verify_mismatch_cause():
        with open(old + ".png", "rb") as f:
            F = {k: v["value"] for k, v in requests.post(
                B + "/bill/read", files={"file": ("b.png", f, "image/png")}, timeout=180).json()["fields"].items()}
        v = requests.post(B + "/bill/verify", json={"bill": F}, timeout=30).json()["verification"]
        need(v["status"] == "mismatch", v["status"])
        need(any("2022" in c for c in v["causes"]), str(v["causes"]))
        need(F["reading_type"] == "estimated", "estimated not detected")
        return v["causes"][0][:70]

    def verify_unavailable():
        v = requests.post(B + "/bill/verify", json={"bill": {"total_tnd": 50}}, timeout=30).json()["verification"]
        need(v["status"] == "unavailable", v["status"])
        v2 = requests.post(B + "/bill/verify", json={"bill": {"consumption_kwh": 150, "period_months": 2,
                                                              "subscribed_power_kva": 4, "total_tnd": 30}},
                           timeout=30).json()["verification"]
        need(v2["status"] == "unavailable", "unsupported >2 kVA <=100 kWh/month case must be unavailable")
        return v2["summary"][:70]

    def verify_bad_input():
        r = requests.post(B + "/bill/verify", json={"bill": {"reading_type": "maybe"}}, timeout=30)
        need(r.status_code == 422, str(r.status_code))
        return "422 on bad reading_type"

    def explain(lang):
        def f():
            r = requests.post(B + "/bill/explain", json={"bill": state["fields"], "lang": lang}, timeout=200)
            need(r.ok, r.text[:200])
            j = r.json()
            need("412" in j["text"] or j["mode"] == "llm", "consumption missing from explanation")
            return f"mode={j['mode']}"
        return f

    def advice():
        body = {"bill": state["fields"], "facade": "W", "run_optimizer": True,
                "appliances": [{"name": "Climatiseur salon", "power_w": 1200, "hours_per_day": 5, "days": 60,
                                "reduce_hours_per_day": 1}],
                "setpoint_current_c": 22, "setpoint_target_c": 26}
        r = requests.post(B + "/bill/advice", json=body, timeout=120)
        need(r.ok, r.text[:200])
        j = r.json()
        need(j["scenarios"]["total_kwh"] == 360.0, f"kWh {j['scenarios']['total_kwh']}")
        need(j["scenarios"]["money"] and "saving_tnd" in j["scenarios"]["money"], "no priced impact")
        need(j["shading"]["electricity_savings"] == "Electricity savings have not yet been measured or validated.",
             "missing validation notice")
        need(j["shading"]["designs"], "no design comparison")
        return f"AC 360 kWh, saving {j['scenarios']['money']['saving_tnd']} TND, {len(j['shading']['designs'])} designs"

    def ask(q):
        def f():
            r = requests.post(B + "/bill/ask", json={"question": q, "bill": state["fields"]}, timeout=200)
            need(r.ok, r.text[:200])
            j = r.json()
            need(j["answer"] and j["sources"], "no answer or sources")
            return f"mode={j['mode']} lang={j['lang']} sources={len(j['sources'])}"
        return f

    check("GET /health (bill reader)", health)
    check("POST /bill/read  PNG specimen", read_png)
    check("POST /bill/read  PDF specimen", read_pdf)
    check("POST /bill/read  Arabic specimen", read_arabic)
    check("POST /bill/read  invalid file -> 422", read_bad)
    if "fields" in state:
        check("POST /bill/verify  match", verify_match)
        check("POST /bill/verify  mismatch + cause", verify_mismatch_cause)
        check("POST /bill/verify  unavailable", verify_unavailable)
        check("POST /bill/verify  bad input -> 422", verify_bad_input)
        for lang in ("fr", "ar", "darija"):
            check(f"POST /bill/explain  {lang}", explain(lang))
        check("POST /bill/advice  AC + shading", advice)
        check("POST /bill/ask  Darija (latin)", ask("3lech el fatoura mte3i estimé?"))
        check("POST /bill/ask  Arabic", ask("كيف تحسب الأداءات على الفاتورة؟"))
        check("POST /bill/ask  French", ask("Pourquoi régler la climatisation à 26 degrés ?"))
    ok = sum(r[1] for r in RESULTS)
    print(f"\n{ok}/{len(RESULTS)} passed")
    sys.exit(0 if ok == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
