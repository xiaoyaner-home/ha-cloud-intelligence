"""Versioned, stable identity using synthetic namespace/device identifiers."""

import unittest

from cloud_intelligence import device_unique_id, entity_unique_id


class IdentityTests(unittest.TestCase):
    def test_read_and_control_roles_do_not_replace_each_other(self):
        read = entity_unique_id("demo", "demo-pump-001", "switch")
        control = entity_unique_id("demo", "demo-pump-001", "switch", role="control")
        self.assertEqual(read, entity_unique_id("demo", "demo-pump-001", "switch", role="read"))
        self.assertNotEqual(read, control)
        for role in ("", "switch", "number", None):
            with self.subTest(role=role):
                with self.assertRaises(ValueError):
                    entity_unique_id("demo", "demo-pump-001", "switch", role=role)

    def test_device_and_entity_ids_are_stable_and_separate(self):
        device = device_unique_id("demo-cloud:region-a", "demo-pump-001")
        run = entity_unique_id("demo-cloud:region-a", "demo-pump-001", "run")
        self.assertEqual(device, device_unique_id("demo-cloud:region-a", "demo-pump-001"))
        self.assertEqual(run, entity_unique_id("demo-cloud:region-a", "demo-pump-001", "run"))
        self.assertEqual(
            device,
            "ci:v1:device:1e6692365a51e4ca99209d32b13056c3c0e2d91e8411c4b22fb87251a09410be",
        )
        self.assertEqual(
            run,
            "ci:v1:entity:2439139e64590a9fab7a2d4c1d5200156452c0ef1d9261b1d3694207ad2ab582",
        )
        self.assertRegex(device, r"^ci:v1:device:[0-9a-f]{64}$")
        self.assertRegex(run, r"^ci:v1:entity:[0-9a-f]{64}$")
        self.assertNotEqual(device, run)
        self.assertNotEqual(run, entity_unique_id("demo-cloud:region-a", "demo-pump-001", "switch"))
        self.assertNotEqual(device, device_unique_id("demo-cloud:region-a", "demo-pump-002"))
        self.assertNotEqual(device, device_unique_id("demo-cloud:region-b", "demo-pump-001"))

    def test_components_are_unambiguous_and_not_normalized(self):
        self.assertNotEqual(device_unique_id("a:b", "c"), device_unique_id("a", "b:c"))
        self.assertNotEqual(device_unique_id("a", "BC"), device_unique_id("a", "bc"))
        self.assertNotEqual(entity_unique_id("a", "b:c", "d"), entity_unique_id("a:b", "c", "d"))
        self.assertEqual(device_unique_id("demo", "合成泵"), device_unique_id("demo", "合成泵"))

    def test_invalid_identity_components_are_rejected_not_repaired(self):
        for value in ("", " ", " demo", "demo ", None, 0, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    device_unique_id(value, "demo-pump-001")
                with self.assertRaises(ValueError):
                    device_unique_id("demo", value)
                with self.assertRaises(ValueError):
                    entity_unique_id("demo", "demo-pump-001", value)
