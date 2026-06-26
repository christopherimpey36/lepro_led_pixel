"""The Lepro Pixel LED integration.

One integration, multiple entity platforms (light, number, switch). The
integration setup owns the API connection, fetches the device list, and stores
the connection + raw device list in hass.data. The light platform creates the
entities (which hold per-device state and do the encode/publish work). number
and switch platforms reference those light entities, matching the established
Lepro integration structure. No coordinator.
"""

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

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["light", "number", "switch"]

CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"

SET_PIXELS_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("colors"): [vol.All([vol.Coerce(int)], vol.Length(min=3, max=3))],
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

    try:
        raw_devices = await api.async_setup()
    except LeproAuthError as e:
        raise ConfigEntryNotReady(f"Lepro auth failed: {e}") from e
    except Exception as e:  # noqa: BLE001
        raise ConfigEntryNotReady(f"Lepro setup failed: {e}") from e

    try:
        await api.async_connect()
    except Exception as e:  # noqa: BLE001
        raise ConfigEntryNotReady(f"Lepro MQTT connect failed: {e}") from e

    # Shared store: the light platform fills 'lights' with its entities so the
    # Build the main light entities up front so every platform sees a fully
    # populated 'lights' dict regardless of platform setup order (no retry loop).
    from .light import LeproLight  # local import to avoid circulars at module load

    overrides = entry.options.get(CONF_PIXEL_COUNT, {})
    lights: dict = {}
    for raw in raw_devices:
        did = str(raw["did"])
        lights[did] = LeproLight(api, raw, pixel_override=overrides.get(did))

    store = {
        "api": api,
        "raw_devices": raw_devices,
        "overrides": overrides,
        "lights": lights,   # did -> main LeproLight entity (pre-built)
    }
    hass.data[DOMAIN][entry.entry_id] = store

    # Route inbound MQTT reports to the matching light entity.
    async def _on_message(did: str, data: dict) -> None:
        light = store["lights"].get(did)
        if light is not None:
            light.handle_report(data)

    api.set_message_callback(_on_message)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["api"].async_disconnect()
        if not hass.data[DOMAIN]:
            for svc in (SERVICE_SET_PIXELS, SERVICE_SEND_DEBUG):
                if hass.services.has_service(DOMAIN, svc):
                    hass.services.async_remove(DOMAIN, svc)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    def _find_light(device_id: str):
        for data in hass.data.get(DOMAIN, {}).values():
            light = data["lights"].get(device_id)
            if light is not None:
                return light
        return None

    async def _set_pixels(call: ServiceCall) -> None:
        did = str(call.data["device_id"])
        colors = [tuple(int(c) for c in rgb) for rgb in call.data["colors"]]
        brightness = call.data.get("brightness")
        light = _find_light(did)
        if light is None:
            _LOGGER.error("set_pixels: unknown device_id %s", did)
            return
        await light.async_apply_pixels(colors, brightness)

    async def _send_debug(call: ServiceCall) -> None:
        did = str(call.data["device_id"])
        payload = call.data["payload"]
        for data in hass.data.get(DOMAIN, {}).values():
            if did in data["lights"]:
                await data["api"].async_publish(did, payload)
                return
        _LOGGER.error("send_debug_command: unknown device_id %s", did)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_PIXELS):
        hass.services.async_register(
            DOMAIN, SERVICE_SET_PIXELS, _set_pixels, schema=SET_PIXELS_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_DEBUG):
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_DEBUG, _send_debug, schema=SEND_DEBUG_SCHEMA
        )