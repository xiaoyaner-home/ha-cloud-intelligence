"""Shared, read-only native entity state and immutable registry identity."""

from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._core import device_unique_id, entity_unique_id
from .const import DOMAIN


def identity(data):
    return device_unique_id("alcs-local:" + data["productKey"], data["deviceName"])


class LocalEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator)
        self.description = description
        self._attr_translation_key = description.identifier.lower()
        self._attr_unique_id = entity_unique_id(
            "alcs-local:" + entry.data["productKey"],
            entry.data["deviceName"],
            description.identifier,
        )
        if description.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identity(entry.data))},
            name=entry.title,
            manufacturer="Wilo",
            model="HiMulti-1 WiFi",
            sw_version=coordinator.data.snapshot.sample("version").value,
        )

    @property
    def value(self):
        return self.coordinator.data.snapshot.sample(self.description.identifier).value

    @property
    def extra_state_attributes(self):
        value = self.value
        attrs = {
            "locally_received_at": self.coordinator.data.received_at.get(
                self.description.identifier
            ),
            "timestamp_source": "home_assistant_receive_time",
            "local_reachable": self.coordinator.last_update_success,
        }
        if type(value) is int and (label := self.description.label_for(value)) is not None:
            attrs["meaning"] = label
        return attrs
