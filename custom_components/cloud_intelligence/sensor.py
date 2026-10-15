"""Nine read-only sensors, including observed setpoints (not controls)."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass

from ._core import WILO_MODEL_KEY, entity_descriptions
from .entity import LocalEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        LocalSensor(entry.runtime_data, entry, desc)
        for desc in entity_descriptions(WILO_MODEL_KEY)
        if desc.kind == "sensor"
    )


class LocalSensor(LocalEntity, SensorEntity):
    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator, entry, description)
        self._attr_native_unit_of_measurement = (
            "rpm" if description.unit == "r/min" else description.unit
        )
        if description.identifier == "temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
        elif description.identifier == "pressure":
            self._attr_device_class = SensorDeviceClass.PRESSURE
        if description.identifier in {"temperature", "pressure", "nowSpeed"}:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.value
