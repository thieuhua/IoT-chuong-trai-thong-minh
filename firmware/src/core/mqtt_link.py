import gc
import time
from umqtt.simple import MQTTClient, MQTTException

IO_TIMEOUT_S = 10


class NotAuthorised(Exception):
    pass


def _bytes(value):
    return value.encode() if isinstance(value, str) else value


class MQTTLink:
    def __init__(self, client_id, host, port=1883, user=None, password=None,
                 keepalive=30, handler=None):
        self.client = MQTTClient(_bytes(client_id), host, port=port,
                                 user=_bytes(user), password=_bytes(password),
                                 keepalive=keepalive)
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
