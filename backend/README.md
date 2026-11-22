# ROOTCODE — Intelligence in the design. Resilience in the material.

Team **YingYang** · Kizuna 2026 (Tunisia × Japan) · Esprit, Bloc A

Passive building tiles that shade an apartment window, feed edible plants by gravity and can
optionally cool by evaporation. **No pump, no sensor, no electricity once installed**, so they keep
working during power cuts. The AI is used once, at design time, to fit each tile to one window.

## Quick start

```bash
pip install -r requirements.txt
python run_demo.py                                   # west window, Tunis, 4 plants
python run_demo.py --facade S --rh 0.3 --plants mint chili basil
uvicorn api:app --reload --port 8000                 # API for the dashboard -> /docs
```

`run_demo.py` writes to `output/`: 3 Pareto designs + a conventional baseline, colour previews
(SVG), laser-cutting files, `pareto.png`, `comparison.png` and `report.json`.

## Modules

| Module | File | What it does |
|---|---|---|
| HydroEngine | `rootcode/hydro.py` | Gravity drain-down of the tank through laminar engraved channels (Hagen–Poiseuille, closed-form). Litres per pocket, drip time, Reynolds check |
| Solar Intelligence | `rootcode/solar.py` | pvlib sun position + clear-sky irradiance on the facade; profile-angle model of the perforated screen |
| Evaluation | `rootcode/evaluate.py` | Objectives per window: water (L/day), heat gain (kWh/day), plant deficit |
| ROOTOptimizer | `rootcode/optimizer.py` | NSGA-II (pymoo). Picks Water Saver / Shade Maximizer / Balanced from the real Pareto front |
| Fabrication | `rootcode/export.py` | Laser SVG layers (red = cut, blue = engrave), previews, plots |
| ROOTAgent | `rootcode/agent.py` | Tool-calling LLM; never invents numbers |
| FacadeVision | `rootcode/facade.py` | Tap the window → SAM 2 segmentation → 4 corners → perspective correction (Zhang–He) → real size → tile grid overlay |

Design variables: channel width per pocket, cooling-branch width (can close), daily water,
screen porosity, aperture size, number of stacked screen layers.
Constraints: daylight (effective porosity ≥ 20 %), household water budget, slow drip (≥ 15 min),
laminar flow (Re < 2000, keeps the model valid).

## FacadeVision setup (your RTX 4050)

```bash
# 1. PyTorch with CUDA: copy the exact command from pytorch.org (Windows, pip, your CUDA)
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install "transformers>=4.56" opencv-python pillow python-multipart
# 2. Check the GPU is seen
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 3. Photo -> dimensions + overlay (first run downloads the model weights, do it on good Wi-Fi tonight)
python -m rootcode.facade window.jpg --click 640 410 --width 1.2 --out facade_out.png
# 4. Photo -> full design + laser files in one command
python run_demo.py --photo window.jpg --click 640 410 --real-width 1.2 --facade W
```

Backends are tried in order: `sam2` → `sam` → `classic` (OpenCV, no deep learning). The JSON
says which one ran and why the others failed, so the demo never crashes on stage. Tips: tap the
glass, not the frame; add a second tap on the other pane for split windows. Pure side shots with an
unusual lens can misjudge height by ~10 cm (the tool warns you); `--height` overrides it.
Validated on synthetic pinhole-camera views up to 50° from the side: height error < 2 cm with a
standard phone lens, < 1 cm whenever the photo is tilted both ways (lens estimated from the window).

## ROOTAgent setup

The Claude Pro / ChatGPT Plus apps do not include API access. Use either:

```bash
# Groq free tier (default GROQ_MODEL=qwen/qwen3.8-27b; check console.groq.com for the current list)
export GROQ_API_KEY=...            # Windows: set GROQ_API_KEY=...
python -m rootcode.agent

# Offline on your RTX 4050 with Ollama
ollama pull qwen2.5:7b
export LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5:7b
python -m rootcode.agent
```

If several backends are available they are tried in order (LLM_BASE_URL, Groq, local Ollama): when Groq
is rate-limited (free tier: ~1000 output tokens/min, about one design reply per minute) or the Wi-Fi drops,
the same conversation continues on Ollama automatically.

## API endpoints (for the frontend)

Start: `uvicorn api:app --host 0.0.0.0 --port 8000` · interactive docs at `/docs` · every response has an
`X-Process-Time-ms` header. All responses are plain JSON (no numpy types). Check everything with
`python smoke_test.py --url http://localhost:8000` (prints PASS/FAIL per engine and endpoint).

| Endpoint | What | Typical time (RTX 4050) |
|---|---|---|
| `GET /health` | GPU, SAM 2 loaded?, LLM backends reachable, engines | ~0.1 s |
| `GET /plants` | plant names + daily water need (L/day) | < 10 ms |
| `GET /sun?facade=W&lat=36.81&lon=10.18&date=2026-07-15` | facade solar exposure, peak hour, 24 h profile (W/m2) | < 50 ms (cached) |
| `POST /evaluate` | score ONE given tile design: objectives, constraints, per-pocket litres | < 10 ms |
| `POST /design` | NSGA-II: 3 Pareto designs + baseline, Pareto front, SVG previews. `"fast": true` = 40 generations | 1.6 s fast · 4.5 s default (120 gen) |
| `POST /facade` (multipart) | photo + taps -> SAM 2 mask, real window size, tile grid overlay (base64 PNGs) | ~0.3-0.8 s (first call after start ~10 s if warm-up disabled) |
| `POST /chat` | ROOTAgent conversation; calls the engines, returns reply + last design | Groq ~8-13 s · Ollama ~50 s |
| `POST /tryon` (multipart) | Stage 1: optimized tiles painted on the photo (real geometry, no AI) | ~2 s (incl. fast optimizer) |
| `POST /render` (multipart) | Stage 2: SD 1.5 + ControlNet photoreal render of the try-on, pasted back only on the tiles | see "Try-on and AI render" |

Example bodies:
```json
POST /design    {"plants": ["mint","basil","strawberry","lettuce"], "facade": "W", "rh": 0.55,
                 "window_w": 1.2, "window_h": 1.4, "root_tiles": 4, "water_available_l_day": 6, "fast": true}
POST /evaluate  {"plants": ["mint","basil","strawberry","lettuce"], "facade": "W",
                 "design": {"widths_mm": [0.68,0.62,1.47,1.08], "cool_width_mm": 0, "water_l_day": 0.95,
                            "porosity": 0.26, "aperture_mm": 8.1, "layers": 3}}
POST /chat      {"messages": [{"role": "user", "content": "Design tiles for my west window in Tunis..."}]}
POST /facade    form-data: image=<file>, points="[[265,300],[375,300]]", real_width_m=1.0,
                [real_height_m], [root_tiles=4], [backend=auto|sam2|sam|classic], [return_mask=true]
```
Units: `objectives.water_l_day` = whole window per day; `design.water_l_day` = per root tile;
`plant_deficit` is a fraction (0.05 = 5 %); `heat_kwh_day` = heat through the whole window per day.
Invalid input (unknown plant, no feasible design, bad image) returns HTTP 422 with a readable `detail`.

## Try-on and AI render (Stage 1 + Stage 2)

* **Stage 1 – `rootcode/tryon.py`**: the real optimized geometry (star apertures, pockets, channels,
  same functions as the laser files) drawn on a rectified wall plane and warped onto the photo through
  the 4 corners. Root tiles = bottom row (next to the sill). Corners can be `quad_px` from `/facade`.
* **Stage 2 – `rootcode/enhance.py`**: Stable Diffusion 1.5 (`stable-diffusion-v1-5/stable-diffusion-v1-5`)
  + ControlNet Canny (`lllyasviel/control_v11p_sd15_canny`), img2img on the try-on with its own Canny
  edges as control, 25 steps, fixed seed, max side 768 px. fp16 + CPU offload + attention/VAE slicing
  (fits the 6 GB RTX 4050). The result is composited back **only inside the tile mask** (feathered), so
  the rest of the photo is untouched, and captioned "AI-enhanced visualization of the optimized design".
  If anything fails, the Stage 1 image comes back with `enhanced: false` and
  `message: "enhancement unavailable: <reason>"`.
* Weights (~2.9 GB) live in `../hf_cache` (D: drive), override with `ROOTCODE_HF_CACHE`.

```powershell
python prerender.py samples	est.jpg --corners 208 248 430 248 435 596 205 596 --width 1.0 --plants mint basil strawberry chili
# -> output
enders	ryon_<design>.png, render_<design>.png, before_after.png, renders.json
```
`/render` form fields = `/tryon` fields + `strength` (default 0.35; 0.45+ starts merging the star holes) + `seed` (default 42).

## Energy & Comfort Companion (STEG bills)

Website page `/energy`: upload a STEG bill → review/correct the fields → verification against the official
tariff → explanation in French / Arabic / Darija → appliance scenarios → passive-shading comparison → questions.

| Module | File | What it does |
|---|---|---|
| BillReader | `rootcode/bill_reader.py` | PDF text layer (pdfplumber) or OCR with **RapidOCR = PaddleOCR PP-OCR models on onnxruntime** (French model + Arabic PP-OCRv5 mobile). French/Arabic labels → fields, number normalisation (decimal comma, millimes, Eastern Arabic digits), index cross-check, `found / uncertain / missing` per field. Personal data (name, address, customer/meter numbers) is detected and dropped. Nothing stored. Optional Qwen2-VL-2B fallback (`ROOTCODE_BILL_VLM=1`, only if weights are already cached) |
| Tariff | `rootcode/tariff.py` + `data/steg_tariff.json` | Deterministic `Decimal` calculation of the electricity part: band price, power fee, VAT, municipal surtax, FTE. Compares line by line with the bill → `match / partial / mismatch / unavailable`; tests documented alternatives (2022 PDF taxes, band-by-band, 1 vs 2 months) to explain a mismatch |
| Advisor | `rootcode/energy_advisor.py` + `data/energy_kb.json` | Consumption understanding, appliance kWh = W × h × days / 1000 priced with the tariff, ANME 26 °C rule (labelled), SolarEngine + optimizer shading comparison, keyword retrieval over official STEG/ANME snippets, template explanations in fr/ar/darija/en |
| Agent | `rootcode/agent.py` → `bill_chat()` | Same LLM backends as ROOTAgent, bill-specific tools (`compute_bill`, `appliance_energy`, `search_official_docs`, `sun_on_facade`); never does money arithmetic itself |

Endpoints: `POST /bill/read` (multipart `file`), `POST /bill/verify`, `POST /bill/explain`, `POST /bill/advice`,
`POST /bill/ask` (bodies in `/docs`). Without an LLM, `/bill/explain` returns the deterministic template and
`/bill/ask` returns the bill's verified facts plus the matching official snippets (`mode: "retrieval"`).

```bash
pip install rapidocr python-bidi          # if pip tries to upgrade opencv while the API runs: add --no-deps
python samples/make_specimen_bill.py      # synthetic test bill (fake data) -> samples/bill_specimen.png/.pdf
python bill_smoke_test.py --url http://127.0.0.1:8000   # 15 real HTTP checks
```

**Tariff sources** (checked 2026-11-21): [STEG tariff page](https://www.steg.com.tn/fr/page/les-tarifs-d%C3%A9lectricit%C3%A9),
[STEG BT tariff PDF, 1 May 2022](https://www.steg.com.tn/system/files/pdf/tarifsbt_fr.pdf) (copy in `data/sources/`),
[STEG — Comprendre votre facture](https://www.steg.com.tn/fr/page/comprendre-votre-facture?menu=particulier).
Honest limits: the PDF and the web page disagree on FTE (1 vs 5 mill/kWh) and VAT (13 % vs 7 %/13 %): the web page
is used and the PDF values are tested as a mismatch cause. "Selective" band pricing is our reading of the official
table layout. How STEG splits a 2-month bill into monthly bands is not published (we divide by the months).
RTT contribution, gas and arrears are not verified. The bill reader was tested on a **synthetic** bill only:
test it on real STEG bills (photo and PDF) before the demo and extend the label lists in `bill_reader.py` if needed.
Shading results are solar heat at the window, **not** electricity: "Electricity savings have not yet been measured or validated."

## Studio and digital twin (connected workflow)

One flow, each step feeding the next: **photo → selected space → sunlight → plants and culture → optimized designs
→ preview on the photo → 3D digital twin → water monitoring**. Frontend routes: `/studio` and `/dashboard`.

| Step | Module | What it does |
|---|---|---|
| Space | `rootcode/space.py` | SAM 2 suggestions (surfaces, openings), include / exclude clicks, rectangle or polygon fallback, obstacles (holes = windows / doors), one reference measurement -> metres (perspective-corrected), usable area minus obstacles (5 cm clearance). |
| Sun | `rootcode/sunpath.py` | pvlib clear-sky sun path on the confirmed orientation, sunrise to sunset, summer / winter. EXIF GPS and compass are offered but must be confirmed. |
| Designs | `rootcode/styles.py` | 8 cultural geometries (mashrabiya, Arabic stars, asanoha, sakura, seigaiha, organic branching, honeycomb, hybrid). Some cells become planting cells with an integrated lower water compartment, the others keep the motif as openings. Hidden channels follow the frame members from a top supply tube (never across a window). Planting count is limited by the water budget and the sun class; sun-loving plants go to the most exposed cells (self-shading model). Each style is evaluated with the same context; NSGA-II optimizes the hydraulic variables with the style's screen geometry fixed. |
| Preview | `rootcode/stylerender.py` | Perspective-correct composite of the geometry ONLY inside the selected area; optional realistic version with the existing SD 1.5 + ControlNet, conditioned on that geometry. Labelled as a design visualization. |
| Water | `rootcode/water.py` | Daily water balance per branch reservoir; the warning threshold is dynamic (plants, sun, forecast heat and humidity, losses, rain collection, time to the next refill, safety margin). Open-Meteo forecast (rounded coordinates only), fallback to the sensor temperature. |
| Sensors | `arduino/` | `inbetween_monitor.ino` (potentiometer = simulated level, DHT11, LCD 16x2, buzzer) and `sensor_bridge.py` (serial <-> API; `--simulate` without hardware). |

Endpoints: `POST /space/upload`, `POST /space/segment`, `POST /space/area`, `GET /solar/day`, `POST /studio/styles`,
`POST /studio/preview`, `GET /installation/demo`, `POST /water/status`, `POST|GET /sensors`, `GET /sensors/device`.
Photos stay in server memory for 30 minutes and are never written to disk.

    python studio_smoke_test.py --url http://127.0.0.1:8000 [--realistic]

Honest limits: a photo cannot tell whether a wall can carry the load (about 25-40 kg/m² wet) - the user must check;
surrounding buildings and trees are not modelled in the sun (clear-sky upper bound); the water factors (heat, humidity,
losses) are stated assumptions; levels without a sensor are estimated from consumption since the last refill;
the potentiometer is a simulated level sensor and is labelled as such everywhere.

## Leaf health (team DeepLabV3 model) and plant camera

`rootcode/leafhealth.py` serves the team's own `rootcode/models/deeplabv3_model.pth`, rebuilt exactly as in
`combine-model.ipynb` ("DeepLabV3+ v2"): torchvision `deeplabv3_resnet50`, `classifier[4]` and `aux_classifier[4]`
replaced by 2-class convolutions, input `Resize(256, 256) -> ToTensor -> Normalize(ImageNet)`, class 1 = diseased tissue.
No download (`weights=None`, `load_state_dict(strict=True)`), lazy loading on the first request, one cached instance,
CUDA when available (`ROOTCODE_LEAF_DEVICE=cpu` forces CPU). Measured on the RTX 4050: load 1.4 s, about 25-40 ms per
image (about 0.4 s on CPU), 207 MB VRAM; SAM 2 and the bill OCR keep their latency while it runs.

- `POST /leaf/analyze` (multipart `file`, optional `plant`, `cell`): overlay, affected share of the visible leaf,
  number of areas, warnings and cautious care advice. Detected areas not lying on a leaf (pot, soil, background) are
  ignored and reported. The model does not name the disease; the leaf area comes from a colour rule.
- `/camera?cell=12`: the phone camera page from the `camera` branch, restyled. A photo every 2 minutes (or on demand) is
  posted to `POST /api/camera/photos` (same contract: field `photo`, plus `cell`). The digital twin lists the latest
  photos of the selected cell and analyses them on demand. Photos stay in server memory (last 40), never on disk.
  Phones only open the camera on https: serve the site through a tunnel or https host for the phone.

    python leaf_smoke_test.py --url http://127.0.0.1:8000 leaf1.jpg leaf2.jpg

## Speed (GPU first, everything local)

Measured on the RTX 4050 laptop, on battery, after the server warm-up:

| Step | Before | Now | How |
|---|---|---|---|
| Bill reading | 9 s (22 s first) | 0.6-1.9 s | PP-OCRv6 detector + recogniser run by PyTorch on CUDA (same models, same text); CPU fallback |
| Realistic preview (SD 1.5 + ControlNet) | 16-20 s (64 s first) | ~7 s | whole pipeline on the GPU when VRAM allows, loaded at server start, 20 UniPC steps |
| Surface suggestions | 25 s first | ~2 s | SAM 2 loaded at server start |

The server checks itself: if the GPU is short of memory (another program holds it), the SD pipeline switches to CPU
offload instead of silently spilling into shared memory, and the OCR falls back to the CPU.
Settings: `ROOTCODE_OCR_GPU=0` (CPU OCR), `ROOTCODE_SD_OFFLOAD=1` (force offload), `ROOTCODE_WARMUP_SD=0` (no SD preload).
Plug the laptop in: on battery Windows caps the CPU and the GPU and every step is 2-5x slower.
Run ONE API process: two servers on the same 6 GB GPU make both slow.

## Fabrication (laser cutter)

Per root tile, from `output/laser/<design>/`:
1. `_1_back.svg` — cut once (3 mm acrylic or plywood)
2. `_2_channels_ENGRAVE.svg` — **engrave** the blue shapes ~0.6 mm deep, cut the red holes.
   Test engrave depth on a scrap first and measure it; update `CHANNEL_DEPTH` in `config.py`.
3. `_3_front_xN.svg` — cut N times and stack (N = screen layers chosen by the optimizer)
4. `_4_shade_tile_xN.svg` — screen for shade-only tiles

Seal the back plate to the channel plate (clear silicone or acrylic cement). Feed the manifold from a
bottle above the tile. Put a short cotton wick from each outlet hole into its plant pocket.
**Clear acrylic for the channel layer** lets the jury see the water branch.

## The experiment that proves it (do this first)

Same tank, same water volume, two tiles: `baseline` vs `balanced`.
1. Pour the design volume into the tank.
2. Collect each outlet in a cup; weigh each cup (kitchen scale, 1 g = 1 mL).
3. Compare measured vs predicted litres per pocket (`report.json`).
4. Fit calibration: `k_i = measured_i / predicted_i`, pass it as `Context(calibration={"pocket_0": k0, ...})`
   and rerun. Showing that calibration closes the gap is a strong slide.

Optional: two thermometers behind the baseline and optimized screens under the same lamp.

## Assumptions to state honestly

All marked `ASSUMPTION` in `rootcode/config.py`: plant water needs, window SHGC, evaporation rate,
cooling coupling. Clear-sky irradiance is a worst-case hot day. mm-scale channels can trap air and
lose energy at bends, which is why calibration exists. Use clean water: greywater needs treatment
before use on edible plants.

## Pitch numbers (default run: west window 1.2 × 1.4 m, Tunis, RH 55 %, 4 root tiles)

Re-run before the pitch and copy the exact numbers from your own `report.json`.
With the same daily water, the balanced design brings the plant deficit from ~29 % to ~0 %,
evens out distribution (CV 0.52 → ~0.02) and cuts heat through the window by ~85 % instead of ~56 %.
These are model estimates until your experiment confirms them.
