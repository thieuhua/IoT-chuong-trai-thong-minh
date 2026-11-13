"""Bundle app firmware and submit an OTA job to the backend."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib import error, request
from urllib.parse import quote


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


def json_request(url: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
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
    args = parser.parse_args(argv)
    try:
        files = bundle(args.src, args.with_config)
        version = args.version or default_version(files)
        server = args.server.rstrip("/")
        job = json_request(f"{server}/devices/{quote(args.device, safe='')}/firmware", {
            "version": version, "files": {p: base64.b64encode(d).decode("ascii") for p, d in files.items()},
            "wait_confirm": not args.no_wait})
        print(f"Job {job['job_id']} version {version}", flush=True)
        sent = total = 0
        while True:
            status = json_request(f"{server}/firmware-jobs/{job['job_id']}")
            progress = status.get("progress") or {}
            sent, total = progress.get("sent", sent), progress.get("total", total)
            percent = sent * 100 / total if total else 0
            print(f"{progress.get('stage', status['state'])}: {sent}/{total} bytes ({percent:.1f}%)", flush=True)
            if status["state"] == "succeeded":
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
