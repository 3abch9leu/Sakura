from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.routers import iot
from app.services import iot_store

PAYLOAD = {"device_id":"test-esp32", "temperature_c":28.5, "humidity_pct":65.0,
           "light_adc":500, "soil_moisture_pct":42.0, "water_level_low":False,
           "timestamp":datetime.now(timezone.utc).isoformat()}

@pytest.fixture(autouse=True)
def clear_store():
    with iot_store._lock:
        iot_store._history.clear()
        iot_store._actuators.update(fan_on=False, pump_on=False, buzzer_on=False,
            manual_override=False, emergency_stop=False, physical_actuation_enabled=False)

@pytest.mark.asyncio
async def test_sensor_endpoints_validate_and_store_history():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        bad = {**PAYLOAD, "humidity_pct": 101}
        assert (await c.post("/api/iot/sensors", json=bad)).status_code == 422
        assert (await c.post("/api/iot/sensors", json=PAYLOAD)).status_code == 200
        assert (await c.get("/api/iot/latest")).json()["device_id"] == "test-esp32"
        assert (await c.get("/api/iot/history")).json()["count"] == 1
        assert (await c.post("/api/iot/sensors", json={"device_id":"missing-fields"})).status_code == 422

def test_sample_esp32_json_payload_shape():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "sensor_payload.json").read_text())
    from app.routers.iot import SensorMeasurement
    parsed = SensorMeasurement.model_validate(fixture)
    assert parsed.device_id == "inbetween_esp32_01"
    assert parsed.light_adc == 500

@pytest.mark.asyncio
async def test_non_finite_readings_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/iot/sensors", json={**PAYLOAD, "temperature_c":float("nan")})).status_code == 422

@pytest.mark.asyncio
async def test_climate_recommendations_and_low_water_interlock(monkeypatch):
    async def fake_forecast():
        return {"forecast":[{"temperature_c":20, "humidity_pct":50, "rain_probability":0.1,
            "precipitation_mm":0, "cloud_cover_pct":10, "wind_speed_kmh":4}]}
    monkeypatch.setattr(iot, "forecast", fake_forecast)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        p = {**PAYLOAD, "temperature_c":30, "soil_moisture_pct":10, "water_level_low":True}
        await c.post("/api/iot/sensors", json=p)
        rec = (await c.get("/api/climate/recommendations")).json()
        by_action = {a["action"]: a for a in rec["actions"]}
        assert by_action["ventilation"]["recommendation"] == "open_or_run_fan"
        assert by_action["irrigation"]["recommendation"] == "blocked"

@pytest.mark.asyncio
async def test_manual_simulation_requires_override_and_protects_pump():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/iot/actuators/simulation", json={"pump_on":True})).status_code == 409
        await c.post("/api/iot/sensors", json={**PAYLOAD, "water_level_low":True})
        response = await c.post("/api/iot/actuators/simulation", json={"manual_override":True,"pump_on":True})
        assert response.json()["pump_on"] is False

@pytest.mark.asyncio
async def test_weather_endpoint_calls_pretrained_inference_integration(monkeypatch):
    async def fake_forecast(): return {"model":"DistilHweh-446k", "forecast_hours":12, "forecast":[]}
    monkeypatch.setattr(iot, "forecast", fake_forecast)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        result = await c.get("/api/weather/forecast")
        assert result.json()["model"] == "DistilHweh-446k"
