"""HACS layout and an isolated import of only the installable component."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.package import build, package_members, validate_package


class PackageTests(unittest.TestCase):
    def test_deterministic_archive_and_standalone_ha_import(self):
        validate_package()
        expected = {
            path.relative_to(Path(__file__).resolve().parents[2]).as_posix()
            for path in package_members()
        }
        self.assertIn("custom_components/cloud_intelligence/brand/icon.png", expected)
        self.assertIn("custom_components/cloud_intelligence/brand/icon@2x.png", expected)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a, b = build(root / "a.zip"), build(root / "b.zip")
            self.assertEqual(
                hashlib.sha256(a.read_bytes()).digest(), hashlib.sha256(b.read_bytes()).digest()
            )
            with zipfile.ZipFile(a) as archive:
                self.assertEqual(set(archive.namelist()), expected)
                self.assertTrue(
                    all(
                        p.startswith("custom_components/cloud_intelligence/")
                        for p in archive.namelist()
                    )
                )
                self.assertFalse(any("__pycache__" in p for p in archive.namelist()))
                self.assertNotIn("brand/icon.png", archive.namelist())
                self.assertIn("custom_components/cloud_intelligence/LICENSE", archive.namelist())
                self.assertIn(
                    "custom_components/cloud_intelligence/brand/icon.png", archive.namelist()
                )
                self.assertIn(
                    "custom_components/cloud_intelligence/brand/icon@2x.png", archive.namelist()
                )
                for info in archive.infolist():
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                archive.extractall(root / "install")
            code = """
import importlib, pathlib, sys
sys.path.insert(0, sys.argv[1])
for name in ("config_flow", "sensor", "binary_sensor", "diagnostics", "client", "telemetry"):
    module = importlib.import_module("custom_components.cloud_intelligence." + name)
    assert pathlib.Path(module.__file__).is_relative_to(pathlib.Path(sys.argv[1]))
assert "cloud_intelligence" not in sys.modules
from custom_components.cloud_intelligence.client import validate_input
assert validate_input(dict(host="192.168.254.20", productKey="a15zaTr5sp1", deviceName="SYNTHETIC",
                          accessKey="synthetic-key", accessToken="synthetic-token"))
print("standalone component imports with real Home Assistant")
"""
            result = subprocess.run(
                [sys.executable, "-I", "-c", code, str(root / "install")],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("standalone component imports", result.stdout)

    def test_manifest_locale_and_no_control_platform_contract(self):
        root = Path(__file__).resolve().parents[2]
        manifest = validate_package()
        self.assertEqual(manifest["version"], "0.1.0b0")
        component = root / "custom_components/cloud_intelligence"
        for forbidden in ("switch.py", "number.py", "button.py", "select.py", "services.yaml"):
            self.assertFalse((component / forbidden).exists())
        strings = json.loads((component / "strings.json").read_text())
        names = [*strings["entity"]["sensor"], *strings["entity"]["binary_sensor"]]
        self.assertEqual(len(names), 12)
        self.assertNotIn("refresh", names)
