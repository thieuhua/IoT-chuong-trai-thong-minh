"""Serve the phone UI and forward servo commands to the local IoT API."""

import argparse
from datetime import timedelta
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TOKEN_LIFETIME = timedelta(minutes=30)
TOKEN_RENEW_BEFORE_S = 300


class AdminToken:
    """Access token of an active Admin, signed with JWT_SECRET_KEY from deployment/.env.

    Stays inside this process: the phone page never receives it. Renewed before it expires.
    """

    def __init__(self, username=None):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
        from app import models
        from app.database import SessionLocal
        from app.services import auth
        self._models, self._sessions, self._auth = models, SessionLocal, auth
        self.username = username
        self._lock = threading.Lock()
        self._token, self._expires_at = None, 0.0
        self.user = self._find_admin()

    def _find_admin(self):
        if self._sessions.kw.get("bind") is None:
            raise SystemExit("DATABASE_URL is missing in deployment/.env")
        User = self._models.User
        with self._sessions() as db:
            query = db.query(User).filter(User.role == "Admin", User.status == "active")
            if self.username:
                query = query.filter(User.username == self.username)
            user = query.order_by(User.username).first()
            if user is None:
                raise SystemExit("No active Admin account" + (f" named {self.username}" if self.username else ""))
            return user.id, user.username

    def header(self):
        with self._lock:
            if time.time() >= self._expires_at - TOKEN_RENEW_BEFORE_S:
                self._token, _ = self._auth.create_token(self.user[0], "access", TOKEN_LIFETIME)
                self._expires_at = time.time() + TOKEN_LIFETIME.total_seconds()
            return {"Authorization": f"Bearer {self._token}"}


class ServoDemoServer(ThreadingHTTPServer):
    def __init__(self, address, device_id, actuator, api_port, sensor="room", relay="relay", token=None,
                 relay2="relay2"):
        self.device_url = f"http://127.0.0.1:{api_port}/devices/{device_id}"
        self.actuator = actuator
        self.sensor = sensor
        # Page path -> actuator name in the ESP32 config.json.
        self.relays = {"/relay": relay, "/relay2": relay2}
        self.token = token
        self.page = Path(__file__).with_name("index.html").read_bytes()
        super().__init__(address, ServoDemoHandler)

    def auth_header(self):
        return self.token.header() if self.token else {}

    def command(self, name, args):
        body = {"name": name, "args": args}
        request = Request(f"{self.device_url}/commands", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", **self.auth_header()},
                          method="POST")
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    def set_angle(self, angle):
        return self.command("servo_set", {"name": self.actuator, "angle": angle})

    def relay_state(self, relay):
        return self.command("actuator_state", {"name": relay})

    def set_relay(self, relay, on, duration_ms=None):
        args = {"name": relay, "on": on}
        if duration_ms is not None:
            args["duration_ms"] = duration_ms
        return self.command("relay_set", args)

    def latest_reading(self):
        request = Request(f"{self.device_url}/telemetry/latest", headers=self.auth_header())
        with urlopen(request, timeout=5) as response:
            record = json.load(response)
        if record is None:
            return None
        readings = record["readings"]
        values = readings["values"].get(self.sensor, {})
        return {
            "temperature": values.get("temperature"),
            "humidity": values.get("humidity"),
            "received_at": record["received_at"],
            "sensor_error": readings["errors"].get(self.sensor),
        }


class ServoDemoHandler(BaseHTTPRequestHandler):
    def respond(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, status, body):
        self.respond(status, json.dumps(body).encode())

    def command_response(self, call, failure):
        try:
            result = call()
        except HTTPError as exc:
            message = {401: "Backend từ chối token Admin của demo", 404: "Không tìm thấy thiết bị",
                       409: "Thiết bị đang offline", 504: "ESP32 chưa phản hồi"}.get(exc.code, failure)
            try:
                code = json.load(exc).get("code")
            except (ValueError, AttributeError):
                code = None
            if code == "unknown_command":
                message = "Firmware trên ESP32 chưa hỗ trợ lệnh này (cần nạp bản mới)"
            elif code == "actuator_not_found":
                message = "ESP32 chưa khai báo actuator này trong config.json"
            self.json_response(exc.code, {"error": message})
        except (TimeoutError, URLError, ValueError):
            self.json_response(502, {"error": "Không nhận được phản hồi từ backend"})
        else:
            self.json_response(200, result)

    def read_json(self, limit=128):
        if self.headers.get_content_type() != "application/json":
            raise ValueError
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= limit:
            raise ValueError
        body = json.loads(self.rfile.read(size))
        if not isinstance(body, dict):
            raise ValueError
        return body

    def do_GET(self):
        if self.path == "/":
            self.respond(200, self.server.page, "text/html; charset=utf-8")
        elif self.path in self.server.relays:
            relay = self.server.relays[self.path]
            self.command_response(lambda: self.server.relay_state(relay), "Không đọc được trạng thái relay")
        elif self.path == "/telemetry":
            try:
                reading = self.server.latest_reading()
            except HTTPError as exc:
                self.json_response(502, {"error": f"Backend trả lỗi {exc.code} khi đọc số đo"})
            except (TimeoutError, URLError, ValueError, KeyError, TypeError):
                self.json_response(502, {"error": "Không đọc được số đo từ backend"})
            else:
                self.json_response(200, reading)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path in self.server.relays:
            relay = self.server.relays[self.path]
            try:
                body = self.read_json()
                on, duration_ms = body.get("on"), body.get("duration_ms")
                if type(on) is not bool or not (duration_ms is None or (
                        type(duration_ms) is int and 100 <= duration_ms <= 86400000 and on)):
                    raise ValueError
            except ValueError:
                self.json_response(400, {"error": "Cần on true/false (duration_ms tùy chọn khi bật)"})
                return
            self.command_response(lambda: self.server.set_relay(relay, on, duration_ms),
                                  "Backend từ chối lệnh relay")
            return
        if self.path != "/angle":
            self.send_error(404)
            return
        if self.headers.get_content_type() != "application/json":
            self.json_response(415, {"error": "Expected application/json"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 128:
                raise ValueError
            body = json.loads(self.rfile.read(size))
            angle = body.get("angle") if isinstance(body, dict) else None
            if type(angle) is not int or not 0 <= angle <= 180:
                raise ValueError
        except ValueError:
            self.json_response(400, {"error": "Angle must be an integer from 0 to 180"})
            return
        try:
            state = self.server.set_angle(angle)
        except HTTPError as exc:
            message = {401: "Backend từ chối token Admin của demo", 404: "Không tìm thấy thiết bị",
                       409: "Thiết bị đang offline", 504: "ESP32 chưa phản hồi"}.get(
                           exc.code, "Backend từ chối lệnh servo")
            self.json_response(exc.code, {"error": message})
        except (TimeoutError, URLError, ValueError):
            self.json_response(502, {"error": "Không nhận được phản hồi từ backend"})
        else:
            self.json_response(200, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--actuator", default="servo")
    parser.add_argument("--sensor", default="room")
    parser.add_argument("--relay", default="relay", help="first relay (G26) name in config.json")
    parser.add_argument("--relay2", default="relay2", help="second relay (G27) name in config.json")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--admin", help="Admin username used to sign the token (default: first active Admin)")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{3,48}", args.device) or args.device == "provision":
        parser.error("invalid device ID")
    token = AdminToken(args.admin)
    with ServoDemoServer((args.bind, args.port), args.device, args.actuator,
                         args.api_port, args.sensor, args.relay, token, args.relay2) as server:
        print(f"Admin token for: {token.user[1]}", flush=True)
        print(f"http://{args.bind}:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
