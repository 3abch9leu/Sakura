
import httpx

from fastapi import FastAPI, HTTPException, Query
from app.services.open_meteo import get_weather

app = FastAPI(
    title="ROOTCODE - Intelligent Climate Management",
    description="Smart greenhouse water and energy optimization API",
    version="1.0.0"
)


@app.get("/")
async def home():
    return {
        "project": "ROOTCODE",
        "module": "Intelligent Climate Management",
        "status": "running"
    }


@app.get("/weather")
async def weather(
    latitude: float = Query(52.52, ge=-90, le=90),
    longitude: float = Query(13.41, ge=-180, le=180)
):
    try:
        data = await get_weather(latitude, longitude)
        return data

    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve weather data from Open-Meteo"
        )
