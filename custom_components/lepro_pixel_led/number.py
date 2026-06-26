"""Number platform: effect Speed and Sensitivity (pixel devices), referencing the light."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    lights = hass.data[DOMAIN][entry.entry_id]["lights"]
    entities: list[NumberEntity] = []
    for light in lights.values():
        if light.supports_pixels:
            entities.append(LeproSpeedNumber(light))
            entities.append(LeproSensitivityNumber(light))
    async_add_entities(entities)


class _LeproNumberBase(NumberEntity):
    _attr_has_entity_name = True
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, light) -> None:
        self.parent = light
        self._attr_device_info = {"identifiers": {(DOMAIN, light.did)}}

    async def async_added_to_hass(self) -> None:
        self.parent.register_pixel(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class LeproSpeedNumber(_LeproNumberBase):
    _attr_translation_key = "speed"

    def __init__(self, light) -> None:
        super().__init__(light)
        self._attr_unique_id = f"{light.did}_speed"

    @property
    def native_value(self) -> float:
        return float(self.parent.speed)

    async def async_set_native_value(self, value: float) -> None:
        await self.parent.async_apply_speed(int(round(value)))


class LeproSensitivityNumber(_LeproNumberBase):
    _attr_translation_key = "sensitivity"

    def __init__(self, light) -> None:
        super().__init__(light)
        self._attr_unique_id = f"{light.did}_sensitivity"

    @property
    def native_value(self) -> float:
        return float(self.parent.sensitivity)

    async def async_set_native_value(self, value: float) -> None:
        await self.parent.async_apply_sensitivity(int(round(value)))