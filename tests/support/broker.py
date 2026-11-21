"""Broker MQTT chạy trong bộ nhớ, dùng cho test không cần Mosquitto thật.

Mô phỏng đúng những gì hệ thống dựa vào (docs/protocol.md mục 8):
- đăng nhập bằng username/password, client id bị ghim theo tài khoản;
- Dynamic Security: backend gửi lệnh JSON vào `$CONTROL/dynamic-security/v1`,
  broker trả lời ở `.../response` với đúng các chuỗi lỗi của Mosquitto 2.0;
- ACL mặc định từ chối publish/subscribe, chỉ cho phép theo role;
- retained message (payload rỗng thì xóa), Last Will khi mất kết nối.

Mỗi lần giao tin được chạy bằng một task asyncio riêng, giống mạng thật: bên gửi
không chờ bên nhận xử lý xong. Dùng `await broker.settle()` để chờ mọi tin đã giao.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field

CONTROL_TOPIC = "$CONTROL/dynamic-security/v1"
RESPONSE_TOPIC = CONTROL_TOPIC + "/response"


class NotAuthorised(ConnectionError):
    """CONNACK 5 (not authorised)."""


def topic_matches(topic_filter: str, topic: str) -> bool:
    filter_parts, topic_parts = topic_filter.split("/"), topic.split("/")
    for index, part in enumerate(filter_parts):
        if part == "#":
            return True
        if index >= len(topic_parts):
            return False
        if part != "+" and part != topic_parts[index]:
            return False
    return len(filter_parts) == len(topic_parts)


@dataclass
class Account:
    username: str
    password: str
    clientid: str | None = None
    roles: list[str] = field(default_factory=list)
    admin: bool = False  # tài khoản `backend`: toàn quyền như admin dynsec


@dataclass
class Session:
    client_id: str
    account: Account | None
    handlers: list = field(default_factory=list)  # (filter, handler)
    will: tuple | None = None
    connected: bool = True


class InMemoryBroker:
    def __init__(self, *, backend_password: str = "backend-pw", bootstrap_password: str = "bootstrap-pw"):
        self.accounts: dict[str, Account] = {}
        self.roles: dict[str, list[dict]] = {}
        self.sessions: dict[str, Session] = {}
        self.retained: dict[str, bytes] = {}
        self.log: list[tuple[str, str, bytes]] = []  # (client, topic, payload) đã được chấp nhận
        self.denied: list[tuple[str, str, str]] = []  # (client, hành động, topic) bị ACL chặn
        self.control_commands: list[dict] = []  # lệnh dynsec backend đã gửi
        self._tasks: set[asyncio.Task] = set()
        self.drop_to: set[str] = set()  # client id đang "mất mạng": không nhận gì
        self.queues: list = []  # hàng đợi xử lý tuần tự của các BrokerTransport
        # Giống deployment/mosquitto/entrypoint.sh
        self.accounts["backend"] = Account("backend", backend_password, admin=True)
        self.roles["bootstrap"] = [
            dict(acltype="publishClientSend", topic="iot/v1/provision/+/request", allow=True),
            dict(acltype="subscribePattern", topic="iot/v1/provision/+/response", allow=True),
        ]
        self.accounts["bootstrap"] = Account("bootstrap", bootstrap_password, roles=["bootstrap"])

    # Kết nối ---------------------------------------------------------------
    def connect(self, client_id: str, username: str | None, password: str | None,
                will: tuple | None = None) -> Session:
        account = self.accounts.get(username or "")
        if account is None or account.password != password:
            raise NotAuthorised(f"bad username or password for {username!r}")
        if account.clientid is not None and account.clientid != client_id:
            raise NotAuthorised(f"client id {client_id!r} is not allowed for {username!r}")
        old = self.sessions.get(client_id)
        if old is not None:  # client id trùng: broker ngắt phiên cũ (session takeover)
            old.connected = False
        session = Session(client_id, account, will=will)
        self.sessions[client_id] = session
        return session

    def disconnect(self, session: Session, *, graceful: bool = True) -> None:
        if not session.connected:
            return
        session.connected = False
        if self.sessions.get(session.client_id) is session:
            del self.sessions[session.client_id]
        if not graceful and session.will:
            topic, payload, retain = session.will
            self._accept(session, topic, payload, retain)

    # Quyền -------------------------------------------------------------------
    def _acls(self, account: Account):
        for role in account.roles:
            yield from self.roles.get(role, [])

    def can_publish(self, account: Account | None, topic: str) -> bool:
        if account is None:
            return False
        if account.admin:
            return True
        return any(acl["acltype"] == "publishClientSend" and acl.get("allow")
                   and topic_matches(acl["topic"], topic) for acl in self._acls(account))

    def can_subscribe(self, account: Account | None, topic_filter: str) -> bool:
        if account is None:
            return False
        if account.admin:
            return True
        for acl in self._acls(account):
            if not acl.get("allow"):
                continue
            if acl["acltype"] == "subscribeLiteral" and acl["topic"] == topic_filter:
                return True
            if acl["acltype"] == "subscribePattern" and topic_matches(acl["topic"], topic_filter) \
                    and "#" not in topic_filter and "+" not in topic_filter:
                return True
        return False

    # Publish / subscribe -----------------------------------------------------
    def subscribe(self, session: Session, topic_filter: str, handler) -> bool:
        if not session.connected:
            raise ConnectionError("not connected")
        if not self.can_subscribe(session.account, topic_filter):
            self.denied.append((session.client_id, "subscribe", topic_filter))
            return False  # Mosquitto trả SUBACK 0x80, client vẫn kết nối
        session.handlers.append((topic_filter, handler))
        for topic, payload in list(self.retained.items()):
            if topic_matches(topic_filter, topic):
                self._deliver(session, handler, topic, payload)
        return True

    def publish(self, session: Session, topic: str, payload: bytes, retain: bool = False) -> bool:
        if not session.connected:
            raise ConnectionError("not connected")
        if topic == CONTROL_TOPIC and session.account and session.account.admin:
            self._control(session, payload)
            return True
        if not self.can_publish(session.account, topic):
            # Mosquitto với MQTT 3.1.1 bỏ im lặng tin không có quyền.
            self.denied.append((session.client_id, "publish", topic))
            return False
        self._accept(session, topic, payload, retain)
        return True

    def _accept(self, session: Session, topic: str, payload: bytes, retain: bool) -> None:
        self.log.append((session.client_id, topic, payload))
        if retain:
            if payload:
                self.retained[topic] = payload
            else:
                self.retained.pop(topic, None)
        for target in list(self.sessions.values()):
            if target.client_id in self.drop_to:
                continue
            for topic_filter, handler in list(target.handlers):
                if topic_matches(topic_filter, topic):
                    self._deliver(target, handler, topic, payload)

    def _deliver(self, session: Session, handler, topic: str, payload: bytes) -> None:
        async def run():
            if not session.connected:
                return
            result = handler(topic, payload)
            if inspect.isawaitable(result):
                await result
        task = asyncio.get_running_loop().create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def settle(self, rounds: int = 50) -> None:
        """Chờ tới khi không còn tin nào đang giao (kể cả tin sinh ra trong lúc giao)."""
        def busy():
            return bool(self._tasks) or any(q.busy for q in self.queues)
        for _ in range(rounds):
            await asyncio.sleep(0)
            if not busy():
                await asyncio.sleep(0)
                if not busy():
                    return
            if self._tasks:
                await asyncio.gather(*list(self._tasks), return_exceptions=True)
            for queue in self.queues:
                await queue.join()

    # Dynamic Security ------------------------------------------------------
    def _control(self, session: Session, payload: bytes) -> None:
        responses = []
        for command in json.loads(payload).get("commands", []):
            self.control_commands.append(command)
            name = command.get("command")
            error = self._run_control(name, command)
            response = {"command": name, "correlationData": command.get("correlationData")}
            if error:
                response["error"] = error
            if name == "getClient" and not error:
                account = self.accounts[command["username"]]
                response["data"] = {"client": {"username": account.username, "clientid": account.clientid,
                                               "roles": [{"rolename": r} for r in account.roles]}}
            responses.append(response)
        self._accept(session, RESPONSE_TOPIC, json.dumps({"responses": responses}).encode(), False)

    def _run_control(self, name: str, c: dict) -> str | None:
        if name == "createRole":
            if c["rolename"] in self.roles:
                return "Role already exists"
            self.roles[c["rolename"]] = []
        elif name == "deleteRole":
            if self.roles.pop(c["rolename"], None) is None:
                return "Role not found"
            for account in self.accounts.values():
                if c["rolename"] in account.roles:
                    account.roles.remove(c["rolename"])
        elif name == "addRoleACL":
            acls = self.roles.get(c["rolename"])
            if acls is None:
                return "Role not found"
            if any(a["acltype"] == c["acltype"] and a["topic"] == c["topic"] for a in acls):
                return "ACL with this topic already exists"
            acls.append(dict(acltype=c["acltype"], topic=c["topic"], allow=c.get("allow", False)))
        elif name == "removeRoleACL":
            acls = self.roles.get(c["rolename"])
            if acls is None:
                return "Role not found"
            acl = next((a for a in acls if a["acltype"] == c["acltype"]
                        and a["topic"] == c["topic"]), None)
            if acl is None:
                return "ACL not found"
            acls.remove(acl)
        elif name == "createClient":
            if c["username"] in self.accounts:
                return "Client already exists"
            self.accounts[c["username"]] = Account(
                c["username"], c.get("password"), clientid=c.get("clientid"),
                roles=[r["rolename"] for r in c.get("roles", [])])
        elif name == "deleteClient":
            account = self.accounts.pop(c["username"], None)
            if account is None:
                return "Client not found"
            self._kick(account.username)
        elif name in {"setClientPassword", "setClientId", "getClient", "addClientRole"}:
            account = self.accounts.get(c["username"])
            if account is None:
                return "Client not found"
            if name == "setClientPassword":
                account.password = c["password"]
                self._kick(account.username)
            elif name == "setClientId":
                account.clientid = c["clientid"]
                self._kick(account.username)
            elif name == "addClientRole":
                if c["rolename"] in account.roles:
                    return "Internal error"  # đúng hành vi Mosquitto 2.0.22
                account.roles.append(c["rolename"])
        else:
            return "Unknown command"
        return None

    def _kick(self, username: str) -> None:
        # Dynsec ngắt client bị sửa tài khoản (không chạy Last Will vì broker chủ động ngắt).
        for session in list(self.sessions.values()):
            if session.account and session.account.username == username:
                self.disconnect(session, graceful=False)


class BrokerTransport:
    """Thay MqttTransport (paho) của backend, cùng giao diện mà DeviceGateway dùng."""

    def __init__(self, broker: InMemoryBroker, *, client_id: str = "backend", username: str = "backend",
                 password: str = "backend-pw"):
        self.broker = broker
        self.client_id, self.username, self.password = client_id, username, password
        self.session: Session | None = None
        self.callbacks = []
        self.published: list[tuple[str, bytes, int, bool]] = []
        # Giống MqttTransport: handler "ordered" chạy lần lượt theo thứ tự tin đến
        # (status/meta/telemetry), handler không ordered (resp, DynSec) chạy ngay.
        self._queue: asyncio.Queue | None = None
        self._worker: asyncio.Task | None = None
        broker.queues.append(self)

    @property
    def busy(self) -> bool:
        return self._queue is not None and self._queue._unfinished_tasks > 0

    async def join(self) -> None:
        if self._queue is not None:
            await self._queue.join()

    async def _run_queue(self) -> None:
        while True:
            handler, topic, payload = await self._queue.get()
            try:
                result = handler(topic, payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                import logging
                logging.getLogger("tests.broker").exception("handler failed")
            finally:
                self._queue.task_done()

    @property
    def connected(self) -> bool:
        return bool(self.session and self.session.connected)

    async def start(self) -> None:
        if self._worker is None:
            self._queue = asyncio.Queue()
            self._worker = asyncio.get_running_loop().create_task(self._run_queue())
        self.session = self.broker.connect(self.client_id, self.username, self.password)
        for callback in self.callbacks:
            result = callback(True)
            if inspect.isawaitable(result):
                await result

    async def stop(self) -> None:
        if self.session:
            self.broker.disconnect(self.session)

    async def close(self) -> None:
        await self.stop()
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    def on_connection_change(self, callback) -> None:
        self.callbacks.append(callback)

    async def subscribe(self, topic_filter, handler, qos=1, ordered=True) -> None:
        if ordered:
            original = handler
            def handler(topic, payload):
                self._queue.put_nowait((original, topic, payload))
        if not self.broker.subscribe(self.session, topic_filter, handler):
            raise PermissionError(topic_filter)

    async def publish(self, topic, payload, qos=0, retain=False) -> None:
        if not self.connected:
            raise ConnectionError("Not connected to MQTT broker")
        self.published.append((topic, payload, qos, retain))
        self.broker.publish(self.session, topic, payload, retain)
