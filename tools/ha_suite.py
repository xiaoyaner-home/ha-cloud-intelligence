"""Entrypoint executed only in the HA test container, never against a live device."""

import importlib.metadata
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(*args):
    subprocess.run([sys.executable, "-B", *args], cwd=ROOT, check=True, timeout=120)


def main():
    assert sys.version_info[:2] == (3, 14)
    for package, expected in {
        "homeassistant": "2026.9.1",
        "cryptography": "48.0.1",
        "coverage": "7.16.0",
    }.items():
        actual = importlib.metadata.version(package)
        assert actual == expected, (package, actual, expected)
        print(f"{package}=={actual}", flush=True)
    print(sys.version, flush=True)
    run("tools/sync_core.py")
    run(
        "-m",
        "coverage",
        "run",
        "--branch",
        "--source=custom_components.cloud_intelligence,cloud_intelligence",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-t",
        ".",
        "-v",
    )
    run("-m", "coverage", "report", "--fail-under=90")
    run("tools/mutation_check.py", "--ha")


if __name__ == "__main__":
    main()
