"""Gateway settings. Values come from arguments or IOT_* / MQTT_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AuthMode(str, Enum):
    NONE = "none"      # anonymous broker (demo/deployment)
    DYNSEC = "dynsec"  # per-device accounts (deployment/)


@dataclass
class GatewayConfig:
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    username: str | None = "backend"
    password: str | None = None
    auth_mode: AuthMode = AuthMode.DYNSEC
    auto_approve: bool = False
    db_path: Path = Path("data/iot.sqlite3")
    command_timeout_s: float = 10.0
    # A device that sends nothing for max(offline_after_s, 3 x its interval_s) is marked offline,
    # even without an LWT (e.g. the broker restarted and replayed a stale retained "online").
    offline_after_s: float = 90.0
    liveness_check_s: float = 10.0
    connect_timeout_s: float = 10.0
    client_id_prefix: str = "backend"
    bootstrap_password: str | None = None
    broker_tls: bool = False
    # Secondary backend (e.g. a teammate working remotely): add devices seen on retained meta
    # to the local registry instead of ignoring them. Keep off on the main backend, so a
    # revoked device does not come back from a stale retained message.
    adopt_devices: bool = False

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> GatewayConfig:
        """Read deployment settings, with process environment taking precedence."""
        env = dict(os.environ)
        if env_file is not None and Path(env_file).is_file():
            for line in Path(env_file).read_text(encoding="utf-8").splitlines():
                key, sep, value = line.strip().partition("=")
                if sep and not key.startswith("#"):
                    env.setdefault(key.strip(), value.strip())
        mode = AuthMode(env.get("IOT_AUTH_MODE", AuthMode.DYNSEC.value))
        tls = env.get("IOT_BROKER_TLS", "0").lower()
        if tls not in {"0", "1", "false", "true", "no", "yes"}:
            raise ValueError("IOT_BROKER_TLS must be 0 or 1 (or false/true, no/yes)")
        return cls(
            broker_host=env.get("IOT_BROKER_HOST", cls.broker_host),
            broker_port=int(env.get("IOT_BROKER_PORT", cls.broker_port)),
            username=env.get("IOT_BROKER_USERNAME", "backend") if mode is AuthMode.DYNSEC else None,
            password=env.get("MQTT_BACKEND_PASSWORD") if mode is AuthMode.DYNSEC else None,
            auth_mode=mode,
            auto_approve=env.get("IOT_AUTO_APPROVE", "0").lower() in {"1", "true", "yes"},
            db_path=Path(env.get("IOT_DB_PATH", str(cls.db_path))),
            command_timeout_s=float(env.get("IOT_COMMAND_TIMEOUT", cls.command_timeout_s)),
            offline_after_s=float(env.get("IOT_OFFLINE_AFTER", cls.offline_after_s)),
            connect_timeout_s=float(env.get("IOT_CONNECT_TIMEOUT", cls.connect_timeout_s)),
            client_id_prefix=env.get("IOT_CLIENT_ID_PREFIX", cls.client_id_prefix),
            bootstrap_password=env.get("MQTT_BOOTSTRAP_PASSWORD"),
            broker_tls=tls in {"1", "true", "yes"},
            adopt_devices=env.get("IOT_ADOPT_DEVICES", "0").lower() in {"1", "true", "yes"},
        )
