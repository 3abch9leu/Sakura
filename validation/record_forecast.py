
import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.weather_inference import predict_tunis

OUTPUT_FILE = Path(__file__).parent / "forecast_history.jsonl"


async def main():
    result = await predict_tunis()

    record = {
        "recorded_at": datetime.now(
            ZoneInfo("Africa/Tunis")
        ).isoformat(),
        "city": result["city"],
        "model": result["model"],
        "forecast": result["forecast"]
    }

    with OUTPUT_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")

    print("Forecast successfully recorded!")
    print("Recorded at:", record["recorded_at"])
    print("Forecast hours:", len(record["forecast"]))
    print("Saved to:", OUTPUT_FILE)


if __name__ == "__main__":
    asyncio.run(main())
