"""Config and options flow for Lepro Pixel LED."""

from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_PIXEL_COUNT, DOMAIN

REGION_OPTIONS = [
    selector.SelectOptionDict(value="eu", label="Europe"),
    selector.SelectOptionDict(value="us", label="United States"),
    selector.SelectOptionDict(value="na", label="North America"),
    selector.SelectOptionDict(value="fe", label="Far East"),
]

LANGUAGE_OPTIONS = [
    selector.SelectOptionDict(value="en", label="English"),
    selector.SelectOptionDict(value="it", label="Italiano"),
    selector.SelectOptionDict(value="ja", label="Japanese"),
]

DATA_SCHEMA = vol.Schema({
    vol.Required("account"): str,
    vol.Required("password"): str,
    vol.Optional("region", default="eu"): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=REGION_OPTIONS,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    vol.Optional("language", default="en"): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=LANGUAGE_OPTIONS,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
})


class LeproPixelLedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial account setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            account = user_input["account"]
            await self.async_set_unique_id(account.lower())
            self._abort_if_unique_id_configured()

            # Create a mutable dictionary for the user input
            data = dict(user_input)
            
            # Note: Persistent MAC generation and API validation are safely deferred 
            # to async_setup_entry in light.py to prevent blocking the UI thread here.
            return self.async_create_entry(title="Lepro Smart Lighting", data=data)

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return LeproOptionsFlow(entry)


class LeproOptionsFlow(config_entries.OptionsFlow):
    """Allow per-device pixel-count overrides for edge cases."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            overrides: dict[str, int] = {}
            raw = user_input.get("pixel_overrides", "").strip()
            if raw:
                for part in raw.split(","):
                    if ":" in part:
                        did, _, cnt = part.partition(":")
                        did = did.strip()
                        try:
                            n = int(cnt.strip())
                        except ValueError:
                            continue
                        if did and n > 0:
                            overrides[did] = n
            return self.async_create_entry(
                title="", data={CONF_PIXEL_COUNT: overrides}
            )

        current = self.entry.options.get(CONF_PIXEL_COUNT, {})
        current_str = ", ".join(f"{k}:{v}" for k, v in current.items())
        schema = vol.Schema(
            {
                vol.Optional(
                    "pixel_overrides", default=current_str
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)