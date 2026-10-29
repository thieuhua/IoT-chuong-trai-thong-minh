"""Read a DHT11 on ESP32 GPIO23 and print measurements to USB serial."""

import time

import dht
from machine import Pin


DHT_PIN = 23
READ_INTERVAL_MS = 2000


def main():
    sensor = dht.DHT11(Pin(DHT_PIN, Pin.IN, Pin.PULL_UP))
    print("ESP32 | DHT11 | DATA=GPIO%d | Serial=115200 baud" % DHT_PIN)
    print("Doc cam bien moi 2 giay. Nhan Ctrl+C de dung.")

    # Allow the sensor to stabilise after power-on.
    time.sleep_ms(READ_INTERVAL_MS)

    while True:
        try:
            sensor.measure()
            print(
                "Nhiet do: %d C | Do am: %d %%RH"
                % (sensor.temperature(), sensor.humidity())
            )
        except OSError as exc:
            print(
                "Loi doc DHT11: %s | Kiem tra VCC, GND va DATA -> GPIO%d."
                % (exc, DHT_PIN)
            )

        time.sleep_ms(READ_INTERVAL_MS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Da dung doc DHT11. Reset ESP32 de chay lai.")
