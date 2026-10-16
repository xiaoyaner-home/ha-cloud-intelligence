"""Fixed Wilo report-request transport, not a general device setter.

Opt 1 has no packet MAC or replay protection. Use only on a trusted LAN.
Duplicate filtering is session-local, bounded, and is not anti-replay protection.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import math
import re
import secrets
import socket
import time
from collections import OrderedDict
from datetime import UTC, datetime

from . import alcs as p


class Socket:
    """Nonblocking UDP with cancellable bounded receives."""

    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.timeout = 10.0

    def bind(self, address):
        self.socket.bind(address)

    def getsockname(self):
        return self.socket.getsockname()

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendto(self, packet, peer):
        return self.socket.sendto(packet, peer)

    async def recvfrom(self, size):
        return await asyncio.wait_for(
            asyncio.get_running_loop().sock_recvfrom(self.socket, size), self.timeout
        )

    def close(self):
        self.socket.close()


class _Endpoint:
    """Client-local port memory, not a listener or a reservation between reads."""

    def __init__(self):
        self._port = 0

    def bind(self, sock, boundip):
        sock.bind((boundip, self._port))
        # Synchronous, immediately after bind: cancellation/errors later in the
        # session must not lose the OS-selected port. Never retry on conflict.
        self._port = sock.getsockname()[1]


PRODUCT_KEY = "a15zaTr5sp1"  # public model key, NOT a device identity
POST = "/sys/{product_key}/{device_name}/thing/event/property/post"
SET = "/sys/{product_key}/{device_name}/thing/service/property/set"
STATES = frozenset(
    (
        "switch",
        "temperature",
        "presSet",
        "mode",
        "error",
        "errorState",
        "run",
        "propor",
        "version",
        "pressure",
        "tarSpeed",
        "nowSpeed",
    )
)
MAX_PACKETS = 4096
DEDUPE_SECONDS = 60.0
DEDUPE_CAPACITY = 512


class _Window:
    """Session-local bounded MID+plaintext-digest duplicate filter, NOT anti-replay.

    Same MID/digest is retransmission; same MID/different digest is a conflict.
    A new MID with equal payload is a new report. Never evict unexpired entries
    on capacity pressure, because doing so would silently reopen duplicates.
    """

    def __init__(self, ttl=DEDUPE_SECONDS, capacity=DEDUPE_CAPACITY):
        self.ttl, self.capacity = ttl, capacity
        self.entries = OrderedDict()

    def check(self, mid, payload, now):
        while self.entries and next(iter(self.entries.values()))[0] + self.ttl <= now:
            self.entries.popitem(last=False)
        digest = hashlib.sha256(payload).digest()
        if mid in self.entries:
            return "duplicate" if self.entries[mid][1] == digest else "conflict"
        if len(self.entries) >= self.capacity:
            return "full"
        self.entries[mid] = (now, digest)
        return "new"

    def clear(self):
        self.entries.clear()


def _json(payload):
    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj:
                raise ValueError("duplicate JSON key")
            obj[k] = v
        return obj

    def constant(_value):
        raise ValueError("nonfinite JSON number")

    obj = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(obj, dict):
        raise ValueError("object required")
    return obj


def _code(body):
    value = body.get("code")
    if isinstance(value, str) and re.fullmatch(r"[0-9]{3}", value):
        value = int(value)
    return value if type(value) is int and 100 <= value <= 599 else None


def _reply(body, expected_id):
    # No notification ID is compared to registration ID: separate envelope types.
    return (
        set(body).issubset({"id", "code", "data", "message", "msg"})
        and type(body.get("id")) in (str, int)
        and str(body["id"]) == str(expected_id)
        and _code(body) is not None
        and isinstance(body.get("data"), dict)
    )


def _properties(body):
    if (
        set(body) != {"id", "version", "method", "params"}
        or not isinstance(body.get("id"), str)
        or not 1 <= len(body["id"]) <= 64
        or body.get("version") != "1.0"
        or body.get("method") != "thing.event.property.post"
    ):
        raise ValueError("unsupported notification envelope")
    props = body["params"]
    if not isinstance(props, dict) or not props or not set(props) <= STATES | {"refresh"}:
        raise ValueError("unsupported property shape")
    for key, value in props.items():
        if key == "version":
            if (
                not isinstance(value, str)
                or len(value) > 64
                or not value
                or not value.isprintable()
            ):
                raise ValueError("invalid version")
        elif key in ("pressure", "presSet"):
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e9:
                raise ValueError("invalid numeric property")
        elif type(value) is not int or abs(value) > 1_000_000_000:
            raise ValueError("invalid integer property")
        elif key in ("switch", "mode", "errorState", "run") and value not in (0, 1):
            raise ValueError("invalid binary/enum property")
        elif key == "refresh" and value != 1:
            raise ValueError("invalid refresh echo")
    return {k: v for k, v in props.items() if k in STATES}, "refresh" in props


def _options(message, path, session_id=None, *, discovery=False):
    allowed = {11, 12, 14} if session_id is None else {6, 11, 12, 14, 71}
    # Discovery may carry Observe metadata; unencrypted auth must not accept it.
    if discovery:
        allowed.add(6)
    if any(k not in allowed for k, _ in message["options"]):
        raise ValueError("unsupported protection/option")
    for number, max_size in ((6, 3), (12, 2), (14, 4)):
        values = p._option_values(message, number)
        if len(values) > 1 or (values and len(values[0]) > max_size):
            raise ValueError("invalid option shape")
    ctype = p._option_values(message, 12)
    if ctype:
        encoded = ctype[0]
        value = int.from_bytes(encoded, "big")
        if value not in (42, 50) and not (session_id is not None and encoded == b""):
            raise ValueError("unsupported content format")
    if p._option_values(message, 11) and p.coap_path(message) != path:
        raise ValueError("wrong resource identity")
    if session_id is not None:
        values = p._option_values(message, 71)
        if (
            len(values) != 1
            or not 1 <= len(values[0]) <= 4
            or int.from_bytes(values[0], "big") != session_id
        ):
            raise ValueError("wrong/missing session")


def _inputs(boundip, candidate, credentials, request_report, maxwait, allow_network):
    if type(request_report) is not bool or type(allow_network) is not bool:
        raise ValueError("explicit boolean flags required")
    if type(maxwait) not in (int, float) or not math.isfinite(maxwait) or not 0 < maxwait <= 60:
        raise ValueError("maxwait must be positive and at most 60 seconds")
    if not isinstance(credentials, dict) or any(
        not isinstance(credentials.get(k), str) or not 1 <= len(credentials[k]) <= 4096
        for k in ("productKey", "deviceName", "accessKey", "accessToken")
    ):
        raise ValueError("in-memory credentials required")
    if credentials["productKey"] != PRODUCT_KEY or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,64}", credentials["deviceName"]
    ):
        raise ValueError("unreviewed model/invalid device identity")
    if (
        not isinstance(candidate, dict)
        or not isinstance(candidate.get("profile"), list)
        or not any(
            isinstance(x, dict)
            and x.get("productKey") == credentials["productKey"]
            and x.get("deviceName") == credentials["deviceName"]
            for x in candidate["profile"]
        )
    ):
        raise ValueError("credential identity not in candidate profile")
    for index, addr in enumerate((boundip, candidate.get("ip"))):
        if not isinstance(addr, str):
            raise ValueError("literal unicast IPv4 string required")
        ip = ipaddress.IPv4Address(addr)
        if ip.is_multicast or (ip.is_unspecified and index != 0) or int(ip) == 0xFFFFFFFF:
            raise ValueError("literal unicast IPv4 required")
    port = candidate.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid peer port")
    if not allow_network:
        raise PermissionError("network disabled; explicit in-memory opt-in required")
    return (str(ipaddress.IPv4Address(candidate["ip"])), port)


async def run_once(
    boundip,
    candidate,
    credentials,
    request_report=False,
    maxwait=10,
    *,
    allow_network=False,
    _endpoint=None,
):
    """Authenticate, subscribe and collect a bounded local report; always close."""
    peer = _inputs(boundip, candidate, credentials, request_report, maxwait, allow_network)
    result = {
        "status": "auth_timeout",
        "auth_code": None,
        "auth_verified": False,
        "read_only": not request_report,
        "subscription_code": None,
        "subscribed": False,
        "telemetry": {},
        "receive_at": {},
        "reports": [],
        "notification_count": 0,
        "duplicate_count": 0,
        "rejected_packets": 0,
        "observe_zero_count": 0,
        "refresh": {
            "requested": request_report,
            "send_attempts": 0,
            "sent": False,
            "response_code": None,
            "status": "not_sent" if request_report else "disabled",
        },
    }
    sock, key, sid = None, None, None
    window = _Window()
    start = time.monotonic()
    overall = start + maxwait
    deadline = min(overall, start + 10)
    phase = "auth"
    base = secrets.randbelow(65536)
    token_prefix = secrets.token_bytes(7)
    nonce = secrets.token_hex(8)
    fmt = {"product_key": credentials["productKey"], "device_name": credentials["deviceName"]}
    requests = {}

    def send(stage):
        index = {"auth": 0, "subscribe": 1, "refresh": 2}[stage]
        mid = (base + index) % 65536
        token = token_prefix + bytes([index])
        if stage == "auth":
            path = p.AUTH_PATH_FMT.format(**fmt)
            body = p.build_auth_payload(
                mid,
                fmt["product_key"],
                fmt["device_name"],
                credentials["accessKey"],
                credentials["accessToken"],
                nonce,
            )
            options = [(12, b"\x32")]
        else:
            path = (POST if stage == "subscribe" else SET).format(**fmt)
            # The only property/set body in this module is fixed here. No caller
            # input can supply property keys, values, method, path or retries.
            body = p.build_request(
                mid,
                "thing.event.property.post"
                if stage == "subscribe"
                else "thing.service.property.set",
                {} if stage == "subscribe" else {"refresh": 1},
            )
            body = p.alcs_encrypt(body, key)
            options = [(12, b"\x2a"), (71, sid.to_bytes(4, "big"))]
            if stage == "subscribe":
                options.append((6, b""))
        requests[stage] = {"id": mid, "token": token, "path": path}
        packet = p.coap_encode(1, mid, token, path, body, p.COAP_TYPE_CON, options)
        if stage == "refresh":
            result["refresh"]["send_attempts"] = 1  # BEFORE send; a failed send may be uncertain
            result["refresh"]["status"] = "send_uncertain"
        written = sock.sendto(packet, peer)
        if written != len(packet):
            raise OSError("incomplete UDP send")
        if stage == "refresh":
            result["refresh"].update(sent=True, status="pending")

    def ack(message):
        if message["type"] == p.COAP_TYPE_CON:
            sock.sendto(
                p.coap_encode(0, message["msgid"], b"", "/", message_type=p.COAP_TYPE_ACK), peer
            )

    try:
        sock = Socket()
        if _endpoint is None:
            sock.bind((boundip, 0))
        else:
            result["status"] = "bind_error"
            _endpoint.bind(sock, boundip)
        result["status"] = "auth_timeout"
        send("auth")
        for _ in range(MAX_PACKETS):
            left = deadline - time.monotonic()
            if left <= 0:
                break
            sock.settimeout(left)
            try:
                packet, remote = await sock.recvfrom(16384)
            except TimeoutError:
                break
            if time.monotonic() >= deadline:
                break  # do not transition/send after the total/stage budget
            if remote != peer:
                result["rejected_packets"] += 1
                continue
            try:
                message = p.coap_decode(packet)
                stage = next(
                    (s for s, req in requests.items() if req["token"] == message["token"]), None
                )
                if (
                    stage is None
                    or (phase == "auth" and stage != "auth")
                    or message["type"] not in (0, 1, 2)
                ):
                    raise ValueError("unmatched message")
                if stage == "auth" and phase != "auth":
                    continue
                if message["code"] == 0 and not message["payload"]:
                    continue  # empty ACK is transport-only, no app success
                if message["code"] >= 128:
                    if stage == phase or stage == "subscribe":
                        result["status"] = (
                            "auth_rejected" if stage == "auth" else "subscription_rejected"
                        )
                        break
                    if stage == "refresh":
                        result["refresh"]["status"] = "rejected"
                    continue
                if message["code"] != 69 or not message["payload"]:
                    raise ValueError("not application content")
                req = requests[stage]
                _options(message, req["path"], None if stage == "auth" else sid)
                plain = (
                    message["payload"]
                    if stage == "auth"
                    else p.alcs_decrypt(message["payload"], key)
                )
                ack(message)  # pinned endpoint/token/session; including retransmissions
                body = _json(plain)
                if stage == "auth":
                    if not _reply(body, req["id"]):
                        raise ValueError("unmatched auth envelope")
                    result["auth_code"] = _code(body)
                    if result["auth_code"] != 200:
                        result["status"] = "auth_rejected"
                        break
                    data = body["data"]
                    try:
                        p.verify_server_proof(data, credentials["accessToken"])
                        p.negotiate_auth_options(data)
                        if type(data.get("opt")) is not int or data["opt"] != 1:
                            raise ValueError("this model requires explicit opt1")
                        value = data.get("sessionId")
                        if type(value) is not int and not (
                            isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value)
                        ):
                            raise ValueError("invalid session")
                        sid = int(value)
                        if not 1 <= sid <= 0xFFFFFFFF:
                            raise ValueError("invalid session")
                    except ValueError:
                        result["status"] = "auth_rejected"
                        break
                    result["auth_verified"] = True
                    key = p.hmac_sha1_raw(
                        (nonce + data["randomKey"]).encode(), credentials["accessToken"].encode()
                    )
                    phase, result["status"] = "subscribe", "subscription_timeout"
                    deadline = min(overall, time.monotonic() + 10)
                    if time.monotonic() >= deadline:
                        break
                    send("subscribe")
                elif stage == "refresh":
                    if not _reply(body, req["id"]) or body["data"] != {}:
                        raise ValueError("unmatched refresh response")
                    if result["refresh"]["response_code"] is None:
                        code = _code(body)
                        result["refresh"].update(
                            response_code=code, status="accepted" if code == 200 else "rejected"
                        )
                elif _reply(body, req["id"]):
                    if body["data"] != {}:
                        raise ValueError("invalid registration response data")
                    if result["subscribed"]:
                        continue  # duplicated registration must NEVER cause a second refresh
                    result["subscription_code"] = _code(body)
                    if result["subscription_code"] != 200:
                        result["status"] = "subscription_rejected"
                        break
                    result["subscribed"], result["status"] = True, "listened"
                    phase, deadline = "listen", overall
                    if request_report and time.monotonic() < overall:
                        send("refresh")
                else:
                    if not result["subscribed"] or len(p._option_values(message, 6)) != 1:
                        raise ValueError("not an established Observe notification")
                    props, echo = _properties(body)
                    dedupe = window.check(message["msgid"], plain, time.monotonic())
                    if dedupe == "duplicate":
                        result["duplicate_count"] += 1
                        continue
                    if dedupe == "full":
                        result["status"] = "dedupe_capacity"
                        break
                    if dedupe == "conflict":
                        raise ValueError("MID collision in duplicate window")
                    timestamp = datetime.now(UTC).isoformat()
                    result["telemetry"].update(props)
                    result["receive_at"].update({name: timestamp for name in props})
                    result["reports"].append(
                        {"receive_at": timestamp, "properties": props, "refresh_echo": echo}
                    )
                    result["notification_count"] += 1
                    if int.from_bytes(p._option_values(message, 6)[0], "big") == 0:
                        result["observe_zero_count"] += 1
                    if set(result["telemetry"]) == STATES:
                        result["status"] = "complete"
                        break
            except (ValueError, UnicodeError, OverflowError, RecursionError):
                result["rejected_packets"] += 1
                continue
        else:
            result["status"] = "packet_limit"
    except OSError:
        if result["status"] != "bind_error":
            result["status"] = "transport_error"
        # Never serialize exceptions, packets, identity, endpoint or keys.
    finally:
        window.clear()  # never carried across auth sessions/processes
        key, sid = None, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                result["status"] = "transport_error"
        if result["refresh"]["status"] == "pending":
            result["refresh"]["status"] = "unconfirmed"
    return result
