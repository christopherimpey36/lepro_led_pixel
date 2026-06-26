"""The Lepro Pixel LED integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv

from .api import LeproApi, LeproAuthError
from .const import (
    CONF_PIXEL_COUNT,
    CONF_REGION,
    DOMAIN,
    SERVICE_SEND_DEBUG,
    SERVICE_SET_PIXELS,
)
from .coordinator import LeproCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["light"]

CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"

SET_PIXELS_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("colors"): [
            vol.All([vol.Coerce(int)], vol.Length(min=3, max=3))
        ],
        vol.Optional("brightness"): vol.All(int, vol.Range(min=0, max=255)),
    }
)

SEND_DEBUG_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("payload"): dict,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lepro Pixel LED from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api = LeproApi(
        hass_config_dir=hass.config.config_dir,
        entry_id=entry.entry_id,
        account=entry.data[CONF_ACCOUNT],
        password=entry.data[CONF_PASSWORD],
        region=entry.data.get(CONF_REGION, "eu"),
    )
    overrides = entry.options.get(CONF_PIXEL_COUNT, {})
    coordinator = LeproCoordinator(api, pixel_overrides=overrides)

    try:
        await coordinator.async_setup()
    except LeproAuthError as e:
        raise ConfigEntryNotReady(f"Lepro auth failed: {e}") from e
    except Exception as e:  # noqa: BLE001
        raise ConfigEntryNotReady(f"Lepro setup failed: {e}") from e

    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["coordinator"].async_shutdown()
        if not hass.data[DOMAIN]:
            for svc in (SERVICE_SET_PIXELS, SERVICE_SEND_DEBUG):
                if hass.services.has_service(DOMAIN, svc):
                    hass.services.async_remove(DOMAIN, svc)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (e.g. pixel overrides)."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent)."""

    def _find_coordinator(device_id: str) -> LeproCoordinator | None:
        for data in hass.data.get(DOMAIN, {}).values():
            coord: LeproCoordinator = data["coordinator"]
            if device_id in coord.devices:
                return coord
        return None

    async def _set_pixels(call: ServiceCall) -> None:
        did = str(call.data["device_id"])
        colors = [tuple(int(c) for c in rgb) for rgb in call.data["colors"]]
        brightness = call.data.get("brightness")
        coord = _find_coordinator(did)
        if coord is None:
            _LOGGER.error("set_pixels: unknown device_id %s", did)
            return
        await coord.async_set_pixels(did, colors, brightness)

    async def _send_debug(call: ServiceCall) -> None:
        did = str(call.data["device_id"])
        payload = call.data["payload"]
        coord = _find_coordinator(did)
        if coord is None:
            _LOGGER.error("send_debug_command: unknown device_id %s", did)
            return
        await coord.api.async_publish(did, payload)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_PIXELS):
        hass.services.async_register(
            DOMAIN, SERVICE_SET_PIXELS, _set_pixels, schema=SET_PIXELS_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_DEBUG):
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_DEBUG, _send_debug, schema=SEND_DEBUG_SCHEMA
        )