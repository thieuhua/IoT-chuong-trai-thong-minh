"""Over-the-air update of /app through ota_* commands (docs/protocol.md section 7).

Files are staged in /app_new and verified here. The swap itself is done by the loader (main.py)
on the next boot, from the "committing" state, so the running app never renames /app and a power
cut at any point is recoverable. The loader also rolls back if the new version never confirms.
"""
import binascii
import gc
import hashlib
import json
import os

APP_DIR = "/app"
NEW_DIR = "/app_new"
OLD_DIR = "/app_old"
OTA_FILE = "/ota.json"
CONFIG_FILE = "/config.json"
ALLOWED_EXT = (".py", ".mpy", ".json")
PATH_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_-./"
RESERVED = ("main.py", "boot.py")
MAX_FILES = 64
FREE_MARGIN = 64 * 1024


class OtaError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def rmtree(path):
    if not _exists(path):
        return
    if os.stat(path)[0] & 0x4000:
        for name in os.listdir(path):
            rmtree(path + "/" + name)
        os.rmdir(path)
    else:
        os.remove(path)


def _mkdirs(path):
    current = ""
    for part in path.strip("/").split("/")[:-1]:
        current += "/" + part
        if not _exists(current):
            os.mkdir(current)


def sha256_file(path):
    digest = hashlib.sha256()
    buf = bytearray(512)
    with open(path, "rb") as stream:
        while True:
            count = stream.readinto(buf)
            if not count:
                break
            digest.update(buf[:count] if count < 512 else buf)
    return binascii.hexlify(digest.digest()).decode()


def _copy(source, target):
    _mkdirs(target)
    buf = bytearray(512)
    with open(source, "rb") as src, open(target, "wb") as dst:
        while True:
            count = src.readinto(buf)
            if not count:
                break
            dst.write(buf[:count] if count < 512 else buf)


def check_path(path):
    """Relative path inside /app; config.json is the only file that lands outside it."""
    if (not isinstance(path, str) or not path or len(path) > 64 or path[0] == "/"
            or ".." in path or "//" in path or path in RESERVED
            or any(c not in PATH_CHARS for c in path) or not path.endswith(ALLOWED_EXT)):
        raise OtaError("bad_args", "invalid path: " + str(path))
    return path


def load_state():
    try:
        with open(OTA_FILE) as stream:
            state = json.load(stream)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    with open(OTA_FILE + ".tmp", "w") as stream:
        json.dump(state, stream)
    os.rename(OTA_FILE + ".tmp", OTA_FILE)


def current_version(default):
    return load_state().get("version") or default


def _current_hash(path):
    try:
        return sha256_file(CONFIG_FILE if path == "config.json" else APP_DIR + "/" + path)
    except OSError:
        return None


class Receiver:
    """One update in progress. Lives in RAM only; a reboot simply discards it."""

    def __init__(self, version, files):
        if not isinstance(version, str) or not 1 <= len(version) <= 40:
            raise OtaError("bad_args", "version must be a 1..40 char string")
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
            raise OtaError("bad_args", "files must be a list of 1..%d entries" % MAX_FILES)
        state = load_state().get("state", "ok")
        if state != "ok":
            raise OtaError("ota_error", "previous update is still '%s'; wait for it to confirm" % state)
        self.version = version
        self.files = {}
        total = 0
        for entry in files:
            if not isinstance(entry, dict):
                raise OtaError("bad_args", "file entry must be an object")
            path = check_path(entry.get("path"))
            size, digest = entry.get("size"), entry.get("sha256")
            if type(size) is not int or size < 0 or not isinstance(digest, str) or len(digest) != 64:
                raise OtaError("bad_args", "bad size/sha256 for " + path)
            if path in self.files:
                raise OtaError("bad_args", "duplicate path " + path)
            self.files[path] = {"size": size, "sha256": digest, "written": 0, "need": True}
            total += size
        if "app.py" not in self.files:
            raise OtaError("bad_args", "update must contain app.py")
        rmtree(OLD_DIR)  # stale leftovers only: state is "ok", so nothing can roll back to it
        rmtree(NEW_DIR)
        stat = os.statvfs("/")
        if total + FREE_MARGIN > stat[0] * stat[3]:
            raise OtaError("ota_error", "not enough flash for %d bytes" % total)
        os.mkdir(NEW_DIR)
        for path, info in self.files.items():
            if _current_hash(path) == info["sha256"]:
                info["need"] = False
            elif info["size"] == 0:
                _mkdirs(NEW_DIR + "/" + path)
                open(NEW_DIR + "/" + path, "wb").close()
        self.manifest = [(e["path"], e["size"], e["sha256"]) for e in files]

    def same_manifest(self, version, files):
        try:
            return version == self.version and [
                (e["path"], e["size"], e["sha256"]) for e in files] == self.manifest
        except (KeyError, TypeError):
            return False

    def need(self):
        return [path for path, info in self.files.items() if info["need"] and info["size"]]

    def progress(self):
        return {path: info["written"] for path, info in self.files.items() if info["need"]}

    def chunk(self, path, offset, data):
        info = self.files.get(path)
        if info is None or not info["need"]:
            raise OtaError("bad_args", "path not expected: " + str(path))
        if type(offset) is not int or not isinstance(data, str):
            raise OtaError("bad_args", "offset must be int and data base64 text")
        if offset < info["written"]:
            return info["written"]  # duplicate (QoS 1 redelivery / backend retry): ack again
        if offset != info["written"]:
            raise OtaError("bad_args", "expected offset %d" % info["written"])
        try:
            raw = binascii.a2b_base64(data)
        except ValueError:
            raise OtaError("bad_args", "data is not base64")
        # a2b_base64 silently skips invalid characters; a length check catches that early
        # (commit would still reject the file by sha256).
        if len(data) % 4 or len(raw) != len(data) // 4 * 3 - data[-2:].count("="):
            raise OtaError("bad_args", "data is not valid base64")
        if info["written"] + len(raw) > info["size"]:
            raise OtaError("bad_args", "data beyond declared size of " + path)
        target = NEW_DIR + "/" + path
        if offset == 0:
            _mkdirs(target)
        with open(target, "ab" if offset else "wb") as stream:
            stream.write(raw)
        info["written"] += len(raw)
        del raw
        gc.collect()
        return info["written"]

    def commit(self, running_version):
        """Verify /app_new, complete it with unchanged files, hand over to the loader."""
        for path, info in self.files.items():
            if info["need"]:
                if info["written"] != info["size"]:
                    raise OtaError("ota_error", "incomplete file " + path)
                if sha256_file(NEW_DIR + "/" + path) != info["sha256"]:
                    raise OtaError("ota_error", "sha256 mismatch for " + path)
            elif path != "config.json":
                _copy(APP_DIR + "/" + path, NEW_DIR + "/" + path)
        config = self.files.get("config.json")
        _save_state({"state": "committing", "boots": 0, "version": self.version,
                     "prev": running_version, "config": bool(config and config["need"])})

    def status(self):
        return {"version": self.version, "need": self.need(), "written": self.progress()}


def abort():
    rmtree(NEW_DIR)


def loader_module():
    """main.py's module (MicroPython keeps it importable as __main__, not always in sys.modules)."""
    try:
        import __main__
        return __main__
    except ImportError:
        return None


def in_trial():
    return load_state().get("state") == "trial"


def confirm():
    """Called by the app once it has proven itself online; ends the trial."""
    state = load_state()
    if state.get("state") != "trial":
        return False
    state["state"] = "ok"
    state["boots"] = 0
    _save_state(state)
    loader = loader_module()
    if loader is not None and hasattr(loader, "confirmed"):
        loader.confirmed = True  # stops the loader's confirm deadline (RAM flag only)
    rmtree(OLD_DIR)
    return True
