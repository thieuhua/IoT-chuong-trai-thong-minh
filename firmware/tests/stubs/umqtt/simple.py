class MQTTException(Exception):
    pass


class Socket:
    def __init__(self):
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


class MQTTClient:
    instances = []
    next_messages = []
    next_connect_error = None

    def __init__(self, client_id, server, port=1883, user=None, password=None, keepalive=0):
        self.client_id, self.server, self.port = client_id, server, port
        self.user, self.password, self.keepalive = user, password, keepalive
        self.events = []
        self.publishes = []
        self.subscriptions = []
        self.messages = list(type(self).next_messages)
        type(self).next_messages = []
        self.connect_error = type(self).next_connect_error
        type(self).next_connect_error = None
        self.sock = Socket()
        self.will = None
        type(self).instances.append(self)

    def set_callback(self, callback):
        self.callback = callback

    def set_last_will(self, topic, payload, retain=False, qos=0):
        self.will = (topic, payload, retain, qos)
        self.events.append(("will",))

    def connect(self):
        self.events.append(("connect",))
        if self.connect_error:
            raise self.connect_error

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        self.events.append(("subscribe", topic, qos))

    def publish(self, topic, payload, retain=False, qos=0):
        self.publishes.append((topic, payload, retain, qos))
        self.events.append(("publish", topic, payload, retain, qos))

    def inject(self, topic, payload):
        self.messages.append((topic, payload))

    def check_msg(self):
        if self.messages:
            message = self.messages.pop(0)
            if isinstance(message, BaseException):
                raise message
            self.callback(*message)

    def ping(self):
        self.events.append(("ping",))

    def disconnect(self):
        self.events.append(("disconnect",))
        self.sock.close()
