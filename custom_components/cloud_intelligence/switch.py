"""Opt-in, non-optimistic Wilo enable permission. Never motor-running control."""

import asyncio

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

from ._core import entity_unique_id
from .const import DOMAIN, ENABLE_POWER_CONTROL
from .entity import identity


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get(ENABLE_POWER_CONTROL, False) is True:
        async_add_entities([PowerSwitch(entry.runtime_data, entry)])


class PowerSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "power_control"
    _attr_assumed_state = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = entity_unique_id(
            "alcs-local:" + entry.data["productKey"],
            entry.data["deviceName"],
            "switch",
            role="control",
        )
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, identity(entry.data))})

    @property
    def is_on(self):
        return self.coordinator.data.snapshot.powered

    async def async_device_update(self, warning=True):
        # Entity's default staged-update shortcut returns immediately with cached
        # state. An overlapping explicit refresh must instead fail closed.
        if self._update_staged:
            self.coordinator.async_set_update_error(
                UpdateFailed("Local refresh already in progress")
            )
            raise HomeAssistantError("Local refresh already in progress")
        await super().async_device_update(warning)

    async def async_update(self):
        """Finish a real read for homeassistant.update_entity, never a debounce."""
        if not self.enabled:
            return
        try:
            # async_refresh uses HA's existing refresh lock, but bypasses its
            # request cooldown. Busy control/read failures publish unavailable.
            await self.coordinator.async_refresh()
        except asyncio.CancelledError:
            self.coordinator.async_set_update_error(UpdateFailed("Local refresh cancelled"))
            # DUC may already have set success=False without notifying listeners
            # when cancellation interrupts its read. Publish that failure now.
            self.coordinator.async_update_listeners()
            raise

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_power(False)
