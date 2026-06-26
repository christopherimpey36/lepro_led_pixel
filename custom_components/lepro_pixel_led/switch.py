"""Switch platform: master power for all devices, referencing the light."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities(LeproPowerSwitch(light) for light in lights.values())


class LeproPowerSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "power"

    def __init__(self, light) -> None:
        self.parent = light
        self._attr_unique_id = f"{light.did}_power"
        self._attr_device_info = {"identifiers": {(DOMAIN, light.did)}}

    async def async_added_to_hass(self) -> None:
        self.parent.register_pixel(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self.parent.state.is_on

    async def async_turn_on(self, **kwargs) -> None:
        await self.parent.async_apply_power(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.parent.async_apply_power(False)