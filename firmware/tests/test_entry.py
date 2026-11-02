import sys
import time
import machine
import app
import main


def test_entry_keyboard_interrupt_stops(monkeypatch, capsys):
    def stop():
        raise KeyboardInterrupt()
    monkeypatch.setattr(app, "run", stop)
    main.main()
    assert "Firmware stopped" in capsys.readouterr().out
    assert machine.reset_calls == 0


def test_entry_unexpected_exception_prints_sleeps_resets(monkeypatch):
    events = []
    def fail():
        raise RuntimeError("unexpected")
    monkeypatch.setattr(app, "run", fail)
    monkeypatch.setattr(sys, "print_exception", lambda exc: events.append(str(exc)), raising=False)
    monkeypatch.setattr(time, "sleep", lambda seconds: events.append(seconds))
    monkeypatch.setattr(machine, "reset", lambda: events.append("reset"))
    main.main()
    assert events == ["unexpected", 5, "reset"]
