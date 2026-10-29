"""ESP32 flash entry point: run the MQTT demo automatically at power-on."""

import machine
import sys
import time

try:
    from mqtt_demo_app import main
    main()
except KeyboardInterrupt:
    print("MQTT demo stopped; reset the board to start again.")
except Exception as exc:
    sys.print_exception(exc)
    print("MQTT demo crashed; restarting in 5 seconds.")
    time.sleep(5)
    machine.reset()
