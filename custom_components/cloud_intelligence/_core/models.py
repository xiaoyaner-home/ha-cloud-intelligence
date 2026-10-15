"""Immutable model metadata; TSL write declarations do not enable commands."""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .snapshot import Snapshot

WILO_MODEL_KEY = "wilo_himulti_1"


@dataclass(frozen=True)
class EntityDescription:
    identifier: str
    name: str
    kind: str
    value_type: str
    declared_access: str = "r"
    unit: str | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None
    options: tuple[tuple[int, str], ...] = ()
    max_length: int | None = None
    write_enabled: bool = False
    role: str = "read"
    diagnostic: bool = False
    enabled_by_default: bool = True

    def label_for(self, code: int) -> str | None:
        """Unknown enum codes have no invented label."""
        return dict(self.options).get(code)


@dataclass(frozen=True)
class ModelDescription:
    key: str
    name: str
    properties: tuple[EntityDescription, ...]

    def property(self, identifier: str) -> EntityDescription | None:
        return next((item for item in self.properties if item.identifier == identifier), None)


_WILO = ModelDescription(
    key=WILO_MODEL_KEY,
    name="Wilo HiMulti-1 WiFi",
    properties=(
        EntityDescription("switch", "Power", "switch", "bool", "rw"),
        EntityDescription(
            "temperature",
            "Water temperature",
            "sensor",
            "int",
            unit="°C",
            minimum=0,
            maximum=100,
            step=1,
        ),
        EntityDescription(
            "presSet",
            "Working pressure setting",
            "number",
            "float",
            "rw",
            unit="bar",
            minimum=1.0,
            maximum=8.0,
            step=0.1,
        ),
        EntityDescription(
            "refresh", "Refresh now", "button", "enum", "rw", options=((1, "refresh_now"),)
        ),
        EntityDescription(
            "mode",
            "Operating mode",
            "select",
            "enum",
            "rw",
            options=((0, "automatic"), (1, "manual")),
        ),
        EntityDescription(
            "error",
            "Fault code",
            "sensor",
            "enum",
            options=(
                (0, "no_fault"),
                (1, "undervoltage"),
                (2, "overvoltage"),
                (3, "pressure_sensor_fault"),
                (4, "ipm_overtemperature"),
                (5, "water_shortage"),
                (8, "motor_phase_loss_or_excess_current"),
                (9, "ipm_overcurrent"),
                (13, "communication_fault"),
            ),
        ),
        EntityDescription("errorState", "Fault", "binary_sensor", "bool"),
        EntityDescription("run", "Motor running", "binary_sensor", "bool"),
        EntityDescription(
            "propor",
            "Starting pressure ratio",
            "number",
            "int",
            "rw",
            minimum=10,
            maximum=90,
            step=1,
        ),
        EntityDescription("version", "Software version", "sensor", "text", max_length=64),
        EntityDescription(
            "pressure",
            "Working pressure",
            "sensor",
            "float",
            unit="bar",
            minimum=0.0,
            maximum=8.0,
            step=0.1,
        ),
        EntityDescription(
            "tarSpeed",
            "Target speed",
            "number",
            "int",
            "rw",
            unit="r/min",
            minimum=1200,
            maximum=4800,
            step=60,
        ),
        EntityDescription(
            "nowSpeed",
            "Actual speed",
            "sensor",
            "int",
            unit="r/min",
            minimum=0,
            maximum=4800,
            step=60,
        ),
    ),
)


def model_for(model_key: str) -> ModelDescription | None:
    """Only an explicit, authoritative adapter key selects a known model."""
    return _WILO if model_key == WILO_MODEL_KEY else None


def _read_only_description(identifier: str, value: object) -> EntityDescription:
    value_type = {bool: "bool", int: "int", float: "float", str: "text"}.get(type(value), "unknown")
    return EntityDescription(
        identifier=identifier,
        name=identifier,
        kind="binary_sensor" if type(value) is bool else "sensor",
        value_type=value_type,
        declared_access="r",
        write_enabled=False,
        diagnostic=True,
        enabled_by_default=False,
    )


def entity_descriptions(
    model_key: str, snapshot: "Snapshot | None" = None
) -> tuple[EntityDescription, ...]:
    """Known metadata plus read-only fallbacks for otherwise unknown properties."""
    model = model_for(model_key)
    properties = model.properties if model else ()
    known = tuple(
        replace(
            item,
            kind="binary_sensor" if item.value_type == "bool" else "sensor",
            role="read",
            diagnostic=item.identifier in {"version", "error"},
            enabled_by_default=item.identifier not in {"version", "error"},
        )
        for item in properties
        if item.identifier != "refresh"
    )
    identifiers = {item.identifier for item in properties}
    extra = (
        ()
        if snapshot is None
        else tuple(
            _read_only_description(identifier, sample.value)
            for identifier, sample in sorted(snapshot.properties.items())
            if identifier not in identifiers
        )
    )
    return known + extra


def control_descriptions(model_key: str) -> tuple[EntityDescription, ...]:
    """Dormant future-control metadata only: never instantiate commands from this."""
    model = model_for(model_key)
    if model is None:
        return ()
    return tuple(
        replace(item, role="control", enabled_by_default=False)
        for item in model.properties
        if item.declared_access == "rw"
    )
