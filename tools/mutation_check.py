"""Prove two safety/semantic regressions fail assertions in isolated copies."""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = (
    (
        "running_is_not_power",
        "cloud_intelligence/snapshot.py",
        'value = self.sample("run").value',
        'value = self.sample("switch").value',
        "tests.test_snapshot.SnapshotTests.test_power_run_online_freshness_are_independent",
    ),
    (
        "unknown_models_stay_read_only",
        "cloud_intelligence/models.py",
        "write_enabled=False,",
        "write_enabled=True,",
        "tests.test_models.ModelTests.test_unknown_models_are_read_only",
    ),
)


def run_test(copy: Path, test: str) -> subprocess.CompletedProcess:
    environment = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
        PYTHONHASHSEED="0",
        PYTHONPATH=str(copy),
    )
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", test, "-v"],
        cwd=copy,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


HA_MUTATIONS = (
    (
        "explicit_power_refresh_must_not_debounce",
        "custom_components/cloud_intelligence/switch.py",
        "await self.coordinator.async_refresh()",
        "await self.coordinator.async_request_refresh()",
        "tests.ha.test_lifecycle.Lifecycle.test_explicit_power_refresh_bypasses_active_debounce",
    ),
    (
        "overlapping_explicit_refresh_must_fail_closed",
        "custom_components/cloud_intelligence/switch.py",
        "if self._update_staged:",
        "if False:",
        "tests.ha.test_lifecycle.Lifecycle.test_overlapping_explicit_power_refresh_never_returns_cached_on",
    ),
    (
        "local_binary_power_is_not_motor_run",
        "custom_components/cloud_intelligence/binary_sensor.py",
        "return self.value",
        'return self.coordinator.data.snapshot.sample("switch").value',
        "tests.ha.test_lifecycle.Lifecycle.test_add_twelve_native_entities_device_and_binary_separation",
    ),
    (
        "encrypted_content_format_zero_is_valid",
        "custom_components/cloud_intelligence/telemetry.py",
        'and not (session_id is not None and encoded == b"")',
        "and not False",
        "tests.protocol.test_contracts.Contracts.test_encrypted_ctype0_all_reply_shapes",
    ),
    (
        "power_payload_cannot_invert_permission",
        "custom_components/cloud_intelligence/telemetry.py",
        'params = {"switch": int(_power.enabled)}',
        'params = {"switch": int(not _power.enabled)}',
        "tests.protocol.test_power.PowerTests.test_both_directions_fixed_single_send_and_stable_endpoint",
    ),
    (
        "power_must_preserve_other_settings",
        "custom_components/cloud_intelligence/client.py",
        'for k in telemetry.SETTINGS - {"switch"}',
        "for k in frozenset()",
        "tests.protocol.test_power.PowerTests.test_ack200_unchanged_partial_or_other_setting_change_is_unknown",
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ha", action="store_true")
    mutations = HA_MUTATIONS if parser.parse_args().ha else MUTATIONS
    for name, filename, original, replacement, test in mutations:
        source = ROOT / filename
        before = hashlib.sha256(source.read_bytes()).digest()
        with TemporaryDirectory(prefix="cloud-intelligence-mutation-") as temporary:
            copy = Path(temporary) / "repo"
            shutil.copytree(
                ROOT,
                copy,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".coverage*",
                    ".ruff_cache",
                ),
            )
            baseline = run_test(copy, test)
            if baseline.returncode != 0:
                print(f"FAIL {name}: unmodified temporary copy did not pass")
                print(baseline.stdout + baseline.stderr)
                return 1
            target = copy / filename
            content = target.read_text()
            if content.count(original) != 1:
                print(f"FAIL {name}: mutation target must match exactly once")
                return 1
            target.write_text(content.replace(original, replacement))
            result = run_test(copy, test)
            output = result.stdout + result.stderr
            failure = f"FAIL: {test.rsplit('.', 1)[1]} "
            if not (
                result.returncode == 1
                and failure in output
                and "AssertionError:" in output
                and "ERROR:" not in output
            ):
                print(f"FAIL {name}: expected semantic assertion failure was not observed")
                print(output)
                return 1
            print(f"PASS {name}: independent baseline green; mutant exit={result.returncode}")
            print(next(line for line in output.splitlines() if line.startswith("FAIL:")))
            print(next(line for line in output.splitlines() if line.startswith("FAILED (")))
        if hashlib.sha256(source.read_bytes()).digest() != before:
            print(f"FAIL {name}: working source changed")
            return 1
    print(f"Detected {len(mutations)} of {len(mutations)} independent mutations; source unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
