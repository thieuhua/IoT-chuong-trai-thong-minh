import binascii
import machine
import os
from core.storage import load_json, save_json


class Identity:
    def __init__(self, state_path="/state.json", device_path="/device.json"):
        self.hw_id = binascii.hexlify(machine.unique_id()).decode()
        self.state_path = state_path
        self.device_path = device_path
        self.state = load_json(state_path, {})
        self.state["boot"] = self.state.get("boot", 0) + 1
        save_json(state_path, self.state)
        self.boot = self.state["boot"]
        self.seq = 0
        self.device = None
        self.load_device()

    def load_device(self):
        self.device = load_json(self.device_path, None)
        if not self.device:
            self.device = {"password": binascii.hexlify(os.urandom(16)).decode(),
                           "device_id": None}
            save_json(self.device_path, self.device)
        return self.device

    def next_id(self):
        self.seq += 1
        return "%s-%s" % (self.boot, self.seq)

    def approve(self, device_id):
        self.device["device_id"] = device_id
        save_json(self.device_path, self.device)

    def revoke(self):
        os.remove(self.device_path)
        self.device = None

    def set_interval(self, seconds):
        updated = dict(self.state)
        updated["interval_s"] = seconds
        save_json(self.state_path, updated)
        self.state = updated
