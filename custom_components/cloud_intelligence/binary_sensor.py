"""Power permission, motor running, and fault are independent observations."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from ._core import WILO_MODEL_KEY, entity_descriptions
from .entity import LocalEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        LocalBinarySensor(entry.runtime_data, entry, desc)
        for desc in entity_descriptions(WILO_MODEL_KEY)
        if desc.kind == "binary_sensor"
    )


class LocalBinarySensor(LocalEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator, entry, description)
        if description.identifier == "run":
            self._attr_device_class = BinarySensorDeviceClass.RUNNING
        elif description.identifier == "errorState":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        return self.value
