"""Bundle app firmware and submit an OTA job to the backend."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib import error, request
from urllib.parse import quote


STAGE_TEXT = {
    "begin": "device compares file hashes",
    "commit": "device verifies sha256",
    "reboot": "rebooting, loader installs the new /app",
    "trial": "new version running on trial (confirms after ~30 s online)",
    "done": "confirmed",
}


def bundle(source: Path, with_config: bool = False) -> dict[str, bytes]:
    if not source.is_dir():
        raise ValueError(f"Source directory does not exist: {source}")
    files = {}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not path.is_file() or "__pycache__" in relative.parts or path.name == "main.py":
            continue
        if path.suffix in (".py", ".mpy") or (with_config and relative.as_posix() == "config.json"):
            files[relative.as_posix()] = path.read_bytes()
    if "app.py" not in files:
        raise ValueError("Source must contain app.py")
    return files


def default_version(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, data in sorted(files.items()):
        name = path.encode("utf-8")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + digest.hexdigest()[:8]


# An OTA job with trial confirmation can take minutes; the token only lives in this process.
TOKEN_LIFETIME = timedelta(hours=2)
_auth = {"admin": None, "header": None}


def auth_header() -> dict[str, str]:
    """Bearer token of an active Admin, signed with JWT_SECRET_KEY from deployment/.env."""
    if _auth["header"] is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app import models
        from app.database import SessionLocal
        from app.services import auth
        if SessionLocal.kw.get("bind") is None:
            raise ValueError("DATABASE_URL is missing in deployment/.env")
        with SessionLocal() as db:
            query = db.query(models.User).filter(models.User.role == "Admin",
                                                 models.User.status == "active")
            if _auth["admin"]:
                query = query.filter(models.User.username == _auth["admin"])
            user = query.order_by(models.User.username).first()
            if user is None:
                raise ValueError("No active Admin account"
                                 + (f" named {_auth['admin']}" if _auth["admin"] else ""))
            token, _ = auth.create_token(user.id, "access", TOKEN_LIFETIME)
        _auth["header"] = {"Authorization": f"Bearer {token}"}
    return _auth["header"]


def json_request(url: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json", **auth_header()})
    with request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--src", type=Path, default=Path("../firmware/src"))
    parser.add_argument("--version")
    parser.add_argument("--with-config", action="store_true")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--no-wait", action="store_true", help="Skip device confirmation; still poll the upload job")
    parser.add_argument("--admin", help="Admin username used to sign the token (default: first active Admin)")
    args = parser.parse_args(argv)
    _auth["admin"] = args.admin
    try:
        files = bundle(args.src, args.with_config)
        version = args.version or default_version(files)
        server = args.server.rstrip("/")
        job = json_request(f"{server}/devices/{quote(args.device, safe='')}/firmware", {
            "version": version, "files": {p: base64.b64encode(d).decode("ascii") for p, d in files.items()},
            # Always true: the server job's ota_status polling is the command the device needs in
            # order to confirm a trial. --no-wait only stops this CLI from watching.
            "wait_confirm": True})
        print(f"Job {job['job_id']} version {version}", flush=True)
        last = None
        while True:
            status = json_request(f"{server}/firmware-jobs/{job['job_id']}")
            progress = status.get("progress") or {}
            stage = progress.get("stage", status["state"])
            if stage == "upload":
                sent, total = progress.get("sent", 0), progress.get("total", 0)
                line = f"upload: {sent}/{total} bytes ({sent * 100 / total if total else 100:.0f}%)"
            else:
                line = f"{stage}: {STAGE_TEXT.get(stage, '')}".rstrip(": ")
            if line != last:
                print(line, flush=True)
                last = line
            if args.no_wait and stage in ("reboot", "trial") and status["state"] == "running":
                print(f"Installed; the server keeps watching the trial (job {job['job_id']}).", flush=True)
                return 0
            if status["state"] == "succeeded":
                result = status.get("result") or {}
                print(f"OK: {result.get('version', version)} {result.get('state', '')}, "
                      f"sent {result.get('sent_files', '?')}/{result.get('files', '?')} files, "
                      f"{result.get('sent_bytes', '?')} bytes", flush=True)
                return 0
            if status["state"] == "failed":
                print(status.get("error") or "Firmware job failed", file=sys.stderr)
                return 1
            time.sleep(1)
    except error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        return 2
    except (error.URLError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
