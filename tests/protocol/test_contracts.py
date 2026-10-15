"""Offline contracts. Direct script and unittest import both prohibit real UDP."""

import copy
import json
import unittest
from unittest.mock import patch

from custom_components.cloud_intelligence import telemetry as t
from tests.protocol.fixtures import (
    CANDIDATE,
    CREDS,
    LOCAL,
    PEER,
    FakeSocket,
    mutate_packet,
    report,
    rewire,
    unwire,
)


class Contracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        guard = patch.object(t, "Socket", side_effect=AssertionError("REAL NETWORK FORBIDDEN"))
        guard.start()
        self.addCleanup(guard.stop)

    async def run_fake(self, f=None, **kwargs):
        f = f or FakeSocket()
        with patch.object(t, "Socket", return_value=f) as factory:
            r = await t.run_once(LOCAL, CANDIDATE, CREDS, allow_network=True, **kwargs)
        self.assertTrue(f.closed)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(f.bound, (LOCAL, 0))
        if f.timeout is not None:
            self.assertLessEqual(f.timeout, 60)
        return r, f

    async def test_network_disabled(self):
        with self.assertRaises(PermissionError):
            await t.run_once(LOCAL, CANDIDATE, CREDS)

    async def test_two_zero_observe_frames(self):
        r, f = await self.run_fake()
        self.assertTrue(r["auth_verified"])
        self.assertTrue(r["read_only"])
        self.assertTrue(r["subscribed"])
        self.assertEqual(r["notification_count"], 2)
        self.assertEqual(r["observe_zero_count"], 2)
        self.assertTrue(r["reports"][0]["refresh_echo"])
        self.assertEqual(r["telemetry"], dict(pressure=1.3, temperature=23))
        self.assertEqual(len(f.sent), 2)
        self.assertEqual(len(f.acks), 4)

    async def test_report_once_exact(self):
        r, f = await self.run_fake(request_report=True)
        self.assertFalse(r["read_only"])
        self.assertEqual(len(f.sent), 3)
        self.assertEqual(r["refresh"]["send_attempts"], 1)
        self.assertEqual(r["refresh"]["status"], "accepted")
        self.assertEqual(r["notification_count"], 2)
        self.assertEqual(len({x["mid"] for x in f.sent}), 3)
        self.assertEqual(len({x["token"] for x in f.sent}), 3)

    async def test_report_response_first(self):
        r, _ = await self.run_fake(FakeSocket(response_first=True), request_report=True)
        self.assertEqual(r["notification_count"], 2)
        self.assertEqual(r["refresh"]["response_code"], 200)

    async def test_encrypted_ctype0_all_reply_shapes(self):
        r, f = await self.run_fake(FakeSocket(content_format=b""), request_report=True)
        self.assertTrue(r["auth_verified"])
        self.assertTrue(r["subscribed"])
        self.assertEqual(r["notification_count"], 2)
        self.assertEqual(r["observe_zero_count"], 2)
        self.assertEqual(r["refresh"]["send_attempts"], 1)
        self.assertEqual(r["refresh"]["response_code"], 200)
        self.assertEqual(len(f.sent), 3)

    async def test_auth_ctype0_still_rejected(self):
        r, f = await self.run_fake(FakeSocket(auth_options=[(12, b"")]), request_report=True)
        self.assertFalse(r["auth_verified"])
        self.assertFalse(r["subscribed"])
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(r["refresh"]["send_attempts"], 0)

    async def test_auth_observe_still_rejected(self):
        r, f = await self.run_fake(
            FakeSocket(auth_options=[(6, b""), (12, b"\x32")]), request_report=True
        )
        self.assertFalse(r["auth_verified"])
        self.assertFalse(r["subscribed"])
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(r["refresh"]["send_attempts"], 0)

    async def test_subscribe_rejected_no_report(self):
        r, f = await self.run_fake(FakeSocket(subscribe_code=400), request_report=True)
        self.assertFalse(r["subscribed"])
        self.assertEqual(len(f.sent), 2)

    async def test_subscribe_wrong_id_no_report(self):
        r, f = await self.run_fake(
            FakeSocket(reg_change=lambda b: b.update(id="wrong")), request_report=True
        )
        self.assertFalse(r["subscribed"])
        self.assertEqual(len(f.sent), 2)

    async def test_timeout_no_retry(self):
        r, f = await self.run_fake(FakeSocket(refresh_code=None), request_report=True)
        self.assertEqual(r["refresh"]["status"], "unconfirmed")
        self.assertEqual(len(f.sent), 3)

    async def test_reject_no_retry(self):
        r, f = await self.run_fake(FakeSocket(refresh_code=400), request_report=True)
        self.assertEqual(r["refresh"]["status"], "rejected")
        self.assertEqual(len(f.sent), 3)

    async def test_send_uncertain_no_retry(self):
        r, f = await self.run_fake(FakeSocket(send_failure=True), request_report=True)
        self.assertEqual(r["refresh"]["status"], "send_uncertain")
        self.assertEqual(r["refresh"]["send_attempts"], 1)
        self.assertEqual(len(f.sent), 3)
        self.assertNotIn("synthetic-secret", json.dumps(r))

    async def test_arbitrary_set_impossible(self):
        with self.assertRaises(TypeError):
            await t.run_once(LOCAL, CANDIDATE, CREDS, params={"switch": 0})
        with self.assertRaises(ValueError):
            await t.run_once(LOCAL, CANDIDATE, CREDS, request_report={"refresh": 1})

    async def test_duplicate_still_ack(self):
        r, f = await self.run_fake(FakeSocket(notifications=[(101, report({"pressure": 1.3}))] * 2))
        self.assertEqual(r["notification_count"], 1)
        self.assertEqual(r["duplicate_count"], 1)
        self.assertEqual(len(f.acks), 4)

    async def test_new_mid_same_payload_kept(self):
        r, _ = await self.run_fake(
            FakeSocket(
                notifications=[(101, report({"pressure": 1.3})), (102, report({"pressure": 1.3}))]
            )
        )
        self.assertEqual(r["notification_count"], 2)

    async def test_mid_conflict(self):
        r, _ = await self.run_fake(
            FakeSocket(
                notifications=[(101, report({"pressure": 1.3})), (101, report({"pressure": 2.5}))]
            )
        )
        self.assertEqual(r["notification_count"], 1)
        self.assertEqual(r["telemetry"]["pressure"], 1.3)

    async def test_partial_merge_receive_time(self):
        r, _ = await self.run_fake(
            FakeSocket(
                notifications=[(101, report({"pressure": 1.3})), (102, report({"temperature": 23}))]
            )
        )
        self.assertEqual(set(r["telemetry"]), {"pressure", "temperature"})
        self.assertEqual(set(r["receive_at"]), {"pressure", "temperature"})
        self.assertNotIn("device_reporttime", json.dumps(r))

    async def test_empty_ack_not_success(self):
        r, f = await self.run_fake(FakeSocket(only_ack=True), request_report=True)
        self.assertFalse(r["subscribed"])
        self.assertEqual(len(f.sent), 1)

    async def test_safe_output(self):
        r, _ = await self.run_fake(request_report=True)
        for forbidden in (
            *CREDS.values(),
            PEER[0],
            "sessionId",
            "session_key",
            "randomKey",
            "ciphertext",
        ):
            self.assertNotIn(forbidden, json.dumps(r))

    async def test_all_twelve(self):
        props = dict(
            switch=1,
            temperature=23,
            presSet=4,
            mode=0,
            error=13,
            errorState=0,
            run=0,
            propor=23,
            version="SYNTHETIC-v1",
            pressure=1.3,
            tarSpeed=1800,
            nowSpeed=0,
        )
        fake = FakeSocket(notifications=[(101, report(props))])
        receive = fake.recvfrom
        complete_received = False

        async def must_not_wait_after_complete(size):
            nonlocal complete_received
            self.assertFalse(
                complete_received, "Complete reports must return before another receive"
            )
            packet, peer = await receive(size)
            if any(number == 6 for number, _ in unwire(packet)["opts"]):
                complete_received = True
            return packet, peer

        fake.recvfrom = must_not_wait_after_complete
        r, _ = await self.run_fake(fake, request_report=True)
        self.assertEqual(r["status"], "complete")
        self.assertEqual(r["telemetry"], props)
        self.assertEqual(r["refresh"]["send_attempts"], 1)

    async def test_session_scope_reset(self):
        a, _ = await self.run_fake()
        b, _ = await self.run_fake()
        self.assertEqual(a["notification_count"], b["notification_count"])
        self.assertEqual(b["duplicate_count"], 0)

    async def test_window(self):
        w = t._Window(ttl=2, capacity=2)
        for args, want in [
            ((1, b"a", 0), "new"),
            ((1, b"a", 1), "duplicate"),
            ((1, b"b", 1), "conflict"),
            ((2, b"a", 1), "new"),
            ((3, b"c", 1), "full"),
            ((1, b"a", 2), "new"),
        ]:
            self.assertEqual(w.check(*args), want)
        w.clear()
        self.assertEqual(len(w.entries), 0)

    async def test_capacity_fail_closed(self):
        original = t._Window
        with patch.object(t, "_Window", side_effect=lambda: original(capacity=1)):
            r, _ = await self.run_fake()
        self.assertEqual(r["status"], "dedupe_capacity")
        self.assertEqual(r["notification_count"], 1)

    async def test_duplicate_registration_no_retrigger(self):
        def duplicate(f, req):
            f.push(f.secure(req, dict(id=req["body"]["id"], code=200, data={}), mid=90))

        r, f = await self.run_fake(FakeSocket(noise=duplicate), request_report=True)
        self.assertEqual(r["refresh"]["send_attempts"], 1)
        self.assertEqual(len(f.sent), 3)

    async def test_early_notification_not_processed(self):
        def early(f, req):
            f.push(f.secure(req, report({"pressure": 99}), mid=90, opts=[(6, b""), (71, b"G")]))

        r, _ = await self.run_fake(FakeSocket(noise=early))
        self.assertEqual(r["notification_count"], 2)
        self.assertEqual(r["telemetry"]["pressure"], 1.3)

    async def test_json_duplicate_key(self):
        raw = (
            b'{"id":"x","version":"1.0","params":{"pressure":1,"pressure":2},'
            b'"method":"thing.event.property.post"}'
        )
        r, _ = await self.run_fake(FakeSocket(notifications=[(100, raw)]))
        self.assertEqual(r["notification_count"], 0)

    async def test_non_binary_format(self):
        def change(packet, peer, f):
            m = unwire(packet)
            m["type"] = 1
            m["opts"] = [(k, b"\x2a" if k == 12 else v) for k, v in m["opts"]]
            return rewire(m), peer

        r, f = await self.run_fake(FakeSocket(notification_change=change))
        self.assertEqual(r["notification_count"], 2)
        self.assertEqual(len(f.acks), 2)

    async def test_bind_failure_close(self):
        f = FakeSocket()

        def bad(a):
            raise OSError("secret bind failure")

        f.bind = bad
        with patch.object(t, "Socket", return_value=f):
            r = await t.run_once(LOCAL, CANDIDATE, CREDS, allow_network=True)
        self.assertTrue(f.closed)
        self.assertEqual(r["status"], "transport_error")
        self.assertEqual(f.sent, [])

    async def test_close_failure_sanitized(self):
        f = FakeSocket()

        def bad():
            f.closed = True
            raise OSError("secret close failure")

        f.close = bad
        r, _ = await self.run_fake(f)
        self.assertEqual(r["status"], "transport_error")

    async def test_finally_clears_window(self):
        original = t._Window
        captured = []

        class Tracked(original):
            def clear(self):
                super().clear()
                captured.append(len(self.entries))

        with patch.object(t, "_Window", Tracked):
            await self.run_fake()
        self.assertEqual(captured, [0])

    async def test_input_objects_not_mutated(self):
        before = copy.deepcopy((CANDIDATE, CREDS))
        await self.run_fake(request_report=True)
        self.assertEqual((CANDIDATE, CREDS), before)

    async def test_fixed_profile_allowlist(self):
        # Runtime tests themselves use only synthetic TEST-NET peers.
        self.assertTrue(PEER[0].startswith("192.0.2."))
        self.assertEqual(
            set(t.STATES),
            {
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
            },
        )

    async def test_total_deadline_late_auth(self):
        f, now = FakeSocket(), [0.0]
        recv = f.recvfrom

        async def timed(n):
            packet, peer = await recv(n)
            if unwire(packet)["code"] == 69:
                now[0] = 1.1
            return packet, peer

        f.recvfrom = timed
        with patch.object(t.time, "monotonic", side_effect=lambda: now[0]):
            r, f = await self.run_fake(f, maxwait=1, request_report=True)
        self.assertEqual(len(f.sent), 1)
        self.assertFalse(r["subscribed"])


def attach(name, fn):
    setattr(Contracts, "test_" + name, fn)


for name, mutate in {
    "missing_proof": lambda b: b["data"].pop("sign"),
    "wrong_proof": lambda b: b["data"].update(sign="A" * 28),
    "nonce": lambda b: b["data"].update(randomKey="bad"),
    "missing_opt": lambda b: b["data"].pop("opt"),
    "opt0": lambda b: b["data"].update(opt=0),
    "opt_seq": lambda b: b["data"].update(opt=3),
    "opt_checksum": lambda b: b["data"].update(opt=5),
    "opt_unknown": lambda b: b["data"].update(opt=9),
    "opt_bool": lambda b: b["data"].update(opt=True),
    "missing_session": lambda b: b["data"].pop("sessionId"),
    "zero_session": lambda b: b["data"].update(sessionId=0),
    "bool_session": lambda b: b["data"].update(sessionId=True),
    "seqstart": lambda b: b["data"].update(seqStart=True),
    "id": lambda b: b.update(id="wrong"),
    "rejected": lambda b: b.update(code=401),
}.items():

    async def test(self, mutate=mutate):
        r, f = await self.run_fake(FakeSocket(auth_change=mutate), request_report=True)
        self.assertFalse(r["subscribed"])
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(r["refresh"]["send_attempts"], 0)

    attach("auth_" + name, test)
for kind in (
    "peer",
    "port",
    "token",
    "session",
    "missing_session",
    "duplicate_session",
    "oversized_session",
    "sequence",
    "group",
    "missing_observe",
    "oversized_observe",
    "duplicate_observe",
    "unknown_option",
    "path",
    "format",
    "bad_ciphertext",
):

    async def test(self, kind=kind):
        r, _ = await self.run_fake(
            FakeSocket(notification_change=lambda p, a, f: mutate_packet(p, a, f, kind))
        )
        self.assertEqual(r["notification_count"], 0)

    attach("notify_" + kind, test)
for kind in (
    "format",
    "oversized_format",
    "duplicate_format",
    "unknown_option",
    "missing_session",
    "session",
):

    async def test(self, kind=kind):
        r, _ = await self.run_fake(
            FakeSocket(
                content_format=b"", notification_change=lambda p, a, f: mutate_packet(p, a, f, kind)
            )
        )
        self.assertEqual(r["notification_count"], 0)

    attach("ctype0_reject_" + kind, test)
for stage, kinds in (
    (1, ("peer", "token", "path")),
    (2, ("peer", "token", "path", "session", "missing_session", "duplicate_session", "sequence")),
):
    for kind in kinds:

        async def test(self, stage=stage, kind=kind):
            def transform(index, packet, peer, f):
                return mutate_packet(packet, peer, f, kind) if index == stage else (packet, peer)

            r, f = await self.run_fake(FakeSocket(reply_transform=transform), request_report=True)
            self.assertFalse(r["subscribed"])
            self.assertEqual(r["refresh"]["send_attempts"], 0)
            self.assertEqual(len(f.sent), stage)

        attach(f"exchange_{stage}_{kind}", test)
for name, value in {
    "array": [],
    "wrapped": {"pressure": {"value": 1.3, "time": 123}},
    "empty": {},
    "unknown": {"unsafe": 1},
    "string": {"pressure": "1.3"},
    "bool": {"pressure": True},
    "nan": {"pressure": float("nan")},
    "inf": {"pressure": float("inf")},
    "refresh": {"refresh": 2},
    "bool_refresh": {"refresh": True},
    "switch": {"switch": 2},
}.items():

    async def test(self, value=value):
        r, _ = await self.run_fake(FakeSocket(notifications=[(100, report(value))]))
        self.assertEqual(r["notification_count"], 0)

    attach("shape_" + name, test)
for name, change in {
    "method": {"method": "thing.service.property.set"},
    "version": {"version": "2"},
    "id": {"id": 123},
    "extra": {"data": {}},
}.items():

    async def test(self, change=change):
        body = report({"pressure": 1.3})
        body.update(change)
        r, _ = await self.run_fake(FakeSocket(notifications=[(100, body)]))
        self.assertEqual(r["notification_count"], 0)

    attach("envelope_" + name, test)
for name, kwargs in {
    "long": {"maxwait": 61},
    "bool": {"maxwait": True},
    "zero": {"maxwait": 0},
    "nan": {"maxwait": float("nan")},
    "inf": {"maxwait": float("inf")},
    "request": {"request_report": 1},
    "gate": {"allow_network": 1},
}.items():

    async def test(self, kwargs=kwargs):
        with self.assertRaises(ValueError):
            await t.run_once(LOCAL, CANDIDATE, CREDS, **dict({"allow_network": True}, **kwargs))

    attach("input_" + name, test)
for kind in ("identity", "port", "model", "local_integer"):

    async def test(self, kind=kind):
        candidate, credentials, local = copy.deepcopy(CANDIDATE), dict(CREDS), LOCAL
        if kind == "identity":
            candidate["profile"][0]["deviceName"] = "OTHER"
        if kind == "port":
            candidate["port"] = True
        if kind == "model":
            credentials["productKey"] = "other-model"
        if kind == "local_integer":
            local = 1
        with self.assertRaises(ValueError):
            await t.run_once(local, candidate, credentials, allow_network=True)

    attach("scope_" + kind, test)


if __name__ == "__main__":
    unittest.main(verbosity=2)
