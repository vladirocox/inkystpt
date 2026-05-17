import json
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

ASSETS_DIR = os.environ.get(
    "ASSETS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets"),
)

_ARRIVALS_URL = "https://live.stpt.ro/proxy-smtt-cache.php"
_ARRIVALS_TTL = 12
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://live.stpt.ro/",
}


@dataclass
class StationPoint:
    stop_id: str
    name: str
    latitude: float
    longitude: float
    lines: list[str]

    def to_json(self) -> dict:
        return {
            "stop_id": self.stop_id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "lines": self.lines,
        }


def _http_get_json(url: str, params: dict | None = None, timeout: int = 8) -> Any:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class BusAPI:
    def __init__(self):
        self._lock = threading.Lock()
        self._stations: dict[str, StationPoint] | None = None
        self._arrivals_cache: dict[str, Any] = {}

    def _load_stations(self) -> dict[str, StationPoint]:
        routes_path = os.path.join(ASSETS_DIR, "routes", "lines-config.json")
        stations: dict[str, StationPoint] = {}
        if not os.path.exists(routes_path):
            return stations
        with open(routes_path, "r") as f:
            raw = json.load(f)
        for line_id, line_data in raw.items():
            for direction in ("tur", "retur"):
                direction_data = line_data.get(direction)
                if not direction_data:
                    continue
                ids = direction_data.get("ids", [])
                names = direction_data.get("stations", [])
                coords = direction_data.get("coords", [])
                for i, stop_id in enumerate(ids):
                    if stop_id not in stations:
                        lat = float(coords[i][1]) if i < len(coords) and len(coords[i]) > 1 else 0.0
                        lon = float(coords[i][0]) if i < len(coords) and len(coords[i]) > 0 else 0.0
                        name = names[i] if i < len(names) else ""
                        stations[stop_id] = StationPoint(
                            stop_id=stop_id,
                            name=name,
                            latitude=lat,
                            longitude=lon,
                            lines=[],
                        )
                    stations[stop_id].lines.append(f"{line_id}_{direction}")
        return stations

    def _get_stations(self) -> dict[str, StationPoint]:
        with self._lock:
            if self._stations is None:
                self._stations = self._load_stations()
            return self._stations

    def search_stations(self, query: str, limit: int = 20) -> list[dict]:
        q = query.strip().lower()
        stations = list(self._get_stations().values())
        if not q:
            stations.sort(key=lambda s: s.name.lower())
            return [s.to_json() for s in stations[:limit]]
        results = [
            s for s in stations
            if q in s.name.lower() or q in s.stop_id.lower()
        ]
        results.sort(key=lambda s: s.name.lower())
        return [s.to_json() for s in results[:limit]]

    def get_station(self, stop_id: str) -> StationPoint | None:
        return self._get_stations().get(stop_id)

    def get_arrivals(self, stop_id: str) -> list[dict]:
        with self._lock:
            cached = self._arrivals_cache.get(stop_id)
            if cached and (time.time() - cached["ts"]) < _ARRIVALS_TTL:
                return cached["data"]
        try:
            raw = _http_get_json(_ARRIVALS_URL, params={"stopid": stop_id}, timeout=8)
        except Exception:
            return []
        arrivals = self._parse_arrivals(raw)
        with self._lock:
            self._arrivals_cache[stop_id] = {"data": arrivals, "ts": time.time()}
        return arrivals

    def _parse_arrivals(self, raw: Any) -> list[dict]:
        if isinstance(raw, dict):
            raw = raw.get("arrivals") or raw.get("data") or raw.get("times") or []
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            minutes = self._extract_minutes(item)
            times = self._extract_times(item)
            result.append({
                "line": str(item.get("line") or item.get("route") or ""),
                "destination": str(item.get("headsign") or item.get("destination") or ""),
                "minutes": minutes[0] if minutes else 0,
                "minutes_list": minutes,
                "type": str(item.get("type") or item.get("vehicle_type") or "bus"),
                "arrival_time": times[0] if times else None,
                "arrival_times": times,
            })
        return result

    def _extract_minutes(self, item: dict) -> list[int]:
        raw = item.get("minutes") or item.get("eta_minutes") or 0
        if isinstance(raw, list):
            return [int(m) for m in raw if isinstance(m, (int, float))]
        if isinstance(raw, (int, float)):
            return [int(raw)]
        raw_times = item.get("times") or []
        if isinstance(raw_times, list):
            mins = []
            for t in raw_times:
                if isinstance(t, str) and "|" in t:
                    parts = t.split("|")
                    if len(parts) > 1 and parts[1].strip().isdigit():
                        mins.append(int(parts[1].strip()))
            return mins
        return []

    def _extract_times(self, item: dict) -> list[str]:
        raw_times = item.get("times") or []
        if not isinstance(raw_times, list):
            return []
        times = []
        for t in raw_times:
            if isinstance(t, str):
                time_part = t.split("|")[0].strip()
                if time_part:
                    times.append(time_part)
            elif isinstance(t, dict):
                time_part = str(t.get("time", "")).strip()
                if time_part:
                    times.append(time_part)
        return times


BUS_API = BusAPI()
