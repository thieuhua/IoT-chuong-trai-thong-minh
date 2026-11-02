STA_IF = 0


class WLAN:
    def __init__(self, mode):
        self.connected = True

    def active(self, value):
        pass

    def connect(self, ssid, password):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def isconnected(self):
        return self.connected

    def ifconfig(self):
        return ("192.0.2.10", "255.255.255.0", "192.0.2.1", "192.0.2.1")

    def status(self, key):
        return -45
