"""Switch platform for Lepro LED master power overrides."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up power-only switch entities for Lepro devices."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not data or "entities" not in data:
        return

    lights = data.get("entities", [])
    switches = []
    
    for light in lights:
        # Attach only to the parent controller
        if hasattr(light, "_did") and hasattr(light, "state_store"):
            switches.append(LeproPowerSwitch(light))

    if switches:
        async_add_entities(switches)


class LeproPowerSwitch(SwitchEntity):
    """Master Power bypass switch for a Lepro device."""

    def __init__(self, light):
        self._light = light
        self._attr_has_entity_name = True
        self._attr_translation_key = "power"
        self._attr_unique_id = f"{light._did}_power"
        self._attr_device_info = light._attr_device_info

    async def async_added_to_hass(self) -> None:
        self._light.register_pixel(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return bool(self._light.state_store.is_on)

    async def async_turn_on(self, **kwargs) -> None:
        # Use the underlying light's async turn on to ensure state sync
        await self._light.async_turn_on()

    async def async_turn_off(self, **kwargs) -> None:
        # Use the underlying light's async turn off to ensure state sync
        await self._light.async_turn_off()