# Copy to mqtt_demo_settings.py, then enter your own Wi-Fi settings.
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

# Windows mobile hotspot IPv4; recheck if the laptop network changes.
# ESP32 must use the PC's LAN IP, never localhost / 127.0.0.1.
MQTT_HOST = "192.168.137.1"
MQTT_PORT = 1883
DEVICE_ID = "esp32-mqtt-demo"
PUBLISH_INTERVAL_SECONDS = 5
