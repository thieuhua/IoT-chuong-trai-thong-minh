"""Send device commands through the backend REST API (standard library only)."""
import argparse
import getpass
import json
import sys
from urllib import error, parse, request


HTTP_ERRORS = {
    401: "Authentication failed or session expired",
    403: "Permission denied",
    404: "Device or endpoint not found",
    409: "Device offline or command conflicts with current state",
    502: "Device command failed or broker unavailable",
    504: "Device did not respond before the timeout",
}


def request_json(base_url, path, body=None, token=None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    req = request.Request(base_url.rstrip("/") + path, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=20) as response:
            return json.load(response)
    except error.HTTPError as exc:
        # Do not echo arbitrary response bodies, especially from the login endpoint.
        exc.close()
        raise ValueError("HTTP %s: %s" %
                         (exc.code, HTTP_ERRORS.get(exc.code, "Backend request failed"))) from None
    except error.URLError as exc:
        raise ValueError("Cannot reach backend: %s" % exc.reason) from None
    except (ValueError, UnicodeError):
        raise ValueError("Backend returned invalid JSON") from None


def parser():
    result = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Examples (password is prompted, never passed as an argument):
  device_cmd.py --user admin list
  device_cmd.py --user admin esp32-ID ping
  device_cmd.py --user admin esp32-ID read '{"sensor":"room"}'
  device_cmd.py --user admin esp32-ID relay_set '{"on":true,"duration_ms":3000}'
  device_cmd.py --user admin esp32-ID servo_set '{"angle":90}'
PowerShell 5.1: if native argument quoting strips JSON quotes, escape them as \\".''')
    result.add_argument("--url", default="http://127.0.0.1:8000")
    result.add_argument("--user", required=True)
    result.add_argument("device", help="Device ID, or list")
    result.add_argument("command", nargs="?")
    result.add_argument("json_args", nargs="?", default="{}")
    return result


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    try:
        url = parse.urlsplit(args.url)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("--url must be an HTTP(S) URL without credentials")
        if url.query or url.fragment:
            raise ValueError("--url must not contain a query or fragment")
        if args.device == "list":
            if args.command is not None:
                raise ValueError("list takes no command arguments")
            body = None
            path = "/devices"
        else:
            if args.command is None:
                raise ValueError("A device ID must be followed by a command")
            try:
                command_args = json.loads(args.json_args)
            except ValueError:
                raise ValueError("json_args must be a valid JSON object") from None
            if not isinstance(command_args, dict):
                raise ValueError("json_args must be a JSON object")
            path = "/devices/" + parse.quote(args.device, safe="") + "/commands"
            body = {"name": args.command, "args": command_args, "timeout_s": 10}
        password = getpass.getpass("Backend password: ")
        login = request_json(args.url, "/auth/login", {"username": args.user, "password": password})
        if not isinstance(login, dict) or not isinstance(login.get("access_token"), str) or not login["access_token"]:
            raise ValueError("Login response has no access token")
        result = request_json(args.url, path, body, login["access_token"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, EOFError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
