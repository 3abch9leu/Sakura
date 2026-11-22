"""Transparent greenhouse rules; thresholds are configurable and crop-specific."""
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ClimateConfig:
    soil_irrigation_below_pct: float = 35.0
    rain_probability_skip_pct: float = 60.0
    ventilation_temperature_delta_c: float = 2.0
    max_ventilation_outdoor_humidity_pct: float = 85.0
    evaporative_max_outdoor_humidity_pct: float = 65.0
    shading_light_adc: int = 2600
    shading_temperature_c: float = 30.0

CONFIG = ClimateConfig()

def wet_bulb_stull_c(temp_c: float, rh_pct: float) -> float:
    """Stull (2011) approximation, valid approximately 5–99% RH and -20–50 C."""
    import math
    rh = max(5.0, min(99.0, rh_pct))
    return (temp_c * math.atan(0.151977 * math.sqrt(rh + 8.313659))
            + math.atan(temp_c + rh) - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)

def recommend(measurement: dict[str, Any] | None, forecast: dict[str, Any] | None,
              config: ClimateConfig = CONFIG) -> dict[str, Any]:
    if measurement is None:
        return {"status": "waiting_for_sensors", "current_conditions": None,
                "forecast_summary": None, "actions": [],
                "safety_constraints": ["No sensor measurement: actuators remain off."],
                "sensor_status": "offline"}
    fcs = (forecast or {}).get("forecast", [])
    f = fcs[0] if fcs else None
    indoor_t, indoor_h = measurement["temperature_c"], measurement["humidity_pct"]
    outdoor_t = f.get("temperature_c") if f else None
    outdoor_h = f.get("humidity_pct") if f else None
    rain = f.get("rain_probability", 0) * 100 if f else None
    precip = f.get("precipitation_mm", 0) if f else None
    reasons: list[str] = []
    actions = []
    if outdoor_t is not None and indoor_t - outdoor_t >= config.ventilation_temperature_delta_c and outdoor_h <= config.max_ventilation_outdoor_humidity_pct:
        actions.append({"action": "ventilation", "recommendation": "open_or_run_fan", "reason": "Outdoor air is cooler by the configured margin and humidity is acceptable.", "actuator_command": "none; recommendation only"})
    else:
        why = "Forecast unavailable." if f is None else "Outdoor air is not sufficiently cooler or its humidity is too high."
        actions.append({"action": "ventilation", "recommendation": "keep_closed", "reason": why, "actuator_command": "none; recommendation only"})
    if measurement["soil_moisture_pct"] < config.soil_irrigation_below_pct:
        if measurement["water_level_low"]:
            actions.append({"action": "irrigation", "recommendation": "blocked", "reason": "Soil is below configured threshold, but reservoir-low interlock prevents pumping.", "actuator_command": "none"})
            reasons.append("Pump prohibited while reservoir is low.")
        elif rain is None:
            actions.append({"action": "irrigation", "recommendation": "defer_and_recheck", "reason": "Soil is below the configured threshold, but forecast precipitation is unavailable; recheck before watering.", "actuator_command": "none; recommendation only"})
        elif rain >= config.rain_probability_skip_pct:
            actions.append({"action": "irrigation", "recommendation": "defer_and_recheck", "reason": "Rain probability meets configured defer threshold.", "actuator_command": "none; recommendation only"})
        else:
            actions.append({"action": "irrigation", "recommendation": "irrigate", "reason": "Soil moisture is below configured crop threshold and reservoir is available.", "actuator_command": "none; recommendation only"})
    else:
        actions.append({"action": "irrigation", "recommendation": "not_needed", "reason": "Soil moisture is at or above configured threshold.", "actuator_command": "none; recommendation only"})
    wet = wet_bulb_stull_c(outdoor_t, outdoor_h) if outdoor_t is not None and outdoor_h is not None else None
    evap_ok = bool(wet is not None and outdoor_h < config.evaporative_max_outdoor_humidity_pct and outdoor_t - wet >= 3.0)
    actions.append({"action": "evaporative_cooling", "recommendation": "favorable" if evap_ok else "unfavorable_or_unknown", "wet_bulb_c": round(wet, 1) if wet is not None else None, "wet_bulb_depression_c": round(outdoor_t - wet, 1) if wet is not None else None, "method": "Stull 2011 wet-bulb approximation; indicative only", "reason": "Outdoor humidity and wet-bulb depression satisfy configured screening conditions." if evap_ok else "Humidity is high, wet-bulb depression is small, or forecast is unavailable.", "actuator_command": "none; recommendation only"})
    shade = measurement["light_adc"] >= config.shading_light_adc and indoor_t >= config.shading_temperature_c
    actions.append({"action": "shading", "recommendation": "consider_shading" if shade else "not_indicated", "reason": "Light and indoor temperature exceed configured thresholds." if shade else "Configured light and temperature thresholds are not both exceeded.", "actuator_command": "none; recommendation only"})
    forecast_summary = ({"model": (forecast or {}).get("model"), "forecast_hours": len(fcs), "forecast": fcs} if f else None)
    return {"status": "ok", "current_conditions": {k: measurement[k] for k in ("temperature_c", "humidity_pct", "light_adc", "soil_moisture_pct", "water_level_low", "timestamp", "device_id")}, "forecast_summary": forecast_summary, "actions": actions, "safety_constraints": reasons + ["Recommendations never directly actuate outputs.", "Pump requires a present, fresh measurement with reservoir available.", "Physical actuation is disabled by default; reset and emergency stop leave outputs off."], "sensor_status": "online"}
