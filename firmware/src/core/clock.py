import time


class Clock:
    def __init__(self):
        self.synced = False
        self.epoch_offset = 946684800 if time.gmtime(0)[0] == 2000 else 0

    def sync(self):
        try:
            import ntptime
            ntptime.timeout = 2
            ntptime.settime()
            self.synced = True
        except (OSError, ImportError) as exc:
            print("NTP unavailable:", exc)
        return self.synced

    def now(self):
        # Integer on purpose: ESP32 floats are 32-bit (~128 s resolution at current epoch values).
        return time.time() + self.epoch_offset if self.synced else None
