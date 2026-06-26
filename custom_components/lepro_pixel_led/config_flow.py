"""Config and options flow for Lepro Pixel LED."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LeproApi, LeproAuthError
from .const import CONF_PIXEL_COUNT, CONF_REGION, DOMAIN, REGIONS

CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"


class LeproConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial account setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            account = user_input[CONF_ACCOUNT]
            await self.async_set_unique_id(account.lower())
            self._abort_if_unique_id_configured()

            # validate credentials by attempting login
            api = LeproApi(
                hass_config_dir=self.hass.config.config_dir,
                entry_id="validate",
                account=account,
                password=user_input[CONF_PASSWORD],
                region=user_input[CONF_REGION],
            )
            try:
                await api.async_setup()
            except LeproAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=account,
                    data={
                        CONF_ACCOUNT: account,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_REGION: user_input[CONF_REGION],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNT): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_REGION, default="eu"): vol.In(list(REGIONS.keys())),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return LeproOptionsFlow(entry)


class LeproOptionsFlow(OptionsFlow):
    """Allow per-device pixel-count overrides.

    Stored as options under CONF_PIXEL_COUNT: a dict of {did: count}. A value of
    0 (or absent) means auto-detect.
    """

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # parse the single text field "did:count, did:count" into a dict
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