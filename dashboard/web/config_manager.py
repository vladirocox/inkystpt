import os
import yaml
import threading
import fcntl
import tempfile
import bcrypt
from typing import Any

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/home/vladirocox/dashboard/config.yaml")
RELOAD_FLAG = "/tmp/reload_flag"

DEFAULT_CONFIG: dict[str, Any] = {
    "setup_complete": False,
    "password_hash": "",
    "name": "",
    "timezone": "Europe/Bucharest",
    "location": {"lat": 45.7489, "lon": 21.2087, "city": "Timisoara"},
    "bus": {
        "stop_id": "",
        "stop_name": "",
        "num_departures": 2,
        "show_arrival_time": True,
        "schedule": [],
    },
    "google_home": {
        "device_name": "",
        "show_now_playing": True,
    },
    "display": {
        "refresh_interval": 30,
        "theme": "default",
    },
    "system": {
        "cpu_temp": 0,
        "memory_usage": 0,
        "uptime": 0,
    },
}


class ConfigManager:
    def __init__(self, path: str = CONFIG_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._config: dict[str, Any] | None = None

    def _ensure_file(self):
        if not os.path.exists(self._path):
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as f:
                yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)

    def _read_file(self) -> dict[str, Any]:
        if not os.path.exists(self._path):
            return DEFAULT_CONFIG.copy()
        try:
            with open(self._path, "r") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = yaml.safe_load(f) or {}
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            return DEFAULT_CONFIG.copy()
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged

    def _write_file(self, config: dict[str, Any]):
        self._ensure_file()
        # Atomic write: write to temp file then rename
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yaml.dump(config, f, default_flow_style=False)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.replace(tmp_path, self._path)

    def signal_reload(self):
        with open(RELOAD_FLAG, "w") as f:
            f.write("reload")

    def get(self) -> dict[str, Any]:
        with self._lock:
            if self._config is None:
                self._config = self._read_file()
            return self._config.copy()

    def get_raw(self) -> dict[str, Any]:
        with self._lock:
            if self._config is None:
                self._config = self._read_file()
            return self._config

    def refresh(self):
        with self._lock:
            self._config = self._read_file()

    def update(self, updates: dict[str, Any]):
        with self._lock:
            config = self._read_file()
            self._deep_merge(config, updates)
            self._write_file(config)
            self._config = config
        self.signal_reload()

    def set_password(self, plain_password: str):
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
        self.update({"password_hash": hashed.decode("utf-8")})

    def verify_password(self, plain_password: str) -> bool:
        stored = self.get().get("password_hash", "")
        if not stored:
            return False
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), stored.encode("utf-8")
        )

    def is_setup_complete(self) -> bool:
        return self.get().get("setup_complete", False)

    def _deep_merge(self, base: dict, updates: dict):
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value


CONFIG = ConfigManager()
