
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
import torch
from safetensors.torch import load_file
from transformers import AutoConfig, AutoModel


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = BASE_DIR / "models" / "hweh-446k"
METADATA_PATH = MODEL_DIR / "weather_sequences.metadata.json"

LATITUDE = 36.8065
LONGITUDE = 10.1815
CITY = "Tunis"
TIMEZONE = "Africa/Tunis"

LOCATION_ID = 77
HISTORY_HOURS = 72
FORECAST_HOURS = 12

TEMP_SCALE = 50.0
HUMIDITY_SCALE = 100.0
WIND_SCALE = 100.0

HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "weather_code",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "visibility",
    "wind_speed_10m",
    "wind_direction_10m",
]

WEATHER_CLASSES = [
    "Clear",
    "Cloudy",
    "Fog",
    "Drizzle",
    "Rain",
    "Snow",
    "Thunderstorm",
]


# --------------------------------------------------
# LOAD PRETRAINED MODEL
# --------------------------------------------------

config = AutoConfig.from_pretrained(
    str(MODEL_DIR),
    trust_remote_code=True,
    local_files_only=True,
)

# Initialize the model using the configuration.
# This correctly initializes the target normalization buffers.
model = AutoModel.from_config(
    config,
    trust_remote_code=True,
)

# Load pretrained weights directly from Safetensors.
# This avoids the problematic from_pretrained() loading path.
state_dict = load_file(
    str(MODEL_DIR / "model.safetensors"),
    device="cpu",
)

result = model.load_state_dict(
    state_dict,
    strict=False,
)

# Verify that every pretrained tensor was loaded.
if result.missing_keys or result.unexpected_keys:
    raise RuntimeError(
        f"Checkpoint mismatch. "
        f"Missing keys: {result.missing_keys}. "
        f"Unexpected keys: {result.unexpected_keys}."
    )

DEVICE = torch.device("cpu")

model.to(DEVICE)
model.eval()

# Verify the normalization statistics.
if model.temp_std.item() <= 0:
    raise RuntimeError("Invalid temperature normalization standard deviation.")

if model.humidity_std.item() <= 0:
    raise RuntimeError("Invalid humidity normalization standard deviation.")

print("Pretrained weather model loaded successfully.")
print("Temperature mean:", model.temp_mean.item())
print("Temperature std:", model.temp_std.item())
print("Humidity mean:", model.humidity_mean.item())
print("Humidity std:", model.humidity_std.item())


# --------------------------------------------------
# WEATHER CODE MAPPING
# --------------------------------------------------

def weather_code_to_bucket(code):

    if code is None or pd.isna(code):
        return 1

    code = int(code)

    if code == 0:
        return 0

    if code in (1, 2, 3):
        return 1

    if code in (45, 48):
        return 2

    if code in (51, 53, 55, 56, 57):
        return 3

    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return 4

    if code in (71, 73, 75, 77, 85, 86):
        return 5

    if code in (95, 96, 99):
        return 6

    return 1


def cyc(values, period):

    angle = 2.0 * np.pi * (values / period)

    return np.sin(angle), np.cos(angle)


# --------------------------------------------------
# GET HISTORICAL WEATHER FROM OPEN-METEO
# --------------------------------------------------

async def fetch_history():

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(HOURLY_VARS),
        "past_days": 4,
        "forecast_days": 1,
        "timezone": "UTC",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:

        response = await client.get(url, params=params)

        response.raise_for_status()

        data = response.json()

    if "hourly" not in data or not data["hourly"]:
        raise ValueError(
            "Open-Meteo returned no hourly observations."
        )

    df = pd.DataFrame(data["hourly"])

    missing = [
        column
        for column in HOURLY_VARS
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Missing weather variables: {missing}"
        )

    df["time"] = pd.to_datetime(
        df["time"],
        utc=True,
        errors="coerce",
    )

    df = (
        df.dropna(subset=["time"])
        .sort_values("time")
        .drop_duplicates(subset=["time"])
        .reset_index(drop=True)
    )

    numeric_columns = [
        "temperature_2m",
        "relative_humidity_2m",
        "apparent_temperature",
        "precipitation",
        "weather_code",
        "pressure_msl",
        "surface_pressure",
        "cloud_cover",
        "visibility",
        "wind_speed_10m",
        "wind_direction_10m",
    ]

    for column in numeric_columns:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df["weather_code"] = df["weather_code"].fillna(1)

    df["precipitation"] = df["precipitation"].fillna(0.0)

    interpolate_columns = [
        "temperature_2m",
        "relative_humidity_2m",
        "apparent_temperature",
        "precipitation",
        "pressure_msl",
        "surface_pressure",
        "cloud_cover",
        "visibility",
        "wind_speed_10m",
        "wind_direction_10m",
    ]

    for column in interpolate_columns:

        df[column] = (
            df[column]
            .interpolate(limit_direction="both")
            .ffill()
            .bfill()
        )

    # Only use completed historical hours.
    now_utc = pd.Timestamp.now(tz="UTC").floor("h")

    df = df[df["time"] < now_utc].copy()

    if len(df) < HISTORY_HOURS:

        raise ValueError(
            f"Need {HISTORY_HOURS} historical hours, "
            f"got {len(df)}."
        )

    return df.tail(HISTORY_HOURS).reset_index(drop=True)


# --------------------------------------------------
# BUILD THE 22 MODEL FEATURES
# --------------------------------------------------

def build_sequence(df):

    hour = df["time"].dt.hour.to_numpy()

    day_of_year = df["time"].dt.dayofyear.to_numpy()

    hour_sin, hour_cos = cyc(
        hour.astype(float),
        24.0,
    )

    doy_sin, doy_cos = cyc(
        day_of_year.astype(float),
        365.25,
    )

    temp = np.nan_to_num(
        df["temperature_2m"].to_numpy(dtype=float)
    )

    humidity = np.nan_to_num(
        df["relative_humidity_2m"].to_numpy(dtype=float)
    )

    apparent = np.nan_to_num(
        df["apparent_temperature"].to_numpy(dtype=float)
    )

    precip = np.nan_to_num(
        df["precipitation"].to_numpy(dtype=float)
    )

    pressure = np.nan_to_num(
        df["pressure_msl"].to_numpy(dtype=float)
    )

    surface_pressure = np.nan_to_num(
        df["surface_pressure"].to_numpy(dtype=float)
    )

    cloud_cover = np.nan_to_num(
        df["cloud_cover"].to_numpy(dtype=float)
    )

    visibility = np.nan_to_num(
        df["visibility"].to_numpy(dtype=float)
    )

    wind = np.nan_to_num(
        df["wind_speed_10m"].to_numpy(dtype=float)
    )

    wind_direction = np.nan_to_num(
        df["wind_direction_10m"].to_numpy(dtype=float)
    )

    humidity = np.clip(humidity, 0, 100)

    cloud_cover = np.clip(cloud_cover, 0, 100)

    precip = np.clip(precip, 0, None)

    wind = np.clip(wind, 0, None)

    visibility = np.clip(visibility, 0, None)

    wind_sin, wind_cos = cyc(
        wind_direction,
        360.0,
    )

    weather_buckets = (
        df["weather_code"]
        .fillna(1)
        .apply(weather_code_to_bucket)
        .to_numpy(dtype=np.int64)
    )

    rows = []

    for i in range(len(df)):

        weather_one_hot = np.zeros(
            7,
            dtype=np.float32,
        )

        weather_one_hot[weather_buckets[i]] = 1.0

        features = np.array(
            [
                temp[i] / TEMP_SCALE,
                humidity[i] / HUMIDITY_SCALE,
                apparent[i] / TEMP_SCALE,
                np.log1p(max(precip[i], 0.0)) / 3.0,
                pressure[i] / 1100.0,
                surface_pressure[i] / 1100.0,
                cloud_cover[i] / 100.0,
                visibility[i] / 50000.0,
                wind[i] / WIND_SCALE,
                wind_sin[i],
                wind_cos[i],
                hour_sin[i],
                hour_cos[i],
                doy_sin[i],
                doy_cos[i],
            ],
            dtype=np.float32,
        )

        rows.append(
            np.concatenate([
                features,
                weather_one_hot,
            ])
        )

    sequence = np.asarray(
        rows,
        dtype=np.float32,
    )

    if sequence.shape != (HISTORY_HOURS, 22):

        raise ValueError(
            f"Unexpected input shape: {sequence.shape}"
        )

    if not np.isfinite(sequence).all():

        raise ValueError(
            "Input contains non-finite values."
        )

    return sequence


# --------------------------------------------------
# RUN THE PRETRAINED MODEL
# --------------------------------------------------

def get_logits(output):

    if isinstance(output, dict) and "logits" in output:
        return output["logits"]

    if hasattr(output, "logits"):
        return output.logits

    return output


async def predict_tunis():

    df = await fetch_history()

    sequence = build_sequence(df)

    X = (
        torch.from_numpy(sequence)
        .unsqueeze(0)
        .to(DEVICE)
    )

    location = torch.tensor(
        [LOCATION_ID],
        dtype=torch.long,
    ).to(DEVICE)

    with torch.no_grad():

        output = model(
            X=X,
            location_id=location,
        )

        logits = get_logits(output)

        (
            temp_pred,
            humidity_pred,
            apparent_pred,
            precip_pred,
            pressure_pred,
            surface_pressure_pred,
            cloud_pred,
            wind_pred,
            wind_sin_pred,
            wind_cos_pred,
            rain_logit,
            weather_logits,
        ) = logits

        temp_pred = temp_pred.squeeze(0).cpu().numpy()

        humidity_pred = humidity_pred.squeeze(0).cpu().numpy()

        apparent_pred = apparent_pred.squeeze(0).cpu().numpy()

        precip_pred = precip_pred.squeeze(0).cpu().numpy()

        pressure_pred = pressure_pred.squeeze(0).cpu().numpy()

        surface_pressure_pred = (
            surface_pressure_pred.squeeze(0).cpu().numpy()
        )

        cloud_pred = cloud_pred.squeeze(0).cpu().numpy()

        wind_pred = wind_pred.squeeze(0).cpu().numpy()

        rain_probability = (
            torch.sigmoid(rain_logit)
            .squeeze(0)
            .cpu()
            .numpy()
        )

        weather_probabilities = (
            torch.softmax(weather_logits, dim=-1)
            .squeeze(0)
            .cpu()
            .numpy()
        )

        weather_indices = np.argmax(
            weather_probabilities,
            axis=-1,
        )

    # Validate numerical predictions before returning them.
    regression_predictions = [
        temp_pred,
        humidity_pred,
        apparent_pred,
        precip_pred,
        pressure_pred,
        surface_pressure_pred,
        cloud_pred,
        wind_pred,
    ]

    for prediction in regression_predictions:

        if not np.isfinite(prediction).all():

            raise ValueError(
                "Model returned non-finite weather predictions."
            )

    horizon = min(
        FORECAST_HOURS,
        len(temp_pred),
        len(humidity_pred),
        len(weather_indices),
    )

    context_end = df["time"].iloc[-1]

    local_zone = ZoneInfo(TIMEZONE)

    forecasts = []

    for i in range(horizon):

        target_time = (
            context_end + pd.Timedelta(hours=i + 1)
        )

        weather_index = int(weather_indices[i])

        forecasts.append({

            "lead_hours": i + 1,

            "time_local": (
                target_time
                .tz_convert(local_zone)
                .isoformat()
            ),

            "temperature_c": float(temp_pred[i]),

            "humidity_pct": float(
                np.clip(humidity_pred[i], 0, 100)
            ),

            "apparent_temperature_c": float(
                apparent_pred[i]
            ),

            "precipitation_mm": float(
                max(0, precip_pred[i])
            ),

            "pressure_hpa": float(
                pressure_pred[i]
            ),

            "surface_pressure_hpa": float(
                surface_pressure_pred[i]
            ),

            "cloud_cover_pct": float(
                np.clip(cloud_pred[i], 0, 100)
            ),

            "wind_speed_kmh": float(
                max(0, wind_pred[i])
            ),

            "rain_probability": float(
                np.clip(rain_probability[i], 0, 1)
            ),

            "weather_class": WEATHER_CLASSES[weather_index],

            "weather_probabilities": {

                name: float(probability)

                for name, probability in zip(
                    WEATHER_CLASSES,
                    weather_probabilities[i],
                )
            },
        })

    return {

        "city": CITY,

        "location_id": LOCATION_ID,

        "model": "DistilHweh-446k",

        "history_hours": len(df),

        "input_shape": list(sequence.shape),

        "forecast_hours": horizon,

        "forecast": forecasts,
    }
