import gc
import time
from umqtt.simple import MQTTClient, MQTTException

IO_TIMEOUT_S = 10
# Outside /app: survives an OTA rollback, so a failed TLS trial can be diagnosed over Wi-Fi
# afterwards (get_info returns it as "last_mqtt_error").
ERROR_FILE = "/mqtt_error.txt"


def _note(text, mode="a"):
    try:
        with open(ERROR_FILE, mode) as f:
            f.write("%s mem_free=%d; " % (text, gc.mem_free()))
    except Exception:
        pass


def remember_error(stage, exc):
    _note("%s %s: %r" % (stage, type(exc).__name__, exc.args))


class _TimedTLS:
    """Wraps the SSLContext to log handshake progress to ERROR_FILE.

    No socket timeout here: on the ESP32 build tested (MicroPython 1.29, no PSRAM) the handshake
    hung even with one, so a hang is left to the OTA trial watchdog to recover.
    """

    def __init__(self, ctx):
        self.ctx = ctx

    def wrap_socket(self, sock, server_hostname=None, **kwargs):
        _note("tls handshake start", "w")
        wrapped = self.ctx.wrap_socket(sock, server_hostname=server_hostname, **kwargs)
        _note("tls handshake ok")
        return wrapped


def last_error():
    try:
        with open(ERROR_FILE) as f:
            return f.read()
    except OSError:
        return None


class NotAuthorised(Exception):
    pass


def _bytes(value):
    return value.encode() if isinstance(value, str) else value


def tls_context(tls):
    """SSLContext for config["mqtt"]["tls"]: {"ca": PEM text} or {"ca_file": path}.

    With a CA the broker certificate (chain, validity dates, host name/IP) is verified;
    {"insecure": true} encrypts without verification (testing only).
    """
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ca = tls.get("ca")
    if ca is None and tls.get("ca_file"):
        with open(tls["ca_file"]) as f:
            ca = f.read()
    if ca:
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cadata=_bytes(ca))
    elif tls.get("insecure"):
        ctx.verify_mode = ssl.CERT_NONE
    else:
        raise ValueError("mqtt.tls needs ca, ca_file or insecure")
    return ctx


class MQTTLink:
    def __init__(self, client_id, host, port=1883, user=None, password=None,
                 keepalive=30, handler=None, tls=None):
        kwargs = {}
        if tls:
            gc.collect()  # the TLS handshake needs a large contiguous block
            try:
                kwargs["ssl"] = _TimedTLS(tls_context(tls))
            except Exception as exc:
                remember_error("tls_context", exc)
                raise
        self.client = MQTTClient(_bytes(client_id), host, port=port,
                                 user=_bytes(user), password=_bytes(password),
                                 keepalive=keepalive, **kwargs)
        self.tls = bool(tls)
        self.keepalive = keepalive
        self.handler = handler
        self.closed = False
        self.last_out = time.ticks_ms()
        self.client.set_callback(self._dispatch)

    def _dispatch(self, topic, payload):
        # umqtt sends PUBACK after dispatch for incoming QoS 1 commands. Incoming packets do not
        # count for keepalive, so last_out is not touched here.
        if self.handler:
            self.handler(topic.decode() if isinstance(topic, bytes) else topic, payload)

    def set_last_will(self, topic, payload, retain=True, qos=1):
        self.client.set_last_will(_bytes(topic), payload, retain=retain, qos=qos)

    def connect(self):
        try:
            self.client.connect()
        except MQTTException as exc:
            if exc.args and exc.args[0] in (4, 5):
                raise NotAuthorised("MQTT credentials refused")
            remember_error("tls" if self.tls else "plain", exc)
            raise
        except Exception as exc:
            remember_error("tls" if self.tls else "plain", exc)
            raise
        self.last_out = time.ticks_ms()
        self._set_timeout()
        gc.collect()

    def _set_timeout(self):
        # umqtt has no timeouts and check_msg() leaves the socket fully blocking; without this a
        # half-open TCP link could hang a QoS 1 publish or SUBACK wait forever.
        sock = getattr(self.client, "sock", None)
        if sock is not None:
            sock.settimeout(IO_TIMEOUT_S)

    def subscribe(self, topic, qos=1):
        self.client.subscribe(_bytes(topic), qos=qos)
        self.last_out = time.ticks_ms()

    def publish(self, topic, payload, retain=False, qos=0):
        self.client.publish(_bytes(topic), payload, retain=retain, qos=qos)
        self.last_out = time.ticks_ms()

    def poll(self):
        self.client.check_msg()
        self._set_timeout()
        if self.keepalive and time.ticks_diff(time.ticks_ms(), self.last_out) >= self.keepalive * 500:
            self.client.ping()
            self.last_out = time.ticks_ms()

    def close(self, graceful=True):
        if self.closed:
            return
        self.closed = True
        try:
            if graceful and getattr(self.client, "sock", None) is not None:
                self.client.disconnect()
        except OSError:
            pass
        finally:
            sock = getattr(self.client, "sock", None)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
