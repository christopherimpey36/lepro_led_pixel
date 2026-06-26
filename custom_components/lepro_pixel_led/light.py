"""Light platform for Lepro Pixel LED.

Entity model:
  * d50 pixel devices (ZB1/E1/N1):
      - one MAIN light: on/off, whole-string fill colour, brightness, effects
      - N PIXEL lights: per-bulb colour; each change re-sends the full d50
  * d5 single-colour devices (E27):
      - one light with RGB + colour-temperature (warm<->cool), matching the app
"""

from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EFFECT_NONE, SPECIAL_EFFECT_TO_D60_PREFIX
from .coordinator import LeproCoordinator, LeproDevice

EFFECT_LIST = [EFFECT_NONE, *SPECIAL_EFFECT_TO_D60_PREFIX.keys()]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LeproCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[LightEntity] = []
    for dev in coordinator.devices.values():
        if dev.supports_pixels:
            entities.append(LeproMainLight(coordinator, dev))
            for idx in range(dev.pixel_count):
                entities.append(LeproPixelLight(coordinator, dev, idx))
        else:
            entities.append(LeproBulbLight(coordinator, dev))

    async_add_entities(entities)


class _LeproBase(LightEntity):
    """Shared wiring: device info + listener registration."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LeproCoordinator, dev: LeproDevice) -> None:
        self.coordinator = coordinator
        self.dev = dev
        self._attr_device_info = {
            "identifiers": {(DOMAIN, dev.did)},
            "name": dev.name,
            "manufacturer": "Lepro",
            "model": dev.series or "Lepro LED",
            "serial_number": dev.did,
            "sw_version": dev.fw,
            "hw_version": dev.hw,
        }

    async def async_added_to_hass(self) -> None:
        self._unsub = self.dev.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if getattr(self, "_unsub", None):
            self._unsub()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self.dev.state.is_on

    @property
    def brightness(self) -> int | None:
        return self.dev.state.brightness


class LeproMainLight(_LeproBase):
    """Whole-string light for a pixel device: fill colour, brightness, effects."""

    _attr_translation_key = "string"
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = EFFECT_LIST

    def __init__(self, coordinator: LeproCoordinator, dev: LeproDevice) -> None:
        super().__init__(coordinator, dev)
        self._attr_unique_id = f"{dev.did}_string"

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        px = self.dev.state.pixels
        return px[0] if px else None

    @property
    def effect(self) -> str | None:
        return self.dev.state.effect or EFFECT_NONE

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.dev.state.brightness)

        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] != EFFECT_NONE:
            await self.coordinator.async_set_effect(
                self.dev.did, kwargs[ATTR_EFFECT], brightness
            )
            return

        if ATTR_RGB_COLOR in kwargs:
            # fill: every pixel to the chosen colour
            rgb = tuple(int(c) for c in kwargs[ATTR_RGB_COLOR])
            pixels = [rgb] * self.dev.pixel_count
            await self.coordinator.async_set_pixels(self.dev.did, pixels, brightness)
            return

        if ATTR_BRIGHTNESS in kwargs:
            # brightness-only: re-send current pixels at new brightness
            pixels = self.dev.state.pixels or [(255, 255, 255)] * self.dev.pixel_count
            if len(pixels) != self.dev.pixel_count:
                pixels = (pixels + [pixels[-1]] * self.dev.pixel_count)[: self.dev.pixel_count]
            await self.coordinator.async_set_pixels(self.dev.did, pixels, brightness)
            return

        # bare on
        await self.coordinator.async_set_power(self.dev.did, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_power(self.dev.did, False)


class LeproPixelLight(_LeproBase):
    """A single addressable bulb. Each change re-sends the full d50."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(
        self, coordinator: LeproCoordinator, dev: LeproDevice, index: int
    ) -> None:
        super().__init__(coordinator, dev)
        self.index = index
        n = str(index + 1).rjust(2, "0")
        self._attr_translation_key = "pixel"
        self._attr_translation_placeholders = {"index": n}
        self._attr_unique_id = f"{dev.did}_pixel_{n}"

    def _current_pixels(self) -> list[tuple[int, int, int]]:
        px = list(self.dev.state.pixels)
        n = self.dev.pixel_count
        if len(px) < n:
            px = px + [(255, 255, 255)] * (n - len(px))
        elif len(px) > n:
            px = px[:n]
        return px

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        px = self._current_pixels()
        return px[self.index] if self.index < len(px) else (255, 255, 255)

    async def async_turn_on(self, **kwargs) -> None:
        pixels = self._current_pixels()
        if ATTR_RGB_COLOR in kwargs:
            pixels[self.index] = tuple(int(c) for c in kwargs[ATTR_RGB_COLOR])
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.dev.state.brightness)
        await self.coordinator.async_set_pixels(self.dev.did, pixels, brightness)

    async def async_turn_off(self, **kwargs) -> None:
        # turning a pixel "off" = set it black; the string stays on
        pixels = self._current_pixels()
        pixels[self.index] = (0, 0, 0)
        await self.coordinator.async_set_pixels(self.dev.did, pixels)


class LeproBulbLight(_LeproBase):
    """Single-colour bulb (E27): RGB + warm/cool colour temperature."""

    _attr_translation_key = "bulb"
    _attr_supported_color_modes = {ColorMode.RGB, ColorMode.COLOR_TEMP}
    _attr_min_color_temp_kelvin = 2700
    _attr_max_color_temp_kelvin = 6500

    def __init__(self, coordinator: LeproCoordinator, dev: LeproDevice) -> None:
        super().__init__(coordinator, dev)
        self._attr_unique_id = f"{dev.did}_bulb"

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.COLOR_TEMP if self.dev.state.is_white_mode else ColorMode.RGB

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        px = self.dev.state.pixels
        return px[0] if px else None

    @property
    def color_temp_kelvin(self) -> int | None:
        return self.dev.state.color_temp_kelvin

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.dev.state.brightness)

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self.coordinator.async_set_white(
                self.dev.did, int(kwargs[ATTR_COLOR_TEMP_KELVIN]), brightness
            )
            return

        if ATTR_RGB_COLOR in kwargs:
            rgb = tuple(int(c) for c in kwargs[ATTR_RGB_COLOR])
            await self.coordinator.async_set_rgb(self.dev.did, rgb, brightness)
            return

        if ATTR_BRIGHTNESS in kwargs:
            if self.dev.state.is_white_mode and self.dev.state.color_temp_kelvin:
                await self.coordinator.async_set_white(
                    self.dev.did, self.dev.state.color_temp_kelvin, brightness
                )
            else:
                rgb = self.rgb_color or (255, 255, 255)
                await self.coordinator.async_set_rgb(self.dev.did, rgb, brightness)
            return

        await self.coordinator.async_set_power(self.dev.did, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_power(self.dev.did, False)