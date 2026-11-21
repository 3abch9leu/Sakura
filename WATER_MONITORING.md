# 💧 ROOTCODE · Water Monitoring Automatic Analyzer

> **Instant, zero-click water quality analyzer for irrigation and agricultural screening.**  
> Enter data once or import CSV, and the system automatically validates, temperature-compensates, and judges water fitness with zero manual steps.

Part of the **Sakura** platform (Kizuna 2026 Hackathon) — tackling **Water, Energy & Agriculture** with smart tech.

---

## 🎯 Key Capabilities

1. **Zero-Click Instant Analysis**
   - Analysis executes in real-time as data is typed or loaded.
   - No calibration forms or verification gates required to obtain a verdict.

2. **Automated Conversion & Compensation**
   - **EC compensated to 25 °C**: $EC_{25} = \frac{EC_{measured}}{1 + 0.02 \times (T - 25)}$.
   - If water temperature is missing, raw EC is displayed with an explicit warning note.

3. **Built-in Agronomic & Health Thresholds**
   - Benchmarked against **FAO Irrigation and Drainage Paper 29** and **WHO guidelines**.
   - Parameters: pH, Turbidity, Electrical Conductivity (EC @ 25 °C), Temperature, Tank Level, and ORP (informational).
   - Fully customizable in an optional collapsible **Advanced Thresholds** panel.

4. **Rigorous Verdict Engine (Worst Parameter Decides)**
   - ✅ **CLEAN**: All judged parameters within safe thresholds.
   - ⚠️ **ACCEPTABLE WITH CAUTION**: No hazardous parameters, but at least one warning flag.
   - ❌ **NOT CLEAN**: Any parameter in the hazardous range, failing microbiological test, or source is Greywater.
   - ❔ **CANNOT DECIDE**: Missing required parameters (pH, turbidity, EC, temperature) — explicitly enumerates what is missing. Never assumes missing data is safe.
   - **Greywater Rule**: Always strictly classified as **❌ NOT CLEAN** for edible crops per FAO/WHO standards.
   - **Simulated Data Protection**: Data tagged `SIMULATED` can **never** produce a `CLEAN` verdict.

5. **Sensors Plausibility Guards**
   - Rejects physically impossible values (e.g., pH outside 0–14, negative turbidity/EC, tank level outside 0–100%).

6. **Scientific Honesty & Confidence Badging**
   - Explicit disclaimer: *"Based on sensor readings only. Sensors cannot detect bacteria, so this is a screening result for plant irrigation, not a drinking-water certificate."*
   - Confidence Badge:
     - 🟢 **HIGH**: Passing microbiological lab/kit record logged.
     - 🟡 **MEDIUM**: Sensor and manual measurements only.
     - 🔴 **LOW**: Calibration unverified or missing data.

7. **5 Built-in Interactive Test Cases**
   - **All Clean**: pH 7.2, Turbidity 2.0 NTU, EC 450 µS/cm, Temp 22 °C → `CLEAN`
   - **One Warning**: pH 7.0, Turbidity 8.0 NTU, EC 400 µS/cm, Temp 20 °C → `ACCEPTABLE WITH CAUTION`
   - **Bad Value**: pH 7.0, Turbidity 32.0 NTU, EC 400 µS/cm, Temp 20 °C → `NOT CLEAN`
   - **Missing Data**: pH 7.0 only → `CANNOT DECIDE` (lists missing parameters)
   - **Greywater**: Any inputs → `NOT CLEAN` (crop irrigation prohibited)

8. **Multilingual & Completely Offline**
   - Supports **English**, **Français**, and **العربية** (with native RTL layout).
   - Single-file zero-dependency web app (`index.html`) using HTML5, CSS3, and Vanilla JavaScript.
   - Works fully offline with LocalStorage persistence.

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

No build step, Node.js, or external library is needed.

### Option 1: Direct File Open
Double click `index.html` to open it in any modern browser (Chrome, Firefox, Safari, Edge).

### Option 2: Local HTTP Server
Run from this directory:
```bash
python -m http.server 8000
```
Then navigate to `http://localhost:8000/index.html`.

---

## 📁 File Structure

```
.
├── index.html                  # Full application: UI, live analysis engine, charts & local storage
├── WATER_MONITORING.md         # Detailed technical and user documentation
└── samples/
    ├── rootcode-sample-data.csv    # Sample dataset with multiple sources
    └── rootcode-template.csv       # Standardized CSV header template for bulk import
```
