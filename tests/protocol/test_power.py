"""Opt-in power control: synthetic wire tests, no device networking."""

import asyncio
import json
import unittest
from unittest.mock import patch

from custom_components.cloud_intelligence import telemetry
from custom_components.cloud_intelligence.client import CannotConnect, InvalidAuth, LocalClient
from custom_components.cloud_intelligence.power import (
    PowerCancelled,
    PowerDisabled,
    PowerOutcomeUnknown,
)
from tests.protocol import oracle
from tests.protocol.fixtures import PEER, mutate_packet, report, unwire, wire
from tests.protocol.test_client import DATA, VALUES, LanSocket


class PowerSocket(LanSocket):
    def __init__(self, *, power_failure=False, **kwargs):
        super().__init__(**kwargs)
        self.power_failure = power_failure
        self.power_requests = []
        self.power_started = asyncio.Event()
        self.block = False
        self.entered = asyncio.Event()

    def sendto(self, packet, peer):
        req = unwire(packet)
        if req["path"].endswith("/thing/service/property/set"):
            body = json.loads(oracle.decrypt(req["payload"], self.key))
            if "switch" in body["params"]:
                req["body"] = body
                self.power_requests.append(req)
                self.power_started.set()
                assert body["params"] in ({"switch": 0}, {"switch": 1})
                assert type(body["params"]["switch"]) is int
                assert body["method"] == "thing.service.property.set"
                assert (71, b"\0\0\0G") in req["opts"]
                assert all(k != 6 for k, _ in req["opts"])
                # ACK and accepted set response are deliberately not state proof.
                self.push(wire(0, req["mid"], typ=2))
                self.push(self.secure(req, dict(id=body["id"], code=200, data={}), mid=400))
                if self.power_failure:
                    raise OSError("synthetic private error")
                return len(packet)
        return super().sendto(packet, peer)

    async def recvfrom(self, size):
        if self.block:
            self.entered.set()
            await asyncio.Event().wait()
        return await super().recvfrom(size)


class PowerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        guard = patch("socket.socket", side_effect=AssertionError("REAL NETWORK FORBIDDEN"))
        guard.start()
        self.addCleanup(guard.stop)

    def client(self, **kwargs):
        return LocalClient(dict(DATA), enable_power_control=True, **kwargs)

    def sockets(self, before=None, after=None, **kwargs):
        return [
            LanSocket(),
            PowerSocket(
                notifications=[(101, report(VALUES if before is None else before))], **kwargs
            ),
            PowerSocket(
                notifications=[(301, report({**VALUES, "switch": 0} if after is None else after))]
            ),
        ]

    async def test_disabled_strict_bool_unknown_model_and_arbitrary_inputs(self):
        with patch.object(telemetry, "Socket") as factory:
            with self.assertRaises(PowerDisabled):
                await LocalClient(DATA).set_power(False)
            for value in (0, 1, "false", None, {"switch": 0}, [], 1.0):
                with self.subTest(value=value), self.assertRaises(TypeError):
                    await self.client().set_power(value)
            for kwargs in (
                {"property": "mode"},
                {"path": "/arbitrary"},
                {"params": {"switch": 0}},
                {"value": 0},
            ):
                with self.assertRaises(TypeError):
                    await self.client().set_power(False, **kwargs)
            bad = self.client()
            bad.data["productKey"] = "unknown"
            with self.assertRaises(ValueError):
                await bad.set_power(False)
            for flag in (1, "true", None):
                with self.assertRaises(PowerDisabled):
                    await LocalClient(DATA, enable_power_control=flag).set_power(False)
            factory.assert_not_called()

    async def test_target_satisfied_is_noop(self):
        for enabled in (False, True):
            sockets = self.sockets(before={**VALUES, "switch": int(enabled)})
            with patch.object(telemetry, "Socket", side_effect=sockets) as factory:
                result = await self.client().set_power(enabled)
            self.assertFalse(result.sent or result.uncertain)
            self.assertEqual(result.snapshot.snapshot.powered, enabled)
            self.assertEqual(factory.call_count, 2)
            self.assertEqual(sockets[1].power_requests, [])
            self.assertTrue(all(s.closed for s in sockets[:2]))

    async def test_both_directions_fixed_single_send_and_stable_endpoint(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                sockets = self.sockets(
                    before={**VALUES, "switch": int(not enabled)},
                    after={
                        **VALUES,
                        "switch": int(enabled),
                        "pressure": 2.1,
                        "nowSpeed": 1200,
                        "run": 1,
                    },
                )
                with patch.object(telemetry, "Socket", side_effect=sockets):
                    result = await self.client().set_power(enabled)
                self.assertTrue(result.sent)
                self.assertFalse(result.uncertain)
                self.assertEqual(result.snapshot.snapshot.powered, enabled)
                self.assertEqual(len(sockets[1].power_requests), 1)
                self.assertEqual(
                    sockets[1].power_requests[0]["body"]["params"], {"switch": int(enabled)}
                )
                self.assertEqual(sockets[2].power_requests, [])
                self.assertEqual(sockets[1].getsockname(), sockets[2].getsockname())
                self.assertTrue(all(s.closed for s in sockets))
                self.assertEqual(
                    dict(result.before),
                    {k: VALUES[k] for k in telemetry.SETTINGS} | {"switch": int(not enabled)},
                )
                self.assertNotEqual(sockets[1].sent[1]["token"], sockets[2].sent[1]["token"])

    async def test_pre_read_incomplete_invalid_or_wrong_auth_never_writes(self):
        for options in (
            {"notifications": []},
            {"notifications": [(101, report({"switch": 1}))]},
            {"notifications": [(101, report({**VALUES, "presSet": 9}))]},
            {"auth_change": lambda body: body["data"].update(sign="wrong")},
            {"auth_change": lambda body: body["data"].update(opt=0)},
            {"auth_change": lambda body: body["data"].update(randomKey="short")},
            *[
                {
                    "notification_change": lambda packet, peer, fake, kind=kind: mutate_packet(
                        packet, peer, fake, kind
                    )
                }
                for kind in ("token", "session", "peer", "path", "missing_session")
            ],
        ):
            with self.subTest(options=options):
                sockets = [LanSocket(), PowerSocket(**options)]
                with patch.object(telemetry, "Socket", side_effect=sockets):
                    with self.assertRaises((CannotConnect, InvalidAuth)):
                        await self.client().set_power(False)
                self.assertEqual(sockets[1].power_requests, [])
                self.assertTrue(all(s.closed for s in sockets))

    async def test_ack200_unchanged_partial_or_other_setting_change_is_unknown(self):
        for after in (
            VALUES,
            {"switch": 0},
            *[
                {**VALUES, "switch": 0, key: value}
                for key, value in (
                    ("presSet", 4.1),
                    ("mode", 1),
                    ("propor", 31),
                    ("tarSpeed", 1860),
                )
            ],
        ):
            with self.subTest(after=after):
                sockets = self.sockets(after=after)
                with patch.object(telemetry, "Socket", side_effect=sockets):
                    with self.assertRaises(PowerOutcomeUnknown) as error:
                        await self.client().set_power(False)
                self.assertTrue(error.exception.sent and error.exception.uncertain)
                self.assertEqual(len(sockets[1].power_requests), 1)
                self.assertTrue(all(s.closed for s in sockets))
                self.assertNotIn(DATA["deviceName"], str(error.exception))

    async def test_same_session_old_target_cannot_confirm(self):
        sockets = self.sockets(after=VALUES)
        # Even a target-valued report queued in the write session cannot confirm.
        sockets[1].notifications.append((102, report({**VALUES, "switch": 0})))
        with patch.object(telemetry, "Socket", side_effect=sockets):
            with self.assertRaises(PowerOutcomeUnknown):
                await self.client().set_power(False)
        self.assertEqual(len(sockets[1].power_requests), 1)

    async def test_old_session_packet_in_new_window_cannot_confirm(self):
        sockets = self.sockets(after=VALUES)
        original = sockets[2].sendto

        def send(packet, peer):
            count = original(packet, peer)
            req = unwire(packet)
            if req["path"].endswith("/thing/event/property/post"):
                old_req = sockets[1].sent[1]
                old = sockets[1].secure(
                    old_req,
                    report({**VALUES, "switch": 0}),
                    mid=500,
                    opts=[(6, b""), (12, b""), (71, b"G")],
                )
                sockets[2].queue.insert(0, (old, PEER))
            return count

        sockets[2].sendto = send
        with patch.object(telemetry, "Socket", side_effect=sockets):
            with self.assertRaises(PowerOutcomeUnknown):
                await self.client().set_power(False)

    async def test_send_failure_timeout_and_cancel_never_resend(self):
        sockets = self.sockets(power_failure=True)
        with patch.object(telemetry, "Socket", side_effect=sockets):
            with self.assertRaises(PowerOutcomeUnknown):
                await self.client().set_power(False)
        self.assertEqual(len(sockets[1].power_requests), 1)
        self.assertTrue(sockets[1].closed)
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                sockets = self.sockets()
                sockets[2].block = True
                client = self.client(timeout=0.1)
                with patch.object(telemetry, "Socket", side_effect=sockets):
                    task = asyncio.create_task(client.set_power(False))
                    await asyncio.wait_for(sockets[2].entered.wait(), 1)
                    if cancel:
                        task.cancel()
                    with self.assertRaises(
                        PowerCancelled if cancel else PowerOutcomeUnknown
                    ) as error:
                        await task
                self.assertTrue(error.exception.sent and error.exception.uncertain)
                self.assertEqual(len(sockets[1].power_requests), 1)
                self.assertTrue(all(s.closed for s in sockets))
                self.assertFalse(client._reading)

    async def test_budget_exhaustion_before_report_or_send_never_writes(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from custom_components.cloud_intelligence import client as client_module

        client = self.client()
        with (
            patch.object(client, "_identity", new=AsyncMock()),
            patch.object(
                client_module, "time", SimpleNamespace(monotonic=iter((0.0, 11.0)).__next__)
            ),
            patch.object(telemetry, "Socket") as factory,
        ):
            with self.assertRaises(CannotConnect):
                await client.set_power(False)
            factory.assert_not_called()
        sockets = self.sockets()
        clock = [0.0]
        parse = telemetry.parse_snapshot

        def expire(*args, **kwargs):
            result = parse(*args, **kwargs)
            clock[0] = 11.0  # Validation consumed the remaining session budget.
            return result

        with (
            patch.object(telemetry, "Socket", side_effect=sockets),
            patch.object(
                telemetry, "time", SimpleNamespace(monotonic=lambda clock=clock: clock[0])
            ),
            patch.object(telemetry, "parse_snapshot", side_effect=expire),
        ):
            with self.assertRaises(CannotConnect):
                await self.client().set_power(False)
        self.assertEqual(sockets[1].power_requests, [])
        self.assertTrue(all(sock.closed for sock in sockets[:2]))

    async def test_deadline_caps_validation_and_rejects_invalid_internal_values(self):
        from types import SimpleNamespace

        from custom_components.cloud_intelligence import client as client_module

        for deadline in (True, "1", float("nan"), float("inf")):
            client = self.client()
            with patch.object(telemetry, "Socket") as factory:
                with self.assertRaises(ValueError):
                    await client.set_power(False, _deadline=deadline)
                factory.assert_not_called()
            self.assertFalse(client._reading)
        for timeout, deadline, elapsed in ((0.1, 100, 0.2), (10, 0.1, 0.2), (10, -1, 0)):
            client = self.client(timeout=timeout)
            clock = [0.0]
            validate = client_module.validate_input

            def pause(data, validate=validate, clock=clock, elapsed=elapsed):
                result = validate(data)
                clock[0] = elapsed
                return result

            with (
                patch.object(
                    client_module, "time", SimpleNamespace(monotonic=lambda clock=clock: clock[0])
                ),
                patch.object(client_module, "validate_input", side_effect=pause),
                patch.object(telemetry, "Socket") as factory,
            ):
                outcome = (
                    await asyncio.gather(
                        client.set_power(False, _deadline=deadline), return_exceptions=True
                    )
                )[0]
                self.assertIsInstance(outcome, CannotConnect)
                factory.assert_not_called()
            self.assertFalse(client._reading)
            self.assertEqual(client.timeout, timeout)

    async def test_deadline_transport_setup_cannot_restart_budget(self):
        from types import SimpleNamespace

        from custom_components.cloud_intelligence import client as client_module

        sockets = self.sockets()
        clock = [100.0]  # Deliberately unrelated to the real event-loop epoch.
        inputs = telemetry._inputs

        def pause(*args, **kwargs):
            result = inputs(*args, **kwargs)
            clock[0] = 102.0
            return result

        with (
            patch.object(
                client_module, "time", SimpleNamespace(monotonic=lambda clock=clock: clock[0])
            ),
            patch.object(
                telemetry, "time", SimpleNamespace(monotonic=lambda clock=clock: clock[0])
            ),
            patch.object(telemetry, "_inputs", side_effect=pause),
            patch.object(telemetry, "Socket", side_effect=sockets),
        ):
            outcome = (
                await asyncio.gather(
                    self.client(timeout=1).set_power(False), return_exceptions=True
                )
            )[0]
        self.assertEqual(sockets[1].sent, [])
        self.assertIsInstance(outcome, CannotConnect)
        self.assertEqual(sockets[1].power_requests, [])
        self.assertTrue(all(sock.closed for sock in sockets[:2]))

    async def test_deadline_final_encoding_expiry_forbids_irreversible_send(self):
        from types import SimpleNamespace

        from custom_components.cloud_intelligence import client as client_module

        sockets = self.sockets()
        clock = [100.0]
        encode = telemetry.p.coap_encode
        set_packets = []

        def pause(*args, **kwargs):
            packet = encode(*args, **kwargs)
            if args[3].endswith("/thing/service/property/set"):
                set_packets.append(packet)
                if len(set_packets) == 2:  # refresh is allowed; expire encoding switch.
                    clock[0] = 101.0
            return packet

        client = self.client(timeout=1)
        with (
            patch.object(
                client_module, "time", SimpleNamespace(monotonic=lambda clock=clock: clock[0])
            ),
            patch.object(
                telemetry, "time", SimpleNamespace(monotonic=lambda clock=clock: clock[0])
            ),
            patch.object(telemetry.p, "coap_encode", side_effect=pause),
            patch.object(telemetry, "Socket", side_effect=sockets),
        ):
            outcome = (await asyncio.gather(client.set_power(False), return_exceptions=True))[0]
        self.assertEqual(len(set_packets), 2)
        self.assertEqual(sockets[1].power_requests, [])
        self.assertIsInstance(outcome, CannotConnect)
        self.assertFalse(client._reading)
        self.assertTrue(all(sock.closed for sock in sockets[:2]))

    async def test_deadline_postread_sync_expiry_is_unknown_not_success(self):
        from types import SimpleNamespace

        from custom_components.cloud_intelligence import client as client_module

        sockets = self.sockets()
        clock = [100.0]
        client = self.client(timeout=1)
        snapshot = client._snapshot
        calls = []

        def pause(*args, **kwargs):
            result = snapshot(*args, **kwargs)
            calls.append(result)
            if len(calls) == 2:
                clock[0] = 101.0
            return result

        with (
            patch.object(
                client_module, "time", SimpleNamespace(monotonic=lambda clock=clock: clock[0])
            ),
            patch.object(
                telemetry, "time", SimpleNamespace(monotonic=lambda clock=clock: clock[0])
            ),
            patch.object(client, "_snapshot", side_effect=pause),
            patch.object(telemetry, "Socket", side_effect=sockets),
        ):
            with self.assertRaises(PowerOutcomeUnknown) as error:
                await client.set_power(False)
        self.assertTrue(error.exception.sent and error.exception.uncertain)
        self.assertEqual(len(sockets[1].power_requests), 1)
        self.assertFalse(client._reading)
        self.assertTrue(all(sock.closed for sock in sockets))

    async def test_incomplete_physical_send_is_unknown_without_retry(self):
        sockets = self.sockets()
        original = sockets[1].sendto

        def short_send(packet, peer):
            count = original(packet, peer)
            return 0 if sockets[1].power_started.is_set() else count

        sockets[1].sendto = short_send
        with patch.object(telemetry, "Socket", side_effect=sockets):
            with self.assertRaises(PowerOutcomeUnknown) as error:
                await self.client().set_power(False)
        self.assertTrue(error.exception.sent and error.exception.uncertain)
        self.assertEqual(len(sockets[1].power_requests), 1)
        self.assertTrue(all(sock.closed for sock in sockets[:2]))

    async def test_verification_wrong_proof_or_packet_binding_is_unknown(self):
        for kind in ("proof", "opt", "nonce", "token", "session", "peer", "port", "path", "format"):
            with self.subTest(kind=kind):
                sockets = self.sockets()
                if kind in ("proof", "opt", "nonce"):
                    field, value = {
                        "proof": ("sign", "wrong"),
                        "opt": ("opt", 0),
                        "nonce": ("randomKey", "short"),
                    }[kind]
                    sockets[2].auth_change = lambda body, field=field, value=value: body[
                        "data"
                    ].update({field: value})
                else:
                    sockets[2].notification_change = (
                        lambda packet, peer, fake, kind=kind: mutate_packet(
                            packet, peer, fake, kind
                        )
                    )
                with patch.object(telemetry, "Socket", side_effect=sockets):
                    with self.assertRaises(PowerOutcomeUnknown) as error:
                        await self.client().set_power(False)
                self.assertTrue(error.exception.sent and error.exception.uncertain)
                self.assertEqual(len(sockets[1].power_requests), 1)
                self.assertTrue(all(s.closed for s in sockets))

    async def test_pre_identity_timeout_cancel_and_invalid_budget_no_write(self):
        with patch.object(telemetry, "Socket") as factory:
            for timeout in (0, True, 11, float("nan")):
                with self.assertRaises(ValueError):
                    await self.client(timeout=timeout).set_power(False)
            factory.assert_not_called()
        for cancel in (False, True):
            discovery = PowerSocket()
            discovery.block = True
            client = self.client(timeout=0.05)
            with patch.object(telemetry, "Socket", return_value=discovery) as factory:
                task = asyncio.create_task(client.set_power(False))
                await asyncio.wait_for(discovery.entered.wait(), 1)
                if cancel:
                    task.cancel()
                with self.assertRaises(
                    asyncio.CancelledError if cancel else CannotConnect
                ) as error:
                    await task
            self.assertNotIsInstance(error.exception, (PowerCancelled, PowerOutcomeUnknown))
            self.assertTrue(discovery.closed)
            self.assertEqual(discovery.power_requests, [])
            self.assertEqual(factory.call_count, 1)
            self.assertFalse(client._reading)

    async def test_private_transport_gate_rejects_arbitrary_attempt(self):
        from custom_components.cloud_intelligence.power import _PowerAttempt
        from tests.protocol.fixtures import CANDIDATE, CREDS, LOCAL

        for power, request_report in (
            ({"switch": 0}, True),
            (_PowerAttempt(1), True),
            (_PowerAttempt(False, started=True), True),
            (_PowerAttempt(False), False),
        ):
            with self.subTest(power=power), patch.object(telemetry, "Socket") as factory:
                with self.assertRaises(ValueError):
                    await telemetry.run_once(
                        LOCAL,
                        CANDIDATE,
                        CREDS,
                        request_report=request_report,
                        allow_network=True,
                        _power=power,
                    )
                factory.assert_not_called()

    async def test_two_clients_progress_independently_while_one_control_blocked(self):
        first = self.client()
        sockets = self.sockets()
        sockets[1].block = True
        with patch.object(telemetry, "Socket", side_effect=sockets[:2]):
            pending = asyncio.create_task(first.set_power(False))
            await asyncio.wait_for(sockets[1].entered.wait(), 1)
        other = self.client()
        other_sockets = self.sockets()
        with patch.object(telemetry, "Socket", side_effect=other_sockets):
            result = await other.set_power(False)
        self.assertTrue(result.sent and first._reading)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertFalse(first._reading or other._reading)
        self.assertTrue(all(s.closed for s in other_sockets + sockets[:2]))

    async def test_unexpected_post_send_exception_is_sanitized_unknown(self):
        sockets = self.sockets()
        original = sockets[2].recvfrom

        async def broken(size):
            await original(size)
            raise RuntimeError("synthetic-private-body")

        sockets[2].recvfrom = broken
        with patch.object(telemetry, "Socket", side_effect=sockets):
            with self.assertRaises(PowerOutcomeUnknown) as error:
                await self.client().set_power(False)
        self.assertNotIn("synthetic-private-body", str(error.exception))
        self.assertTrue(all(s.closed for s in sockets))

    async def test_read_write_overlap_rejected_without_queue_and_clients_independent(self):
        for first_write in (False, True):
            sockets = self.sockets()
            sockets[1].block = True
            client = self.client()
            with patch.object(telemetry, "Socket", side_effect=sockets) as factory:
                task = asyncio.create_task(
                    client.set_power(False) if first_write else client.read()
                )
                await asyncio.wait_for(sockets[1].entered.wait(), 1)
                for operation in (client.read(), client.set_power(False)):
                    with self.assertRaises(CannotConnect):
                        await operation
                self.assertEqual(factory.call_count, 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertFalse(client._reading)
            other = self.client()
            self.assertIsNot(client._endpoint, other._endpoint)
            self.assertTrue(all(s.closed for s in sockets[:2]))
