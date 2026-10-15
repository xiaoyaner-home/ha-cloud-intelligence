"""Build a deterministic manual-install ZIP of the self-contained HACS component."""

import hashlib
import json
import struct
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/cloud_intelligence"
BRAND = COMPONENT / "brand"
BRAND_FILENAMES = {
    "icon.png",
    "icon@2x.png",
    "dark_icon.png",
    "dark_icon@2x.png",
    "logo.png",
    "logo@2x.png",
    "dark_logo.png",
    "dark_logo@2x.png",
}
EXPECTED_BRAND_SIZES = {"icon.png": (256, 256), "icon@2x.png": (512, 512)}


def _png_size(path):
    raw = path.read_bytes()
    assert raw[:8] == bytes((137, 80, 78, 71, 13, 10, 26, 10)), f"Not a PNG: {path}"
    assert raw[12:16] == b"IHDR", f"Missing PNG IHDR: {path}"
    assert raw[24] == 8 and raw[25] == 6, f"PNG must be 8-bit RGBA: {path}"
    chunks = []
    position = 8
    while position < len(raw):
        length = struct.unpack(">I", raw[position : position + 4])[0]
        chunks.append(raw[position + 4 : position + 8])
        position += length + 12
    assert chunks[0] == b"IHDR" and chunks[-1] == b"IEND", f"Malformed PNG: {path}"
    assert all(chunk in {b"IHDR", b"IDAT", b"IEND"} for chunk in chunks)
    return struct.unpack(">II", raw[16:24])


def package_members():
    """Return the only component files permitted in the public install ZIP."""
    members = []
    for path in sorted(COMPONENT.rglob("*")):
        if path.is_dir():
            continue
        assert not path.is_symlink(), f"Symlink is not packageable: {path}"
        relative = path.relative_to(COMPONENT)
        if path.name == "LICENSE" or path.suffix in {".py", ".json"}:
            members.append(path)
        elif relative.parent == Path("brand") and path.name in BRAND_FILENAMES:
            members.append(path)
        else:
            raise AssertionError(f"Unexpected component file; refusing to omit it: {relative}")
    return members


def validate_package():
    assert (COMPONENT / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["domain"] == "cloud_intelligence"
    assert manifest["name"] == "Cloud Intelligence (Local)"
    assert manifest["codeowners"] == ["@xiaoyaner0201"]
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"
    assert manifest["integration_type"] == "device"
    assert manifest["requirements"] == ["cryptography==48.0.1"]

    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert set(hacs) == {"name", "homeassistant"}
    assert hacs["name"] == manifest["name"]
    assert hacs["homeassistant"] == "2026.9.1"

    root_brand = ROOT / "brand"
    for filename, size in EXPECTED_BRAND_SIZES.items():
        component_path = BRAND / filename
        root_path = root_brand / filename
        assert _png_size(component_path) == size
        assert root_path.read_bytes() == component_path.read_bytes()

    strings = json.loads((COMPONENT / "strings.json").read_text())
    for locale in ("en", "zh-Hans", "zh-Hant", "ja"):
        text = json.loads((COMPONENT / "translations" / f"{locale}.json").read_text())
        assert _keys(text) == _keys(strings), f"Translation shape mismatch: {locale}"
        if locale == "en":
            assert text == strings
    package_members()
    return manifest


def _keys(value, prefix=""):
    if not isinstance(value, dict):
        assert isinstance(value, str) and value
        return {prefix}
    return set().union(*(_keys(v, f"{prefix}.{k}") for k, v in value.items()))


def build(output):
    validate_package()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in package_members():
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.create_version = 20
            info.extract_version = 20
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )
    return output


def main():
    manifest = validate_package()
    path = build(ROOT / "dist" / f"cloud_intelligence-{manifest['version']}.zip")
    print(f"Built {path.relative_to(ROOT)}")
    print(f"SHA256 {hashlib.sha256(path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
