
import httpx
import pandas as pd
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent / "observations.csv"

LATITUDE = 36.8065
LONGITUDE = 10.1815

DATES = {
    "start_date": "2026-11-16",
    "end_date": "2026-11-20"
}

# Actual historical weather variables
archive_params = {
    "latitude": LATITUDE,
    "longitude": LONGITUDE,
    **DATES,
    "hourly": (
        "temperature_2m,relative_humidity_2m,"
        "apparent_temperature,precipitation,weather_code,"
        "pressure_msl,surface_pressure,cloud_cover,"
        "wind_speed_10m,wind_direction_10m"
    ),
    "timezone": "UTC"
}

archive_url = "https://archive-api.open-meteo.com/v1/archive"

# Historical forecast visibility: input feature only
visibility_params = {
    "latitude": LATITUDE,
    "longitude": LONGITUDE,
    **DATES,
    "hourly": "visibility",
    "timezone": "UTC"
}

visibility_url = (
    "https://historical-forecast-api.open-meteo.com/v1/forecast"
)

with httpx.Client(timeout=60) as client:
    archive_response = client.get(
        archive_url, params=archive_params
    )
    archive_response.raise_for_status()

    visibility_response = client.get(
        visibility_url, params=visibility_params
    )
    visibility_response.raise_for_status()

archive = archive_response.json()["hourly"]
visibility = visibility_response.json()["hourly"]

df = pd.DataFrame(archive)
visibility_df = pd.DataFrame(visibility)

if df["time"].tolist() != visibility_df["time"].tolist():
    raise ValueError("The two datasets have different timestamps.")

df["visibility"] = visibility_df["visibility"]

df.to_csv(OUTPUT_FILE, index=False)

print("Dataset saved successfully!")
print("Observations:", len(df))
print("Columns:", list(df.columns))
print("Missing values:")
print(df.isnull().sum())
print("Visibility source: Historical Forecast API (input proxy)")
print("Saved to:", OUTPUT_FILE)
