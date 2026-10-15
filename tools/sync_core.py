"""Check byte-for-byte packaged core parity, or update it explicitly."""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cloud_intelligence"
DEST = ROOT / "custom_components/cloud_intelligence/_core"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    sources = sorted(SOURCE.glob("*.py"))
    if args.update:
        DEST.mkdir(parents=True, exist_ok=True)
        for source in sources:
            shutil.copyfile(source, DEST / source.name)
    actual = {p.name for p in DEST.glob("*.py")}
    if actual != {p.name for p in sources}:
        raise SystemExit("Packaged core file set differs")
    for source in sources:
        if source.read_bytes() != (DEST / source.name).read_bytes():
            raise SystemExit(f"Packaged core drift: {source.name}; run tools/sync_core.py --update")
    print(f"Packaged core matches all {len(sources)} canonical files byte-for-byte")


if __name__ == "__main__":
    main()
