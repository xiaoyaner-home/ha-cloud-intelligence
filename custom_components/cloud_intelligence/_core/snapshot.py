"""Parse property shadows without conflating status, power, running or freshness."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from types import MappingProxyType

from .models import EntityDescription, model_for

type Scalar = bool | int | float | str


class SnapshotError(ValueError):
    """Error/malformed envelope; messages deliberately exclude server content."""


class OnlineState(StrEnum):
    ONLINE = "online"
    UNKNOWN = "unknown"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    FUTURE = "future"
    UNKNOWN = "unknown"


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


@dataclass(frozen=True)
class PropertySample:
    value: Scalar | None
    reported_at_ms: int | None
    issues: tuple[str, ...] = ()

    def freshness(self, *, now_ms: int, max_age_ms: int) -> Freshness:
        """Pure caller-clock classification; never substitute a fetch timestamp."""
        if not _nonnegative_int(now_ms) or not _nonnegative_int(max_age_ms):
            raise ValueError("Freshness arguments must be nonnegative integer milliseconds")
        if self.value is None or self.reported_at_ms is None:
            return Freshness.UNKNOWN
        age = now_ms - self.reported_at_ms
        if age < 0:
            return Freshness.FUTURE
        return Freshness.FRESH if age <= max_age_ms else Freshness.STALE


@dataclass(frozen=True)
class Snapshot:
    model_key: str
    online: OnlineState
    properties: Mapping[str, PropertySample]

    def sample(self, identifier: str) -> PropertySample:
        return self.properties.get(identifier, PropertySample(None, None, ("missing_property",)))

    @property
    def powered(self) -> bool | None:
        if model_for(self.model_key) is None:
            return None
        value = self.sample("switch").value
        return value if type(value) is bool else None

    @property
    def running(self) -> bool | None:
        if model_for(self.model_key) is None:
            return None
        value = self.sample("run").value
        return value if type(value) is bool else None


def _value(value: object, description: EntityDescription | None) -> Scalar:
    if type(value) not in (bool, int, float, str):
        raise ValueError("Not a scalar")
    if type(value) is float and not isfinite(value):
        raise ValueError("Non-finite value")
    if description is None:
        return value
    match description.value_type:
        case "bool":
            if type(value) is bool:
                return value
            if type(value) is int and value in (0, 1):
                return bool(value)
            raise ValueError("Not a boolean")
        case "enum":
            if type(value) is not int:
                raise ValueError("Not an integer enum code")
            return value
        case "text":
            if type(value) is not str or len(value) > description.max_length:
                raise ValueError("Invalid text")
            return value
        case "int" | "float":
            allowed = (int,) if description.value_type == "int" else (int, float)
            if type(value) not in allowed:
                raise ValueError("Invalid number type")
            if value < description.minimum or value > description.maximum:
                raise ValueError("Outside declared bounds")
            return float(value) if description.value_type == "float" else value
        case _:
            raise ValueError("Unsupported model property type")


def _sample(entry: object, description: EntityDescription | None) -> PropertySample:
    if not isinstance(entry, Mapping):
        return PropertySample(None, None, ("invalid_entry",))
    issues = []
    value = None
    if "value" not in entry:
        issues.append("missing_value")
    else:
        try:
            value = _value(entry["value"], description)
        except ValueError:
            issues.append("invalid_value")
    time = entry.get("time")
    if "time" not in entry:
        issues.append("missing_time")
    elif not _nonnegative_int(time):
        issues.append("invalid_time")
    return PropertySample(value, time if _nonnegative_int(time) else None, tuple(issues))


def parse_snapshot(payload: object, *, model_key: str, status: object = None) -> Snapshot:
    """Parse apiVer 1.0.4 decoded response; no merging, I/O, auth or commands."""
    if not isinstance(payload, Mapping):
        raise SnapshotError("Invalid property response envelope")
    if payload.get("code") != "200":
        raise SnapshotError("Property request did not succeed")
    data = payload.get("data")
    if not isinstance(data, Mapping) or any(not isinstance(key, str) or not key for key in data):
        raise SnapshotError("Invalid property data map")
    model = model_for(model_key)
    properties = {
        key: _sample(entry, model.property(key) if model else None) for key, entry in data.items()
    }
    online = OnlineState.UNKNOWN
    if type(status) is int and status == 1:
        online = OnlineState.ONLINE
    return Snapshot(model_key, online, MappingProxyType(properties))
