STA_IF = 0


class WLAN:
    def __init__(self, mode):
        self.connected = True
        self.ssid = "test"
        self.visible = []
        self.fail_ssids = set()
        self.scan_error = None
        self.scan_calls = 0
        self.attempts = []

    def active(self, value):
        pass

    def connect(self, ssid, password):
        self.attempts.append(ssid)
        if ssid in self.fail_ssids:
            raise OSError("connection failed")
        self.ssid = ssid
        self.connected = True

    def config(self, key):
        if key in ("ssid", "essid"):
            return self.ssid
        raise ValueError(key)

    def scan(self):
        self.scan_calls += 1
        if self.scan_error:
            raise self.scan_error
        return [(ssid.encode(), b"", 1, -45, 3, False) for ssid in self.visible]

    def disconnect(self):
        self.connected = False

    def isconnected(self):
        return self.connected

    def ifconfig(self):
        return ("192.0.2.10", "255.255.255.0", "192.0.2.1", "192.0.2.1")

    def status(self, key):
        return -45
