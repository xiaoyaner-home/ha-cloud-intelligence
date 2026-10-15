"""Independent synthetic LAN server, input boundaries and cryptographic oracle."""

import asyncio
import ipaddress
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from custom_components.cloud_intelligence import alcs, telemetry
from custom_components.cloud_intelligence.client import (
    CannotConnect,
    IdentityMismatch,
    InvalidAuth,
    LocalClient,
    validate_input,
)
from tests.protocol import oracle
from tests.protocol.fixtures import CREDS, PEER, FakeSocket, js, report, rewire, unwire, wire

DATA = {**CREDS, "host": "192.168.254.20", "name": "Synthetic pump"}
VALUES = dict(
    switch=1,
    temperature=23,
    presSet=4,
    mode=0,
    error=0,
    errorState=0,
    run=0,
    propor=30,
    version="SYNTHETIC-v1",
    pressure=1.3,
    tarSpeed=1800,
    nowSpeed=0,
)


class LanSocket(FakeSocket):
    def __init__(self, profile=None, discovery_noise=(), **kwargs):
        super().__init__(**kwargs)
        self.profile = (
            [{"productKey": CREDS["productKey"], "deviceName": CREDS["deviceName"]}]
            if profile is None
            else profile
        )
        self.discovery_noise = discovery_noise

    def sendto(self, packet, peer):
        self.assert_peer = peer
        req = unwire(packet)
        if req["path"] == "/dev/core/service/dev":
            self.sent.append(req)
            body = json.loads(req["payload"])
            for noise in self.discovery_noise:
                self.queue.append(noise)
            self.queue.append(
                (
                    wire(
                        69,
                        12,
                        req["token"],
                        js(
                            {
                                "id": body["id"],
                                "code": 200,
                                "data": {"devices": {"profile": self.profile, "port": 9999}},
                            }
                        ),
                        [(12, b"\x32")],
                    ),
                    PEER,
                )
            )
            return len(packet)
        return super().sendto(packet, PEER)

    async def recvfrom(self, n):
        packet, peer = await super().recvfrom(n)
        return packet, (DATA["host"], 5683) if peer == PEER else peer


class DiscoverySocket:
    """Independent fake UDP: empty ACK, then NON/Observe 0 with the full URI."""

    def __init__(self, change=None, remote=None, observe=(b"",), only_ack=False):
        self.change, self.remote, self.observe, self.only_ack = change, remote, observe, only_ack
        self.sent, self.received, self.queue = [], [], []
        self.closed = False

    def bind(self, address):
        self.bound = address

    def settimeout(self, timeout):
        self.timeout = timeout

    def close(self):
        self.closed = True

    def sendto(self, packet, peer):
        request = unwire(packet)
        assert request["code"] == 1 and request["path"] == "/dev/core/service/dev"
        self.sent.append((request, peer))
        body = {
            "id": json.loads(request["payload"])["id"],
            "code": 200,
            "data": {"devices": {"profile": [{k: CREDS[k] for k in ("productKey", "deviceName")}]}},
            "message": "",
        }
        body["message"] = "x" * (168 - len(js(body)))
        response = dict(
            code=69,
            mid=(request["mid"] + 17) % 65536,
            type=1,
            token=request["token"],
            payload=js(body),
            opts=[(6, value) for value in self.observe]
            + [(11, part) for part in (b"dev", b"core", b"service", b"dev")],
        )
        if self.change:
            self.change(response)
        self.queue.append((wire(0, request["mid"], typ=2), peer))
        if not self.only_ack:
            self.queue.append((rewire(response), peer if self.remote is None else self.remote))
        return len(packet)

    async def recvfrom(self, size):
        if not self.queue:
            raise TimeoutError
        packet, peer = self.queue.pop(0)
        self.received.append(unwire(packet))
        return packet, peer


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        guard = patch("socket.socket", side_effect=AssertionError("REAL NETWORK FORBIDDEN"))
        guard.start()
        self.addCleanup(guard.stop)

    async def run_client(self, *, profile=None, require_complete=False, **kwargs):
        discovery, state = LanSocket(profile=profile), LanSocket(**kwargs)
        with patch.object(telemetry, "Socket", side_effect=[discovery, state]):
            try:
                result = await LocalClient(DATA).read(require_complete=require_complete)
            finally:
                self.assertTrue(discovery.closed)
        self.assertTrue(state.closed)
        return result, state

    async def test_complete_real_wire_without_phone_dependency(self):
        data, state = await self.run_client(
            notifications=[(101, report(VALUES))], content_format=b"", require_complete=True
        )
        self.assertTrue(data.complete)
        self.assertEqual(data.snapshot.powered, True)
        self.assertEqual(data.snapshot.running, False)
        self.assertIsNone(data.snapshot.sample("pressure").reported_at_ms)
        self.assertEqual(len(data.received_at), 12)
        self.assertEqual(len(state.sent), 3)
        self.assertEqual(state.assert_peer, (DATA["host"], 5683))

    async def test_discovery_non_observe_zero_complete_report_once(self):
        discovery = DiscoverySocket()
        state = LanSocket(notifications=[(101, report(VALUES))], content_format=b"")
        with patch.object(telemetry, "Socket", side_effect=[discovery, state]) as factory:
            result = await LocalClient(DATA).read(require_complete=True)
        self.assertTrue(discovery.closed and state.closed)
        self.assertEqual(factory.call_count, 2)
        self.assertTrue(result.complete)
        self.assertEqual(len(result.received_at), 12)
        self.assertEqual(len(discovery.sent), 1)
        request, peer = discovery.sent[0]
        self.assertEqual(peer, (DATA["host"], 5683))
        ack, response = discovery.received
        self.assertEqual((ack["code"], ack["type"], ack["token"]), (0, 2, b""))
        self.assertEqual(ack["mid"], request["mid"])
        self.assertEqual((response["code"], response["type"]), (69, 1))
        self.assertNotEqual(response["mid"], request["mid"])
        self.assertEqual(response["token"], request["token"])
        self.assertEqual(len(response["payload"]), 168)
        self.assertEqual(response["path"], "/dev/core/service/dev")
        self.assertEqual(
            [(n, len(v)) for n, v in response["opts"]], [(6, 0), (11, 3), (11, 4), (11, 7), (11, 3)]
        )
        self.assertEqual(len(state.sent), 3)
        self.assertTrue(state.sent[0]["path"].endswith("/core/service/auth"))
        self.assertTrue(state.sent[1]["path"].endswith("/thing/event/property/post"))
        refresh = [r for r in state.sent if r["path"].endswith("/thing/service/property/set")]
        self.assertEqual(len(refresh), 1)
        self.assertEqual(refresh[0]["body"]["params"], {"refresh": 1})

    async def test_discovery_observe_uint24_boundary(self):
        for value in (b"\0", b"\x01", b"\x01\0", b"\xff\xff\xff"):
            with self.subTest(value=value):
                discovery = DiscoverySocket(observe=(value,))
                state = LanSocket(notifications=[(101, report(VALUES))])
                with patch.object(telemetry, "Socket", side_effect=[discovery, state]):
                    self.assertTrue((await LocalClient(DATA).read(require_complete=True)).complete)
                self.assertTrue(discovery.closed and state.closed)

    async def test_discovery_observe_does_not_relax_initial_completeness(self):
        discovery, state = DiscoverySocket(), LanSocket()
        with patch.object(telemetry, "Socket", side_effect=[discovery, state]):
            with self.assertRaises(CannotConnect):
                await LocalClient(DATA).read(require_complete=True)
        self.assertTrue(discovery.closed and state.closed)
        self.assertEqual(len(state.sent), 3)

    async def test_discovery_observe_rejects_invalid_options_before_auth(self):
        for options in (
            [(6, b""), (6, b"\x01")],
            [(6, b"\x01\0\0\0")],
            *[[(6, b""), (number, b"G")] for number in (71, 72, 73, 99)],
        ):
            with self.subTest(options=options):
                await self.assert_discovery_rejected(
                    DiscoverySocket(
                        change=lambda m, options=options: m.update(opts=options + m["opts"][1:])
                    )
                )

    async def assert_discovery_rejected(self, discovery, error=CannotConnect):
        state = LanSocket(notifications=[(101, report(VALUES))])
        with patch.object(telemetry, "Socket", side_effect=[discovery, state]) as factory:
            with self.assertRaises(error):
                await LocalClient(DATA).read(require_complete=True)
        self.assertTrue(discovery.closed)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(len(discovery.sent), 1)
        self.assertEqual(state.sent, [])

    async def test_discovery_observe_preserves_correlation_before_auth(self):
        for field, value in (("token", b"wrong"), ("code", 68), ("type", 3)):
            with self.subTest(field=field):
                await self.assert_discovery_rejected(
                    DiscoverySocket(
                        change=lambda m, field=field, value=value: m.update({field: value})
                    )
                )
        for remote in (("192.168.254.21", 5683), (DATA["host"], 9999)):
            with self.subTest(remote=remote):
                await self.assert_discovery_rejected(DiscoverySocket(remote=remote))
        await self.assert_discovery_rejected(DiscoverySocket(only_ack=True))
        await self.assert_discovery_rejected(
            DiscoverySocket(change=lambda m: m["opts"].append((11, b"wrong")))
        )

    async def test_discovery_observe_preserves_application_and_device_identity(self):
        for field in ("id", "productKey", "deviceName"):

            def change(message, field=field):
                body = json.loads(message["payload"])
                if field == "id":
                    body["id"] = "wrong"
                else:
                    body["data"]["devices"]["profile"][0][field] = "OTHER"
                message["payload"] = js(body)

            with self.subTest(field=field):
                await self.assert_discovery_rejected(
                    DiscoverySocket(change=change),
                    CannotConnect if field == "id" else IdentityMismatch,
                )

    async def test_initial_partial_rejected_subsequent_partial_not_zero(self):
        with self.assertRaises(CannotConnect):
            await self.run_client(require_complete=True)
        data, _ = await self.run_client()
        self.assertFalse(data.complete)
        self.assertIsNone(data.snapshot.sample("run").value)
        self.assertEqual(data.snapshot.sample("pressure").value, 1.3)

    async def test_wrong_identity_no_auth_or_report(self):
        discovery = LanSocket(profile=[{"productKey": CREDS["productKey"], "deviceName": "OTHER"}])
        with patch.object(telemetry, "Socket", return_value=discovery):
            with self.assertRaises(IdentityMismatch):
                await LocalClient(DATA).read()
        self.assertTrue(discovery.closed)
        self.assertEqual(len(discovery.sent), 1)

    async def test_auth_rejected_sanitized(self):
        with self.assertRaises(InvalidAuth) as error:
            await self.run_client(auth_change=lambda body: body.update(code=401))
        self.assertNotIn(CREDS["accessToken"], str(error.exception))
        self.assertNotIn(CREDS["accessToken"], repr(LocalClient(DATA)))

    async def test_no_notifications_is_failure(self):
        with self.assertRaises(CannotConnect):
            await self.run_client(notifications=[])

    async def test_identity_noise_and_timeout(self):
        fake = LanSocket()
        fake.recvfrom = AsyncMock(side_effect=TimeoutError)
        with patch.object(telemetry, "Socket", return_value=fake):
            with self.assertRaises(CannotConnect):
                await LocalClient(DATA).read()
        self.assertTrue(fake.closed)

    async def test_identity_rejects_bad_messages(self):
        for bad in (
            (b"bad", PEER),
            (wire(69, 1, b"wrong", b"{}"), PEER),
            (wire(0, 1, b"", b""), PEER),
            (wire(69, 1, b"wrong", b"{}"), ("192.0.2.99", 5683)),
        ):
            fake, state = (
                LanSocket(discovery_noise=[bad]),
                LanSocket(notifications=[(101, report(VALUES))]),
            )
            with patch.object(telemetry, "Socket", side_effect=[fake, state]):
                data = await LocalClient(DATA).read(require_complete=True)
                self.assertTrue(data.complete)

    async def test_cancel_closes_identity_socket(self):
        fake = LanSocket()
        fake.recvfrom = AsyncMock(side_effect=lambda n: asyncio.Event().wait())

        # A cancellable receive (not a sleeping thread).
        async def wait(n):
            await asyncio.Event().wait()

        fake.recvfrom = wait
        with patch.object(telemetry, "Socket", return_value=fake):
            task = asyncio.create_task(LocalClient(DATA).read())
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(fake.closed)

    async def test_total_timeout_and_socket_close(self):
        fake = LanSocket()

        async def wait(n):
            await asyncio.Event().wait()

        fake.recvfrom = wait
        with patch.object(telemetry, "Socket", return_value=fake):
            with self.assertRaises(CannotConnect):
                await LocalClient(DATA, timeout=0.01).read()
        self.assertTrue(fake.closed)

    async def test_invalid_config_before_socket(self):
        for key, value in [
            ("productKey", "unknown"),
            ("deviceName", "bad/identity"),
            ("accessKey", ""),
            ("accessToken", " padded"),
            ("host", "8.8.8.8"),
            ("host", "127.0.0.1"),
            ("host", "224.0.1.187"),
            ("host", "0.0.0.0"),
            ("host", "device.local"),
            ("host", "::1"),
            ("name", 12),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                await LocalClient({**DATA, key: value}).read()
        for timeout in (0, 11, True):
            with self.assertRaises(ValueError):
                await LocalClient(DATA, timeout=timeout).read()
        self.assertEqual(
            validate_input({k: v for k, v in DATA.items() if k != "name"})["name"],
            "Wilo HiMulti-1 WiFi",
        )

    async def test_host_must_be_literal_text_and_extra_inputs_not_stored(self):
        with self.assertRaises(ValueError):
            validate_input({**DATA, "host": int(ipaddress.IPv4Address(DATA["host"]))})
        self.assertNotIn(
            "unused_secret", validate_input({**DATA, "unused_secret": "synthetic-extra"})
        )

    async def test_socket_adapter_nonblocking(self):
        sock = Mock()
        with patch.object(telemetry.socket, "socket", return_value=sock):
            udp = telemetry.Socket()
        sock.setblocking.assert_called_once_with(False)
        udp.bind(("0.0.0.0", 0))
        udp.settimeout(0.1)
        udp.sendto(b"packet", PEER)
        with patch.object(
            asyncio.get_running_loop(), "sock_recvfrom", new=AsyncMock(return_value=(b"data", PEER))
        ):
            self.assertEqual(await udp.recvfrom(10), (b"data", PEER))
        udp.close()
        sock.close.assert_called_once()


class CryptoTests(unittest.TestCase):
    def test_independent_ecb_oracle_all_block_boundaries(self):
        key = bytes(range(20))
        for size in (1, 15, 16, 17, 31, 32, 33, 100, 1000):
            data = bytes(i % 256 for i in range(size))
            ciphertext = oracle.encrypt(data, key)
            self.assertEqual(alcs.alcs_encrypt(data, key), ciphertext)
            self.assertEqual(alcs.alcs_decrypt(ciphertext, key), data)
            self.assertEqual(oracle.decrypt(alcs.alcs_encrypt(data, key), key), data)

    def test_invalid_ciphertext_and_empty_payload(self):
        for data in (b"", b"x", bytes(16), bytes(32)):
            with self.assertRaises(ValueError):
                alcs.alcs_decrypt(data, bytes(20))
        with self.assertRaises(ValueError):
            alcs.alcs_encrypt(b"", bytes(20))

    def test_coap_malformed_and_extended_options(self):
        for data in (
            b"",
            b"123",
            b"\x49\x01\x00\x01",
            b"\x40\x01\x00\x01\xf0",
            b"\x40\x01\x00\x01\xd0",
            b"\x40\x01\x00\x01\xe0\0",
        ):
            with self.assertRaises(ValueError):
                alcs.coap_decode(data)
        packet = alcs.coap_encode(1, 12, b"token", "/abc", b"body", options=[(300, b"x" * 300)])
        self.assertEqual(alcs.coap_decode(packet)["payload"], b"body")
        for kwargs in ({"msgid": -1}, {"token": b"x" * 9}, {"path": "bad"}):
            with self.assertRaises(ValueError):
                alcs.coap_encode(**dict(dict(code=1, msgid=1, token=b"", path="/"), **kwargs))
