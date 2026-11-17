import network
import time

_wlan = None


def interface():
    global _wlan
    if _wlan is None:
        _wlan = network.WLAN(network.STA_IF)
    return _wlan


def connected():
    return interface().isconnected()


def connect(ssid, password, timeout_s=20, feed=None):
    wlan = interface()
    wlan.active(True)
    if not wlan.isconnected():
        try:
            # After a drop the driver may still be reconnecting; connect() would raise a state error.
            wlan.disconnect()
        except OSError:
            pass
        wlan.connect(ssid, password)
        started = time.ticks_ms()
        while not wlan.isconnected():
            if feed:
                feed()
            if time.ticks_diff(time.ticks_ms(), started) >= timeout_s * 1000:
                wlan.disconnect()
                raise OSError("Wi-Fi timeout")
            time.sleep_ms(50)
    print("ESP32 IP:", wlan.ifconfig()[0])
    return wlan


def connect_any(networks, timeout_s=20, feed=None):
    """Keep an existing connection, or try visible profiles in configured order."""
    if isinstance(networks, dict):
        networks = [networks]
    wlan = interface()
    wlan.active(True)
    if wlan.isconnected():
        ssid = None
        for key in ("ssid", "essid"):
            try:
                ssid = wlan.config(key)
                break
            except (ValueError, OSError):
                pass
        if isinstance(ssid, bytes):
            ssid = ssid.decode()
        for profile in networks:
            if profile["ssid"] == ssid:
                print("Wi-Fi SSID:", ssid, "IP:", wlan.ifconfig()[0])
                return profile
        # A connection made from the REPL may not have a configured profile.
        # Keep it, but use the default broker rather than another network's override.
        print("Wi-Fi SSID:", ssid, "IP:", wlan.ifconfig()[0])
        return {"ssid": ssid}

    candidates = networks
    if feed:
        feed()
    try:
        visible = [entry[0] for entry in wlan.scan()]
        candidates = [profile for profile in networks
                      if profile["ssid"].encode() in visible or profile["ssid"] in visible]
        if not candidates:
            candidates = networks
    except OSError:
        pass
    finally:
        if feed:
            feed()
    for profile in candidates:
        if feed:
            feed()
        try:
            connect(profile["ssid"], profile["password"], timeout_s, feed)
        except OSError:
            continue
        print("Wi-Fi SSID:", profile["ssid"], "IP:", wlan.ifconfig()[0])
        return profile
    raise OSError("Wi-Fi: no configured network")
