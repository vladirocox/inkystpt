import threading
import time
from typing import Any


class CastAPI:
    def __init__(self):
        self._lock = threading.Lock()

    def scan_devices(self, timeout: int = 10) -> list[dict]:
        try:
            from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

            discovered = []

            class CastListener(ServiceListener):
                def add_service(self, zc, type_, name):
                    info = zc.get_service_info(type_, name)
                    if info:
                        props = info.properties
                        discovered.append({
                            "name": name.replace("._googlecast._tcp.local.", "").replace("._googlecast._tcp.local", ""),
                            "host": str(info.server) if info.server else "",
                            "port": info.port,
                            "uuid": str(props.get(b"id", b"").decode("utf-8")) if props.get(b"id") else "",
                            "model": str(props.get(b"md", b"").decode("utf-8")) if props.get(b"md") else "",
                        })

                def remove_service(self, zc, type_, name):
                    pass

                def update_service(self, zc, type_, name):
                    pass

            zc = Zeroconf()
            listener = CastListener()
            browser = ServiceBrowser(zc, "_googlecast._tcp.local.", listener)
            time.sleep(timeout)
            browser.cancel()
            zc.close()
            return discovered
        except ImportError as e:
            return [{"error": f"zeroconf not available: {e}"}]
        except Exception as e:
            return [{"error": str(e)}]


CAST_API = CastAPI()
