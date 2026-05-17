import json, os, time, sys, hashlib, urllib.request, urllib.parse
from PIL import Image, ImageDraw, ImageFont
from inky import WHITE, BLACK, RED

CONFIG_PATH = os.environ.get("CONFIG_PATH", os.path.join(os.path.dirname(__file__), "config.yaml"))
RELOAD_FLAG = "/tmp/reload_flag"

sys.path.insert(0, os.path.dirname(__file__))
from web.config_manager import CONFIG

WIDTH, HEIGHT = 212, 104

try:
    FONT_LG = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
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

_CAST_CACHE = None
_LAST_CRITICAL = None
_FORCE_REFRESH = True
_LAST_NP = None
_MIN_UPDATE_INTERVAL = 60
_LAST_UPDATE_TIME = 0

def sanitize_np_text(text):
    result = []
    for c in text:
        cp = ord(c)
        if 0x20 <= cp < 0x7F:
            result.append(c)
        elif 0xA0 <= cp <= 0xFF:
            result.append(c)
        elif 0x100 <= cp <= 0x24F:
            result.append(c)
        elif 0x250 <= cp <= 0x2AF:
            result.append(c)
        elif 0x2B0 <= cp <= 0x2FF:
            result.append(c)
        elif 0x300 <= cp <= 0x36F:
            result.append(c)
        elif 0x370 <= cp <= 0x3FF:
            result.append(c)
        elif 0x400 <= cp <= 0x52F:
            result.append(c)
        elif 0x2000 <= cp <= 0x2BFF:
            result.append(c)
        elif cp == 0xFEFF:
            continue
    return ''.join(result)

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
    now = time.localtime()
    current_total = now.tm_hour * 60 + now.tm_min

    bus_cfg = config.get("bus", {})
    stop_name = bus_cfg.get("stop_name", "")
    num_deps = bus_cfg.get("num_departures", 2)
    dest = stop_name

    # Try smtt.ro scraper first
    smtt_entries = []
    if stop_id:
        from web.api.schedule_api import fetch_schedule
        smtt_entries = fetch_schedule(stop_id)

    if smtt_entries:
        # Group times by line
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
                # Fill remaining slots with tomorrow's first departures
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
                # All times passed for today — show tomorrow times with +1
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

    # Fallback to user-entered config schedule
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

def fetch_now_playing(config):
    global _CAST_CACHE
    cast_cfg = config.get("google_home", {})
    if not cast_cfg.get("show_now_playing"):
        return None
    dev_name = cast_cfg.get("device_name", "")
    if not dev_name:
        return None

    uuid_str = dev_name.split("-")[-1]
    host = port = None

    if _CAST_CACHE and _CAST_CACHE.get("uuid") == uuid_str:
        host, port = _CAST_CACHE["host"], _CAST_CACHE["port"]

    if not host:
        try:
            from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
            found = []
            class L(ServiceListener):
                def add_service(s, zc, t, n):
                    info = zc.get_service_info(t, n)
                    if info and info.properties and info.properties.get(b"id", b"").decode() == uuid_str:
                        found.append({"host": str(info.server), "port": info.port, "uuid": uuid_str})
                def remove_service(s, zc, t, n): pass
                def update_service(s, zc, t, n): pass
            zc = Zeroconf()
            b = ServiceBrowser(zc, "_googlecast._tcp.local.", L())
            time.sleep(2)
            b.cancel()
            zc.close()
            if found:
                host, port = found[0]["host"], found[0]["port"]
                _CAST_CACHE = found[0]
        except Exception:
            return None

    if not host:
        return None

    try:
        from uuid import UUID
        import pychromecast
        cast = pychromecast.get_chromecast_from_host(
            (host, port, UUID(uuid_str), None, None)
        )
        cast.wait(5)
        mc = cast.media_controller
        mc.block_until_active(3)
        status = mc.status
        cast.disconnect()
        if status and status.player_state == "PLAYING":
            return {"title": sanitize_np_text(status.title or ""), "artist": sanitize_np_text(status.artist or "")}
    except Exception:
        return None
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

def compute_critical_hash(weather, arrivals, now_playing):
    h = {}
    if weather:
        h["w"] = (round(weather.get("temp", 0)), weather.get("code"))
    if arrivals:
        h["a"] = sorted(
            (a["line"], a["destination"], a.get("time_str", ""), a.get("minutes", 0))
            for a in arrivals if a.get("line") and a.get("destination")
        )
    if now_playing:
        h["n"] = (now_playing.get("title", ""), now_playing.get("artist", ""))
    return hashlib.md5(json.dumps(h, sort_keys=True).encode()).hexdigest()

def render(config, weather=None, arrivals=None, now_playing=None, greeting=None):
    img = Image.new("P", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)

    bus_cfg = config.get("bus", {})
    stop_name = bus_cfg.get("stop_name", "")

    if weather is None:
        loc = config.get("location", {})
        lat, lon = loc.get("lat"), loc.get("lon")
        if lat and lon:
            weather = fetch_weather(lat, lon)
    if arrivals is None:
        stop_id = bus_cfg.get("stop_id", "")
        if stop_id:
            live_arrivals = fetch_arrivals(stop_id)
            if live_arrivals:
                num_deps = bus_cfg.get("num_departures", 2)
                live_keys = set()
                for a in live_arrivals:
                    live_keys.add((a.get("line", ""), a.get("destination", "")))
                if len(live_keys) < num_deps:
                    sched = get_schedule_arrivals(config, stop_id=stop_id)
                    if sched:
                        covered = set(live_keys)
                        for sa in sched:
                            skey = (sa.get("line", ""), sa.get("destination", ""))
                            if skey not in covered:
                                live_arrivals.append(sa)
                                covered.add(skey)
                                if len(covered) >= num_deps:
                                    break
                arrivals = live_arrivals
    if not arrivals:
        stop_id = bus_cfg.get("stop_id", "")
        if stop_id:
            schedule_arrivals = get_schedule_arrivals(config, stop_id=stop_id)
            if schedule_arrivals:
                arrivals = schedule_arrivals
    if now_playing is None:
        now_playing = fetch_now_playing(config)

    if greeting is None:
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

    # Greeting + weather - always at top
    if greeting:
        draw.text((8, y), greeting, fill=BLACK, font=FONT_LG)
    if weather:
        sym = WEATHER_SYMBOLS.get(weather.get("code", 0), "?")
        temp = weather.get("temp", "?")
        tw = draw.textlength(f"{temp}\u00b0 {sym}", font=FONT_LG)
        draw.text((WIDTH - 8 - tw, y), f"{temp}\u00b0 {sym}", fill=BLACK, font=FONT_LG)

    # Current time below greeting
    try:
        now_str = time.strftime("%H:%M")
        draw.text((8, y + 16), now_str, fill=BLACK, font=FONT_SM)
    except Exception:
        pass

    y += 26

    # Calculate remaining space and what to draw below
    remaining = HEIGHT - y

    if not has_bus and now_playing:
        # Big now-playing mode - fill remaining space
        title = now_playing.get("title", "").strip()
        artist = now_playing.get("artist", "").strip()

        title = truncate_by_width(title, FONT_LG, WIDTH - 16, draw)
        artist = truncate_by_width(artist, FONT_SM, WIDTH - 16, draw)

        if greeting:
            title_prefix = "\u266a "
        else:
            title_prefix = ""

        # Center title+artist in remaining space
        title_line = title_prefix + title
        artist_line = artist

        th = 16  # FONT_LG height approx
        ah = 12  # FONT_SM height approx
        total_h = th + ah + 4
        y_start = y + max(0, (remaining - total_h) // 2)

        tw = draw.textlength(title_line, font=FONT_LG)
        draw.text(((WIDTH - tw) / 2, y_start), title_line, fill=BLACK, font=FONT_LG)
        if artist:
            tw2 = draw.textlength(artist_line, font=FONT_SM)
            draw.text(((WIDTH - tw2) / 2, y_start + th + 4), artist_line, fill=BLACK, font=FONT_SM)

        return img

    if now_playing or has_bus or has_bus_config:
        num_deps_render = bus_cfg.get("num_departures", 2)
        # Calculate total height of below section
        below_h = 18  # now-playing row + gap
        if has_bus:
            if stop_name:
                below_h += 13
            below_h += 13 * min(len(grouped), num_deps_render)
        elif has_bus_config:
            below_h += 25

        # Center below section in remaining space
        y_start = y + max(0, (remaining - below_h) // 2)

        # Now-playing
        if now_playing:
            t = now_playing.get("title", "").strip()
            a = now_playing.get("artist", "").strip()
            line = "\u266a " + t
            if a:
                line += "  -  " + a
            line = truncate_by_width(line, FONT_SM, WIDTH - 16, draw)
            tw = draw.textlength(line, font=FONT_SM)
            draw.text(((WIDTH - tw) / 2, y_start), line, fill=BLACK, font=FONT_SM)
        y_start += 18

        # Bus section
        if has_bus:
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
                # Truncate label to fit between line code and times
                label_max_w = (WIDTH - 8 - tw2) - (8 + lw + 4)
                label = truncate_by_width(dest, FONT_SM, max(label_max_w, 10), draw)
                x = 8 + lw + 2
                draw.text((x, y_start), label, fill=BLACK, font=FONT_SM)
                draw.text((WIDTH - 8 - tw2, y_start), ts, fill=BLACK, font=FONT_SM)
                y_start += 13
        elif has_bus_config:
            h = f"\u2500\u2500 {stop_name[:24]} \u2500\u2500"
            tw = draw.textlength(h, font=FONT_SM)
            draw.text(((WIDTH - tw) / 2, y_start), h, fill=RED, font=FONT_SM)
            y_start += 12
            draw.text((12, y_start), "No arrivals now", fill=BLACK, font=FONT_SM)
    elif not config.get("setup_complete", False):
        msg = "Setup incomplete"
        tw = draw.textlength(msg, font=FONT_LG)
        draw.text(((WIDTH - tw) / 2, y), msg, fill=BLACK, font=FONT_LG)
        msg2 = "pizero2w.local:8080"
        tw2 = draw.textlength(msg2, font=FONT_SM)
        draw.text(((WIDTH - tw2) / 2, y + 16), msg2, fill=BLACK, font=FONT_SM)

    return img

def update_display(img):
    img = img.rotate(180)
    try:
        from inky import InkyPHAT
        inky = InkyPHAT("red")
        inky.set_image(img)
        inky.show()
    except ImportError:
        img.save("/tmp/dashboard_preview.png")

if __name__ == "__main__":
    while True:
        try:
            CONFIG.refresh()
            cfg = CONFIG.get()
            weather = fetch_weather(
                cfg.get("location", {}).get("lat", 45.75),
                cfg.get("location", {}).get("lon", 21.21),
            )
            arrivals = fetch_arrivals(cfg.get("bus", {}).get("stop_id", ""))
            now_playing = fetch_now_playing(cfg)

            critical = compute_critical_hash(weather, arrivals, now_playing)
            now = time.time()

            np_key = (now_playing["title"], now_playing["artist"]) if now_playing else None
            is_np_change = (_LAST_NP is not None and np_key != _LAST_NP)

            if critical != _LAST_CRITICAL and (is_np_change or (now - _LAST_UPDATE_TIME) >= _MIN_UPDATE_INTERVAL):
                greeting = resolve_greeting(cfg)
                img = render(cfg, weather, arrivals, now_playing, greeting=greeting)
                update_display(img)
                _LAST_CRITICAL = critical
                _LAST_NP = np_key
                _LAST_UPDATE_TIME = now
                _FORCE_REFRESH = False
                print(f"Updated: {weather.get('temp') if weather else '?'}", file=sys.stderr)
            else:
                print("Skipped", file=sys.stderr)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)

        interval = CONFIG.get().get("display", {}).get("refresh_interval", 30)
        if _FORCE_REFRESH:
            interval = min(interval, 15)
        for _ in range(interval):
            time.sleep(1)
            if os.path.exists(RELOAD_FLAG):
                os.unlink(RELOAD_FLAG)
                _LAST_CRITICAL = None
                _LAST_UPDATE_TIME = 0
                break
