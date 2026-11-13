"""Stable loader: never updated over the air. Installs staged OTA updates, runs /app, rolls back.

/ota.json (always written via tmp + rename):
  {"state": "ok" | "committing" | "trial", "boots": n, "version": "...", "prev": "...", "config": bool}
- committing: the app verified /app_new and asked for a swap. The loader performs it here, step by
  step and idempotently, so a power cut at any point just repeats the remaining steps.
- trial: new version running. The app calls core.ota.confirm() once it has been online for a while.
  Each reset counts a boot; after MAX_TRIAL_BOOTS the previous /app (/app_old) and config come back.
  A hardware WDT catches hangs; a timer catches a version that runs but never confirms.
Ctrl+C leaves the REPL available for mpremote (in trial mode the WDT still resets the board).
"""
import json
import machine
import os
import sys
import time

APP_DIR = "/app"
NEW_DIR = "/app_new"
OLD_DIR = "/app_old"
OTA_FILE = "/ota.json"
CONFIG = "/config.json"
CONFIG_OLD = "/config.json.old"
MAX_TRIAL_BOOTS = 2
TRIAL_WDT_MS = 60000          # hang guard; the app feeds it through feed()
TRIAL_CONFIRM_MS = 300000     # runs but never confirms -> reset (and count a boot)

wdt = None                    # read by the app: sys.modules["__main__"].wdt
confirmed = False             # set by core.ota.confirm(); checked by the timer (RAM only)
_timer = None


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _rmtree(path):
    if not _exists(path):
        return
    if os.stat(path)[0] & 0x4000:  # directory
        for name in os.listdir(path):
            _rmtree(path + "/" + name)
        os.rmdir(path)
    else:
        os.remove(path)


def load_state():
    try:
        with open(OTA_FILE) as stream:
            state = json.load(stream)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}  # missing or corrupt: treat as "ok"


def save_state(state):
    with open(OTA_FILE + ".tmp", "w") as stream:
        json.dump(state, stream)
    os.rename(OTA_FILE + ".tmp", OTA_FILE)


def _install(state):
    """Finish a 'committing' swap. Every step checks what is already done."""
    new_config = NEW_DIR + "/config.json"
    if _exists(new_config):
        if _exists(CONFIG):
            _rmtree(CONFIG_OLD)
            os.rename(CONFIG, CONFIG_OLD)
        os.rename(new_config, CONFIG)
    if _exists(NEW_DIR):
        if _exists(APP_DIR):
            _rmtree(OLD_DIR)
            os.rename(APP_DIR, OLD_DIR)
        os.rename(NEW_DIR, APP_DIR)
    state["state"] = "trial"
    state["boots"] = 0
    save_state(state)
    print("OTA: installed version", state.get("version"))


def _rollback(state):
    print("OTA: version", state.get("version"), "failed; restoring", state.get("prev"))
    if _exists(OLD_DIR):
        _rmtree(APP_DIR)
        os.rename(OLD_DIR, APP_DIR)
    if state.get("config") and _exists(CONFIG_OLD):
        _rmtree(CONFIG)
        os.rename(CONFIG_OLD, CONFIG)
    save_state({"state": "ok", "boots": 0, "version": state.get("prev"),
                "rolled_back_from": state.get("version")})


def _confirm_deadline(_timer):
    if not confirmed:
        print("OTA: trial not confirmed in time; resetting")
        machine.reset()


def check_ota():
    global wdt, _timer
    state = load_state()
    if state.get("state") == "committing":
        _install(state)
    if state.get("state") != "trial":
        return state
    boots = state.get("boots", 0) + 1
    if boots > MAX_TRIAL_BOOTS:
        if _exists(OLD_DIR):
            _rollback(state)
        else:
            # Nothing to restore: stop the trial rather than reset forever.
            save_state({"state": "ok", "boots": 0, "version": state.get("version")})
        return load_state()
    state["boots"] = boots
    save_state(state)
    print("OTA: trial boot", boots, "of", MAX_TRIAL_BOOTS, "for version", state.get("version"))
    wdt = machine.WDT(timeout=TRIAL_WDT_MS)
    # Timer(0) belongs to actuators; Timer(1) is the loader's.
    _timer = machine.Timer(1)
    _timer.init(mode=machine.Timer.ONE_SHOT, period=TRIAL_CONFIRM_MS, callback=_confirm_deadline)
    return state


def main():
    try:
        check_ota()
        if _exists(APP_DIR) and APP_DIR not in sys.path:
            sys.path.insert(0, APP_DIR)
        import app
        app.run()
    except KeyboardInterrupt:
        if _timer is not None:
            _timer.deinit()
        print("Firmware stopped; reset the board to start again.")
    except Exception as exc:
        sys.print_exception(exc)
        print("Firmware crashed; restarting in 5 seconds.")
        time.sleep(5)
        machine.reset()


if __name__ == "__main__":
    main()
