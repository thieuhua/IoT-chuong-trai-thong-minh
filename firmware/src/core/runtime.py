"""Short cooperative waits, including watchdog feeding during recovery."""
import time


def pause(seconds, feed=None):
    started = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), started) < seconds * 1000:
        if feed:
            feed()
        time.sleep_ms(50)
