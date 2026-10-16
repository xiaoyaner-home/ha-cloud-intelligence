"""Low-frequency local polling; no cloud/phone fallback."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CannotConnect, IdentityMismatch, InvalidAuth, LocalClient
from .const import DEFAULT_INTERVAL, DOMAIN, ENABLE_POWER_CONTROL, MIN_INTERVAL
from .power import PowerCancelled, PowerDisabled, PowerOutcomeUnknown


class PowerServiceOutcomeUnknown(HomeAssistantError):
    """HA service failure with safe machine-readable outcome flags."""

    sent = True
    uncertain = True


class LocalCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        interval = max(
            MIN_INTERVAL, min(3600, int(entry.options.get("scan_interval", DEFAULT_INTERVAL)))
        )
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )
        self.client = LocalClient(
            dict(entry.data),
            enable_power_control=entry.options.get(ENABLE_POWER_CONTROL, False) is True,
        )
        self.entry = entry
        self.pending = None
        self.power_pending = None
        self.closed = False

    async def _async_update_data(self):
        # Do not launch a poll against a control's exclusive session or queue it.
        if self.power_pending is not None:
            raise UpdateFailed("Local operation in progress")
        self.pending = asyncio.create_task(self.client.read(require_complete=self.data is None))
        try:
            return await self.pending
        except InvalidAuth:
            raise ConfigEntryAuthFailed("Local authorization must be re-imported") from None
        except (CannotConnect, IdentityMismatch):
            raise UpdateFailed("Local telemetry unavailable") from None
        finally:
            self.pending = None

    async def async_set_power(self, enabled: bool):
        if type(enabled) is not bool:
            raise TypeError("Power requires a strict bool")
        if self.closed or self.entry.options.get(ENABLE_POWER_CONTROL, False) is not True:
            raise HomeAssistantError("Experimental power control is disabled")
        if self.pending is not None or self.power_pending is not None:
            raise HomeAssistantError("Local operation already in progress")
        self.power_pending = asyncio.create_task(self.client.set_power(enabled))
        try:
            result = await self.power_pending
            self.async_set_updated_data(result.snapshot)
            return result
        except PowerCancelled:
            self.async_set_update_error(UpdateFailed("Power outcome unknown"))
            raise
        except PowerOutcomeUnknown:
            self.async_set_update_error(UpdateFailed("Power outcome unknown"))
            raise PowerServiceOutcomeUnknown(
                "Power outcome unknown; do not automatically retry"
            ) from None
        except (CannotConnect, IdentityMismatch, InvalidAuth, PowerDisabled):
            raise HomeAssistantError("Power request refused before confirmation") from None
        finally:
            self.power_pending = None

    async def async_close(self):
        self.closed = True
        await self.async_shutdown()
        tasks = [task for task in (self.pending, self.power_pending) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
