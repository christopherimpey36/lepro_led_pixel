"""Number platform for Lepro LED speed and sensitivity selectors."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, THEMES, SPECIAL_EFFECT_TO_D60_PREFIX

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up number entities for Lepro LED speeds."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not data or "entities" not in data:
        return

    lights = data.get("entities", [])
    numbers = []
    
    for light in lights:
        # Only attach sliders to the main parent device, not the child pixels
        if not hasattr(light, "_did") or not hasattr(light, "supports_pixels"):
            continue
            
        if light.supports_pixels:
            numbers.append(LeproSpeedNumber(light))
            numbers.append(LeproSensitivityNumber(light))

    if numbers:
        async_add_entities(numbers)


class _LeproNumberBase(NumberEntity):
    _attr_has_entity_name = True
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, light) -> None:
        self._light = light
        self._attr_device_info = light._attr_device_info

    async def async_added_to_hass(self) -> None:
        self._light.register_pixel(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    async def _reapply_current_state(self):
        """Automatically pushes the updated speed/sensitivity to the running effect/theme."""
        current_effect = self._light.state_store.effect
        if current_effect in THEMES:
            await self._light.async_apply_theme(current_effect, self._light.state_store.brightness)
        elif current_effect in SPECIAL_EFFECT_TO_D60_PREFIX:
            await self._light.async_apply_effect(current_effect, self._light.state_store.brightness)


class LeproSpeedNumber(_LeproNumberBase):
    _attr_translation_key = "speed"

    def __init__(self, light) -> None:
        super().__init__(light)
        self._attr_unique_id = f"{light._did}_speed"

    @property
    def native_value(self) -> float:
        return float(getattr(self._light, "_speed", 50))

    async def async_set_native_value(self, value: float) -> None:
        self._light._speed = int(round(value))
        await self._reapply_current_state()
        self.async_write_ha_state()


class LeproSensitivityNumber(_LeproNumberBase):
    _attr_translation_key = "sensitivity"

    def __init__(self, light) -> None:
        super().__init__(light)
        self._attr_unique_id = f"{light._did}_sensitivity"

    @property
    def native_value(self) -> float:
        return float(getattr(self._light, "_sensitivity", 50))

    async def async_set_native_value(self, value: float) -> None:
        self._light._sensitivity = int(round(value))
        await self._reapply_current_state()
        self.async_write_ha_state()