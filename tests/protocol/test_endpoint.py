"""Endpoint lifecycle regressions, NOT a reproduction of a hardware failure.

Real UDP is restricted to loopback. Protocol replies are synthetic; no LAN/cloud
or device access is performed, even though LocalClient retains its input gate.
"""

import asyncio
import socket
import unittest
from unittest.mock import patch

from custom_components.cloud_intelligence import telemetry
from custom_components.cloud_intelligence.client import (
    CannotConnect,
    IdentityMismatch,
    InvalidAuth,
    LocalClient,
)
from tests.protocol.fixtures import report, unwire
from tests.protocol.test_client import DATA, VALUES, LanSocket
from tests.protocol.test_power import PowerSocket

UDP = telemetry.Socket


class BoundLanSocket(LanSocket):
    """Synthetic protocol server with a real, exclusively loopback UDP binding."""

    def __init__(self, sink, **kwargs):
        super().__init__(**kwargs)
        self.udp = UDP()
        self.sink = sink
        self.entered = asyncio.Event()
        self.block = False

    def bind(self, address):
        self.bound = address
        self.udp.bind(("127.0.0.1", address[1]))
        self.actual = self.udp.socket.getsockname()

    def getsockname(self):
        return self.udp.socket.getsockname()

    def sendto(self, packet, peer):
        assert peer == (DATA["host"], 5683)
        # Capture actual outgoing UDP source ports, not just bind arguments.
        self.udp.sendto(packet, self.sink.getsockname())
        return super().sendto(packet, peer)

    async def recvfrom(self, size):
        self.entered.set()
        if self.block:
            await asyncio.Event().wait()
        return await super().recvfrom(size)

    def close(self):
        self.udp.close()
        super().close()


class BoundPowerSocket(BoundLanSocket, PowerSocket):
    """Real loopback endpoint with synthetic enable-only server behavior."""


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sink.bind(("127.0.0.1", 0))
        self.sink.setblocking(False)
        self.addCleanup(self.sink.close)
        self.sockets = []

    def state(self, **kwargs):
        sock = BoundLanSocket(self.sink, notifications=[(101, report(VALUES))], **kwargs)
        self.sockets.append(sock)
        self.addCleanup(sock.close)
        return sock

    async def read_round(self, client, state=None):
        discovery = self.state()
        state = self.state() if state is None else state
        with patch.object(telemetry, "Socket", side_effect=[discovery, state]):
            try:
                result = await client.read(require_complete=True)
            finally:
                self.assertTrue(discovery.closed)
                self.assertTrue(state.closed)
        return result, state

    async def test_power_rebinds_actual_endpoint_and_read_reuses_it(self):
        client = LocalClient(dict(DATA), enable_power_control=True)
        sockets = [
            BoundPowerSocket(self.sink),
            BoundPowerSocket(self.sink, notifications=[(101, report(VALUES))]),
            BoundPowerSocket(self.sink, notifications=[(301, report({**VALUES, "switch": 0}))]),
        ]
        for sock in sockets:
            self.addCleanup(sock.close)
        with patch.object(telemetry, "Socket", side_effect=sockets):
            result = await client.set_power(False)
        self.assertTrue(result.sent)
        self.assertEqual(sockets[1].actual, sockets[2].actual)
        self.assertTrue(all(sock.udp.socket.fileno() == -1 for sock in sockets))
        _, state = await self.read_round(client)
        self.assertEqual(state.actual, sockets[1].actual)
        seen_power = []
        while True:
            try:
                packet, peer = self.sink.recvfrom(16384)
            except BlockingIOError:
                break
            req = unwire(packet)
            if req["token"] == sockets[1].power_requests[0]["token"]:
                seen_power.append(peer)
        self.assertEqual(seen_power, [sockets[1].actual])

    async def test_repeated_reads_use_actual_same_source_endpoint(self):
        client = LocalClient(dict(DATA))
        states = []
        for _ in range(4):
            result, state = await self.read_round(client)
            self.assertTrue(result.complete)
            states.append(state)
        ports = [state.actual[1] for state in states]
        self.assertEqual(ports, [ports[0]] * 4)
        self.assertEqual([state.bound[1] for state in states], [0] + [ports[0]] * 3)
        # Each auth datagram really traverses loopback with that source port.
        seen = []
        while True:
            try:
                packet, peer = self.sink.recvfrom(16384)
            except BlockingIOError:
                break
            if unwire(packet)["path"].endswith("/core/service/auth"):
                seen.append(peer)
        self.assertEqual(seen, [("127.0.0.1", ports[0])] * 4)
        self.assertTrue(all(sock.udp.socket.fileno() == -1 for sock in self.sockets))
        self.assertNotIn(str(ports[0]), repr(client))
        self.assertNotIn("port", client.data)

    async def test_first_auth_failure_keeps_bound_port(self):
        for mode in ("rejected", "timeout", "send_error", "cancel", "total_timeout"):
            with self.subTest(mode=mode):
                client = LocalClient(dict(DATA), timeout=0.05)
                state = self.state()
                if mode == "rejected":
                    state.auth_change = lambda body: body.update(code=401)
                elif mode == "timeout":
                    state.only_ack = True
                elif mode == "send_error":
                    state.sendto = lambda *args: (_ for _ in ()).throw(OSError("synthetic"))
                else:
                    state.block = True
                if mode == "cancel":
                    discovery = self.state()
                    with patch.object(telemetry, "Socket", side_effect=[discovery, state]):
                        task = asyncio.create_task(client.read())
                        await asyncio.wait_for(state.entered.wait(), 1)
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                    self.assertTrue(discovery.closed and state.closed)
                else:
                    with self.assertRaises(InvalidAuth if mode == "rejected" else CannotConnect):
                        await self.read_round(client, state)
                _, recovered = await self.read_round(client)
                self.assertEqual(recovered.actual, state.actual)
                self.assertEqual(recovered.bound[1], state.actual[1])
                self.assertFalse(client._reading)

    async def test_later_failures_and_partial_do_not_reset_endpoint_or_values(self):
        client = LocalClient(dict(DATA))
        _, first = await self.read_round(client)
        rejected = self.state(auth_change=lambda body: body.update(code=401))
        with self.assertRaises(InvalidAuth):
            await self.read_round(client, rejected)
        empty = self.state()
        empty.notifications = []
        with self.assertRaises(CannotConnect):
            await self.read_round(client, empty)
        partial = self.state()
        partial.notifications = [(101, report({"pressure": 1.3}))]
        discovery = self.state()
        with patch.object(telemetry, "Socket", side_effect=[discovery, partial]):
            result = await client.read()
        self.assertIsNone(result.snapshot.sample("run").value)
        self.assertFalse(result.complete)
        self.assertTrue(discovery.closed and partial.closed)
        _, recovered = await self.read_round(client)
        for state in (rejected, empty, partial, recovered):
            self.assertEqual(state.actual, first.actual)

    async def test_real_bind_conflict_fails_without_fallback_and_recovers(self):
        client = LocalClient(dict(DATA))
        _, first = await self.read_round(client)
        owner = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(owner.close)
        owner.bind(first.actual)
        conflict = self.state()
        with self.assertRaisesRegex(CannotConnect, "UDP endpoint bind failed"):
            await self.read_round(client, conflict)
        self.assertEqual(conflict.bound[1], first.actual[1])
        self.assertEqual(conflict.sent, [])
        self.assertEqual(owner.getsockname(), first.actual)
        owner.close()
        _, recovered = await self.read_round(client)
        self.assertEqual(recovered.actual, first.actual)

    async def test_identity_timeout_and_cancellation_release_guard_without_changing_port(self):
        for established in (False, True):
            with self.subTest(established=established):
                client = LocalClient(dict(DATA), timeout=0.05)
                first = None
                if established:
                    _, first = await self.read_round(client)
                discovery = self.state()
                discovery.block = True
                with patch.object(telemetry, "Socket", return_value=discovery) as factory:
                    with self.assertRaises(CannotConnect):
                        await client.read()
                self.assertTrue(discovery.closed)
                self.assertEqual(factory.call_count, 1)
                discovery = self.state()
                discovery.block = True
                with patch.object(telemetry, "Socket", return_value=discovery) as factory:
                    task = asyncio.create_task(client.read())
                    await asyncio.wait_for(discovery.entered.wait(), 1)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertTrue(discovery.closed)
                self.assertEqual(factory.call_count, 1)
                self.assertFalse(client._reading)
                _, recovered = await self.read_round(client)
                if first is None:
                    self.assertEqual(recovered.bound[1], 0)
                else:
                    self.assertEqual(recovered.actual, first.actual)

    async def test_initial_bind_error_does_not_choose_a_port(self):
        client = LocalClient(dict(DATA))
        failed = self.state()
        with patch.object(failed, "bind", side_effect=OSError("synthetic")):
            with self.assertRaisesRegex(CannotConnect, "UDP endpoint bind failed"):
                await self.read_round(client, failed)
        _, recovered = await self.read_round(client)
        self.assertEqual(recovered.bound[1], 0)
        _, again = await self.read_round(client)
        self.assertEqual(again.actual, recovered.actual)

    async def test_concurrent_read_rejected_without_socket_or_wait(self):
        client = LocalClient(dict(DATA))
        discovery, state = self.state(), self.state()
        state.block = True
        with patch.object(telemetry, "Socket", side_effect=[discovery, state]) as factory:
            task = asyncio.create_task(client.read())
            await asyncio.wait_for(state.entered.wait(), 1)
            with self.assertRaisesRegex(CannotConnect, "Read already in progress"):
                await asyncio.wait_for(client.read(), 0.1)
            self.assertEqual(factory.call_count, 2)
            self.assertFalse(state.closed)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(discovery.closed and state.closed)
        _, recovered = await self.read_round(client)
        self.assertEqual(recovered.actual, state.actual)

    async def test_two_clients_have_independent_live_bindings(self):
        first, second = LocalClient(dict(DATA)), LocalClient(dict(DATA))
        discovery, state = self.state(), self.state()
        state.block = True
        with patch.object(telemetry, "Socket", side_effect=[discovery, state]):
            task = asyncio.create_task(first.read())
            await asyncio.wait_for(state.entered.wait(), 1)
        try:
            _, other = await self.read_round(second)
            self.assertNotEqual(other.actual, state.actual)
            _, again = await self.read_round(second)
            self.assertEqual(other.actual, again.actual)
            self.assertIsNot(first._endpoint, second._endpoint)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        _, recovered = await self.read_round(first)
        self.assertEqual(recovered.actual, state.actual)

    async def test_exact_identity_still_checked_before_every_auth(self):
        client = LocalClient(dict(DATA))
        _, first = await self.read_round(client)
        wrong = self.state(profile=[{"productKey": DATA["productKey"], "deviceName": "OTHER"}])
        with patch.object(telemetry, "Socket", return_value=wrong) as factory:
            with self.assertRaises(IdentityMismatch):
                await client.read()
        self.assertTrue(wrong.closed)
        self.assertEqual(factory.call_count, 1)
        _, recovered = await self.read_round(client)
        self.assertEqual(recovered.actual, first.actual)

    async def test_close_releases_real_socket_after_each_phase_cancellation(self):
        for path in (
            "/core/service/auth",
            "/thing/event/property/post",
            "/thing/service/property/set",
        ):
            with self.subTest(path=path):
                client = LocalClient(dict(DATA))
                discovery, state = self.state(), self.state()
                send = state.sendto
                blocked = asyncio.Event()

                def block_after_send(
                    packet, peer, send=send, path=path, state=state, blocked=blocked
                ):
                    written = send(packet, peer)
                    if unwire(packet)["path"].endswith(path):
                        state.block = True
                        blocked.set()
                    return written

                state.sendto = block_after_send
                with patch.object(telemetry, "Socket", side_effect=[discovery, state]):
                    task = asyncio.create_task(client.read())
                    await asyncio.wait_for(blocked.wait(), 1)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertTrue(discovery.closed and state.closed)
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    probe.bind(state.actual)
                finally:
                    probe.close()
                _, recovered = await self.read_round(client)
                self.assertEqual(recovered.actual, state.actual)
