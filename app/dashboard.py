
import streamlit as st
import pandas as pd
import plotly.express as px
import asyncio
from pathlib import Path

from app.services.weather_inference import predict_tunis


# =====================================================
# CONFIGURATION
# =====================================================

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_FILE = BASE_DIR / "validation" / "backtest_results.csv"

st.set_page_config(
    page_title="ROOTCODE | AI Climate Intelligence",
    page_icon="🌱",
    layout="wide"
)


# =====================================================
# HEADER
# =====================================================

st.title("🌱 ROOTCODE — AI Climate Intelligence")

st.caption(
    "Pretrained AI Weather Forecasting & "
    "Intelligent Climate Management"
)

st.divider()


# =====================================================
# HISTORICAL MODEL PERFORMANCE
# =====================================================

st.header("📊 AI Model Performance")

if not RESULTS_FILE.exists():
    st.error(
        "Backtest results not found. "
        "Run: python validation/backtest.py"
    )
    st.stop()

df = pd.read_csv(RESULTS_FILE)

temperature_mae = (
    df["temperature_predicted"] -
    df["temperature_actual"]
).abs().mean()

humidity_mae = (
    df["humidity_predicted"] -
    df["humidity_actual"]
).abs().mean()

temperature_rmse = (
    (df["temperature_predicted"] -
     df["temperature_actual"]) ** 2
).mean() ** 0.5

humidity_rmse = (
    (df["humidity_predicted"] -
     df["humidity_actual"]) ** 2
).mean() ** 0.5


c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Temperature MAE",
    f"{temperature_mae:.2f} °C"
)

c2.metric(
    "Humidity MAE",
    f"{humidity_mae:.2f} %"
)

c3.metric(
    "Temperature RMSE",
    f"{temperature_rmse:.2f} °C"
)

c4.metric(
    "Evaluated Predictions",
    len(df)
)

st.info(
    "Historical evaluation based on four rolling "
    "12-hour forecast periods using Open-Meteo "
    "archive observations as the reference."
)

st.divider()


# =====================================================
# NAVIGATION
# =====================================================

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Overview",
    "🌡️ Temperature",
    "💧 Humidity",
    "🔮 Future Forecast"
])


# =====================================================
# TAB 1 — OVERVIEW
# =====================================================

with tab1:

    st.subheader("Prediction Performance")

    temp_data = df[
        [
            "time",
            "temperature_predicted",
            "temperature_actual"
        ]
    ].melt(
        id_vars="time",
        var_name="Series",
        value_name="Temperature (°C)"
    )

    temp_data["Series"] = temp_data["Series"].map({
        "temperature_predicted": "AI Prediction",
        "temperature_actual": "Observed Weather"
    })

    fig = px.line(
        temp_data,
        x="time",
        y="Temperature (°C)",
        color="Series",
        markers=True,
        title="AI Predictions vs Observed Temperature"
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    st.subheader("Historical Evaluation Summary")

    st.write(
        "The model is evaluated using historical "
        "weather observations for Tunis."
    )

    st.dataframe(
        df,
        use_container_width=True
    )


# =====================================================
# TAB 2 — TEMPERATURE
# =====================================================

with tab2:

    st.subheader("🌡️ Temperature Analysis")

    fig = px.line(
        df,
        x="time",
        y=[
            "temperature_predicted",
            "temperature_actual"
        ],
        markers=True,
        title="Predicted vs Observed Temperature"
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    st.metric(
        "Temperature MAE",
        f"{temperature_mae:.2f} °C"
    )


# =====================================================
# TAB 3 — HUMIDITY
# =====================================================

with tab3:

    st.subheader("💧 Humidity Analysis")

    fig = px.line(
        df,
        x="time",
        y=[
            "humidity_predicted",
            "humidity_actual"
        ],
        markers=True,
        title="Predicted vs Observed Humidity"
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    st.metric(
        "Humidity MAE",
        f"{humidity_mae:.2f} %"
    )


# =====================================================
# TAB 4 — LIVE FUTURE FORECAST
# =====================================================

with tab4:

    st.header("🔮 Live AI Weather Forecast")

    st.write(
        "Use the pretrained DistilHweh-446k model "
        "to predict weather conditions for the "
        "next 12 hours in Tunis."
    )

    st.caption(
        "The model uses the latest 72 completed "
        "historical weather hours as input."
    )

    if st.button(
        "🚀 Generate Future Predictions",
        type="primary",
        use_container_width=True
    ):

        with st.spinner(
            "AI model is analyzing recent weather data..."
        ):

            try:

                forecast_result = asyncio.run(
                    predict_tunis()
                )

                forecast_df = pd.DataFrame(
                    forecast_result["forecast"]
                )

                if forecast_df.empty:
                    st.warning("No forecast data returned.")
                    st.stop()

                st.session_state["forecast_df"] = forecast_df

                st.success(
                    "12-hour AI forecast generated successfully!"
                )

            except Exception as error:

                st.error(
                    f"Forecast generation failed: {error}"
                )


    # Display saved forecast after generation

    if "forecast_df" in st.session_state:

        forecast_df = st.session_state["forecast_df"]

        st.divider()

        st.subheader("Next-hour Predictions")

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Temperature",
            f"{forecast_df.iloc[0]['temperature_c']:.1f} °C"
        )

        c2.metric(
            "Humidity",
            f"{forecast_df.iloc[0]['humidity_pct']:.1f} %"
        )

        c3.metric(
            "Weather",
            forecast_df.iloc[0]["weather_class"]
        )

        st.divider()

        st.subheader("🌡️ Temperature Forecast")

        fig = px.line(
            forecast_df,
            x="time_local",
            y="temperature_c",
            markers=True,
            title="Predicted Temperature — Next 12 Hours"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        st.subheader("💧 Humidity Forecast")

        fig = px.line(
            forecast_df,
            x="time_local",
            y="humidity_pct",
            markers=True,
            title="Predicted Humidity — Next 12 Hours"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        st.subheader("🌬️ Wind Forecast")

        fig = px.line(
            forecast_df,
            x="time_local",
            y="wind_speed_kmh",
            markers=True,
            title="Predicted Wind Speed — Next 12 Hours"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        st.subheader("Complete AI Predictions")

        st.dataframe(
            forecast_df,
            use_container_width=True
        )

        st.download_button(
            "⬇️ Download Forecast CSV",
            data=forecast_df.to_csv(index=False),
            file_name="tunis_ai_forecast.csv",
            mime="text/csv"
        )


# =====================================================
# FOOTER
# =====================================================

st.divider()

st.caption(
    "ROOTCODE | DistilHweh-446k | Tunis, Tunisia | "
    "AI Climate Intelligence"
)
