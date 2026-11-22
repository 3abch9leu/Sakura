# INBETWEEN ESP32 greenhouse guide

INBETWEEN extends the existing ROOTCODE weather application. The existing DistilHweh-446k inference code and model files are left untouched. Sensor API and rules are separate modules; outdoor forecasts are obtained from the existing `predict_tunis()` function.

## Architecture

```text
ESP32 + DHT22/LDR/potentiometer/float simulation
        | HTTP JSON POST /api/iot/sensors
        v
FastAPI (Pydantic validation, in-memory latest + bounded history)
        |                          |
        | /api/climate/recommendations <- DistilHweh forecast
        v
Streamlit dashboard (measurements, AI forecast, recommendations, simulation status)
```

The backend stores at most 1,000 readings in process memory. Restarting it clears history. Use a database and authentication/TLS termination before production exposure. The actuator API is a backend simulation only and does not send commands to ESP32. Firmware local indicator logic is likewise a demonstration; physical actuation is not enabled by this project.

## Parts and GPIO

Use ESP32 DevKit V1, DHT22, photoresistor module, potentiometer (soil proxy), pushbutton (reservoir proxy), 16x2 I2C LCD, buzzer, two LEDs and two 220-ohm resistors. All grounds share GND. Keep ESP32 GPIO signals at 3.3 V; never feed 5 V into a GPIO. In the Wokwi diagram the LCD module supply is 5 V and its I2C pins connect directly for simulation. For a physical unit, power/use an I2C level shifter or a 3.3 V compatible LCD backpack and confirm SDA/SCL pull-ups do not rise above 3.3 V.

| Component | GPIO |
|---|---:|
| DHT22 DATA | 4 |
| LDR AO | 34 |
| Soil potentiometer SIG | 35 |
| Float simulation button | 27 |
| LCD SDA / SCL | 21 / 22 |
| Buzzer | 25 |
| Fan LED | 18 |
| Pump LED | 19 |

Wokwi uses an LDR module AO reading, not calibrated lux. The soil potentiometer is a percentage proxy whose dry/wet ADC endpoints need calibration for a real probe. The reservoir button uses `INPUT_PULLUP`: released/open or disconnected reads reservoir LOW (safe); press it to ground GPIO27 to represent water available. Thus a missing switch wire fails closed.

## Wokwi

1. Open [Wokwi ESP32 simulator](https://wokwi.com/projects/new/esp32).
2. Import the contents of `firmware/inbetween` (`diagram.json`, `sketch.ino`, `libraries.txt`) into a new ESP32 project.
3. Copy `config.example.h` to `config.h`, then set `SERVER_URL`. The ignored `config.h` is intentionally excluded from Git.
4. For local sensor-only simulation, leave endpoint as a placeholder; JSON measurements and local indicators still appear in Serial/LCD. Change DHT22 values through its component UI; adjust LDR and potentiometer controls; click the water button to represent water available.
5. Wokwi's **Public Gateway** does not route to the computer's localhost. For it, expose port 8000 through a publicly reachable HTTPS tunnel (or deploy the API to a reachable HTTPS host), set that HTTPS base URL, and configure trusted TLS CA validation. Alternatively, Wokwi's **Private IoT Gateway** supports local-network access (the firmware can target `http://host.wokwi.internal:8000`); it requires the separate gateway application and supported Wokwi plan/setup. Never assume ordinary `localhost` works from the Public Gateway. Do not set `TLS_INSECURE_FOR_DEVELOPMENT` true for anything beyond a disposable test.

Firmware reconnects Wi-Fi, samples every 5 seconds, and posts every 15 seconds with an HTTP timeout. Wi-Fi simulation credentials default to Wokwi's documented guest network; configure real credentials for a physical ESP32. NTP is used for timestamps. If time sync is not yet available, the firmware sends the epoch sentinel; the backend safely reports sensors offline for climate recommendations until a current timestamp arrives. JSON is emitted to Serial as diagnostics and sent over HTTP; Serial diagnostics also report local output states.

## Backend API

- `POST /api/iot/sensors`: validated payload (`device_id`, temperature C, humidity %, light ADC 0–4095, soil %, water-low boolean, ISO timestamp).
- `GET /api/iot/latest`: latest reading (404 before first POST).
- `GET /api/iot/history?limit=100`: recent readings (limit 1–1000).
- `GET /api/weather/forecast`: runs pretrained 12-hour Tunis forecast.
- `GET /api/climate/recommendations`: fresh sensor reading plus AI forecast and transparent rules.
- `GET /api/iot/actuators`: current backend simulation outputs.
- `POST /api/iot/actuators/simulation`: boolean simulation state; requires manual override. Pump is forced off unless a latest reading says reservoir available. Emergency stop forces all outputs off.

Interactive OpenAPI docs are at `/docs`. Example payload is `tests/fixtures/sensor_payload.json`. API latest/history are real sensor reports; backend actuator fields are only simulated; AI values are predictions; climate results are rule-based recommendations and are not commands.

## Climate rules and limits

Thresholds live in `app/services/climate_engine.py` as `ClimateConfig`; defaults are demonstration configuration, not crop science guidance. Ventilation is suggested only when forecast outdoor temperature is at least the configured margin cooler and outdoor humidity is acceptable. Irrigation checks configured soil percentage, reservoir, and rain probability. Evaporative cooling uses the Stull 2011 wet-bulb approximation and screens wet-bulb depression/humidity; this is an indicative estimate, not a psychrometric control model. Shading combines light ADC and indoor temperature thresholds. Wind speed and cloud cover are included in forecast summaries for human interpretation; thresholds should be set for crop, greenhouse geometry, and local calibration.

The recommendation endpoint rejects stale readings (>5 minutes) for decision use. Missing sensor data yields a waiting/offline state and no recommendations. The model is not a verified station forecast and recommendations should be reviewed by an operator.

## Physical safety

GPIO 18/19 represent LEDs only. Never drive a fan, pump, relay coil, or motor directly from an ESP32 pin. For actual loads, use correctly rated MOSFET/relay driver circuits, flyback protection where appropriate, separate load supplies, common reference where required, fusing, enclosure, and an independent emergency stop. Preserve a reservoir-low hardware interlock in series with pump control. Firmware sets outputs off during reset and blocks its local demo pump when water is low. API simulation has a manual override and emergency stop; it does not provide a production physical-control channel. Do not enable physical actuation without independent safeguards and crop-specific commissioning.

## Run the full application (PowerShell)

From the project directory, activate the environment that contains the model stack, then install the listed dependencies:

```powershell
..venv-aiScriptsActivate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In a second PowerShell window:

```powershell
..venv-aiScriptsActivate.ps1
python -m streamlit run app/dashboard.py
```

The dashboard expects the API at `http://127.0.0.1:8000`; launch both processes locally. The existing weather/backtesting tabs remain available. Install requirements first in a Python environment compatible with the project's PyTorch/model stack. Tests: `python -m pytest -q`.
