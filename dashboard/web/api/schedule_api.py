import json
import os
import re
import threading
import time
import urllib.request
import urllib.parse

ASSETS_DIR = os.environ.get(
    "ASSETS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets"),
)

_SCHEDULE_CACHE = {}
_SCHEDULE_TTL = 3600
_SCHEDULE_LOCK = threading.Lock()

_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "text/html",
}


def _http_get(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _get_all_station_info(stop_id: str) -> list[dict]:
    routes_path = os.path.join(ASSETS_DIR, "routes", "lines-config.json")
    if not os.path.exists(routes_path):
        return []
    with open(routes_path, "r") as f:
        raw = json.load(f)
    results = []
    for line_id, line_data in raw.items():
        for direction in ("tur", "retur"):
            dd = line_data.get(direction, {})
            ids = dd.get("ids", [])
            names = dd.get("stations", [])
            for i, sid in enumerate(ids):
                if sid == stop_id:
                    name = names[i] if i < len(names) else ""
                    results.append({"line": line_id, "direction": direction, "stop_name": name})
    return results


def _get_smtt_url(line: str, direction: str) -> str:
    line_slug = "linie-transport-public-" + line.lower().replace(" ", "")
    if direction == "retur":
        line_slug += "-r"
    return f"https://smtt.ro/{line_slug}/"


def _parse_times_from_html(html: str, stop_id: str) -> list[str]:
    pattern = re.escape(stop_id) + r'"[^>]*data-times="([^"]*)"'
    m = re.search(pattern, html)
    if not m:
        return []
    raw = m.group(1)
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part or "|" not in part:
            continue
        hour_str, rest = part.split("|", 1)
        minute_str = rest.split("-")[0].strip()
        if minute_str:
            try:
                h = int(hour_str)
                m = int(minute_str)
                result.append(f"{h:02d}:{m:02d}")
            except ValueError:
                pass
    return result


def fetch_schedule(stop_id: str) -> list[dict]:
    cache_key = f"schedule_{stop_id}"
    now = time.time()
    with _SCHEDULE_LOCK:
        cached = _SCHEDULE_CACHE.get(cache_key)
        if cached and (now - cached["ts"]) < _SCHEDULE_TTL:
            return cached["times"]

    all_info = _get_all_station_info(stop_id)
    if not all_info:
        return []

    all_times = []
    seen = set()
    for info in all_info:
        url = _get_smtt_url(info["line"], info["direction"])
        try:
            html = _http_get(url)
        except Exception:
            continue
        raw_times = _parse_times_from_html(html, stop_id)
        for t in raw_times:
            dedup_key = f"{t}|{info['line']}"
            if dedup_key not in seen:
                seen.add(dedup_key)
                all_times.append({"time": t, "line": info["line"]})

    all_times.sort(key=lambda x: x["time"])

    with _SCHEDULE_LOCK:
        _SCHEDULE_CACHE[cache_key] = {"times": all_times, "ts": now}
    return all_times
