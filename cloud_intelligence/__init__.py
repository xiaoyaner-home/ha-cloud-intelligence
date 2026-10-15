"""Pure, read-only Cloud Intelligence device semantics; no transport or HA imports."""

from .identity import device_unique_id, entity_unique_id
from .models import (
    WILO_MODEL_KEY,
    EntityDescription,
    ModelDescription,
    control_descriptions,
    entity_descriptions,
    model_for,
)
from .snapshot import (
    Freshness,
    OnlineState,
    PropertySample,
    Snapshot,
    SnapshotError,
    parse_snapshot,
)

__all__ = [
    "WILO_MODEL_KEY",
    "EntityDescription",
    "Freshness",
    "ModelDescription",
    "OnlineState",
    "PropertySample",
    "Snapshot",
    "SnapshotError",
    "control_descriptions",
    "device_unique_id",
    "entity_descriptions",
    "entity_unique_id",
    "model_for",
    "parse_snapshot",
]
