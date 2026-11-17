"""Manage local firmware configuration without printing passwords (Python 3.11)."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile


FIRMWARE = Path(__file__).resolve().parents[1]


def load_config(path):
    with path.open(encoding="utf-8-sig") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object")
    return config


def networks(config):
    profiles = config.get("wifi")
    if isinstance(profiles, dict):
        profiles = [profiles]
    if not isinstance(profiles, list) or any(not isinstance(p, dict) for p in profiles):
        raise ValueError("wifi must be an object or a list of objects")
    return profiles


def save_config(path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def bootstrap_password(path):
    # Read dotenv syntax only; never execute it or echo a line/value.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(?:export\s+)?MQTT_BOOTSTRAP_PASSWORD\s*=\s*(.*)$", line)
        if not match:
            continue
        value = match.group(1).strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (value[end + 1:].strip() and
                           not value[end + 1:].lstrip().startswith("#")):
                raise ValueError("Invalid quoted MQTT_BOOTSTRAP_PASSWORD")
            value = value[1:end]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        if not value:
            raise ValueError("MQTT_BOOTSTRAP_PASSWORD is empty")
        return value
    raise ValueError("MQTT_BOOTSTRAP_PASSWORD is missing from the dotenv file")


def port_number(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be in 1..65535")
    return number


def check_config(config):
    profiles = networks(config)
    if not profiles:
        raise ValueError("wifi must contain at least one network")
    seen = set()
    for index, profile in enumerate(profiles):
        label = "wifi[%s]" % index
        if not isinstance(profile.get("ssid"), str) or not profile["ssid"].strip():
            raise ValueError(label + ".ssid must be a nonempty string")
        if profile["ssid"] in seen:
            raise ValueError(label + ".ssid is duplicated")
        seen.add(profile["ssid"])
        if not isinstance(profile.get("password"), str):
            raise ValueError(label + ".password must be a string (empty for open Wi-Fi)")
        if "mqtt_host" in profile and (not isinstance(profile["mqtt_host"], str)
                                       or not profile["mqtt_host"].strip()):
            raise ValueError(label + ".mqtt_host must be a nonempty string")
        if "mqtt_port" in profile:
            check_port(profile["mqtt_port"], label + ".mqtt_port")
    mqtt = config.get("mqtt")
    if not isinstance(mqtt, dict):
        raise ValueError("mqtt must be an object")
    for key in ("host", "bootstrap_password"):
        if not isinstance(mqtt.get(key), str) or not mqtt[key].strip():
            raise ValueError("mqtt." + key + " must be a nonempty string")
    if "bootstrap_user" in mqtt and (not isinstance(mqtt["bootstrap_user"], str)
                                     or not mqtt["bootstrap_user"].strip()):
        raise ValueError("mqtt.bootstrap_user must be a nonempty string")
    if "port" in mqtt:
        check_port(mqtt["port"], "mqtt.port")
    return placeholder_paths(config)


def check_port(value, label):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError(label + " must be an integer in 1..65535")


def placeholder_paths(value, path="config"):
    result = []
    if isinstance(value, dict):
        for key, child in value.items():
            result.extend(placeholder_paths(child, path + "." + key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(placeholder_paths(child, path + "[%s]" % index))
    elif isinstance(value, str) and value.startswith(("YOUR_", "FROM_")):
        result.append(path)
    return result


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, default=FIRMWARE / "src" / "config.json")
    result.add_argument("--example", type=Path, default=FIRMWARE / "config.example.json")
    result.add_argument("--env", type=Path, default=FIRMWARE.parent / "deployment" / ".env")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create from example and read bootstrap password from dotenv")
    init.add_argument("--force", action="store_true")
    add = commands.add_parser("wifi-add", help="Add/update Wi-Fi; password via prompt or stdin only")
    add.add_argument("ssid")
    add.add_argument("--mqtt-host")
    add.add_argument("--mqtt-port", type=port_number)
    add.add_argument("--first", action="store_true")
    add.add_argument("--password-stdin", action="store_true")
    remove = commands.add_parser("wifi-remove")
    remove.add_argument("ssid")
    commands.add_parser("wifi-list", help="List networks in priority order, without passwords")
    commands.add_parser("check", help="Validate required fields and warn about placeholders")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            if args.config.exists() and not args.force:
                raise ValueError("Configuration already exists; use init --force to replace it")
            config = load_config(args.example)
            config["mqtt"]["bootstrap_password"] = bootstrap_password(args.env)
            save_config(args.config, config)
            print("Configuration initialized")
            return 0
        config = load_config(args.config)
        profiles = networks(config)
        if args.command == "wifi-list":
            for index, profile in enumerate(profiles, 1):
                print("%s. %s mqtt_host=%s" %
                      (index, profile.get("ssid", ""),
                       profile.get("mqtt_host", config.get("mqtt", {}).get("host", ""))))
        elif args.command == "check":
            warnings = check_config(config)
            for path in warnings:
                print("Warning: placeholder at " + path)
            print("Configuration valid (%s network(s))" % len(profiles))
        elif args.command == "wifi-add":
            if not args.ssid.strip():
                raise ValueError("SSID must be nonempty")
            if args.mqtt_host is not None and not args.mqtt_host.strip():
                raise ValueError("MQTT host must be nonempty")
            if args.password_stdin:
                line = sys.stdin.readline()
                if not line:
                    raise ValueError("No password received on stdin")
                password = line.rstrip("\r\n")
            else:
                password = getpass.getpass("Wi-Fi password: ")
            index = next((i for i, p in enumerate(profiles) if p.get("ssid") == args.ssid), None)
            profile = dict(profiles[index]) if index is not None else {"ssid": args.ssid}
            profile["password"] = password
            if args.mqtt_host is not None:
                profile["mqtt_host"] = args.mqtt_host
            if args.mqtt_port is not None:
                profile["mqtt_port"] = args.mqtt_port
            if index is not None:
                profiles[index] = profile
                if args.first:
                    profiles.insert(0, profiles.pop(index))
            elif args.first:
                profiles.insert(0, profile)
            else:
                profiles.append(profile)
            config["wifi"] = profiles
            save_config(args.config, config)
            print("Wi-Fi saved")
        elif args.command == "wifi-remove":
            remaining = [p for p in profiles if p.get("ssid") != args.ssid]
            if len(remaining) == len(profiles):
                raise ValueError("SSID not found")
            config["wifi"] = remaining
            save_config(args.config, config)
            print("Wi-Fi removed")
        return 0
    except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
        # JSONDecodeError describes position only, never the configuration contents.
        message = str(exc) if not isinstance(exc, (KeyError, TypeError)) else "Invalid configuration structure"
        print("Error: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
