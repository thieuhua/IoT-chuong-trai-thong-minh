"""Small atomic JSON files; an interrupted write leaves the old file intact."""
import json
import os


def load_json(path, default):
    try:
        with open(path, "r") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    temporary = path + ".tmp"
    with open(temporary, "w") as stream:
        json.dump(obj, stream)
        stream.flush()
    os.rename(temporary, path)
