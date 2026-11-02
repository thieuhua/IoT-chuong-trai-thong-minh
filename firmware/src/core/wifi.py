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
