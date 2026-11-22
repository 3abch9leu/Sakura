"""
Serial bridge: Arduino <-> INBETWEEN API.

    pip install pyserial
    python arduino/sensor_bridge.py --port COM5 --api http://127.0.0.1:8000 --branch 0

Reads the Arduino's JSON lines (potentiometer level = SIMULATED reservoir sensor, DHT11 temperature and
humidity), posts them to POST /sensors, then asks GET /sensors/device what the LCD and buzzer should show
(computed from the dynamic water budget) and writes it back to the board.

--simulate runs without hardware: a level that slowly decreases, labelled "simulated".
"""
import argparse
import json
import math
import time
import urllib.request


def post(api, path, body):
    req = urllib.request.Request(api + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def get(api, path):
    with urllib.request.urlopen(api + path, timeout=5) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="serial port, e.g. COM5 or /dev/ttyUSB0")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--branch", type=int, default=0, help="branch (reservoir group) where the sensor sits")
    ap.add_argument("--raw-min", type=float, default=0)
    ap.add_argument("--raw-max", type=float, default=1023)
    ap.add_argument("--simulate", action="store_true", help="no hardware: send a simulated decreasing level")
    a = ap.parse_args()

    ser = None
    if not a.simulate:
        import serial                                   # pyserial
        ser = serial.Serial(a.port, 115200, timeout=1)
        time.sleep(2)                                   # board resets when the port opens
    t0, last_dev = time.time(), 0
    print("bridge running; Ctrl+C to stop")
    while True:
        if ser:
            line = ser.readline().decode(errors="ignore").strip()
            if not line.startswith("{"):
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
        else:
            time.sleep(2)
            frac = max(0.0, 0.9 - (time.time() - t0) / 900)          # empties in ~15 min
            r = {"source": "simulated", "level_raw": frac * 1023, "temp_c": 30 + 2 * math.sin(time.time() / 60),
                 "humidity": 45}
        r.update(branch=a.branch, raw_min=a.raw_min, raw_max=a.raw_max)
        if r.get("source") == "arduino" and r.pop("simulated_level", False):
            r["source"] = "arduino (potentiometer = simulated level)"
        try:
            post(a.api, "/sensors", r)
            if time.time() - last_dev > 4:
                last_dev = time.time()
                d = get(a.api, "/sensors/device")
                print(f"level_raw={r.get('level_raw')} T={r.get('temp_c')} -> {d['line1']} | {d['line2']} buzz={d['buzz']}")
                if ser:
                    ser.write(f"L1:{d['line1']}\nL2:{d['line2']}\nBZ:{1 if d['buzz'] else 0}\n".encode())
        except Exception as e:
            print("API not reachable:", type(e).__name__, e)


if __name__ == "__main__":
    main()
