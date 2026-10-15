"""Fail clearly when development tools do not match the pinned requirements."""

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def main() -> int:
    if sys.version_info[:2] != (3, 13):
        print("Development checks require Python 3.13; see .python-version")
        return 1
    requirements = Path(__file__).resolve().parents[1] / "requirements-dev.txt"
    for line in requirements.read_text().splitlines():
        package, expected = line.split("==")
        try:
            actual = version(package)
        except PackageNotFoundError:
            print(f"Missing pinned development tool: {package}=={expected}")
            return 1
        if actual != expected:
            print(f"Version mismatch: {package} requires {expected}, found {actual}")
            return 1
        print(f"{package}=={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
