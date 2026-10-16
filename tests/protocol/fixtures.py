"""Independent synthetic server: cryptography AES oracle + standalone CoAP codec."""

import base64
import hashlib
import hmac
import json
import struct

from tests.protocol import oracle

CREDS = dict(
    productKey="a15zaTr5sp1",
    deviceName="SYNTHETIC_DEVICE",
    accessKey="synthetic-access",
    accessToken="synthetic-secret",
)
PEER, LOCAL = ("192.0.2.20", 5683), "192.0.2.10"
CANDIDATE = dict(
    ip=PEER[0],
    port=PEER[1],
    profile=[dict(productKey=CREDS["productKey"], deviceName=CREDS["deviceName"])],
)


def wire(code, mid, token=b"", payload=b"", opts=(), typ=0):
    def field(n):
        if n < 13:
            return n, b""
        if n < 269:
            return 13, bytes([n - 13])
        return 14, struct.pack("!H", n - 269)

    out = bytes([0x40 | typ << 4 | len(token), code]) + struct.pack("!H", mid) + token
    prev = 0
    for n, v in sorted(opts, key=lambda option: option[0]):
        d, de = field(n - prev)
        length, le = field(len(v))
        out += bytes([d << 4 | length]) + de + le + v
        prev = n
    return out + (b"\xff" + payload if payload else b"")


def unwire(packet):
    n = packet[0] & 15
    pos, prev, opts = 4 + n, 0, []

    def field(n):
        nonlocal pos
        if n == 13:
            v = packet[pos] + 13
            pos += 1
            return v
        if n == 14:
            v = int.from_bytes(packet[pos : pos + 2], "big") + 269
            pos += 2
            return v
        return n

    while pos < len(packet) and packet[pos] != 255:
        b = packet[pos]
        pos += 1
        d, size = field(b >> 4), field(b & 15)
        prev += d
        opts.append((prev, packet[pos : pos + size]))
        pos += size
    return dict(
        code=packet[1],
        mid=int.from_bytes(packet[2:4], "big"),
        type=packet[0] >> 4 & 3,
        token=packet[4 : 4 + n],
        opts=opts,
        payload=packet[pos + 1 :] if pos < len(packet) else b"",
        path="/" + "/".join(v.decode() for k, v in opts if k == 11),
    )


def js(obj):
    return json.dumps(obj, separators=(",", ":")).encode()


def report(props):
    return dict(
        id="new-not-registration-id",
        version="1.0",
        method="thing.event.property.post",
        params=props,
    )


def rewire(m):
    return wire(m["code"], m["mid"], m["token"], m["payload"], m["opts"], m["type"])


class FakeSocket:
    def __init__(
        self,
        auth_change=None,
        subscribe_code=200,
        notifications=None,
        notification_change=None,
        reg_change=None,
        refresh_code=200,
        response_first=False,
        send_failure=False,
        noise=None,
        reply_transform=None,
        only_ack=False,
        content_format=b"\x32",
        auth_options=None,
    ):
        self.auth_change, self.reg_change = auth_change, reg_change
        self.subscribe_code, self.refresh_code = subscribe_code, refresh_code
        self.notifications = (
            [(101, report({"refresh": 1})), (102, report({"pressure": 1.3, "temperature": 23}))]
            if notifications is None
            else notifications
        )
        self.notification_change, self.response_first, self.send_failure, self.noise = (
            notification_change,
            response_first,
            send_failure,
            noise,
        )
        self.reply_transform, self.only_ack = reply_transform, only_ack
        self.content_format = content_format
        self.auth_options = [(12, b"\x32")] if auth_options is None else auth_options
        self.queue, self.sent, self.acks = [], [], []
        self.closed, self.bound, self.timeout, self.key = False, None, None, None

    def bind(self, a):
        self.bound = a

    def getsockname(self):
        return (self.bound[0], self.bound[1] or 49152)

    def settimeout(self, v):
        self.timeout = v

    def close(self):
        self.closed = True

    def push(self, packet, peer=PEER):
        m = unwire(packet)
        if self.only_ack and m["code"] != 0:
            return
        if self.reply_transform and m["code"] == 69 and not any(k == 6 for k, v in m["opts"]):
            packet, peer = self.reply_transform(len(self.sent), packet, peer, self)
        self.queue.append((packet, peer))

    def secure(self, req, body, mid=91, opts=None, typ=0):
        opts = [(12, self.content_format), (71, b"G")] if opts is None else opts
        return wire(
            69,
            mid,
            req["token"],
            oracle.encrypt(body if isinstance(body, bytes) else js(body), self.key),
            opts,
            typ,
        )

    def sendto(self, packet, peer):
        sent_length = len(packet)
        req = unwire(packet)
        if req["code"] == 0:
            self.acks.append(req)
            assert req["token"] == b"" and req["opts"] == [] and req["payload"] == b""
            return sent_length
        assert peer == PEER and req["code"] == 1
        self.sent.append(req)
        if req["path"].endswith("/core/service/auth"):
            body = json.loads(req["payload"])
            nonce = "SERVERnonce1234"
            assert len(nonce) == 15
            self.key = hmac.new(
                CREDS["accessToken"].encode(),
                (body["params"]["randomKey"] + nonce).encode(),
                hashlib.sha1,
            ).digest()
            data = dict(
                randomKey=nonce,
                sign=base64.b64encode(
                    hmac.new(
                        CREDS["accessToken"].encode(), nonce.encode() + b"\0", hashlib.sha1
                    ).digest()
                ).decode(),
                sessionId=71,
                opt=1,
                seqStart=-20,
            )
            reply = dict(id=str(body["id"]), code=200, data=data)
            if self.auth_change:
                self.auth_change(reply)
            self.push(wire(0, req["mid"], typ=2))
            self.push(wire(69, 80, req["token"], js(reply), self.auth_options))
        else:
            req["body"] = json.loads(oracle.decrypt(req["payload"], self.key))
            if req["path"].endswith("/thing/event/property/post"):
                assert (6, b"") in req["opts"] and req["body"]["params"] == {}
                assert req["body"]["method"] == "thing.event.property.post"
                reply = dict(id=req["body"]["id"], code=self.subscribe_code, data={})
                if self.reg_change:
                    self.reg_change(reply)
                if self.noise:
                    self.noise(self, req)
                self.push(wire(0, req["mid"], typ=2))
                self.push(self.secure(req, reply))
                for mid, body in self.notifications:
                    packet = self.secure(
                        req, body, mid, [(6, b""), (12, self.content_format), (71, b"G")]
                    )
                    peer = PEER
                    if self.notification_change:
                        packet, peer = self.notification_change(packet, peer, self)
                    self.push(packet, peer)
            elif req["path"].endswith("/thing/service/property/set"):
                assert (
                    req["body"]["params"] == {"refresh": 1}
                    and type(req["body"]["params"]["refresh"]) is int
                )
                assert req["body"]["method"] == "thing.service.property.set" and all(
                    k != 6 for k, v in req["opts"]
                )
                if self.send_failure:
                    raise OSError("synthetic-secret must not escape")
                if self.refresh_code is not None:
                    packet = self.secure(
                        req, dict(id=req["body"]["id"], code=self.refresh_code, data={}), mid=202
                    )
                    if self.response_first:
                        self.queue.insert(0, (packet, PEER))
                    else:
                        self.push(packet)
            else:
                raise AssertionError("unapproved resource")
        return sent_length

    async def recvfrom(self, n):
        if self.queue:
            return self.queue.pop(0)
        raise TimeoutError()


def mutate_packet(packet, peer, fake, kind):
    m = unwire(packet)
    if kind == "peer":
        return packet, ("192.0.2.99", 5683)
    if kind == "port":
        return packet, (PEER[0], 9999)
    if kind == "token":
        m["token"] = b"wrong"
    elif kind == "path":
        m["opts"].append((11, b"wrong"))
    elif kind == "sequence":
        m["opts"].append((72, b"\0"))
    elif kind == "group":
        m["opts"].append((73, b"x"))
    elif kind == "unknown_option":
        m["opts"].append((99, b""))
    elif kind == "bad_ciphertext":
        m["payload"] = b"bad"
    else:
        key = 71 if "session" in kind else (6 if "observe" in kind else 12)
        if kind.startswith("missing"):
            m["opts"] = [(k, v) for k, v in m["opts"] if k != key]
        elif kind.startswith("duplicate"):
            m["opts"].append((key, b"G" if key == 71 else b""))
        else:
            value = {
                "session": b"H",
                "oversized_session": b"\0\0\0\0G",
                "oversized_observe": b"\0" * 4,
                "format": b"\0",
                "oversized_format": b"\0" * 3,
            }[kind]
            m["opts"] = [(k, value if k == key else v) for k, v in m["opts"]]
    return rewire(m), peer
