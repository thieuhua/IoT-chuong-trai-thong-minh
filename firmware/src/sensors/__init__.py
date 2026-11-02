"""Only configured drivers are imported, keeping board RAM usage small."""
DRIVERS = {
    "dht11": ("sensors.dht", "DHT11"),
    "dht22": ("sensors.dht", "DHT22"),
    "adc": ("sensors.analog", "Analog"),
    "simulated": ("sensors.simulated", "Simulated"),
}


def build_sensors(configs):
    result = []
    names = set()
    for cfg in configs:
        name = cfg.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("sensor names must be nonempty and unique")
        driver = cfg.get("driver")
        if driver not in DRIVERS:
            raise ValueError("unknown sensor driver: " + str(driver))
        module_name, class_name = DRIVERS[driver]
        module = __import__(module_name, None, None, (class_name,))
        result.append(getattr(module, class_name)(cfg))
        names.add(name)
    return result
