"""
ROOTCODE web API for the dashboard (FastAPI).

    uvicorn api:app --host 0.0.0.0 --port 8000
    open http://localhost:8000/docs

Every response carries an `X-Process-Time-ms` header (exposed to browsers via CORS).
Set ROOTCODE_WARMUP=0 to skip preloading SAM 2 / the solar cache at startup.
"""
import json
import math
import os
import threading
from contextlib import asynccontextmanager
import time
from typing import List, Optional

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from rootcode import config as C
from rootcode.evaluate import Context, evaluate
from rootcode.optimizer import run
from rootcode.export import preview_svg
from rootcode.solar import facade_sun, peak_hour
from rootcode.tile import TileDesign

DEFAULT_N_GEN = 120
FAST_N_GEN = 40

@asynccontextmanager
async def lifespan(_app):
    if os.getenv("ROOTCODE_WARMUP", "1") != "0":
        threading.Thread(target=_warmup, daemon=True).start()
        threading.Thread(target=_warmup_ocr, daemon=True).start()
        threading.Thread(target=_warmup_styles, daemon=True).start()
        threading.Thread(target=_warmup_weather, daemon=True).start()
    yield
    if _STYLE_POOL.get("pool"):
        _STYLE_POOL["pool"].shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="ROOTCODE API (INBETWEEN)", lifespan=lifespan)

# AI weather prediction + ESP32 sensors + greenhouse rules (team branch weather_prediction), under /api/...
from rootcode.weather_ai.iot import router as _weather_router  # noqa: E402  (light import: the model loads on first forecast)
app.include_router(_weather_router)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Process-Time-ms"])

STATE = {"warmup": "not started", "sam_backend": None, "started_at": time.time()}


@app.middleware("http")
async def timing(request: Request, call_next):
    t = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t) * 1000
    response.headers["X-Process-Time-ms"] = f"{ms:.1f}"
    print(f"[timing] {request.method} {request.url.path} {response.status_code} {ms:.0f} ms")
    return response


def jsonable(x):
    """Recursively convert numpy / non-finite values into plain JSON types."""
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return x if math.isfinite(x) else None
    return x


def _check_context(plants, facade):
    bad = [p for p in plants if p not in C.PLANT_DEMAND_L_DAY]
    if bad or not 1 <= len(plants) <= 6:
        raise HTTPException(422, f"plants must be 1-6 of {list(C.PLANT_DEMAND_L_DAY)}; bad: {bad}")
    if str(facade).upper() not in C.FACADE_AZIMUTHS:
        try:
            float(facade)
        except ValueError:
            raise HTTPException(422, f"facade must be one of {list(C.FACADE_AZIMUTHS)} or an azimuth in degrees")


# ---------------------------------------------------------------- startup warm-up
def _warmup():
    STATE["warmup"] = "running"
    try:
        facade_sun(C.DEFAULT_LAT, C.DEFAULT_LON, 270.0)       # fills the pvlib cache
        from rootcode.facade import segment
        img = np.full((256, 256, 3), 200, np.uint8)
        img[64:192, 64:192] = 40                               # dark "window" on a light wall
        _, used, _, errors = segment(img, [(128, 128)])
        STATE["sam_backend"] = used
        STATE["warmup"] = "done" if used == "sam2" else f"done (sam2 unavailable: {errors})"
    except Exception as e:
        STATE["warmup"] = f"failed: {type(e).__name__}: {e}"[:300]


def _warmup_weather():
    """Load the weather model and compute the first forecast in the background (about 15 s), so /weather opens fast."""
    try:
        import asyncio
        import time as _t
        from rootcode.weather_ai import iot
        from rootcode.weather_ai.weather_inference import predict_tunis
        iot._FORECAST_CACHE.update(at=_t.time(), value=asyncio.run(predict_tunis()))
    except Exception:
        pass                                   # the page then computes it on first visit, or reports it unavailable


def _warmup_ocr():
    """Bill OCR (GPU when available) and then the image pipeline load at startup, not on the user's request.
    Sequential on purpose: the OCR is ready in seconds, SD loads after it without competing for the GPU."""
    try:
        from rootcode.bill_reader import warm_up
        warm_up()
    except Exception:
        pass
    if os.getenv("ROOTCODE_WARMUP_SD", "0") == "1":      # opt-in: the default preview needs no AI model
        # load SD last, once SAM 2 is in memory: the free-VRAM check then sees the real budget
        # (full GPU if it fits, CPU offload otherwise - never a silent spill into shared memory)
        t0 = time.time()
        while STATE["warmup"] in ("not started", "running") and time.time() - t0 < 180:
            time.sleep(1)
        try:
            from rootcode import enhance
            enhance.warm_up()
        except Exception:
            pass


# ---------------------------------------------------------------- models
class DesignRequest(BaseModel):
    plants: List[str] = ["mint", "basil", "strawberry", "lettuce"]
    facade: str = "W"
    rh: float = 0.55
    window_w: float = 1.2
    window_h: float = 1.4
    root_tiles: int = 4
    water_available_l_day: float = 6.0
    lat: float = C.DEFAULT_LAT
    lon: float = C.DEFAULT_LON
    fast: bool = False                 # live demo: 40 generations instead of 120
    n_gen: Optional[int] = None        # explicit override (10-300)


class TileParams(BaseModel):
    widths_mm: List[float]             # one engraved channel width per plant pocket
    cool_width_mm: float = 0.0         # < 0.5 mm means the cooling branch is closed
    water_l_day: float = 1.0           # litres poured per root tile per day
    porosity: float = 0.4
    aperture_mm: float = 15.0
    layers: int = 2


class EvaluateRequest(BaseModel):
    design: TileParams
    plants: List[str] = ["mint", "basil", "strawberry", "lettuce"]
    facade: str = "W"
    rh: float = 0.55
    window_w: float = 1.2
    window_h: float = 1.4
    root_tiles: int = 4
    water_available_l_day: float = 6.0
    lat: float = C.DEFAULT_LAT
    lon: float = C.DEFAULT_LON
    calibration: dict = {}


class ChatRequest(BaseModel):
    messages: List[dict]


# ---------------------------------------------------------------- endpoints
@app.get("/", include_in_schema=False)
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/docs")


@app.get("/health")
def health():
    """Status of GPU, segmentation model, LLM backends and engines (fast, loads nothing)."""
    out = {"status": "ok", "uptime_s": round(time.time() - STATE["started_at"], 1),
           "warmup": STATE["warmup"], "segmentation_backend_loaded": STATE["sam_backend"]}
    try:
        import torch
        out["gpu"] = {"torch": torch.__version__, "cuda_available": torch.cuda.is_available(),
                      "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                      "vram_allocated_mb": round(torch.cuda.memory_allocated() / 2**20)
                      if torch.cuda.is_available() else 0}
    except Exception as e:
        out["gpu"] = {"error": str(e)}
    try:
        from rootcode.facade import _MODELS
        out["segmentation_models_in_memory"] = list(_MODELS)
    except Exception as e:
        out["segmentation_models_in_memory"] = f"error: {e}"

    from rootcode import agent
    llm = []
    for name, url, key, model in agent.backends():
        b = {"name": name, "model": model, "base_url": url}
        if name == "groq":
            b["reachable"] = "key set (not pinged)"
        else:
            try:
                import urllib.request
                tags_url = url.rstrip("/").removesuffix("/v1").replace("//localhost", "//127.0.0.1") + "/api/tags"
                with urllib.request.urlopen(tags_url, timeout=1.5) as r:
                    tags = [m["name"] for m in json.load(r).get("models", [])]
                b["reachable"] = True
                b["model_pulled"] = model in tags
            except Exception as e:
                b["reachable"] = False
                b["error"] = type(e).__name__
        llm.append(b)
    out["llm_backends"] = llm
    out["llm_last_used"] = agent.LAST_BACKEND or None
    out["engines"] = {"hydro": "ready", "solar": "ready", "optimizer": "ready (NSGA-II, pymoo)"}
    try:
        from rootcode import enhance
        out["diffusion"] = enhance.status()
    except Exception as e:
        out["diffusion"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        import importlib.util
        from rootcode import bill_reader
        out["bill_reader"] = {"rapidocr_installed": importlib.util.find_spec("rapidocr") is not None,
                              **bill_reader.STATUS}
    except Exception as e:
        out["bill_reader"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        from rootcode import leafhealth
        out["leaf_model"] = {"model_present": os.path.isfile(leafhealth.MODEL_PATH), **leafhealth.STATUS}
    except Exception as e:
        out["leaf_model"] = {"error": f"{type(e).__name__}: {e}"}
    return jsonable(out)


@app.get("/plants")
def plants():
    return C.PLANT_DEMAND_L_DAY


@app.get("/sun")
def sun(facade: str = "W", lat: float = C.DEFAULT_LAT, lon: float = C.DEFAULT_LON,
        date: str = "2026-07-15"):
    """Clear-sky solar exposure of a vertical facade over one day (hourly profile in W/m2)."""
    _check_context(["mint"], facade)
    az = float(C.FACADE_AZIMUTHS.get(facade.upper(), facade))
    s = facade_sun(lat, lon, az, date)
    total = s["beam"] + s["diffuse"]
    per_hour = int(round(1 / s["dt_h"]))
    hourly = [{"hour": h,
               "beam_w_m2": float(s["beam"][h * per_hour:(h + 1) * per_hour].mean()),
               "diffuse_w_m2": float(s["diffuse"][h * per_hour:(h + 1) * per_hour].mean())}
              for h in range(len(total) // per_hour)]
    return jsonable({
        "facade": facade.upper(), "azimuth_deg": az, "lat": lat, "lon": lon, "date": date,
        "kwh_per_m2_day": s["daily_kwh_m2"], "peak_hour": peak_hour(s),
        "peak_w_m2": float(total.max()), "hourly": hourly,
        "note": "clear-sky (worst hot day) estimate, pvlib Ineichen model",
    })


@app.post("/evaluate")
def evaluate_one(req: EvaluateRequest):
    """Score one given tile design (hydraulics + solar + objectives + constraints)."""
    _check_context(req.plants, req.facade)
    if len(req.design.widths_mm) != len(req.plants):
        raise HTTPException(422, "design.widths_mm needs one width per plant")
    d = TileDesign(plants=list(req.plants), **req.design.model_dump())
    ctx = Context(**req.model_dump(exclude={"design"}))
    r = evaluate(d, ctx)
    return jsonable({"design": d.to_dict(), "result": r,
                     "feasible": all(r["constraints"].values())})


@app.post("/design")
def design(req: DesignRequest):
    _check_context(req.plants, req.facade)
    n_gen = req.n_gen or (FAST_N_GEN if req.fast else DEFAULT_N_GEN)
    n_gen = int(min(max(n_gen, 10), 300))
    ctx = Context(**req.model_dump(exclude={"fast", "n_gen"}))
    t = time.perf_counter()
    try:
        out = run(ctx, n_gen=n_gen)
    except RuntimeError as e:          # no feasible design for these inputs
        raise HTTPException(422, str(e))
    designs = {}
    for name, v in out["designs"].items():
        d, r = v["design"], v["result"]
        designs[name] = {"design": d.to_dict(), "result": r,
                         "preview_svg": preview_svg(d, name.replace("_", " ").title())}
    return jsonable({
        "designs": designs,
        "pareto": out["F"].tolist(),          # [[water, heat, deficit], ...] for the dashboard plot
        "plant_safe_found": out["plant_safe_found"],
        "n_gen": n_gen,
        "optimizer_seconds": round(time.perf_counter() - t, 2),
    })


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    from rootcode.agent import chat, LAST_BACKEND
    try:
        reply, messages, last_design = chat(req.messages)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return jsonable({"reply": reply, "messages": messages, "design": last_design,
                     "llm": dict(LAST_BACKEND)})


@app.post("/facade")
async def facade(image: UploadFile = File(...), points: str = Form(...), real_width_m: float = Form(...),
                 real_height_m: Optional[float] = Form(None), root_tiles: int = Form(4),
                 backend: str = Form("auto"), return_mask: bool = Form(True)):
    """points: JSON list of [x, y] taps in ORIGINAL image pixels, e.g. [[640, 410]].
    Tap every pane of a multi-pane window for a full-window mask."""
    from rootcode.facade import analyze, overlay, public, png_b64, load_rgb
    try:
        img, s = load_rgb(await image.read())
        pts = [(x * s, y * s) for x, y in json.loads(points)]
    except Exception as e:
        raise HTTPException(422, f"bad image or points: {e}")
    try:
        res = analyze(img, pts, real_width_m, root_tiles, backend, real_height_m)
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    out = public(res)
    out["image_size_px"] = [int(img.shape[1]), int(img.shape[0])]   # mask/overlay size (may be downscaled)
    out["overlay_png_base64"] = png_b64(overlay(img, res))
    if return_mask:
        m = (res["_mask"] > 0).astype(np.uint8) * 255
        out["mask_png_base64"] = png_b64(np.dstack([m, m, m]))
    return jsonable(out)


# ---------------------------------------------------------------- Stage 1 try-on / Stage 2 AI render
DESIGN_NAMES = ("water_saver", "shade_maximizer", "balanced", "baseline")


def _stage1(img_bytes, corners, real_width_m, real_height_m, plants, facade, rh, water_available_l_day,
            root_tiles, design, fast, design_params):
    """Shared by /tryon and /render: photo + corners -> optimized design -> try-on image."""
    from rootcode.facade import load_rgb, rectify, _order_corners
    from rootcode.tryon import tryon
    try:
        img, s = load_rgb(img_bytes)
        pts = [(float(x) * s, float(y) * s) for x, y in json.loads(corners)]
        if len(pts) != 4:
            raise ValueError("corners needs exactly 4 [x, y] points")
        plant_list = json.loads(plants) if plants.strip().startswith("[") else \
            [p.strip() for p in plants.split(",") if p.strip()]
    except Exception as e:
        raise HTTPException(422, f"bad image, corners or plants: {e}")
    _check_context(plant_list, facade)
    if design not in DESIGN_NAMES:
        raise HTTPException(422, f"design must be one of {DESIGN_NAMES}")

    w_m = float(real_width_m)
    h_m = float(real_height_m) if real_height_m else w_m * rectify(_order_corners(pts), img.shape)[0]
    metrics = None
    if design_params:                                  # design already chosen (e.g. from /design)
        try:
            p = json.loads(design_params)
            d = TileDesign(plants=plant_list, **{k: p[k] for k in
                           ("widths_mm", "cool_width_mm", "water_l_day", "porosity", "aperture_mm", "layers")})
        except Exception as e:
            raise HTTPException(422, f"bad design_params: {e}")
    else:
        ctx = Context(plants=plant_list, facade=facade, rh=rh, window_w=w_m, window_h=h_m,
                      root_tiles=root_tiles, water_available_l_day=water_available_l_day)
        try:
            out = run(ctx, n_gen=FAST_N_GEN if fast else DEFAULT_N_GEN)
        except RuntimeError as e:
            raise HTTPException(422, str(e))
        d, r = out["designs"][design]["design"], out["designs"][design]["result"]
        metrics = {"heat_reduction_pct": r["panel"]["heat_reduction_pct"],
                   "water_l_day": r["objectives"]["water_l_day"],
                   "plant_deficit": r["objectives"]["plant_deficit"]}
    st1 = tryon(img, pts, w_m, d, root_tiles, real_height_m)
    return img, st1, d, metrics


@app.post("/tryon")
def tryon_endpoint(image: UploadFile = File(...), corners: str = Form(...), real_width_m: float = Form(...),
                   real_height_m: Optional[float] = Form(None), plants: str = Form("mint,basil,strawberry,lettuce"),
                   facade: str = Form("W"), rh: float = Form(0.55), water_available_l_day: float = Form(6.0),
                   root_tiles: int = Form(4), design: str = Form("balanced"), fast: bool = Form(True),
                   design_params: Optional[str] = Form(None)):
    """Stage 1: the optimized tiles painted onto the photo (real geometry, no AI).
    corners: JSON [[x,y] x4] in ORIGINAL pixels (e.g. `quad_px` from /facade).
    design_params: optional JSON of a design from /design (skips the optimizer)."""
    from rootcode.facade import png_b64
    t = time.perf_counter()
    _, st1, d, metrics = _stage1(image.file.read(), corners, real_width_m, real_height_m, plants, facade, rh,
                                 water_available_l_day, root_tiles, design, fast, design_params)
    m = st1["mask"] * 255
    return jsonable({"design_name": design, "design": d.to_dict(), "metrics": metrics,
                     "tiles": st1["tiles"], "window_w_m": st1["window_w_m"], "window_h_m": st1["window_h_m"],
                     "tryon_png_base64": png_b64(st1["image"]),
                     "mask_png_base64": png_b64(np.dstack([m, m, m])),
                     "seconds": round(time.perf_counter() - t, 2)})


@app.post("/render")
def render_endpoint(image: UploadFile = File(...), corners: str = Form(...), real_width_m: float = Form(...),
                    real_height_m: Optional[float] = Form(None), plants: str = Form("mint,basil,strawberry,lettuce"),
                    facade: str = Form("W"), rh: float = Form(0.55), water_available_l_day: float = Form(6.0),
                    root_tiles: int = Form(4), design: str = Form("balanced"), fast: bool = Form(True),
                    design_params: Optional[str] = Form(None), strength: float = Form(0.35),
                    seed: int = Form(42)):
    """Stage 2: AI-enhanced photorealistic render of the try-on (SD 1.5 + ControlNet Canny).
    Same inputs as /tryon plus strength (0.3-0.6) and seed. If the AI step is unavailable the
    Stage 1 image is returned with enhanced=false and the reason in `message`."""
    from rootcode.facade import png_b64
    from rootcode import enhance
    t = time.perf_counter()
    _, st1, d, metrics = _stage1(image.file.read(), corners, real_width_m, real_height_m, plants, facade, rh,
                                 water_available_l_day, root_tiles, design, fast, design_params)
    st2 = enhance.enhance(st1["image"], st1["mask"], strength=min(max(strength, 0.1), 0.9), seed=seed)
    return jsonable({"design_name": design, "design": d.to_dict(), "metrics": metrics,
                     "enhanced": st2["enhanced"], "message": st2["message"],
                     "render_png_base64": png_b64(st2["image"]),
                     "render_seconds": st2["seconds"], "peak_vram_mb": st2["peak_vram_mb"],
                     "strength": st2["strength"], "seed": st2["seed"],
                     "seconds": round(time.perf_counter() - t, 2)})


# ---------------------------------------------------------------- Energy & Comfort Companion (STEG bills)
# Privacy: uploaded bills are processed in memory and never written to disk or logged; personal fields
# (name, address, customer / meter numbers) are dropped by the reader. The timing middleware logs paths only.
MAX_BILL_BYTES = 15 * 2**20


class BillFields(BaseModel):
    consumption_kwh: Optional[float] = None
    index_previous: Optional[float] = None
    index_current: Optional[float] = None
    period_start: Optional[str] = None          # YYYY-MM-DD
    period_end: Optional[str] = None
    period_months: Optional[float] = None
    subscribed_power_kva: Optional[float] = None
    reading_type: Optional[str] = None          # "actual" | "estimated"
    energy_amount_tnd: Optional[float] = None
    fixed_charges_tnd: Optional[float] = None
    taxes_tnd: Optional[float] = None
    electricity_total_tnd: Optional[float] = None
    other_charges_tnd: Optional[float] = None   # gas, RTT contribution, arrears... (user-entered)
    total_tnd: Optional[float] = None


class BillRequest(BaseModel):
    bill: BillFields
    history: List[dict] = []                    # [{"period_end": "...", "consumption_kwh": n}] previous bills
    lang: Optional[str] = None                  # fr | ar | darija | en
    use_llm: bool = True


class Appliance(BaseModel):
    name: str = "Appliance"
    power_w: Optional[float] = None
    power_kw: Optional[float] = None
    hours_per_day: float
    days: float
    quantity: float = 1
    reduce_hours_per_day: float = 0


class AdviceRequest(BaseModel):
    bill: Optional[BillFields] = None
    appliances: List[Appliance] = []
    setpoint_current_c: Optional[float] = None
    setpoint_target_c: Optional[float] = None
    facade: Optional[str] = None
    lat: float = C.DEFAULT_LAT
    lon: float = C.DEFAULT_LON
    designs: Optional[dict] = None              # "designs" field of a POST /design response, if available
    run_optimizer: bool = False                 # otherwise run the fast optimizer for the shading comparison
    window_w: float = 1.2
    window_h: float = 1.4


class AskRequest(BaseModel):
    question: str
    history: List[dict] = []                    # previous {"role","content"} turns (user/assistant only)
    bill: Optional[BillFields] = None
    lang: Optional[str] = None


LLM_DOWN = {
    "fr": "L'assistant IA n'est pas disponible pour le moment. Voici les informations officielles les plus proches de votre question :",
    "ar": "المساعد الذكي غير متاح حاليًا. هذه أقرب المعلومات الرسمية لسؤالك:",
    "darija": "المساعد موش متاح توة. هاذي أقرب معلومات رسمية لسؤالك:",
    "en": "The AI assistant is not available right now. Here is the closest official information:",
}
LLM_DOWN_NOTHING = {
    "fr": "L'assistant IA n'est pas disponible et nous n'avons pas trouvé d'information officielle sur ce point.",
    "ar": "المساعد غير متاح ولم نجد معلومة رسمية حول هذه النقطة.",
    "darija": "المساعد موش متاح وما لقيناش معلومة رسمية على هالنقطة.",
    "en": "The AI assistant is not available and we found no official information on this point.",
}
BILL_FACTS = {"fr": "L'assistant IA est hors ligne. Voici ce que montre votre facture vérifiée :",
              "ar": "المساعد الذكي غير متصل. هذا ما تبيّنه فاتورتك بعد التحقق:",
              "darija": "المساعد موش متاح توة. هاو شنوة تقول الفاتورة متاعك:",
              "en": "The AI assistant is offline. Here is what your verified bill shows:"}
EXPLAIN_ASK = {"fr": "Explique-moi ma facture simplement.", "ar": "اشرح لي فاتورتي بطريقة مبسطة.",
               "darija": "فسّرلي الفاتورة متاعي بالساهل.", "en": "Explain my bill simply."}


def _bill_dict(b):
    from datetime import date
    d = b.model_dump(exclude_none=True) if b else {}
    if d.get("reading_type") not in (None, "actual", "estimated"):
        raise HTTPException(422, "reading_type must be 'actual' or 'estimated'")
    for k in ("period_start", "period_end"):
        if d.get(k):
            try:
                date.fromisoformat(d[k])
            except ValueError:
                raise HTTPException(422, f"{k} must be a date YYYY-MM-DD")
    for k, v in d.items():
        if isinstance(v, float) and v < 0:
            raise HTTPException(422, f"{k} cannot be negative")
    return d


@app.post("/bill/read")
async def bill_read(file: UploadFile = File(...)):
    """Upload a STEG bill (JPG/PNG/PDF). Returns extracted fields, each {value, status: found|uncertain|missing}.
    The file is processed in memory and discarded; personal details are not returned."""
    from rootcode.bill_reader import read_bill
    data = await file.read()
    if not data:
        raise HTTPException(422, "empty file")
    if len(data) > MAX_BILL_BYTES:
        raise HTTPException(413, "file too large (max 15 MB)")
    try:
        out = read_bill(data, file.filename or "", file.content_type or "")
    except ValueError as e:
        raise HTTPException(422, str(e))
    except ModuleNotFoundError as e:
        raise HTTPException(503, f"OCR engine not installed: {e}. pip install rapidocr python-bidi")
    finally:
        del data
    return jsonable(out)


@app.post("/bill/verify")
def bill_verify(req: BillRequest):
    """Check the corrected bill against the official STEG tariff (deterministic Python).
    status: match | partial | mismatch | unavailable (never a false match)."""
    from rootcode.tariff import TARIFF, verify
    from rootcode.energy_advisor import understand
    b = _bill_dict(req.bill)
    v = verify(b)
    return jsonable({"verification": v, "understanding": understand(b, v, req.history or None),
                     "tariff_version": TARIFF["version"], "tariff_conflicts": TARIFF["conflicts"],
                     "not_verified": TARIFF["not_verified"]})


@app.post("/bill/explain")
def bill_explain(req: BillRequest):
    """Plain-language explanation in fr / ar / darija / en. Uses ROOTAgent when an LLM answers,
    otherwise a deterministic template (every number comes from the bill or the tariff calculator)."""
    from rootcode.tariff import verify
    from rootcode import energy_advisor as EA
    b = _bill_dict(req.bill)
    lang = req.lang if req.lang in EA.T else "fr"
    v = verify(b)
    base = EA.explain(b, v, lang)
    out = {"lang": lang, "mode": "template", "text": base["text"], "paragraphs": base["paragraphs"],
           "sources": base["sources"], "verification_status": v["status"], "llm_error": None}
    if req.use_llm:
        from rootcode.agent import bill_chat
        try:
            reply, _, srcs = bill_chat([{"role": "user", "content": EXPLAIN_ASK[lang] +
                                         "\n(Verified facts you may use: " + base["text"] + ")"}], b, v,
                                     max_steps=2, timeout=45)     # facts are given: no long tool loop
            out.update(mode="llm", text=reply, paragraphs=[p for p in reply.split("\n\n") if p.strip()],
                       sources=sorted(set(base["sources"] + srcs)))
        except Exception as e:
            out["llm_error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return jsonable(out)


@app.post("/bill/advice")
def bill_advice(req: AdviceRequest):
    """A. consumption understanding, B. appliance scenarios (deterministic kWh + tariff-priced impact),
    C. INBETWEEN shading for the window orientation. Electricity savings from shading are never claimed."""
    from rootcode import energy_advisor as EA
    from rootcode.tariff import verify
    b = _bill_dict(req.bill) if req.bill else {}
    out = {"understanding": None, "scenarios": None, "shading": None}
    if b:
        out["understanding"] = EA.understand(b, verify(b))
    if req.appliances:
        sp = None
        if req.setpoint_current_c is not None and req.setpoint_target_c is not None:
            sp = {"current_c": req.setpoint_current_c, "target_c": req.setpoint_target_c}
        try:
            out["scenarios"] = EA.scenarios([a.model_dump(exclude_none=True) for a in req.appliances], b or None, sp)
        except (ValueError, KeyError) as e:
            raise HTTPException(422, str(e))
    if req.facade:
        _check_context(["mint"], req.facade)
        out["shading"] = EA.shading(req.facade, req.lat, req.lon, designs=req.designs,
                                    run_optimizer=req.run_optimizer and not req.designs,
                                    context={"window_w": req.window_w, "window_h": req.window_h})
    return jsonable(out)


@app.post("/bill/ask")
def bill_ask(req: AskRequest):
    """Question about the bill in French, Arabic or Tunisian Darija. ROOTAgent (bill mode) answers with tools
    and official sources; without an LLM, the matching official snippets are returned instead."""
    from rootcode import energy_advisor as EA
    from rootcode.tariff import verify
    q = req.question.strip()
    if not q:
        raise HTTPException(422, "question is empty")
    lang = req.lang if req.lang in EA.T else EA.detect_language(q)
    b = _bill_dict(req.bill) if req.bill else None
    v = verify(b) if b else None
    hits = EA.retrieve(q)
    cites = [{"title": h["title"], "url": h["url"]} for h in hits if h["url"]]
    history = [m for m in req.history if m.get("role") in ("user", "assistant") and m.get("content")][-8:]
    try:
        from rootcode.agent import bill_chat, LAST_BACKEND
        reply, _, srcs = bill_chat(history + [{"role": "user", "content": q}], b, v)
        used = [c for c in cites if c["url"] in srcs]
        extra = [{"title": u, "url": u} for u in srcs if u not in {c["url"] for c in cites}]
        return jsonable({"mode": "llm", "lang": lang, "answer": reply, "sources": used + extra or cites,
                         "llm": dict(LAST_BACKEND)})
    except RuntimeError as e:
        answer = (LLM_DOWN if hits else LLM_DOWN_NOTHING)[lang]
        if b and v and v["status"] != "unavailable":
            # the verified bill's own facts (deterministic) come first: consumption, band, headroom, reading
            facts = EA.explain(b, v, lang)["paragraphs"][1:5]
            answer = BILL_FACTS[lang] + "\n" + "\n".join(facts) + ("\n\n" + LLM_DOWN[lang] if hits else "")
        return jsonable({"mode": "retrieval", "lang": lang,
                         "answer": answer,
                         "snippets": hits, "sources": cites, "llm_error": str(e)[:200]})


# ================================================================ INBETWEEN Studio: space -> sun -> styles -> preview
# Photos are kept in server MEMORY only (never written to disk), for 30 minutes, so refinement clicks only
# send coordinates. Coordinates are always in the pixels of the (possibly downscaled) image returned here.
_IMAGES = {}
_IMG_TTL = 1800
LAST_WATER = {"statuses": None}


def _img(image_id):
    now = time.time()
    for k in [k for k, v in _IMAGES.items() if now - v["ts"] > _IMG_TTL]:
        _IMAGES.pop(k, None)
    if image_id not in _IMAGES:
        raise HTTPException(404, "image expired or unknown: upload the photo again")
    _IMAGES[image_id]["ts"] = now
    return _IMAGES[image_id]


@app.post("/space/upload")
async def space_upload(image: UploadFile = File(...), suggest: bool = Form(True)):
    """Upload an architectural photo once. Returns image_id, size, EXIF hints (GPS, compass) and
    automatic surface / opening suggestions (SAM 2 on a grid; suggestions only)."""
    import hashlib
    from rootcode.facade import load_rgb
    from rootcode import space
    data = await image.read()
    if not data or len(data) > 20 * 2**20:
        raise HTTPException(413 if data else 422, "empty file or file too large (max 20 MB)")
    try:
        img, s = load_rgb(data, max_side=1280)
    except Exception as e:
        raise HTTPException(422, f"not a readable image: {e}")
    image_id = hashlib.sha256(data).hexdigest()[:16]
    if len(_IMAGES) >= 8:
        _IMAGES.pop(min(_IMAGES, key=lambda k: _IMAGES[k]["ts"]), None)
    hints = space.exif_hints(data)
    _IMAGES[image_id] = {"img": img, "ts": time.time(), "suggestions": None}
    del data
    out = {"image_id": image_id, "width": int(img.shape[1]), "height": int(img.shape[0]), "exif": hints,
           "suggestions": None}
    if suggest:
        t = time.perf_counter()
        sg = space.suggest(img)
        _IMAGES[image_id]["suggestions"] = sg["regions"]
        out["suggestions"] = sg
        out["suggest_seconds"] = round(time.perf_counter() - t, 2)
    return jsonable(out)


class SegmentRequest(BaseModel):
    image_id: str
    mode: str = "click"                    # click | polygon | rect
    points: List[List[float]] = []         # click mode: [[x, y], ...]
    labels: List[int] = []                 # 1 include, 0 exclude
    polygon: List[List[float]] = []        # polygon mode
    rect: List[float] = []                 # rect mode: [x0, y0, x1, y1]


@app.post("/space/segment")
def space_segment(req: SegmentRequest):
    """Interactive selection: include / exclude clicks (SAM 2 -> SAM -> flood fill) or polygon / rectangle.
    Returns a translucent overlay, the selection polygons and the obstacles found inside it."""
    from rootcode import space
    rec = _img(req.image_id)
    img = rec["img"]
    h, w = img.shape[:2]
    t = time.perf_counter()
    backend, score = "manual", None
    if req.mode == "click":
        labels = req.labels or [1] * len(req.points)
        if not req.points or len(req.points) != len(labels):
            raise HTTPException(422, "points and labels must have the same length")
        try:
            mask, backend, score, _ = space.refine(img, [tuple(p) for p in req.points], labels)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(422, str(e))
    elif req.mode == "polygon":
        if len(req.polygon) < 3:
            raise HTTPException(422, "a polygon needs at least 3 points")
        mask = space.mask_from_polygon((h, w), req.polygon)
    elif req.mode == "rect":
        if len(req.rect) != 4:
            raise HTTPException(422, "rect is [x0, y0, x1, y1]")
        x0, y0, x1, y1 = req.rect
        mask = space.mask_from_polygon((h, w), [[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    else:
        raise HTTPException(422, "mode must be click, polygon or rect")
    obs = space.obstacles(mask, rec.get("suggestions"))
    return jsonable({"backend": backend, "score": score, "area_frac": float(mask.mean()),
                     "overlay_png_base64": space.mask_png_b64(mask), "polygons": space.polygons(mask),
                     "obstacles": obs, "seconds": round(time.perf_counter() - t, 3)})


class AreaRequest(BaseModel):
    image_id: str
    selection: List[dict]                    # [{outer, holes}] from /space/segment
    obstacles: List[List[List[float]]] = []  # polygons to keep clear
    reference: dict                          # {"p1": [x, y], "p2": [x, y], "length_m": 1.2}
    height_m: Optional[float] = None


@app.post("/space/area")
def space_area(req: AreaRequest):
    """One reference measurement -> the usable installation area in metres (perspective-corrected)."""
    from rootcode import space
    rec = _img(req.image_id)
    try:
        if not req.reference.get("length_m") or float(req.reference["length_m"]) <= 0:
            raise ValueError("reference length must be positive (metres)")
        out = space.installation_area(rec["img"].shape[:2], req.selection, req.obstacles, req.reference, req.height_m)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e))
    except MemoryError:
        raise HTTPException(422, "this measurement gives an area far too large to process: check the length "
                                 "you typed (metres) and the measuring line")
    return jsonable(out)


@app.get("/solar/day")
def solar_day(azimuth: float = 270.0, lat: float = C.DEFAULT_LAT, lon: float = C.DEFAULT_LON,
              date: str = "2026-06-21", step_min: int = 15):
    """Sun position + clear-sky irradiance on the facade, sunrise to sunset (time slider and 3D light)."""
    from rootcode import sunpath
    try:
        d = dict(sunpath.day(lat, lon, float(azimuth) % 360, date, step_min=int(min(max(step_min, 5), 60))))
    except ValueError as e:
        raise HTTPException(422, str(e))
    d["note"] = "Clear-sky model (pvlib Ineichen): no clouds, surrounding buildings or trees. An upper bound."
    return jsonable(d)


class StylesRequest(BaseModel):
    area: dict                             # /space/area result, or {"width_m", "height_m"}
    plants: List[str] = ["mint", "basil", "strawberry"]
    styles: List[str] = []                 # empty = all
    facade_azimuth: float = 270.0
    lat: float = C.DEFAULT_LAT
    lon: float = C.DEFAULT_LON
    water_available_l_day: Optional[float] = None   # optional limit; None = the design reports what it needs
    greenery: str = "full"                 # "full" (every pocket planted), "balanced", "pattern" (few plants)
    rh: float = 0.55
    prices: Optional[dict] = None          # {"frame_tnd_per_m", "screen_tnd_per_m2", "pocket_tnd"} if known


# ---- parallel style generation: each style is independent, so they run in worker processes (persistent pool,
# warmed at startup). Identical requests (same area, plants, sun, water, styles) are answered from a small cache.
import hashlib  # noqa: E402

_STYLE_CACHE = {}
_STYLE_POOL = {"pool": None, "mode": "sequential", "error": None}
_STYLE_POOL_LOCK = threading.Lock()


def _style_pool():
    with _STYLE_POOL_LOCK:
        if _STYLE_POOL["pool"] is None and os.getenv("ROOTCODE_STYLE_WORKERS", "auto") != "0":
            from concurrent.futures import ProcessPoolExecutor
            n = int(os.getenv("ROOTCODE_STYLE_WORKERS", "0") or 0) or max(2, min(8, (os.cpu_count() or 4) // 2))
            from rootcode.styles_worker import ignore_ctrl_c
            _STYLE_POOL["pool"] = ProcessPoolExecutor(max_workers=n, initializer=ignore_ctrl_c)
            _STYLE_POOL["mode"] = f"parallel ({n} worker processes)"
        return _STYLE_POOL["pool"]


def _warmup_styles():
    try:                                     # leaf and fruit sprites of the photo-like preview
        from rootcode import photoreal
        for p in photoreal.PLANTS.values():
            for k in range(3):
                photoreal.leaf_sprite(p["ratio"], p["serr"], p["gloss"], k)
        for f in ("tomato", "strawberry", "chili", "flower"):
            photoreal.fruit_sprite(f)
    except Exception:
        pass
    try:
        from rootcode.styles_worker import ping
        pool = _style_pool()
        if pool:
            list(pool.map(ping, range(pool._max_workers)))
    except Exception as e:
        _STYLE_POOL["error"] = f"{type(e).__name__}: {e}"[:200]


def _run_styles(args):
    from rootcode.styles_worker import run_style
    pool = None
    try:
        pool = _style_pool()
    except Exception as e:
        _STYLE_POOL["error"] = f"{type(e).__name__}: {e}"[:200]
    if pool:
        try:
            return list(pool.map(run_style, *zip(*args)))
        except Exception as e:                       # broken pool (e.g. a worker crashed): fall back, rebuild later
            _STYLE_POOL.update(pool=None, mode="sequential (pool failed)", error=f"{type(e).__name__}: {e}"[:200])
    return [run_style(*a) for a in args]


_PATTERNS = {"items": None}


@app.get("/studio/patterns")
def studio_patterns():
    """A small drawing of every cultural pattern (real generator output on a 0.9 x 0.7 m sample), for the picker."""
    if _PATTERNS["items"] is None:
        from rootcode import styles as S, sunpath, stylerender
        sun = sunpath.day(C.DEFAULT_LAT, C.DEFAULT_LON, 270.0, "2026-06-21", step_min=30)
        items = []
        for sid, st in S.STYLES.items():
            try:
                g = S.generate(sid, {"width_m": 1.3, "height_m": 1.0}, ["basil", "mint", "strawberry"], sun, 3.0, "moderate", "pattern")
                svg = stylerender.svg(g, show_channels=False, px_per_m=200, tight=True)
            except Exception:
                svg = None
            items.append({"id": sid, "name": st["name"], "culture": st["culture"], "text": st["text"], "svg": svg})
        _PATTERNS["items"] = items
    return _PATTERNS["items"]


@app.post("/studio/styles")
def studio_styles(req: StylesRequest):
    """Every chosen cultural geometry, fitted to the selected area and evaluated under the SAME context:
    sun (pvlib), plants (HydroEngine demand), water budget, NSGA-II on the hydraulic variables."""
    from rootcode import styles as S, sunpath, stylerender
    plants = list(dict.fromkeys(req.plants))
    _check_context(plants, str(req.facade_azimuth % 360))
    ids = [s for s in (req.styles or list(S.STYLES)) if s in S.STYLES]
    if not ids:
        raise HTTPException(422, f"styles must be among {list(S.STYLES)}")
    if not req.area.get("width_m") or not req.area.get("height_m"):
        raise HTTPException(422, "area needs width_m and height_m (use /space/area)")
    t = time.perf_counter()
    az = req.facade_azimuth % 360
    summer = sunpath.day(req.lat, req.lon, az, "2026-06-21", step_min=30)
    winter = sunpath.day(req.lat, req.lon, az, "2026-12-21", step_min=30)
    design_day = sunpath.day(req.lat, req.lon, az, "2026-07-15", step_min=30)
    cls, recs = S.recommendations(summer, winter, req.area, plants)
    if req.greenery not in S.GREENERY:
        raise HTTPException(422, f"greenery must be among {list(S.GREENERY)}")
    water = req.water_available_l_day if req.water_available_l_day and req.water_available_l_day > 0 else None
    args = [(sid, req.area, plants, summer, winter, cls, water, az, req.lat, req.lon, req.rh, req.prices, req.greenery)
            for sid in ids]
    key = hashlib.sha256(json.dumps([a[:3] + a[5:] for a in args], sort_keys=True, default=str).encode()).hexdigest()
    hit = _STYLE_CACHE.get(key)
    if hit:
        out, mode = hit, "cache"
    else:
        out, mode = _run_styles(args), _STYLE_POOL["mode"]
        _STYLE_CACHE[key] = out
        while len(_STYLE_CACHE) > 12:
            _STYLE_CACHE.pop(next(iter(_STYLE_CACHE)))
    sun_light = {k: {x: v[x] for x in ("date", "sunrise", "sunset", "direct_hours", "daily_kwh_m2", "daily_direct_kwh_m2", "peak_w_m2")}
                 for k, v in (("summer", summer), ("winter", winter), ("design", design_day))}
    return jsonable({"exposure_class": cls, "recommendations": recs, "sun": sun_light,
                     "sun_times": {"summer": summer["times"], "winter": winter["times"]},
                     "designs": out, "seconds": round(time.perf_counter() - t, 2), "compute": mode,
                     "note": "Cultural style fixes the geometry; NSGA-II optimises the hidden channels and water for each "
                             "style under identical constraints. Model estimates, not measurements."})


class PreviewRequest(BaseModel):
    image_id: str
    area: dict
    design: dict                           # one entry of /studio/styles "designs"
    realistic: bool = True                 # photo-like render (CPU, about 1-2 s, no AI model)
    ai: bool = False                       # optional extra pass through SD 1.5 + ControlNet (GPU, slower)
    strength: float = 0.25
    seed: int = 42


@app.post("/studio/preview")
def studio_preview(req: PreviewRequest):
    """Before / after layers on the user's photo: segmented area, geometric design (perspective-correct, inside
    the selection only) and, optionally, the realistic preview (SD 1.5 + ControlNet conditioned on the geometry)."""
    from rootcode import stylerender, space, enhance
    from rootcode.facade import png_b64
    rec = _img(req.image_id)
    img = rec["img"]
    t = time.perf_counter()
    try:
        geo, cover, region = stylerender.install(img, req.design, req.area)
    except Exception as e:
        raise HTTPException(422, f"cannot place this design on the photo: {type(e).__name__}: {e}")
    out = {"segmented_overlay_png_base64": space.mask_png_b64(region, color=(168, 179, 155), alpha=140),
           "geometry_png_base64": png_b64(enhance.caption(geo, "Design visualization - not a photograph")),
           "realistic_png_base64": None, "realistic": False, "message": None}
    if req.realistic or req.ai:
        from rootcode import photoreal, styles as S
        t1 = time.perf_counter()
        kind = S.STYLES.get(req.design.get("style"), {}).get("motif")
        motif_fn = (lambda c: S.motif(kind, c, (c.get("row", 0) + c.get("col", 0)) % 2 == 1)) if kind else None
        try:
            real, cover, _ = photoreal.render(img, req.design, req.area, motif_fn=motif_fn)
        except Exception as e:
            raise HTTPException(422, f"cannot render this design on the photo: {type(e).__name__}: {e}")
        out.update(realistic=True, render="photo-like (CPU)", render_seconds=round(time.perf_counter() - t1, 2))
        if req.ai:
            prompt = stylerender.STYLE_PROMPT.format(name=req.design.get("name", "geometric"))
            st2 = enhance.enhance(real, cover, strength=min(max(req.strength, 0.1), 0.5), seed=req.seed, prompt=prompt,
                                  add_caption=False)
            if st2["enhanced"]:
                real = st2["image"].copy()
                real[region == 0] = img[region == 0]
                out.update(render="photo-like + AI pass (GPU)", render_seconds=st2["seconds"])
            else:
                out["message"] = f"AI pass unavailable ({st2['message']}); showing the photo-like render."
        out["realistic_png_base64"] = png_b64(enhance.caption(real, "Design visualization - not a photograph"))
    out["seconds"] = round(time.perf_counter() - t, 2)
    return jsonable(out)


@app.get("/installation/demo")
def installation_demo(style: str = "honeycomb"):
    """A demo installation for the digital twin when no design has been saved yet (clearly labelled)."""
    from rootcode import styles as S, sunpath
    if style not in S.STYLES:
        raise HTTPException(422, f"style must be among {list(S.STYLES)}")
    sun = sunpath.day(C.DEFAULT_LAT, C.DEFAULT_LON, 270.0, "2026-06-21", step_min=30)
    gen = S.generate(style, {"width_m": 1.5, "height_m": 1.2}, ["mint", "basil", "strawberry"], sun, 6.0,
                     sunpath.exposure_class(sun["daily_kwh_m2"]))
    gen["demo"] = True
    gen["context"] = {"lat": C.DEFAULT_LAT, "lon": C.DEFAULT_LON, "facade_azimuth": 270.0, "city": "Tunis"}
    return jsonable(gen)


# ---------------------------------------------------------------- water monitoring + sensors
class SensorReading(BaseModel):
    source: str = "simulated"              # arduino | simulated
    branch: Optional[int] = None           # which branch the level sensor sits in
    level_raw: Optional[float] = None      # potentiometer / sensor 0..1023
    level_frac: Optional[float] = None
    raw_min: float = 0
    raw_max: float = 1023
    temp_c: Optional[float] = None
    humidity: Optional[float] = None       # 0..1 or %


@app.post("/sensors")
def sensors_post(r: SensorReading):
    """From the Arduino bridge (arduino/sensor_bridge.py) or the dashboard's simulation slider."""
    from rootcode import water
    d = r.model_dump()
    if d.get("humidity") is not None and d["humidity"] > 1:
        d["humidity"] = d["humidity"] / 100
    return jsonable(water.put_reading(d))


@app.get("/sensors")
def sensors_get():
    from rootcode import water
    r, hist = water.get_reading()
    return jsonable({"reading": r, "history": hist})


@app.get("/sensors/device")
def sensors_device():
    """What the Arduino should display (LCD 16x2) and whether to sound the buzzer, from the last water status."""
    from rootcode import water
    st = LAST_WATER["statuses"]
    if not st:
        return {"code": "WAIT", "buzz": False, "line1": "INBETWEEN", "line2": "waiting for data"}
    return water.alert_for_device(st)


class WaterRequest(BaseModel):
    branches: List[dict]                   # installation "branches" [{id, capacity_l, need_l_day, plants}]
    levels: dict = {}                      # {branch_id: level_frac} estimated levels (no sensor)
    sensor_branch: Optional[int] = None    # branch that carries the level sensor
    lat: float = C.DEFAULT_LAT
    lon: float = C.DEFAULT_LON
    hours_to_refill: float = 48
    safety_margin: float = 0.2
    losses: float = 0.15
    collector_m2: float = 0.0
    weather: Optional[List[dict]] = None   # override forecast (offline demo)


@app.post("/water/status")
def water_status(req: WaterRequest):
    """Per-reservoir budget with a dynamic warning threshold (plants, sun, heat, losses, rain, refill plan)."""
    from rootcode import water
    wx_source, days = "Open-Meteo forecast", req.weather
    if days is None:
        try:
            days = water.forecast(req.lat, req.lon)
        except Exception as e:
            days, wx_source = None, f"forecast unavailable ({type(e).__name__})"
    else:
        wx_source = "provided by the client"
    reading, _ = water.get_reading()
    fresh = reading if (reading and not reading.get("stale")) else None
    if days is None:
        t = (fresh or {}).get("temp_c")
        rh = (fresh or {}).get("humidity")
        days = [{"date": None, "tmax_c": t if t is not None else 30.0, "rh": rh, "rain_mm": 0}] * 3
        wx_source += "; using the sensor temperature" if t is not None else "; assuming 30 °C (no data)"
    elif fresh and fresh.get("temp_c") is not None:
        days = [dict(days[0], tmax_c=max(days[0]["tmax_c"] or 0, fresh["temp_c"]))] + list(days[1:])
    sensor_branch = req.sensor_branch if req.sensor_branch is not None else (fresh or {}).get("branch")
    statuses = []
    for b in req.branches:
        bid = b.get("id")
        src, lv = "estimated", req.levels.get(str(bid), req.levels.get(bid, 0.6))
        if fresh and fresh.get("level_frac") is not None and sensor_branch == bid:
            src, lv = f"sensor ({fresh.get('source')})", fresh["level_frac"]
        statuses.append(water.branch_budget(b, lv, days, req.losses, req.safety_margin, req.hours_to_refill,
                                            req.collector_m2, level_source=src))
    LAST_WATER["statuses"] = statuses
    return jsonable({"branches": statuses, "weather": days, "weather_source": wx_source, "sensor": reading,
                     "device": water.alert_for_device(statuses),
                     "model": "Daily water balance: HydroEngine demand table x sun, heat and humidity factors, "
                              "losses and rain collection. The factors are stated assumptions, not measurements."})


# ================================================================ Leaf health (team DeepLabV3) + phone camera relay
# The model is loaded on the first analysis only (lazy), then cached; CUDA when available, CPU otherwise.
# Camera photos (camera page, phone back camera) are kept in MEMORY only: last 40, never written to disk.
_CAMERA = []                    # [{id, ts, cell, file_name, bytes, thumb}]
_CAMERA_MAX = 40
_CAMERA_KEY = os.getenv("ROOTCODE_CAMERA_KEY", "")   # optional shared token (?key=...) for the relay


def _thumb(data, side=360):
    import io
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    im.thumbnail((side, side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=78)
    return b.getvalue()


def _leaf_weather(lat, lon):
    """Forecast for the care advice (humidity, rain, heat). Optional: no location, no call."""
    if lat is None or lon is None:
        return None
    try:
        from rootcode import water
        return water.forecast(lat, lon)
    except Exception:
        return None


@app.post("/leaf/analyze")
async def leaf_analyze(file: UploadFile = File(...), plant: Optional[str] = Form(None), cell: Optional[int] = Form(None),
                       lat: Optional[float] = Form(None), lon: Optional[float] = Form(None)):
    """Upload a leaf photo -> lesion segmentation (team DeepLabV3), overlay, affected share, cautious advice."""
    from rootcode import leafhealth
    data = await file.read()
    if not data or len(data) > 15 * 2**20:
        raise HTTPException(413 if data else 422, "empty file or file too large (max 15 MB)")
    try:
        out = await run_in_threadpool(leafhealth.analyze, data, plant, _leaf_weather(lat, lon))
    except Exception as e:
        raise HTTPException(422, f"could not analyse this image: {type(e).__name__}: {e}"[:300])
    out["cell"] = cell
    return jsonable(out)


@app.get("/leaf/status")
def leaf_status():
    from rootcode import leafhealth
    return {**leafhealth.STATUS, "model_file": os.path.basename(leafhealth.MODEL_PATH),
            "model_present": os.path.isfile(leafhealth.MODEL_PATH)}


@app.post("/api/camera/photos")
async def camera_receive(photo: UploadFile = File(...), takenAtMs: Optional[str] = Form(None),
                         fileName: Optional[str] = Form(None), cell: Optional[str] = Form(None),
                         key: Optional[str] = Form(None)):
    """Receive route of the camera page (same contract as the camera branch: multipart field 'photo')."""
    if _CAMERA_KEY and key != _CAMERA_KEY:
        raise HTTPException(401, "wrong camera key")
    data = await photo.read()
    if not data or len(data) > 15 * 2**20:
        raise HTTPException(413 if data else 422, "empty file or file too large")
    try:
        thumb = await run_in_threadpool(_thumb, data)
    except Exception:
        raise HTTPException(422, "not a readable image")
    ts = int(takenAtMs) if (takenAtMs or "").isdigit() else int(time.time() * 1000)
    pid = f"{ts}-{len(_CAMERA)}"
    _CAMERA.append({"id": pid, "ts": ts, "cell": int(cell) if (cell or "").lstrip("-").isdigit() else None,
                    "file_name": fileName or "photo.jpg", "bytes": data, "thumb": thumb})
    del _CAMERA[:-_CAMERA_MAX]
    _camera_announce(_CAMERA[-1])
    return {"ok": True, "id": pid}


def _camera_item(p):
    """Gallery view of a stored photo (fields of the live plant gallery page)."""
    import datetime as _dt
    return {"id": p["id"], "url": f"/api/camera/photos/{p['id']}/image", "takenAtMs": p["ts"],
            "takenAt": _dt.datetime.fromtimestamp(p["ts"] / 1000, _dt.timezone.utc).isoformat(),
            "fileName": p["file_name"]}


_CAMERA_SUBS: list = []          # (loop, asyncio.Queue) of open /api/camera/stream connections


def _camera_announce(p):
    item = json.dumps(_camera_item(p))
    for loop, q in list(_CAMERA_SUBS):
        try:
            loop.call_soon_threadsafe(q.put_nowait, item)
        except Exception:
            pass


@app.get("/api/camera/photos/{pid}/image")
def camera_image(pid: str):
    from fastapi.responses import Response
    p = next((p for p in _CAMERA if p["id"] == pid), None)
    if not p:
        raise HTTPException(404, "photo not found (photos are kept in memory, last 40 only)")
    return Response(p["bytes"], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/camera/stream")
async def camera_stream(request: Request):
    """Server-sent events: one 'photo' event per new photo (live plant gallery)."""
    import asyncio
    from fastapi.responses import StreamingResponse
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    sub = (asyncio.get_running_loop(), q)
    _CAMERA_SUBS.append(sub)

    async def gen():
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    item = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: photo\ndata: {item}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            if sub in _CAMERA_SUBS:
                _CAMERA_SUBS.remove(sub)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/camera/photos")
def camera_list(cell: Optional[int] = None, limit: int = 12):
    import base64
    items = [p for p in reversed(_CAMERA) if cell is None or p["cell"] in (cell, None)][:max(1, min(limit, 40))]
    return [{"id": p["id"], "ts": p["ts"], "cell": p["cell"],
             "thumb_jpg_base64": base64.b64encode(p["thumb"]).decode(), **_camera_item(p)} for p in items]


@app.post("/api/camera/photos/{pid}/analyze")
async def camera_analyze(pid: str, plant: Optional[str] = Form(None), lat: Optional[float] = Form(None),
                         lon: Optional[float] = Form(None)):
    from rootcode import leafhealth
    p = next((p for p in _CAMERA if p["id"] == pid), None)
    if not p:
        raise HTTPException(404, "photo not found (photos are kept in memory, last 40 only)")
    out = await run_in_threadpool(leafhealth.analyze, p["bytes"], plant, _leaf_weather(lat, lon))
    out["cell"] = p["cell"]
    out["camera_photo"] = {"id": p["id"], "ts": p["ts"]}
    return jsonable(out)
