"""The Lepro Pixel LED integration."""

from __future__ import annotations

import json
import logging
import random
import time
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    THEMES,
    SERVICE_SET_PIXELS,
    SERVICE_SET_THEME,
    SERVICE_SEND_DEBUG,
    SERVICE_REQUEST_DEBUG,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["light", "number", "switch"]

# --- Validation Schemas -------------------------------------------------------
SET_PIXELS_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("colors"): [vol.All([vol.Coerce(int)], vol.Length(min=3, max=3))],
        vol.Optional("brightness"): vol.All(int, vol.Range(min=0, max=255)),
    }
)

SET_THEME_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Optional("theme_name"): vol.In(list(THEMES.keys())),
        vol.Optional("custom_colors"): [vol.All([vol.Coerce(int)], vol.Length(min=3, max=3))],
        vol.Optional("brightness"): vol.All(int, vol.Range(min=0, max=255)),
    }
)

SEND_DEBUG_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("payload"): dict,
    }
)

REQUEST_DEBUG_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Optional(
            "keys",
            default=["d1", "d2", "d3", "d4", "d5", "d30", "d50", "d52", "d60", "online"],
        ): [cv.string],
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lepro Pixel LED from a config entry."""
    _register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)
        
        # Clean up global service definitions if no entries remain
        if not hass.data.get(DOMAIN):
            for svc in (SERVICE_SET_PIXELS, SERVICE_SET_THEME, SERVICE_SEND_DEBUG, SERVICE_REQUEST_DEBUG):
                if hass.services.has_service(DOMAIN, svc):
                    hass.services.async_remove(DOMAIN, svc)
    return unloaded


def _register_services(hass: HomeAssistant) -> None:
    """Register regional service hooks for dashboard actions and AI agents."""

    def _find_light_entity(device_id: str):
        """Scan across mapped entries to locate the primary light object context-safely."""
        for entry_id in hass.data.get(DOMAIN, {}):
            device_map = hass.data[DOMAIN][entry_id].get("device_map", {})
            if device_id in device_map:
                return device_map[device_id]
        return None

    async def _set_pixels(call: ServiceCall) -> None:
        """Paint individual string pixels granularly via service call arrays."""
        did = str(call.data["device_id"])
        colors = [tuple(int(c) for c in rgb) for rgb in call.data["colors"]]
        brightness = call.data.get("brightness")
        
        light = _find_light_entity(did)
        if light is None:
            _LOGGER.error("set_pixels: Device %s not found on active registry tracks", did)
            return
        await light.async_apply_pixels(colors, brightness)

    async def _set_theme(call: ServiceCall) -> None:
        """Trigger an algorithmic theme palette or custom on-the-fly voice array."""
        did = str(call.data["device_id"])
        theme_name = call.data.get("theme_name")
        custom_colors = call.data.get("custom_colors")
        brightness = call.data.get("brightness")

        light = _find_light_entity(did)
        if light is None:
            _LOGGER.error("set_theme: Device %s not found on active registry tracks", did)
            return

        # Handle on-the-fly generation from voice intents/custom color loops
        if custom_colors:
            colors = [tuple(int(c) for c in rgb) for rgb in custom_colors]
            # Cycle colors evenly across string length
            pixel_array = [colors[i % len(colors)] for i in range(light.pixel_count)]
            await light.async_apply_pixels(pixel_array, brightness)
        elif theme_name:
            await light.async_apply_theme(theme_name, brightness)

    async def _send_debug(call: ServiceCall) -> None:
        """Community tool: inject raw payloads directly into device execution tracks."""
        did = str(call.data["device_id"])
        payload = call.data["payload"]
        
        for entry_id in hass.data.get(DOMAIN, {}):
            store = hass.data[DOMAIN][entry_id]
            if did in store.get("device_map", {}):
                topic = f"le/{did}/prp/set"
                envelope = {
                    "id": random.randint(0, 1000000000),
                    "t": int(time.time()),
                    "d": payload,
                }
                await store["mqtt_client"].publish(topic, json.dumps(envelope))
                return
        _LOGGER.error("send_debug_command: Unknown device_id %s", did)

    async def _request_debug(call: ServiceCall) -> None:
        """Community tool: poll unverified fields from tracking lines directly via get topic."""
        did = str(call.data["device_id"])
        keys = call.data["keys"]
        
        for entry_id in hass.data.get(DOMAIN, {}):
            store = hass.data[DOMAIN][entry_id]
            if did in store.get("device_map", {}):
                topic = f"le/{did}/prp/get"
                payload = json.dumps({"d": keys})
                await store["mqtt_client"].publish(topic, payload)
                return
        _LOGGER.error("request_debug_state: Unknown device_id %s", did)

    # Core Action API registration hooks
    if not hass.services.has_service(DOMAIN, SERVICE_SET_PIXELS):
        hass.services.async_register(DOMAIN, SERVICE_SET_PIXELS, _set_pixels, schema=SET_PIXELS_SCHEMA)
        
    if not hass.services.has_service(DOMAIN, SERVICE_SET_THEME):
        hass.services.async_register(DOMAIN, SERVICE_SET_THEME, _set_theme, schema=SET_THEME_SCHEMA)

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_DEBUG):
        hass.services.async_register(DOMAIN, SERVICE_SEND_DEBUG, _send_debug, schema=SEND_DEBUG_SCHEMA)
        
    if not hass.services.has_service(DOMAIN, SERVICE_REQUEST_DEBUG):
        hass.services.async_register(DOMAIN, SERVICE_REQUEST_DEBUG, _request_debug, schema=REQUEST_DEBUG_SCHEMA)