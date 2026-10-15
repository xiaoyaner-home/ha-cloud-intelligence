"""Run the offline HA suite in a disposable, resource-capped container."""

import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/home-assistant/home-assistant:2026.9.1"


def main():
    name = "cloud-intelligence-tests-" + uuid.uuid4().hex
    command = [
        "docker",
        "run",
        "--platform",
        "linux/amd64",
        "--rm",
        "--name",
        name,
        "--label",
        "cloud-intelligence.test=true",
        "--pull",
        "never",
        "--network",
        "none",
        "--memory",
        "2g",
        "--cpus",
        "2",
        "--volume",
        f"{ROOT}:/work",
        "--workdir",
        "/work",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONHASHSEED=0",
        "--env",
        "COVERAGE_FILE=/work/.coverage.ha",
        "--entrypoint",
        "python",
        IMAGE,
        "tools/ha_suite.py",
    ]
    try:
        result = subprocess.run(command, check=False, timeout=300)
    finally:
        # Clean up only this task container, including timeout/interruption paths.
        subprocess.run(
            ["docker", "rm", "--force", name],
            check=False,
            timeout=30,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
