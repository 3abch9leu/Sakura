
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app.services.weather_inference as wi


DATA_FILE = PROJECT_ROOT / "validation" / "observations.csv"
OUTPUT_FILE = PROJECT_ROOT / "validation" / "backtest_results.csv"

HISTORY_HOURS = 72
FORECAST_HOURS = 12
STEP_HOURS = 12


def main():
    df = pd.read_csv(DATA_FILE)

    df["time"] = pd.to_datetime(
        df["time"], utc=True, errors="coerce"
    )

    if df["time"].isna().any():
        raise ValueError("Invalid timestamps in observations.csv")

    if df.isna().any().any():
        raise ValueError(
            "Missing values detected. Fix the dataset before backtesting."
        )

    df = df.sort_values("time").reset_index(drop=True)

    required_rows = HISTORY_HOURS + FORECAST_HOURS

    if len(df) < required_rows:
        raise ValueError(
            f"Need at least {required_rows} rows; found {len(df)}."
        )

    observations = df.set_index("time")
    records = []

    wi.model.eval()

    location = torch.tensor(
        [wi.LOCATION_ID],
        dtype=torch.long,
        device=wi.DEVICE
    )

    for start in range(
        0,
        len(df) - required_rows + 1,
        STEP_HOURS
    ):
        history = df.iloc[
            start:start + HISTORY_HOURS
        ].copy()

        sequence = wi.build_sequence(history)

        X = (
            torch.from_numpy(sequence)
            .unsqueeze(0)
            .to(wi.DEVICE)
        )

        with torch.no_grad():
            output = wi.model(X=X, location_id=location)
            logits = wi.get_logits(output)

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
            weather_logits
        ) = logits

        temp_pred = temp_pred.squeeze(0).cpu().numpy()
        humidity_pred = humidity_pred.squeeze(0).cpu().numpy()
        apparent_pred = apparent_pred.squeeze(0).cpu().numpy()
        wind_pred = wind_pred.squeeze(0).cpu().numpy()

        context_end = history["time"].iloc[-1]

        for i in range(FORECAST_HOURS):
            target_time = context_end + pd.Timedelta(hours=i + 1)

            if target_time not in observations.index:
                continue

            actual = observations.loc[target_time]

            records.append({
                "time": target_time.isoformat(),
                "lead_hours": i + 1,
                "temperature_predicted": float(temp_pred[i]),
                "temperature_actual": float(actual["temperature_2m"]),
                "humidity_predicted": float(
                    np.clip(humidity_pred[i], 0, 100)
                ),
                "humidity_actual": float(
                    actual["relative_humidity_2m"]
                ),
                "apparent_predicted": float(apparent_pred[i]),
                "apparent_actual": float(
                    actual["apparent_temperature"]
                ),
                "wind_predicted": float(max(0, wind_pred[i])),
                "wind_actual": float(actual["wind_speed_10m"])
            })

    if not records:
        raise ValueError("No matching prediction and observation hours.")

    results = pd.DataFrame(records)
    results.to_csv(OUTPUT_FILE, index=False)

    print("\nBACKTEST COMPLETED")
    print("Matched predictions:", len(results))
    print("Forecast periods:", results["time"].nunique() // FORECAST_HOURS)
    print("\nMODEL PERFORMANCE")

    comparisons = {
        "Temperature (C)": (
            "temperature_predicted", "temperature_actual"
        ),
        "Humidity (%)": (
            "humidity_predicted", "humidity_actual"
        ),
        "Apparent temperature (C)": (
            "apparent_predicted", "apparent_actual"
        ),
        "Wind speed (km/h)": (
            "wind_predicted", "wind_actual"
        )
    }

    for name, (predicted, actual) in comparisons.items():
        errors = results[predicted] - results[actual]

        mae = np.mean(np.abs(errors))
        rmse = np.sqrt(np.mean(errors ** 2))

        print(f"{name}: MAE={mae:.3f}, RMSE={rmse:.3f}")

    print("\nResults saved to:", OUTPUT_FILE)
    print("\nFirst five predictions:")
    print(results.head().to_string(index=False))


if __name__ == "__main__":
    main()
