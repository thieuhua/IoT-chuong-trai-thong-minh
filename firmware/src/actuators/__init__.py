"""Actuators (outputs) declared in config.json; drivers are imported only when configured."""
DRIVERS = {
    "servo": ("actuators.servo", "Servo"),
}


def build_actuators(configs):
    result = []
    names = set()
    for cfg in configs:
        name = cfg.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("actuator names must be nonempty and unique")
        driver = cfg.get("driver")
        if driver not in DRIVERS:
            raise ValueError("unknown actuator driver: " + str(driver))
        module_name, class_name = DRIVERS[driver]
        module = __import__(module_name, None, None, (class_name,))
        result.append(getattr(module, class_name)(cfg))
        names.add(name)
    return result
