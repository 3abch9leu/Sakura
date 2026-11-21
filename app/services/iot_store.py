"""In-memory IoT measurements and simulated actuator state."""
from collections import deque
from threading import RLock
from datetime import datetime, timezone
from typing import Any

_lock = RLock()
_history: deque[dict[str, Any]] = deque(maxlen=1000)
_actuators: dict[str, Any] = {
    "fan_on": False, "pump_on": False, "buzzer_on": False,
    "manual_override": False, "emergency_stop": False,
    "physical_actuation_enabled": False,
}

def add_measurement(data: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        item = dict(data)
        _history.append(item)
        return item

def latest_measurement() -> dict[str, Any] | None:
    with _lock:
        return dict(_history[-1]) if _history else None

def measurement_history(limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        return [dict(item) for item in list(_history)[-limit:]]

def actuator_state() -> dict[str, Any]:
    with _lock:
        return dict(_actuators)

def set_actuators(**values: Any) -> dict[str, Any]:
    with _lock:
        _actuators.update(values)
        if _actuators["emergency_stop"]:
            _actuators.update(fan_on=False, pump_on=False, buzzer_on=False)
        if _actuators["pump_on"]:
            latest = _history[-1] if _history else None
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest["timestamp"].replace("Z", "+00:00"))).total_seconds() if latest else float("inf")
            except (ValueError, TypeError):
                age = float("inf")
            if latest is None or latest["water_level_low"] or age < -60 or age > 300:
                _actuators["pump_on"] = False
        return dict(_actuators)
