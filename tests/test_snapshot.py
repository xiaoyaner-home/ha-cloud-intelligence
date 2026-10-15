"""Strict decoded property parsing; no cloud credentials or clocks."""

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from cloud_intelligence import (
    WILO_MODEL_KEY,
    Freshness,
    OnlineState,
    SnapshotError,
    parse_snapshot,
)


def parse_value(identifier, value, time=1000):
    return parse_snapshot(
        {
            "code": "200",
            "data": {
                identifier: {"time": time, "value": value},
            },
        },
        model_key=WILO_MODEL_KEY,
    ).sample(identifier)


class SnapshotTests(unittest.TestCase):
    def test_unknown_models_do_not_infer_power_or_running_from_property_names(self):
        snapshot = parse_snapshot(
            {
                "code": "200",
                "data": {
                    "switch": {"time": 1, "value": True},
                    "run": {"time": 1, "value": True},
                },
            },
            model_key="unknown-model",
        )
        self.assertIsNone(snapshot.powered)
        self.assertIsNone(snapshot.running)
        self.assertIs(snapshot.sample("switch").value, True)

    def test_complete_synthetic_fixture_and_timestamp_preservation(self):
        path = Path(__file__).parent / "fixtures" / "wilo_snapshot.json"
        payload = json.loads(path.read_text())
        snapshot = parse_snapshot(payload, model_key=WILO_MODEL_KEY, status=1)
        self.assertEqual(len(snapshot.properties), 13)
        for key, entry in payload["data"].items():
            with self.subTest(key=key):
                sample = snapshot.sample(key)
                self.assertEqual(sample.value, entry["value"])
                self.assertEqual(sample.reported_at_ms, entry["time"])
                self.assertEqual(sample.issues, ())
        self.assertIs(snapshot.powered, True)
        self.assertIs(snapshot.running, False)
        self.assertIs(snapshot.online, OnlineState.ONLINE)
        self.assertIsInstance(snapshot.sample("presSet").value, float)
        self.assertIsInstance(snapshot.sample("temperature").value, int)

    def test_power_run_online_freshness_are_independent(self):
        snapshot = parse_snapshot(
            {
                "code": "200",
                "data": {
                    "switch": {"time": 1000, "value": 1},
                    "run": {"time": 1000, "value": 0},
                    "pressure": {"time": 100, "value": 2.7},
                },
            },
            model_key=WILO_MODEL_KEY,
            status=1,
        )
        self.assertIs(snapshot.powered, True)
        self.assertIs(snapshot.running, False)
        self.assertIs(snapshot.online, OnlineState.ONLINE)
        self.assertIs(
            snapshot.sample("switch").freshness(now_ms=1100, max_age_ms=500), Freshness.FRESH
        )
        self.assertIs(
            snapshot.sample("pressure").freshness(now_ms=1100, max_age_ms=500), Freshness.STALE
        )
        inverse = parse_snapshot(
            {
                "code": "200",
                "data": {
                    "switch": {"time": 1, "value": 0},
                    "run": {"time": 1, "value": 1},
                },
            },
            model_key=WILO_MODEL_KEY,
            status=0,
        )
        self.assertIs(inverse.powered, False)
        self.assertIs(inverse.running, True)
        self.assertIs(inverse.online, OnlineState.UNKNOWN)

    def test_online_status_only_accepts_documented_integer_codes(self):
        for status, expected in [
            (1, OnlineState.ONLINE),
            (0, OnlineState.UNKNOWN),
            (None, OnlineState.UNKNOWN),
            (2, OnlineState.UNKNOWN),
            ("1", OnlineState.UNKNOWN),
            (True, OnlineState.UNKNOWN),
            (1.0, OnlineState.UNKNOWN),
            ({}, OnlineState.UNKNOWN),
        ]:
            with self.subTest(status=status):
                result = parse_snapshot(
                    {"code": "200", "data": {}}, model_key=WILO_MODEL_KEY, status=status
                )
                self.assertIs(result.online, expected)
                self.assertIsNone(result.powered)
                self.assertIsNone(result.running)

    def test_bad_envelopes_raise_without_echoing_server_secrets(self):
        for payload in [
            None,
            [],
            "bad",
            True,
            {},
            {"code": 200, "data": {}},
            {"code": "401", "message": "synthetic-secret"},
            {"code": "200"},
            {"code": "200", "data": None},
            {"code": "200", "data": []},
            {"code": "200", "data": {1: {}}},
            {"code": "200", "data": {"": {}}},
        ]:
            with self.subTest(payload=payload):
                with self.assertRaises(SnapshotError) as context:
                    parse_snapshot(payload, model_key=WILO_MODEL_KEY)
                self.assertNotIn("synthetic-secret", str(context.exception))

    def test_missing_invalid_and_partial_samples_never_become_zero(self):
        snapshot = parse_snapshot(
            {
                "code": "200",
                "data": {
                    "switch": None,
                    "run": {"time": 1000},
                    "pressure": {"time": "1000", "value": "broken"},
                    "temperature": {"time": 1000, "value": 31},
                },
            },
            model_key=WILO_MODEL_KEY,
        )
        self.assertIsNone(snapshot.powered)
        self.assertIsNone(snapshot.running)
        self.assertIsNone(snapshot.sample("pressure").value)
        self.assertEqual(snapshot.sample("switch").issues, ("invalid_entry",))
        self.assertIn("missing_value", snapshot.sample("run").issues)
        self.assertEqual(snapshot.sample("pressure").issues, ("invalid_value", "invalid_time"))
        self.assertEqual(snapshot.sample("temperature").value, 31)
        self.assertEqual(snapshot.sample("absent").issues, ("missing_property",))
        self.assertIsNone(snapshot.sample("absent").value)

    def test_missing_time_preserves_value_but_not_freshness(self):
        snapshot = parse_snapshot(
            {
                "code": "200",
                "data": {
                    "pressure": {"value": 2.7},
                },
            },
            model_key=WILO_MODEL_KEY,
        )
        sample = snapshot.sample("pressure")
        self.assertEqual(sample.value, 2.7)
        self.assertEqual(sample.issues, ("missing_time",))
        self.assertIs(sample.freshness(now_ms=1100, max_age_ms=500), Freshness.UNKNOWN)

    def test_boolean_values_are_not_general_truthiness(self):
        for value, expected in [(0, False), (1, True), (False, False), (True, True)]:
            for key in ("switch", "run", "errorState"):
                with self.subTest(value=value, key=key):
                    self.assertIs(parse_value(key, value).value, expected)
        for value in ("0", "1", "false", 2, -1, 1.0, None, [], {}):
            with self.subTest(value=value):
                sample = parse_value("switch", value)
                self.assertIsNone(sample.value)
                self.assertEqual(sample.issues, ("invalid_value",))

    def test_numeric_types_and_bounds_do_not_coerce_or_round(self):
        for key, value in [
            ("pressure", -0.1),
            ("pressure", 8.1),
            ("presSet", 0.9),
            ("temperature", -1),
            ("temperature", 101),
            ("propor", 9),
            ("tarSpeed", 1199),
            ("nowSpeed", 4801),
            ("nowSpeed", 2.0),
            ("nowSpeed", True),
            ("pressure", True),
            ("pressure", "2.7"),
            ("pressure", float("nan")),
            ("pressure", float("inf")),
            ("pressure", float("-inf")),
        ]:
            with self.subTest(key=key, value=value):
                self.assertIsNone(parse_value(key, value).value)
        for key, value in [
            ("presSet", 1),
            ("presSet", 8),
            ("pressure", 0),
            ("propor", 90),
            ("tarSpeed", 4800),
            ("nowSpeed", 0),
            ("pressure", 2.73),
            ("tarSpeed", 1201),
        ]:
            with self.subTest(key=key, value=value):
                self.assertEqual(parse_value(key, value).value, value)
        self.assertIsInstance(parse_value("pressure", 2).value, float)

    def test_enums_retain_unknown_codes_without_inventing_labels(self):
        for key in ("error", "mode", "refresh"):
            self.assertEqual(parse_value(key, 99).value, 99)
            for value in (True, "1", 1.0, None):
                self.assertIsNone(parse_value(key, value).value)

    def test_text_type_and_declared_maximum_length(self):
        self.assertEqual(parse_value("version", "X" * 64).value, "X" * 64)
        self.assertEqual(parse_value("version", "").value, "")
        for value in ("X" * 65, 123, None):
            self.assertIsNone(parse_value("version", value).value)

    def test_bad_timestamps_are_not_fetch_times(self):
        for time in (None, True, -1, 1.0, "1000", {}, []):
            with self.subTest(time=time):
                sample = parse_value("pressure", 2.7, time=time)
                self.assertEqual(sample.value, 2.7)
                self.assertIsNone(sample.reported_at_ms)
                self.assertEqual(sample.issues, ("invalid_time",))
                self.assertIs(sample.freshness(now_ms=1100, max_age_ms=500), Freshness.UNKNOWN)
        self.assertEqual(parse_value("pressure", 2.7, time=0).reported_at_ms, 0)

    def test_freshness_boundary_future_and_invalid_values(self):
        sample = parse_value("pressure", 2.7)
        for now, threshold, expected in [
            (1000, 0, Freshness.FRESH),
            (1500, 500, Freshness.FRESH),
            (1501, 500, Freshness.STALE),
            (999, 500, Freshness.FUTURE),
        ]:
            with self.subTest(now=now, threshold=threshold):
                self.assertIs(sample.freshness(now_ms=now, max_age_ms=threshold), expected)
        self.assertIs(
            parse_value("pressure", None).freshness(now_ms=1100, max_age_ms=500), Freshness.UNKNOWN
        )
        for now, threshold in [(-1, 1), (True, 1), (1.0, 1), (None, 1), (1, -1), (1, True)]:
            with self.subTest(now=now, threshold=threshold):
                with self.assertRaises(ValueError):
                    sample.freshness(now_ms=now, max_age_ms=threshold)

    def test_generic_unknown_scalars_and_unknown_properties(self):
        for value in (False, 7, 1.5, "demo"):
            with self.subTest(value=value):
                self.assertEqual(parse_value("future_property", value).value, value)
        for value in (None, [], {}, float("nan"), float("inf")):
            self.assertIsNone(parse_value("future_property", value).value)
        unknown = parse_snapshot(
            {
                "code": "200",
                "data": {
                    "switch": {"time": 1, "value": 1},
                },
            },
            model_key="unknown",
        )
        self.assertIsNone(unknown.powered)
        self.assertIsNone(unknown.running)
        self.assertEqual(unknown.sample("switch").value, 1)

    def test_snapshots_are_immutable_and_input_is_not_retained(self):
        payload = {"code": "200", "data": {"run": {"time": 1, "value": 0}}}
        snapshot = parse_snapshot(payload, model_key=WILO_MODEL_KEY)
        payload["data"]["run"]["value"] = 1
        self.assertIs(snapshot.running, False)
        with self.assertRaises(TypeError):
            snapshot.properties["new"] = snapshot.sample("run")
        with self.assertRaises(FrozenInstanceError):
            snapshot.sample("run").value = True
        with self.assertRaises(FrozenInstanceError):
            snapshot.online = OnlineState.UNKNOWN
