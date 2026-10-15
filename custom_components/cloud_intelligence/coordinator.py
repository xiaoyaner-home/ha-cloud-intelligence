"""Low-frequency local polling; no cloud/phone fallback."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CannotConnect, IdentityMismatch, InvalidAuth, LocalClient
from .const import DEFAULT_INTERVAL, DOMAIN, MIN_INTERVAL


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
        self.client = LocalClient(dict(entry.data))
        self.pending = None

    async def _async_update_data(self):
        self.pending = asyncio.create_task(self.client.read(require_complete=self.data is None))
        try:
            return await self.pending
        except InvalidAuth:
            raise ConfigEntryAuthFailed("Local authorization must be re-imported") from None
        except (CannotConnect, IdentityMismatch):
            raise UpdateFailed("Local telemetry unavailable") from None
        finally:
            self.pending = None

    async def async_close(self):
        await self.async_shutdown()
        if self.pending is not None:
            self.pending.cancel()
            await asyncio.gather(self.pending, return_exceptions=True)
