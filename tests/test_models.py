"""Complete TSL metadata and fail-closed entity descriptions."""

import unittest
from dataclasses import FrozenInstanceError

from cloud_intelligence import WILO_MODEL_KEY, entity_descriptions, model_for, parse_snapshot


class ModelTests(unittest.TestCase):
    def test_future_control_descriptions_are_separate_and_disabled(self):
        from cloud_intelligence import control_descriptions

        controls = control_descriptions(WILO_MODEL_KEY)
        self.assertEqual(len(controls), 6)
        self.assertEqual(
            {d.identifier: d.kind for d in controls},
            {
                "switch": "switch",
                "presSet": "number",
                "refresh": "button",
                "mode": "select",
                "propor": "number",
                "tarSpeed": "number",
            },
        )
        self.assertTrue(all(d.role == "control" for d in controls))
        self.assertTrue(all(not d.write_enabled and not d.enabled_by_default for d in controls))
        self.assertEqual(control_descriptions("unknown"), ())
        read = {d.identifier: d for d in entity_descriptions(WILO_MODEL_KEY)}
        self.assertEqual(read["switch"].kind, "binary_sensor")
        self.assertTrue(read["version"].diagnostic)
        self.assertFalse(read["version"].enabled_by_default)
        self.assertTrue(read["pressure"].enabled_by_default)

    def test_all_thirteen_properties_and_numeric_metadata(self):
        model = model_for(WILO_MODEL_KEY)
        self.assertEqual(model.name, "Wilo HiMulti-1 WiFi")
        expected = {
            "switch": ("switch", "bool", "rw", None, None, None, None),
            "temperature": ("sensor", "int", "r", "°C", 0, 100, 1),
            "presSet": ("number", "float", "rw", "bar", 1.0, 8.0, 0.1),
            "refresh": ("button", "enum", "rw", None, None, None, None),
            "mode": ("select", "enum", "rw", None, None, None, None),
            "error": ("sensor", "enum", "r", None, None, None, None),
            "errorState": ("binary_sensor", "bool", "r", None, None, None, None),
            "run": ("binary_sensor", "bool", "r", None, None, None, None),
            "propor": ("number", "int", "rw", None, 10, 90, 1),
            "version": ("sensor", "text", "r", None, None, None, None),
            "pressure": ("sensor", "float", "r", "bar", 0.0, 8.0, 0.1),
            "tarSpeed": ("number", "int", "rw", "r/min", 1200, 4800, 60),
            "nowSpeed": ("sensor", "int", "r", "r/min", 0, 4800, 60),
        }
        actual = {
            p.identifier: (
                p.kind,
                p.value_type,
                p.declared_access,
                p.unit,
                p.minimum,
                p.maximum,
                p.step,
            )
            for p in model.properties
        }
        self.assertEqual(actual, expected)
        self.assertEqual(len(model.properties), 13)
        self.assertEqual(model.property("version").max_length, 64)
        self.assertIsNone(model.property("unrecognized"))
        self.assertTrue(all(p.name for p in model.properties))

    def test_action_enums_and_fault_labels(self):
        model = model_for(WILO_MODEL_KEY)
        self.assertEqual(model.property("refresh").options, ((1, "refresh_now"),))
        self.assertEqual(model.property("mode").options, ((0, "automatic"), (1, "manual")))
        self.assertEqual(
            dict(model.property("error").options),
            {
                0: "no_fault",
                1: "undervoltage",
                2: "overvoltage",
                3: "pressure_sensor_fault",
                4: "ipm_overtemperature",
                5: "water_shortage",
                8: "motor_phase_loss_or_excess_current",
                9: "ipm_overcurrent",
                13: "communication_fault",
            },
        )
        self.assertEqual(model.property("error").label_for(5), "water_shortage")
        self.assertIsNone(model.property("error").label_for(99))
        self.assertIsNone(model.property("pressure").label_for(1))

    def test_known_model_is_metadata_only_not_write_authorization(self):
        descriptions = entity_descriptions(WILO_MODEL_KEY)
        self.assertEqual(len(descriptions), 12)
        self.assertTrue(all(d.kind in {"sensor", "binary_sensor"} for d in descriptions))
        self.assertTrue(all(d.role == "read" for d in descriptions))
        self.assertNotIn("refresh", {d.identifier for d in descriptions})
        self.assertTrue(any(d.declared_access == "rw" for d in descriptions))
        self.assertTrue(all(not d.write_enabled for d in descriptions))
        with self.assertRaises(FrozenInstanceError):
            descriptions[0].write_enabled = True
        with self.assertRaises(FrozenInstanceError):
            model_for(WILO_MODEL_KEY).name = "changed"

    def test_unknown_models_are_read_only(self):
        snapshot = parse_snapshot(
            {
                "code": "200",
                "data": {
                    "switch": {"time": 1, "value": 1},
                    "flag": {"time": 1, "value": True},
                    "speed": {"time": 1, "value": 2.5},
                    "version": {"time": 1, "value": "DEMO"},
                    "broken": {"time": 1, "value": []},
                },
            },
            model_key="unknown-model",
        )
        descriptions = entity_descriptions("unknown-model", snapshot)
        self.assertTrue(all(not d.write_enabled for d in descriptions))
        self.assertTrue(all(d.declared_access == "r" for d in descriptions))
        self.assertTrue(all(d.role == "read" for d in descriptions))
        self.assertTrue(all(d.diagnostic and not d.enabled_by_default for d in descriptions))
        self.assertTrue(all(d.kind in {"sensor", "binary_sensor"} for d in descriptions))
        self.assertEqual([d.identifier for d in descriptions], sorted(snapshot.properties))
        self.assertEqual(
            {d.identifier: d.value_type for d in descriptions},
            {
                "switch": "int",
                "flag": "bool",
                "speed": "float",
                "version": "text",
                "broken": "unknown",
            },
        )

    def test_unknown_selection_is_exact_and_does_not_use_friendly_names(self):
        for key in ("Wilo HiMulti-1 WiFi", "wilo_himulti_1_extra", "", "other"):
            with self.subTest(key=key):
                self.assertIsNone(model_for(key))
                self.assertEqual(entity_descriptions(key), ())

    def test_known_model_extra_properties_remain_read_only(self):
        snapshot = parse_snapshot(
            {
                "code": "200",
                "data": {
                    "dangerousWrite": {"time": 1, "value": True},
                },
            },
            model_key=WILO_MODEL_KEY,
        )
        descriptions = entity_descriptions(WILO_MODEL_KEY, snapshot)
        self.assertEqual(len(descriptions), 13)
        extra = descriptions[-1]
        self.assertEqual(extra.identifier, "dangerousWrite")
        self.assertEqual(extra.kind, "binary_sensor")
        self.assertFalse(extra.write_enabled)
        self.assertEqual(extra.declared_access, "r")
