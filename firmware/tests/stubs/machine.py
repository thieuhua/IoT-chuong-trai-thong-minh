reset_calls = 0


def unique_id():
    return b"\xa0\xb1\xc2\xd3\xe4\xf5"


def reset():
    global reset_calls
    reset_calls += 1


class Pin:
    IN = 0
    PULL_UP = 1

    def __init__(self, pin, *args):
        self.pin = pin


class ADC:
    ATTN_0DB, ATTN_2_5DB, ATTN_6DB, ATTN_11DB = range(4)

    def __init__(self, pin):
        self.pin = pin

    def atten(self, value):
        self.attenuation = value

    def read_u16(self):
        return 32768

    def read_uv(self):
        return 1650000


class WDT:
    def __init__(self, timeout):
        self.timeout = timeout
        self.feeds = 0

    def feed(self):
        self.feeds += 1
