from datetime import datetime, timezone
from typing import Any
import asyncio
import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from app.services import iot_store
from app.services.climate_engine import recommend

router = APIRouter(prefix="/api")

class SensorMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=80)
    temperature_c: float = Field(ge=-40, le=80, allow_inf_nan=False)
    humidity_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    light_adc: int = Field(ge=0, le=4095)
    soil_moisture_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    water_level_low: bool
    timestamp: datetime

@router.post("/iot/sensors")
async def receive_sensor(measurement: SensorMeasurement):
    item = measurement.model_dump(mode="json")
    item["received_at"] = datetime.now(timezone.utc).isoformat()
    iot_store.add_measurement(item)
    return {"success": True, "device_id": item["device_id"], "stored": True, "received_at": item["received_at"]}

@router.get("/iot/latest")
async def latest():
    item = iot_store.latest_measurement()
    if item is None:
        raise HTTPException(404, "No sensor measurement received yet")
    return item

@router.get("/iot/history")
async def history(limit: int = Query(100, ge=1, le=1000)):
    return {"measurements": iot_store.measurement_history(limit), "count": len(iot_store.measurement_history(limit))}

async def forecast():
    try:
        from app.services.weather_inference import predict_tunis
        return await predict_tunis()
    except Exception as exc:
        raise HTTPException(502, f"Weather forecast unavailable: {exc}") from exc

@router.get("/weather/forecast")
async def weather_forecast():
    return await forecast()

@router.get("/climate/recommendations")
async def climate_recommendations():
    measurement = iot_store.latest_measurement()
    if measurement:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(measurement["timestamp"].replace("Z", "+00:00"))).total_seconds()
        except (ValueError, TypeError):
            age = 1e9
        if age < -60 or age > 300:
            measurement = None
    forecast_error = None
    try:
        f = await forecast()
    except HTTPException as exc:
        f = None
        forecast_error = exc.detail
    result = recommend(measurement, f)
    if forecast_error:
        result["status"] = "forecast_unavailable"
        result["forecast_error"] = forecast_error
    return result

@router.get("/iot/actuators")
async def get_actuators():
    return iot_store.actuator_state()

@router.post("/iot/actuators/simulation")
async def simulation_actuators(payload: dict[str, Any]):
    allowed = {"fan_on", "pump_on", "buzzer_on", "manual_override", "emergency_stop"}
    if not payload or set(payload) - allowed or any(type(v) is not bool for v in payload.values()):
        raise HTTPException(422, "Provide boolean simulated actuator fields only")
    if payload.get("manual_override") is False:
        return iot_store.set_actuators(manual_override=False, fan_on=False, pump_on=False, buzzer_on=False, emergency_stop=False)
    if not payload.get("manual_override", iot_store.actuator_state()["manual_override"]):
        raise HTTPException(409, "Enable manual_override before changing simulated outputs")
    return iot_store.set_actuators(**payload)
