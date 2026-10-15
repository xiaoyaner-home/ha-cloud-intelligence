"""Stable versioned identifiers, independent of labels, values and credentials."""

import hashlib
import json


def _unique_id(kind: str, *components: str) -> str:
    if any(type(item) is not str or not item or item != item.strip() for item in components):
        raise ValueError("Identity components must be nonempty unpadded strings")
    encoded = json.dumps(components, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"ci:v1:{kind}:{hashlib.sha256(encoded).hexdigest()}"


def device_unique_id(namespace: str, device_id: str) -> str:
    """Namespace includes cloud/region; device ID must be immutable, not a name."""
    return _unique_id("device", namespace, device_id)


def entity_unique_id(
    namespace: str, device_id: str, property_id: str, *, role: str = "read"
) -> str:
    """Stable read/control roles coexist; never replace a read ID with a control."""
    if type(role) is not str or role not in ("read", "control"):
        raise ValueError("Entity role must be read or control, not a platform name")
    return _unique_id("entity", namespace, device_id, property_id, role)
