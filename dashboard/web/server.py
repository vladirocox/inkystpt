import os
import time
import uuid
import hashlib
import hmac
import subprocess
import json
import urllib.request, urllib.parse

from flask import (
    Flask, request, jsonify, render_template,
    redirect, url_for, make_response, session as flask_session,
)
from functools import wraps

from .config_manager import CONFIG
from .api.bus_api import BUS_API
from .api.cast_api import CAST_API
from .api.weather_api import WEATHER_API

app = Flask(__name__)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest(),
)

SESSION_TTL = 1800


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not CONFIG.is_setup_complete():
            return f(*args, **kwargs)
        user_id = flask_session.get("user_id")
        login_time = flask_session.get("login_time", 0)
        if not user_id or (time.time() - login_time) > SESSION_TTL:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login"))
        flask_session["login_time"] = time.time()
        return f(*args, **kwargs)
    return decorated


def setup_redirect(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if CONFIG.is_setup_complete():
            return redirect(url_for("settings"))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_config():
    return {"config": CONFIG.get()}


@app.route("/")
def index():
    if not CONFIG.is_setup_complete():
        return redirect(url_for("setup"))
    user_id = flask_session.get("user_id")
    if not user_id or (time.time() - flask_session.get("login_time", 0)) > SESSION_TTL:
        return redirect(url_for("login"))
    return redirect(url_for("settings"))


@app.route("/setup")
@setup_redirect
def setup():
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if CONFIG.is_setup_complete():
            user_id = flask_session.get("user_id")
            if user_id and (time.time() - flask_session.get("login_time", 0)) <= SESSION_TTL:
                return redirect(url_for("settings"))
        return render_template("login.html")

    data = request.get_json() or {}
    password = data.get("password", "")
    if CONFIG.verify_password(password):
        flask_session["user_id"] = str(uuid.uuid4())
        flask_session["login_time"] = time.time()
        return jsonify({"ok": True})
    return jsonify({"error": "invalid_password"}), 401


@app.route("/logout")
def logout():
    flask_session.clear()
    return redirect(url_for("login"))


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/api/config", methods=["GET"])
@login_required
def get_config():
    return jsonify(CONFIG.get())


@app.route("/api/config", methods=["POST"])
@login_required
def update_config():
    data = request.get_json() or {}
    CONFIG.update(data)
    return jsonify({"ok": True})


@app.route("/api/setup/password", methods=["POST"])
def setup_password():
    if CONFIG.is_setup_complete():
        return jsonify({"error": "already_configured"}), 403
    data = request.get_json() or {}
    password = data.get("password", "")
    confirm = data.get("confirm_password", "")
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if password != confirm:
        return jsonify({"error": "Passwords do not match"}), 400
    CONFIG.set_password(password)
    flask_session["user_id"] = str(uuid.uuid4())
    flask_session["login_time"] = time.time()
    return jsonify({"ok": True})


@app.route("/api/setup/details", methods=["POST"])
@login_required
def setup_details():
    data = request.get_json() or {}
    updates = {}
    if "name" in data:
        updates["name"] = data["name"]
    if "timezone" in data:
        updates["timezone"] = data["timezone"]
    if "location" in data:
        updates["location"] = data["location"]
    CONFIG.update(updates)
    return jsonify({"ok": True})


@app.route("/api/setup/bus", methods=["POST"])
@login_required
def setup_bus():
    data = request.get_json() or {}
    bus_updates = {}
    if "stop_id" in data:
        bus_updates["stop_id"] = data["stop_id"]
    if "stop_name" in data:
        bus_updates["stop_name"] = data["stop_name"]
    if bus_updates:
        CONFIG.update({"bus": bus_updates})
    return jsonify({"ok": True})


@app.route("/api/setup/google-home", methods=["POST"])
@login_required
def setup_google_home():
    data = request.get_json() or {}
    gh_updates = {}
    if "device_name" in data:
        gh_updates["device_name"] = data["device_name"]
    if gh_updates:
        CONFIG.update({"google_home": gh_updates})
    return jsonify({"ok": True})


@app.route("/api/setup/complete", methods=["POST"])
@login_required
def setup_complete():
    CONFIG.update({"setup_complete": True})
    flask_session["user_id"] = str(uuid.uuid4())
    flask_session["login_time"] = time.time()
    return jsonify({"ok": True})


@app.route("/api/bus/search")
@login_required
def bus_search():
    q = request.args.get("q", "").strip()
    stations = BUS_API.search_stations(q)
    return jsonify({"stations": stations})


@app.route("/api/bus/preview")
@login_required
def bus_preview():
    stop_id = request.args.get("stop_id", "").strip()
    if not stop_id:
        return jsonify({"error": "missing_stop_id"}), 400
    arrivals = BUS_API.get_arrivals(stop_id)
    return jsonify({"arrivals": arrivals})


@app.route("/api/cast/scan")
@login_required
def cast_scan():
    devices = CAST_API.scan_devices()
    return jsonify({"devices": devices})


@app.route("/api/system/info")
@login_required
def system_info():
    info = {"cpu_temp": "N/A", "memory_usage": "N/A", "uptime": 0}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            raw = f.read().strip()
            info["cpu_temp"] = round(int(raw) / 1000, 1)
    except Exception:
        pass
    try:
        total = 0
        available = 0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1])
        if total:
            info["memory_usage"] = round((1 - available / total) * 100, 1)
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            info["uptime"] = int(float(f.read().split()[0]))
    except Exception:
        pass
    return jsonify(info)


@app.route("/api/display/refresh", methods=["POST"])
@login_required
def display_refresh():
    open("/tmp/reload_flag", "w").close()
    return jsonify({"ok": True})


@app.route("/api/mock-render", methods=["POST"])
@login_required
def mock_render():
    data = request.get_json() or {}
    import sys, subprocess, os
    config_json = json.dumps(data)
    dashboard_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
            [sys.executable, os.path.join(dashboard_dir, "mock_render.py")],
            input=config_json,
            capture_output=True,
            text=True,
            timeout=15,
    )
    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip()}), 500
    return jsonify({"png_base64": result.stdout.strip()})


@app.route("/api/geocode/search")
@login_required
def geocode_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "missing_query"}), 400
    try:
        params = urllib.parse.urlencode({
            "name": q, "count": 5, "language": "en", "format": "json"
        })
        req = urllib.request.Request(
            f"https://geocoding-api.open-meteo.com/v1/search?{params}",
            headers={"User-Agent": "Dashboard/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        results = data.get("results", [])
        transformed = []
        for r in results:
            parts = []
            if r.get("country"): parts.append(r["country"])
            if r.get("admin1"): parts.append(r["admin1"])
            if r.get("name"): parts.insert(0, r["name"])
            transformed.append({
                "display_name": ", ".join(parts),
                "lat": r.get("latitude", 0),
                "lon": r.get("longitude", 0),
            })
        return jsonify({"results": transformed})
    except Exception as e:
        return jsonify({"results": transformed})


@app.route("/api/geocode/reverse")
@login_required
def geocode_reverse():
    lat = request.args.get("lat", "").strip()
    lon = request.args.get("lon", "").strip()
    if not lat or not lon:
        return jsonify({"city": ""})
    try:
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&addressdetails=1",
            headers={"User-Agent": "Dashboard/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        addr = data.get("address", {})
        city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or ""
        return jsonify({"city": city})
    except Exception:
        return jsonify({"city": ""})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
