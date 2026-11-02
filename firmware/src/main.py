"""Board entry point; Ctrl+C leaves the REPL available for mpremote."""
import machine
import sys
import time


def main():
    try:
        import app
        app.run()
    except KeyboardInterrupt:
        print("Firmware stopped; reset the board to start again.")
    except Exception as exc:
        sys.print_exception(exc)
        print("Firmware crashed; restarting in 5 seconds.")
        time.sleep(5)
        machine.reset()


if __name__ == "__main__":
    main()
