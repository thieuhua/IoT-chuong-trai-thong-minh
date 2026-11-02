class DHT11:
    def __init__(self, pin):
        self.pin = pin
        self.measures = 0

    def measure(self):
        self.measures += 1

    def temperature(self):
        return 25

    def humidity(self):
        return 60


class DHT22(DHT11):
    pass
