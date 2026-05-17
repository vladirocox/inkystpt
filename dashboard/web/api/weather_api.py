import urllib.request
import urllib.parse
import json
import time
import threading
from typing import Any

_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
_TTL = 300


class WeatherAPI:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}

    def get_weather(self, latitude: float, longitude: float) -> dict:
        grid_key = f"{round(latitude, 2)},{round(longitude, 2)}"
        with self._lock:
            cached = self._cache.get(grid_key)
            if cached and (time.time() - cached["ts"]) < _TTL:
                return cached["data"]

        params = {
            "latitude": str(latitude),
            "longitude": str(longitude),
            "current": "temperature_2m,weather_code,is_day",
            "timezone": "auto",
        }
        url = _WEATHER_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Dashboard/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return {"error": "weather_unavailable"}

        current = raw.get("current") if isinstance(raw, dict) else None
        if not isinstance(current, dict):
            return {"error": "weather_parse_error"}

        result = {
            "temperature_c": current.get("temperature_2m"),
            "weather_code": current.get("weather_code"),
            "is_day": current.get("is_day") == 1,
        }
        with self._lock:
            self._cache[grid_key] = {"data": result, "ts": time.time()}
        return result


WEATHER_API = WeatherAPI()
