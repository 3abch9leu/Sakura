from app.services.climate_engine import recommend, wet_bulb_stull_c

MEASUREMENT = {"device_id":"x", "temperature_c":30.0, "humidity_pct":60.0,
    "light_adc":3000, "soil_moisture_pct":20.0, "water_level_low":False,
    "timestamp":"2026-11-21T12:00:00+00:00"}

def test_safe_missing_sensor_result():
    result = recommend(None, None)
    assert result["sensor_status"] == "offline"
    assert result["actions"] == []

def test_ventilation_irrigation_and_shading_rules():
    forecast = {"forecast":[{"temperature_c":20, "humidity_pct":50, "rain_probability":0.0, "precipitation_mm":0, "cloud_cover_pct":10, "wind_speed_kmh":2}]}
    actions = {a["action"]: a for a in recommend(MEASUREMENT, forecast)["actions"]}
    assert actions["ventilation"]["recommendation"] == "open_or_run_fan"
    assert actions["irrigation"]["recommendation"] == "irrigate"
    assert actions["shading"]["recommendation"] == "consider_shading"

def test_hotter_outdoor_and_rain_defer_irrigation():
    forecast = {"forecast":[{"temperature_c":35, "humidity_pct":90, "rain_probability":0.9}]}
    actions = {a["action"]: a for a in recommend(MEASUREMENT, forecast)["actions"]}
    assert actions["ventilation"]["recommendation"] == "keep_closed"
    assert actions["irrigation"]["recommendation"] == "defer_and_recheck"
    assert actions["evaporative_cooling"]["recommendation"] == "unfavorable_or_unknown"

def test_missing_forecast_fails_safe_for_irrigation_and_ventilation():
    actions = {a["action"]: a for a in recommend(MEASUREMENT, None)["actions"]}
    assert actions["ventilation"]["recommendation"] == "keep_closed"
    assert actions["irrigation"]["recommendation"] == "defer_and_recheck"

def test_wet_bulb_approximation_is_plausible():
    assert 15 < wet_bulb_stull_c(25, 50) < 22
