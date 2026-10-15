"""Allowlisted diagnostics: no authorization, identity, address or readings."""

from .const import DEFAULT_INTERVAL


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "transport": "local_polling",
        "model": "Wilo HiMulti-1 WiFi",
        "last_update_success": coordinator.last_update_success,
        "scan_interval": entry.options.get("scan_interval", DEFAULT_INTERVAL),
        "complete": coordinator.data.complete if coordinator.data else False,
        "valid_property_count": sum(
            s.value is not None for s in coordinator.data.snapshot.properties.values()
        )
        if coordinator.data
        else 0,
    }
