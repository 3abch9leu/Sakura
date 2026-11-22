"""
ROOTCODE Water Quality Engine (Python Module)
Team Sakura - Kizuna 2026 Hackathon

Standalone Python analyzer for AI / backend integration.
Usage:
    from water_engine import WaterEngine, evaluate_reading, PRELOADED_WATER_DATA
"""

from typing import Dict, Any, Optional, Tuple, List

DEFAULT_THRESHOLDS = {
    "ph": {"clean_lo": 6.5, "clean_hi": 8.4, "warn_lo": 6.0, "warn_hi": 9.0, "bad_lo": 0.0, "bad_hi": 14.0, "ref": "FAO 29"},
    "turbidity_ntu": {"clean_lo": 0.0, "clean_hi": 5.0, "warn_lo": 5.0, "warn_hi": 25.0, "bad_lo": 25.0, "bad_hi": 999999.0, "ref": "WHO"},
    "ec_us_cm": {"clean_lo": 0.0, "clean_hi": 700.0, "warn_lo": 700.0, "warn_hi": 3000.0, "bad_lo": 3000.0, "bad_hi": 999999.0, "ref": "FAO 29"},
    "temp_c": {"clean_lo": 10.0, "clean_hi": 30.0, "warn_lo": 5.0, "warn_hi": 35.0, "bad_lo": 0.0, "bad_hi": 45.0, "ref": "FAO"},
    "level_pct": {"clean_lo": 20.0, "clean_hi": 100.0, "warn_lo": 10.0, "warn_hi": 20.0, "bad_lo": 0.0, "bad_hi": 10.0, "ref": "Tank Supply"}
}

PRELOADED_WATER_DATA = {
    "clean": {"source": "clean", "data_type": "MEASURED", "ph": 7.20, "turbidity_ntu": 1.8, "ec_us_cm": 420.0, "temp_c": 21.5, "level_pct": 84.0, "orp_mv": 345.0},
    "rain": {"source": "rain", "data_type": "MEASURED", "ph": 6.40, "turbidity_ntu": 7.8, "ec_us_cm": 48.0, "temp_c": 18.2, "level_pct": 65.0, "orp_mv": 295.0},
    "ac": {"source": "ac", "data_type": "MEASURED", "ph": 6.85, "turbidity_ntu": 0.9, "ec_us_cm": 18.0, "temp_c": 16.0, "level_pct": 45.0, "orp_mv": 320.0},
    "grey": {"source": "grey", "data_type": "MEASURED", "ph": 7.60, "turbidity_ntu": 28.5, "ec_us_cm": 1150.0, "temp_c": 22.8, "level_pct": 28.0, "orp_mv": 180.0}
}


def compensate_ec(ec: float, temp: Optional[float]) -> Tuple[float, bool]:
    """Compensates Electrical Conductivity (EC) to standard 25 °C."""
    if temp is None:
        return float(ec), False
    return float(ec) / (1.0 + 0.02 * (float(temp) - 25.0)), True


def judge_param(param_key: str, value: Optional[float], temp_for_ec: Optional[float] = None, thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Evaluates a single parameter value against thresholds."""
    th_dict = thresholds or DEFAULT_THRESHOLDS
    if value is None:
        return {"status": "missing", "raw": None}
    
    val = float(value)
    th = th_dict.get(param_key)
    if not th:
        return {"status": "ok", "raw": val}
    
    # Plausibility checks
    if param_key == "ph" and (val < 0.0 or val > 14.0):
        return {"status": "invalid", "reason": f"pH {val} outside 0-14 scale", "raw": val}
    if param_key in ("turbidity_ntu", "ec_us_cm") and val < 0.0:
        return {"status": "invalid", "reason": f"{param_key} negative", "raw": val}
    if param_key == "level_pct" and (val < 0.0 or val > 100.0):
        return {"status": "invalid", "reason": f"Level {val}% outside 0-100%", "raw": val}
    
    judged_val = val
    if param_key == "ec_us_cm" and temp_for_ec is not None:
        judged_val, _ = compensate_ec(val, temp_for_ec)
        
    if param_key == "ph":
        if th["clean_lo"] <= judged_val <= th["clean_hi"]:
            return {"status": "ok", "raw": val}
        if th["warn_lo"] <= judged_val <= th["warn_hi"]:
            return {"status": "warn", "raw": val}
        return {"status": "bad", "raw": val}

    if param_key in ("turbidity_ntu", "ec_us_cm"):
        if judged_val <= th["clean_hi"]:
            return {"status": "ok", "raw": val}
        if judged_val <= th["warn_hi"]:
            return {"status": "warn", "raw": val}
        return {"status": "bad", "raw": val}

    if param_key == "temp_c":
        if th["clean_lo"] <= judged_val <= th["clean_hi"]:
            return {"status": "ok", "raw": val}
        if th["warn_lo"] <= judged_val <= th["warn_hi"]:
            return {"status": "warn", "raw": val}
        return {"status": "bad", "raw": val}

    if param_key == "level_pct":
        if judged_val >= th["clean_lo"]:
            return {"status": "ok", "raw": val}
        if judged_val >= th["warn_lo"]:
            return {"status": "warn", "raw": val}
        return {"status": "bad", "raw": val}

    return {"status": "ok", "raw": val}


def evaluate_reading(reading: Dict[str, Any], has_micro_passing: bool = False, has_micro_failing: bool = False) -> Dict[str, Any]:
    """Computes full verdict for a reading."""
    source = reading.get("source", "clean")
    is_simulated = reading.get("data_type") == "SIMULATED" or reading.get("dataType") == "SIMULATED"

    if source == "grey":
        return {
            "verdict": "bad",
            "emoji": "❌",
            "label": "NOT CLEAN",
            "reason": "Greywater: not permitted for edible crops (FAO guidelines)",
            "confidence": "MEDIUM",
            "action": "DO NOT USE for edible crops"
        }

    judged_keys = ["ph", "turbidity_ntu", "ec_us_cm", "temp_c"]
    param_results = {}
    missing = []
    has_bad = False
    has_warn = False
    has_invalid = False

    temp_c = reading.get("temp_c")
    for key in judged_keys:
        val = reading.get(key)
        temp_val = temp_c if key == "ec_us_cm" else None
        res = judge_param(key, val, temp_val)
        param_results[key] = res
        if res["status"] == "missing":
            missing.append(key)
        elif res["status"] == "invalid":
            has_invalid = True
            has_bad = True
        elif res["status"] == "bad":
            has_bad = True
        elif res["status"] == "warn":
            has_warn = True

    if missing:
        return {
            "verdict": "unknown",
            "emoji": "❔",
            "label": "CANNOT DECIDE",
            "reason": f"Missing required parameters: {', '.join(missing)}",
            "confidence": "LOW" if is_simulated else "MEDIUM",
            "action": "Supply missing sensor data before irrigation"
        }

    if is_simulated:
        return {
            "verdict": "unknown",
            "emoji": "❔",
            "label": "CANNOT DECIDE",
            "reason": "Data is SIMULATED — not a physical measurement",
            "confidence": "LOW",
            "action": "Simulated data cannot verify cleanliness"
        }

    if has_micro_failing:
        return {
            "verdict": "bad",
            "emoji": "❌",
            "label": "NOT CLEAN",
            "reason": "Microbiology FAIL: pathogens/coliforms detected",
            "confidence": "HIGH",
            "action": "DO NOT USE for edible crops"
        }

    if has_bad or has_invalid:
        return {
            "verdict": "bad",
            "emoji": "❌",
            "label": "NOT CLEAN",
            "reason": "One or more parameters exceed hazardous limit",
            "confidence": "LOW" if has_invalid else ("HIGH" if has_micro_passing else "MEDIUM"),
            "action": "DO NOT USE for edible crops"
        }

    if has_warn:
        return {
            "verdict": "warn",
            "emoji": "⚠️",
            "label": "ACCEPTABLE WITH CAUTION",
            "reason": "One or more parameters in warning range",
            "confidence": "HIGH" if has_micro_passing else "MEDIUM",
            "action": "Use with caution for plant irrigation"
        }

    return {
        "verdict": "ok",
        "emoji": "✅",
        "label": "CLEAN",
        "reason": "All judged parameters within clean range",
        "confidence": "HIGH" if has_micro_passing else "MEDIUM",
        "action": "SAFE to use for plant irrigation"
    }


class WaterEngine:
    """Wrapper class for object-oriented consumers."""
    DEFAULT_THRESHOLDS = DEFAULT_THRESHOLDS
    PRELOADED_WATER_DATA = PRELOADED_WATER_DATA

    @staticmethod
    def evaluate(reading: Dict[str, Any]) -> Dict[str, Any]:
        return evaluate_reading(reading)

    @staticmethod
    def compensate_ec(ec: float, temp: float) -> Tuple[float, bool]:
        return compensate_ec(ec, temp)
