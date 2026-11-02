"""Run on an ESP32 with MicroPython; no sensor or GPIO wiring required."""

import json
import machine
import network
import random
import time
import ubinascii
from umqtt.simple import MQTTClient

import mqtt_demo_settings as settings

wifi = network.WLAN(network.STA_IF)
client_id = b"esp32-" + ubinascii.hexlify(machine.unique_id())
topic = ("devices/" + settings.DEVICE_ID + "/data").encode()


def connect_wifi():
    wifi.active(True)
    if not wifi.isconnected():
        wifi.connect(settings.WIFI_SSID, settings.WIFI_PASSWORD)
        started = time.ticks_ms()
        while not wifi.isconnected():
            if time.ticks_diff(time.ticks_ms(), started) > 20000:
                wifi.disconnect()
                raise OSError("Wi-Fi timeout; check SSID/password and signal")
            time.sleep_ms(200)
    print("ESP32 IP:", wifi.ifconfig()[0])


def main():
    sequence = 0
    while True:
        client = None
        try:
            connect_wifi()
            client = MQTTClient(client_id, settings.MQTT_HOST,
                                port=settings.MQTT_PORT, keepalive=60)
            client.connect()
            client.sock.settimeout(10)
            print("MQTT connected:", settings.MQTT_HOST, settings.MQTT_PORT)
            while wifi.isconnected():
                sequence += 1
                payload = json.dumps({
                    "device": settings.DEVICE_ID,
                    "temperature_c": round(20 + random.getrandbits(8) / 255 * 10, 2),
                    "simulated": True,
                    "sequence": sequence,
                    "uptime_s": time.ticks_ms() // 1000,
                })
                client.publish(topic, payload.encode(), qos=0, retain=False)
                print("TX", topic, payload)
                time.sleep(settings.PUBLISH_INTERVAL_SECONDS)
        except OSError as exc:
            print("Network error:", exc, "- retry in 5 seconds")
        except KeyboardInterrupt:
            print("Stopped.")
            return
        finally:
            if client is not None and client.sock is not None:
                try:
                    client.disconnect()
                except OSError:
                    client.sock.close()
        time.sleep(5)


if __name__ == "__main__":
    main()
