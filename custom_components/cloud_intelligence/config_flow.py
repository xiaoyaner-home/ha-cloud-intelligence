"""Manual import of one device's own local authorization; no account login."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .client import CannotConnect, IdentityMismatch, InvalidAuth, LocalClient, validate_input
from .const import DEFAULT_INTERVAL, DOMAIN, MIN_INTERVAL
from .entity import identity
from .telemetry import PRODUCT_KEY


def _schema(defaults):
    fields = {}
    for key in ("name", "host", "productKey", "deviceName", "accessKey", "accessToken"):
        marker = (
            vol.Required(key, default=defaults.get(key, ""))
            if key not in {"accessKey", "accessToken"}
            else vol.Required(key)
        )
        fields[marker] = selector.TextSelector(
            selector.TextSelectorConfig(
                type=selector.TextSelectorType.PASSWORD
                if key in {"accessKey", "accessToken"}
                else selector.TextSelectorType.TEXT
            )
        )
    return vol.Schema(fields)


class LocalFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input=None):
        return await self._import("user", user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._import("reauth_confirm", user_input, self._get_reauth_entry())

    async def async_step_reconfigure(self, user_input=None):
        return await self._import("reconfigure", user_input, self._get_reconfigure_entry())

    async def _import(self, step, user_input, entry=None):
        errors = {}
        defaults = (
            dict(entry.data)
            if entry
            else {"name": "Wilo HiMulti-1 WiFi", "productKey": PRODUCT_KEY}
        )
        if user_input is not None:
            try:
                data = validate_input(user_input)
                uid = identity(data)
                if entry is not None and uid != entry.unique_id:
                    return self.async_abort(reason="wrong_device")
                await self.async_set_unique_id(uid)
                if entry is None:
                    self._abort_if_unique_id_configured()
                await LocalClient(data).read(require_complete=True)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except IdentityMismatch:
                errors["base"] = "wrong_device"
            except (ValueError, TypeError):
                errors["base"] = "invalid_input"
            else:
                if entry is not None:
                    return self.async_update_reload_and_abort(entry, data=data, title=data["name"])
                return self.async_create_entry(title=data["name"], data=data)
            # Never echo secrets into form defaults (including after errors).
            defaults.update(
                {k: v for k, v in user_input.items() if k not in {"accessKey", "accessToken"}}
            )
        return self.async_show_form(step_id=step, data_schema=_schema(defaults), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LocalOptions()


class LocalOptions(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "scan_interval",
                        default=self.config_entry.options.get("scan_interval", DEFAULT_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_INTERVAL, max=3600))
                }
            ),
        )
