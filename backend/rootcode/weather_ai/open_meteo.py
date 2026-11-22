
import httpx

BASE_URL = "https://api.open-meteo.com/v1/forecast"


async def get_weather(latitude: float, longitude: float):
    params = {
        "latitude": latitude,
        "longitude": longitude,

        "current": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "wind_speed_10m,"
            "wind_direction_10m,"
            "cloud_cover"
        ),

        "hourly": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "dew_point_2m,"
            "wet_bulb_temperature_2m,"
            "wind_speed_10m,"
            "wind_direction_10m,"
            "shortwave_radiation,"
            "precipitation"
        ),

        "timezone": "auto",
        "forecast_days": 3
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(BASE_URL, params=params)
        response.raise_for_status()

        return response.json()
