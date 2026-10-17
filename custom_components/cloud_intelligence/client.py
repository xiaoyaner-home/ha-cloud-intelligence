"""One-device LAN identity validation and bounded telemetry acquisition."""

import asyncio
import ipaddress
import math
import re
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from . import alcs, telemetry
from ._core import WILO_MODEL_KEY, Snapshot, parse_snapshot
from .power import (
    PowerCancelled,
    PowerDisabled,
    PowerOutcomeUnknown,
    PowerResult,
    _PowerAttempt,
)


class CannotConnect(Exception):
    """The local device did not provide valid telemetry."""


class InvalidAuth(Exception):
    """The device rejected the authorization or server proof."""


class IdentityMismatch(Exception):
    """The configured identity was not advertised by this device."""


def validate_input(data: Mapping) -> dict:
    """Never normalize identifiers or permit remote hosts/DNS."""
    result = {}
    for key in ("productKey", "deviceName", "accessKey", "accessToken"):
        value = data.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= 4096 or value != value.strip():
            raise ValueError("Invalid authorization field")
        result[key] = value
    if data["productKey"] != telemetry.PRODUCT_KEY:
        raise ValueError("Unsupported model")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", data["deviceName"]):
        raise ValueError("Invalid device identity")
    if not isinstance(data.get("host"), str):
        raise ValueError("A literal IPv4 string is required")
    address = ipaddress.IPv4Address(data["host"])
    result["host"] = data["host"]
    if not any(
        address in ipaddress.IPv4Network(net)
        for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    ):
        raise ValueError("A private LAN IPv4 address is required")
    if not isinstance(data.get("name", "Wilo HiMulti-1 WiFi"), str):
        raise ValueError("Invalid name")
    result["name"] = data.get("name") or "Wilo HiMulti-1 WiFi"
    return result


@dataclass(frozen=True)
class LocalSnapshot:
    snapshot: Snapshot
    received_at: Mapping[str, str]
    complete: bool


@dataclass
class LocalClient:
    # Do not allow dataclass representations to expose authorization.
    data: dict = field(repr=False)
    timeout: float = 10.0
    enable_power_control: bool = False
    _endpoint: telemetry._Endpoint = field(
        default_factory=telemetry._Endpoint, init=False, repr=False
    )
    _reading: bool = field(default=False, init=False, repr=False)

    async def _identity(self, peer, deadline):
        sock = telemetry.Socket()
        mid, token = secrets.randbelow(65536), secrets.token_bytes(8)
        path = "/dev/core/service/dev"
        try:
            sock.bind(("0.0.0.0", 0))
            sock.sendto(
                alcs.coap_encode(
                    1,
                    mid,
                    token,
                    path,
                    alcs.build_request(mid, "core/service/dev", {}),
                    options=[(12, b"\x32")],
                ),
                peer,
            )
            for _ in range(telemetry.MAX_PACKETS):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                packet, remote = await sock.recvfrom(16384)
                if remote != peer:
                    continue
                try:
                    message = alcs.coap_decode(packet)
                    if (
                        message["token"] != token
                        or message["code"] != 69
                        or message["type"] not in (0, 1, 2)
                    ):
                        continue
                    telemetry._options(message, path, discovery=True)
                    body = telemetry._json(message["payload"])
                    if not telemetry._reply(body, mid) or telemetry._code(body) != 200:
                        continue
                    devices = body["data"].get("devices")
                    profile = devices.get("profile") if isinstance(devices, dict) else None
                    if not isinstance(profile, list):
                        continue
                    if not any(
                        isinstance(p, dict)
                        and p.get("productKey") == self.data["productKey"]
                        and p.get("deviceName") == self.data["deviceName"]
                        for p in profile
                    ):
                        raise IdentityMismatch
                    # Do not follow a port or address supplied in an unauthenticated reply.
                    if message["type"] == 0:
                        sock.sendto(
                            alcs.coap_encode(0, message["msgid"], b"", "/", message_type=2), peer
                        )
                    return
                except (ValueError, UnicodeError, RecursionError):
                    continue
            raise CannotConnect
        finally:
            sock.close()

    async def read(self, *, require_complete=False) -> LocalSnapshot:
        """Reject overlapping reads immediately; no queue outside the total budget."""
        if self._reading:
            raise CannotConnect("Read already in progress")
        self._reading = True
        try:
            return await self._read_once(require_complete=require_complete)
        finally:
            self._reading = False

    async def set_power(self, enabled: bool, *, _deadline: float | None = None) -> PowerResult:
        """Experimental enable permission, not motor running. Never retry a send.

        A fresh full pre-read and the write share one authenticated Observe session.
        Verification reauthenticates AFTER send on the same endpoint, under the same
        exclusive 10-second operation budget. Old session notifications cannot prove
        success. Local receive time is not a device timestamp or anti-replay proof.
        `_deadline` is an internal time.monotonic() boundary: it may only tighten
        the operation budget, including synchronous validation and packet encoding.
        """
        if type(enabled) is not bool:
            raise TypeError("Power requires a strict bool")
        if self.enable_power_control is not True:
            raise PowerDisabled("Experimental power control is disabled")
        if self._reading:
            raise CannotConnect("Operation already in progress")
        self._reading = True
        attempt = _PowerAttempt(enabled)
        try:
            if type(self.timeout) not in (float, int) or not 0 < self.timeout <= 10:
                raise ValueError("Invalid timeout")
            # Start BEFORE synchronous validation. A caller may tighten this
            # time.monotonic boundary, never extend the client's own budget.
            deadline = time.monotonic() + self.timeout
            if _deadline is not None:
                if type(_deadline) not in (int, float) or not math.isfinite(_deadline):
                    raise ValueError("Invalid operation deadline")
                deadline = min(deadline, _deadline)
            self.data = validate_input(self.data)
            peer = (self.data["host"], 5683)
            candidate = {"ip": peer[0], "port": peer[1], "profile": [self.data]}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CannotConnect
            async with asyncio.timeout(remaining):
                await self._identity(peer, deadline)

                async def report(power=None):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CannotConnect
                    result = await telemetry.run_once(
                        "0.0.0.0",
                        candidate,
                        self.data,
                        request_report=True,
                        maxwait=remaining,
                        allow_network=True,
                        _endpoint=self._endpoint,
                        _power=power,
                        _deadline=deadline,
                    )
                    if result["status"] not in ("complete",):
                        if result["status"] == "auth_rejected":
                            raise InvalidAuth
                        raise CannotConnect
                    snapshot = self._snapshot(result, require_complete=True)
                    if time.monotonic() >= deadline:
                        raise CannotConnect
                    return snapshot

                before = await report(attempt)
                if not attempt.started:
                    if before.snapshot.powered != enabled or not attempt.before:
                        raise CannotConnect
                    return PowerResult(False, before, MappingProxyType(attempt.before))
                after = await report()
                if after.snapshot.powered != enabled or any(
                    after.snapshot.sample(k).value != attempt.before[k]
                    for k in telemetry.SETTINGS - {"switch"}
                ):
                    raise PowerOutcomeUnknown
                return PowerResult(True, after, MappingProxyType(attempt.before))
        except asyncio.CancelledError:
            if attempt.started:
                raise PowerCancelled from None
            raise
        except (CannotConnect, InvalidAuth, IdentityMismatch):
            if attempt.started:
                raise PowerOutcomeUnknown from None
            raise
        except (TimeoutError, OSError):
            if attempt.started:
                raise PowerOutcomeUnknown from None
            raise CannotConnect from None
        except Exception:
            if attempt.started:
                raise PowerOutcomeUnknown from None
            raise
        finally:
            self._reading = False

    async def _read_once(self, *, require_complete) -> LocalSnapshot:
        self.data = validate_input(self.data)
        if type(self.timeout) not in (float, int) or not 0 < self.timeout <= 10:
            raise ValueError("Invalid timeout")
        peer = (self.data["host"], 5683)
        deadline = time.monotonic() + self.timeout
        try:
            async with asyncio.timeout(self.timeout):
                await self._identity(peer, deadline)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CannotConnect
                candidate = {"ip": peer[0], "port": peer[1], "profile": [self.data]}
                result = await telemetry.run_once(
                    "0.0.0.0",
                    candidate,
                    self.data,
                    request_report=True,
                    maxwait=remaining,
                    allow_network=True,
                    _endpoint=self._endpoint,
                )
        except (TimeoutError, OSError):
            raise CannotConnect from None
        if result["status"] == "bind_error":
            raise CannotConnect("UDP endpoint bind failed")
        if result["status"] == "auth_rejected":
            raise InvalidAuth
        if not result["auth_verified"] or not result["subscribed"] or not result["telemetry"]:
            raise CannotConnect
        return self._snapshot(result, require_complete=require_complete)

    @staticmethod
    def _snapshot(result, *, require_complete):
        # Local reports contain NO device source timestamps. Keep them absent.
        snapshot = parse_snapshot(
            {"code": "200", "data": {k: {"value": v} for k, v in result["telemetry"].items()}},
            model_key=WILO_MODEL_KEY,
        )
        complete = all(snapshot.sample(k).value is not None for k in telemetry.STATES)
        if require_complete and not complete:
            raise CannotConnect
        return LocalSnapshot(snapshot, MappingProxyType(dict(result["receive_at"])), complete)
