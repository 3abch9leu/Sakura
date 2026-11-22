# 💧 ROOTCODE · Water Monitoring Automatic Analyzer

> **Instant, zero-click water quality analyzer for irrigation and agricultural screening.**  
> Preloaded with multi-source telemetry, automated temperature compensation, FAO 29 / WHO threshold rules, and modular integration files for team development.

Part of the **Sakura** platform (Kizuna 2026 Hackathon) — tackling **Water, Energy & Agriculture** with smart tech.

---

## 🎯 Key Features & Capabilities

1. **Preloaded Live Telemetry by Default (Never a Blank Page)**
   - Initialized with realistic time-series readings for all **4 water sources** over the past 24 hours.
   - Immediate live verdicts, populated sensor cards, historical time-series charts, and precalculated tank water budgets.
   - Includes passing microbiology verification and sensor calibration records.
   - One-click `[ 🔄 Reset Demo Data ]` button to restore the sample dataset at any time.

2. **Live Sensor Stream Simulation (`[ ⚡ Live Stream ]`)**
   - Toggleable live telemetry stream generator that ticks every 3 seconds.
   - Simulates continuous IoT sensor telemetry with subtle, realistic physical fluctuations.
   - Dynamically updates charts, cards, verdicts, and budget calculations in real time.

3. **Zero-Click Instant Analysis**
   - Analysis executes in real-time as data is typed, streamed, or uploaded.
   - No calibration forms or verification gates required to obtain a verdict.

4. **Automated Conversion & Compensation**
   - **EC compensated to 25 °C**: $EC_{25} = \frac{EC_{measured}}{1 + 0.02 \times (T - 25)}$.
   - If water temperature is missing, raw EC is displayed with an explicit warning note.

5. **Built-in Agronomic & Health Thresholds**
   - Benchmarked against **FAO Irrigation and Drainage Paper 29** and **WHO guidelines**.
   - Parameters: pH, Turbidity, Electrical Conductivity (EC @ 25 °C), Temperature, Tank Level, and ORP (informational).
   - Fully customizable in an optional collapsible **Advanced Thresholds** panel.

6. **Rigorous Verdict Engine (Worst Parameter Decides)**
   - ✅ **CLEAN**: All judged parameters within safe thresholds.
   - ⚠️ **ACCEPTABLE WITH CAUTION**: No hazardous parameters, but at least one warning flag.
   - ❌ **NOT CLEAN**: Any parameter in the hazardous range, failing microbiological test, or source is Greywater.
   - ❔ **CANNOT DECIDE**: Missing required parameters (pH, turbidity, EC, temperature) — explicitly enumerates what is missing. Never assumes missing data is safe.
   - **Greywater Rule**: Always strictly classified as **❌ NOT CLEAN** for edible crops per FAO/WHO standards.
   - **Simulated Data Protection**: Data tagged `SIMULATED` can **never** produce a `CLEAN` verdict.

7. **Sensors Plausibility Guards**
   - Rejects physically impossible values (e.g., pH outside 0–14, negative turbidity/EC, tank level outside 0–100%).

8. **Scientific Honesty & Confidence Badging**
   - Explicit disclaimer: *"Based on sensor readings only. Sensors cannot detect bacteria, so this is a screening result for plant irrigation, not a drinking-water certificate."*
   - Confidence Badge:
     - 🟢 **HIGH**: Passing microbiological lab/kit record logged.
     - 🟡 **MEDIUM**: Sensor and manual measurements only.
     - 🔴 **LOW**: Calibration unverified or missing data.

9. **5 Built-in Interactive Test Cases**
   - **All Clean**: pH 7.2, Turbidity 2.0 NTU, EC 450 µS/cm, Temp 22 °C → `CLEAN`
   - **One Warning**: pH 7.0, Turbidity 8.0 NTU, EC 400 µS/cm, Temp 20 °C → `ACCEPTABLE WITH CAUTION`
   - **Bad Value**: pH 7.0, Turbidity 32.0 NTU, EC 400 µS/cm, Temp 20 °C → `NOT CLEAN`
   - **Missing Data**: pH 7.0 only → `CANNOT DECIDE` (lists missing parameters)
   - **Greywater**: Any inputs → `NOT CLEAN` (crop irrigation prohibited)

10. **Multilingual & Completely Offline**
    - Supports **English**, **Français**, and **العربية** (with native RTL layout).
    - Single-file zero-dependency web app (`index.html`) using HTML5, CSS3, and Vanilla JavaScript.
    - Works fully offline with LocalStorage persistence.

---

## 🔌 Integration Guide for Teammates (Merge & Import)

To make it seamless for team members across different stacks to import and integrate this water analyzer:

| Module File | Target Consumer | Purpose |
| :--- | :--- | :--- |
| **`water-analyzer.ts`** | Angular Frontend (`front` branch) | Strongly-typed TypeScript interfaces, service, and verdict engine. |
| **`water_engine.py`** | Python AI / Backend (`weather_prediction`) | Python module for AI predictions, pipeline evaluations, and data models. |
| **`water-data.json`** | REST / Mock API / Full Stack | Structured JSON containing thresholds, preloaded sources, logs, and test cases. |
| **`water-analyzer.js`** | Node.js / Universal Web | Universal UMD/ES6 module usable with `require` or `<script>`. |
| **`index.html`** | Standalone Dashboard | Self-contained web app exposing `window.WaterAnalyzer` globally. |

### 1. Angular / TypeScript Example
```typescript
import { WaterAnalyzer, WaterReading, VerdictResult } from './water-analyzer';

const reading: WaterReading = {
  source: 'clean',
  ph: 7.20,
  turbidity_ntu: 1.8,
  ec_us_cm: 420,
  temp_c: 21.5,
  level_pct: 84
};

const verdict: VerdictResult = WaterAnalyzer.computeVerdict(reading);
console.log(verdict.label);  // 'CLEAN'
console.log(verdict.action); // 'SAFE to use for plant irrigation'
```

### 2. Python AI Backend Example
```python
from water_engine import evaluate_reading, PRELOADED_WATER_DATA

reading = PRELOADED_WATER_DATA["clean"]
result = evaluate_reading(reading)
print(result["verdict"])  # 'ok'
print(result["label"])    # 'CLEAN'
print(result["action"])   # 'SAFE to use for plant irrigation'
```

### 3. Fetching Raw Data
```javascript
const res = await fetch('./water-data.json');
const { thresholds, latest_readings } = await res.json();
```

---

## 📊 Default Threshold Reference

| Parameter | Unit | Clean | Warning | Hazardous / Bad | Reference Standard |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **pH** | — | 6.5 – 8.4 | 6.0 – 6.5 or 8.4 – 9.0 | < 6.0 or > 9.0 | FAO 29 |
| **Turbidity** | NTU | ≤ 5.0 | 5.0 – 25.0 | > 25.0 | WHO guidelines |
| **EC (at 25 °C)** | µS/cm | ≤ 700 | 700 – 3,000 | > 3,000 | FAO 29 |
| **Water Temp** | °C | 10 – 30 | 5 – 10 or 30 – 35 | < 5 or > 35 | Agronomic range |
| **Tank Level** | % | ≥ 20 % | 10 % – 20 % | < 10 % | Supply heuristic (separate from quality) |
| **ORP** | mV | — | — | — | Informational proxy only (excluded from verdict) |

---

## 🚀 How to Run

### Option 1: Direct File Open
Double click `index.html` to open it in any modern browser (Chrome, Firefox, Safari, Edge).

### Option 2: Local HTTP Server
Run from this directory:
```bash
python -m http.server 8765
```
Then navigate to `http://localhost:8765/index.html`.

---

## 📁 File Structure

```
.
├── index.html                  # Full application: UI, live analysis engine, charts & local storage
├── WATER_MONITORING.md         # Detailed technical and user documentation
├── water-analyzer.ts           # Angular / TypeScript Service & Interfaces for team import
├── water-analyzer.js           # Universal JavaScript module (Node.js & browser)
├── water_engine.py             # Python module for AI backend / data pipeline
├── water-data.json             # Structured JSON dataset for REST / API integration
└── samples/
    ├── rootcode-sample-data.csv    # Sample dataset with multiple sources
    └── rootcode-template.csv       # Standardized CSV header template for bulk import
```
