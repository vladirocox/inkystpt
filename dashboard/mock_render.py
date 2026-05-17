import json, sys, base64, os, urllib.request, urllib.parse, time as _time
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 250, 122

try:
    FONT_LG = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
    FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
except Exception:
    try:
        FONT_LG = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except Exception:
        FONT_LG = FONT_MD = FONT_SM = ImageFont.load_default()

WEATHER_SYMBOLS = {
    0: "O", 1: "~", 2: "~", 3: "~",
    45: "=", 48: "=",
    51: ";", 53: ";", 55: ";",
    61: ";", 63: ";", 65: ";",
    71: "*", 73: "*", 75: "*",
    80: ";", 81: ";", 82: ";",
    95: "!", 96: "!", 99: "!",
}

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)

def truncate_by_width(text, font, max_width, draw_obj):
    for i in range(len(text), 0, -1):
        if draw_obj.textlength(text[:i], font=font) <= max_width:
            return text[:i]
    return ""

def fetch_weather(lat, lon):
    try:
        params = urllib.parse.urlencode({
            "latitude": str(lat), "longitude": str(lon),
            "current": "temperature_2m,weather_code,is_day",
            "timezone": "auto",
        })
        req = urllib.request.Request(
            f"https://api.open-meteo.com/v1/forecast?{params}",
            headers={"User-Agent": "Dashboard/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        cur = data.get("current", {})
        return {"temp": cur.get("temperature_2m"), "code": cur.get("weather_code", 0)}
    except Exception:
        return None

def get_schedule_arrivals(config, stop_id=None):
    import time as _time
    now = _time.localtime()
    current_total = now.tm_hour * 60 + now.tm_min

    bus_cfg = config.get("bus", {})
    stop_name = bus_cfg.get("stop_name", "")
    num_deps = bus_cfg.get("num_departures", 2)
    dest = stop_name

    smtt_entries = []
    if stop_id:
        from web.api.schedule_api import fetch_schedule
        smtt_entries = fetch_schedule(stop_id)

    if smtt_entries:
        lines = {}
        for entry in smtt_entries:
            line = entry["line"]
            lines.setdefault(line, []).append(entry["time"])

        result = []
        for line, times in lines.items():
            times.sort()
            upcoming = []
            for t in times:
                parts = t.strip().split(":")
                if len(parts) != 2:
                    continue
                try:
                    h, m = int(parts[0]), int(parts[1])
                    if h * 60 + m >= current_total:
                        upcoming.append(t)
                except ValueError:
                    continue
            slots_needed = num_deps
            if upcoming:
                for i in range(min(len(upcoming), slots_needed)):
                    result.append({
                        "line": line,
                        "destination": dest,
                        "minutes": 0,
                        "time_str": upcoming[i],
                        "live": False,
                    })
                    slots_needed -= 1
                for i in range(min(len(times), slots_needed)):
                    result.append({
                        "line": line,
                        "destination": dest,
                        "minutes": 0,
                        "time_str": times[i] + "+1",
                        "live": False,
                        "is_next_day": True,
                    })
            else:
                for i in range(min(len(times), num_deps)):
                    result.append({
                        "line": line,
                        "destination": dest,
                        "minutes": 0,
                        "time_str": times[i] + "+1",
                        "live": False,
                        "is_next_day": True,
                    })
        return result

    schedule = config.get("bus", {}).get("schedule", [])
    if not schedule:
        return []
    result = []
    for entry in schedule:
        line = entry.get("line", "")
        destination = entry.get("destination", "")
        times = entry.get("times", [])
        upcoming = []
        for t in times:
            parts = t.strip().split(":")
            if len(parts) != 2:
                continue
            try:
                h, m = int(parts[0]), int(parts[1])
                if h * 60 + m >= current_total:
                    upcoming.append(t)
            except ValueError:
                continue
        upcoming.sort()
        slots_needed = num_deps
        if upcoming:
            for i in range(min(len(upcoming), slots_needed)):
                result.append({
                    "line": line,
                    "destination": destination,
                    "minutes": 0,
                    "time_str": upcoming[i],
                    "live": False,
                })
                slots_needed -= 1
            for i in range(min(len(times), slots_needed)):
                result.append({
                    "line": line,
                    "destination": destination,
                    "minutes": 0,
                    "time_str": times[i] + "+1",
                    "live": False,
                    "is_next_day": True,
                })
        else:
            for i in range(min(len(times), num_deps)):
                result.append({
                    "line": line,
                    "destination": destination,
                    "minutes": 0,
                    "time_str": times[i] + "+1",
                    "live": False,
                    "is_next_day": True,
                })
    return result

def fetch_arrivals(stop_id):
    try:
        params = urllib.parse.urlencode({"stopid": stop_id})
        req = urllib.request.Request(
            f"https://live.stpt.ro/proxy-smtt-cache.php?{params}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        raw = data if isinstance(data, list) else data.get("arrivals") or []
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            times = item.get("times") or []
            minutes = 0
            time_str = ""
            if isinstance(times, list) and len(times) > 0:
                parts = str(times[0]).split("|")
                time_str = parts[0].strip()
                if len(parts) > 1 and parts[1].strip().isdigit():
                    minutes = int(parts[1].strip())
            result.append({
                "line": str(item.get("line") or item.get("route") or ""),
                "destination": str(item.get("headsign") or item.get("destination") or ""),
                "minutes": minutes,
                "time_str": time_str,
                "live": True,
            })
        return result
    except Exception:
        return None

def resolve_greeting(config):
    name = config.get("name", "")
    display_cfg = config.get("display", {})
    greeting = display_cfg.get("greeting", "auto")
    if greeting != "auto":
        return greeting.replace("{name}", name)
    if not name:
        return ""
    return f"Salut, {name}!"

def render(config: dict) -> str:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)

    loc = config.get("location", {})
    lat, lon = loc.get("lat"), loc.get("lon")
    bus_cfg = config.get("bus", {})
    stop_id = bus_cfg.get("stop_id", "")
    stop_name = bus_cfg.get("stop_name", "")

    weather = fetch_weather(lat or 45.75, lon or 21.21) if (lat and lon) else None
    arrivals = fetch_arrivals(stop_id) if stop_id else None
    if arrivals:
        num_deps = bus_cfg.get("num_departures", 2)
        live_keys = set()
        for a in arrivals:
            live_keys.add((a.get("line", ""), a.get("destination", "")))
        if len(live_keys) < num_deps:
            sched = get_schedule_arrivals(config, stop_id=stop_id) if stop_id else None
            if sched:
                covered = set(live_keys)
                for sa in sched:
                    skey = (sa.get("line", ""), sa.get("destination", ""))
                    if skey not in covered:
                        arrivals.append(sa)
                        covered.add(skey)
                        if len(covered) >= num_deps:
                            break
    if not arrivals:
        stop_id = bus_cfg.get("stop_id", "")
        if stop_id:
            schedule_arrivals = get_schedule_arrivals(config, stop_id=stop_id)
            if schedule_arrivals:
                arrivals = schedule_arrivals

    greeting = resolve_greeting(config)

    grouped = {}
    live_status = {}
    if arrivals:
        for a in arrivals:
            key = (a.get("line", ""), a.get("destination", ""))
            time_display = a.get("time_str", "")
            if a.get("live") and a.get("minutes", 0) == 0:
                time_display = "now"
            elif not time_display:
                time_display = str(a.get("minutes", 0)) + "m"
            grouped.setdefault(key, []).append(time_display)
            if a.get("live"):
                live_status[key] = True

    has_bus = bool(arrivals and grouped)
    has_bus_config = bool(stop_name)

    y = 6

    if greeting:
        draw.text((8, y), greeting, fill=BLACK, font=FONT_LG)
    if weather:
        sym = WEATHER_SYMBOLS.get(weather.get("code", 0), "?")
        temp = weather.get("temp", "?")
        tw = draw.textlength(f"{temp}\u00b0 {sym}", font=FONT_LG)
        draw.text((WIDTH - 8 - tw, y), f"{temp}\u00b0 {sym}", fill=BLACK, font=FONT_LG)

    try:
        now_str = _time.strftime("%H:%M")
        draw.text((8, y + 16), now_str, fill=BLACK, font=FONT_SM)
    except Exception:
        pass

    y += 26

    remaining = HEIGHT - y

    if not has_bus and not has_bus_config:
        if not config.get("setup_complete", False):
            msg = "Setup incomplete"
            tw = draw.textlength(msg, font=FONT_LG)
            draw.text(((WIDTH - tw) / 2, y), msg, fill=BLACK, font=FONT_LG)
            msg2 = "pizero2w.local:8080"
            tw2 = draw.textlength(msg2, font=FONT_SM)
            draw.text(((WIDTH - tw2) / 2, y + 16), msg2, fill=BLACK, font=FONT_SM)
        else:
            draw.text((8, y), "Open http://pizero2w.local:8080 to set up", fill=(128, 128, 128), font=FONT_SM)
            y += 14
    elif not has_bus and has_bus_config:
        h = f"\u2500\u2500 {stop_name[:24]} \u2500\u2500"
        tw = draw.textlength(h, font=FONT_SM)
        draw.text(((WIDTH - tw) / 2, y), h, fill=RED, font=FONT_SM)
        y += 12
        draw.text((12, y), "No arrivals now", fill=BLACK, font=FONT_SM)
    elif has_bus:
        num_deps_render = bus_cfg.get("num_departures", 2)
        below_h = 0
        if stop_name:
            below_h += 13
        below_h += 13 * min(len(grouped), num_deps_render)

        y_start = y + max(0, (remaining - below_h) // 2)

        if stop_name:
            h = f"\u2500\u2500 {stop_name[:24]} \u2500\u2500"
            tw = draw.textlength(h, font=FONT_SM)
            draw.text(((WIDTH - tw) / 2, y_start), h, fill=RED, font=FONT_SM)
            y_start += 13
        for idx, ((line, dest), times) in enumerate(grouped.items()):
            if idx >= num_deps_render:
                break
            ts = "  ".join(times[:num_deps_render])
            is_live = live_status.get((line, dest), False)
            draw.text((8, y_start), line, fill=RED if is_live else BLACK, font=FONT_MD)
            lw = draw.textlength(line, font=FONT_MD)
            tw2 = draw.textlength(ts, font=FONT_SM)
            label_max_w = (WIDTH - 8 - tw2) - (8 + lw + 4)
            label = truncate_by_width(dest, FONT_SM, max(label_max_w, 10), draw)
            x = 8 + lw + 2
            draw.text((x, y_start), label, fill=BLACK, font=FONT_SM)
            draw.text((WIDTH - 8 - tw2, y_start), ts, fill=BLACK, font=FONT_SM)
            y_start += 13

    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

if __name__ == "__main__":
    raw = sys.stdin.read()
    config = json.loads(raw) if raw else {}
    print(render(config))
