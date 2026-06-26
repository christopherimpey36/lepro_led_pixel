"""Light platform for Lepro Pixel LED.

The main light entity (LeproLight) is the stateful core for a device: it holds
the protocol, current state, speed/sensitivity, and does all encode/publish
work. Per-bulb pixel entities and the number/switch platforms reference the
main light. This matches the established Lepro integration structure (state in
the light entity, not a separate coordinator/device object).
"""

from __future__ import annotations

import logging

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

from .api import LeproApi
from .const import (
    DEFAULT_MODEL,
    DOMAIN,
    EFFECT_NONE,
    MODELS,
    SPECIAL_EFFECT_TO_D60_PREFIX,
)
from .protocols.base import LeproState
from .protocols.d5 import D5Protocol
from .protocols.d50 import D50Protocol

_LOGGER = logging.getLogger(__name__)

EFFECT_LIST = [EFFECT_NONE, *SPECIAL_EFFECT_TO_D60_PREFIX.keys()]
STATE_KEYS = ["d1", "d2", "d3", "d4", "d5", "d50", "d52", "d60", "online"]


def _resolve_model(series: str) -> dict:
    series_u = (series or "").upper()
    for key, spec in MODELS.items():
        if key.upper() in series_u:
            return spec
    return DEFAULT_MODEL


def _make_protocol(spec: dict, pixel_count: int):
    if spec["protocol"] == "d50":
        return D50Protocol(default_pixels=pixel_count)
    return D5Protocol()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    api: LeproApi = store["api"]
    lights: dict = store["lights"]  # pre-built in __init__, did -> LeproLight

    entities: list[LightEntity] = []
    for light in lights.values():
        entities.append(light)
        if light.supports_pixels:
            for idx in range(light.pixel_count):
                entities.append(LeproPixelLight(light, idx))

    async_add_entities(entities)

    # now that lights exist, subscribe and ask each device for its current state
    for did in lights:
        await api.async_subscribe_device(did)
        await api.async_request_state(did, STATE_KEYS)


class LeproLight(LightEntity):
    """Main, stateful light entity for one Lepro device."""

    _attr_has_entity_name = True

    def __init__(self, api: LeproApi, raw: dict, pixel_override: int | None = None) -> None:
        self.api = api
        self.did = str(raw["did"])
        self.name_raw = raw.get("name", f"Lepro {self.did}")
        self.series = raw.get("series", "") or ""

        self.spec = _resolve_model(self.series)
        self.pixel_count = pixel_override or self.spec.get("pixels", 1) or 1
        self.protocol = _make_protocol(self.spec, self.pixel_count)

        self.state = LeproState()
        self.speed = 50
        self.sensitivity = 50
        self._merge(self.protocol.decode(raw))

        self._pixel_listeners: list = []

        self._attr_unique_id = f"{self.did}_string" if self.supports_pixels else f"{self.did}_bulb"
        self._attr_translation_key = "string" if self.supports_pixels else "bulb"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self.did)},
            "name": self.name_raw,
            "manufacturer": "Lepro",
            "model": self.series or "Lepro LED",
            "serial_number": self.did,
            "sw_version": raw.get("fwVersion", "Unknown"),
            "hw_version": raw.get("hwVersion", "Unknown"),
        }

        if self.supports_pixels:
            self._attr_color_mode = ColorMode.RGB
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_supported_features = LightEntityFeature.EFFECT
            self._attr_effect_list = EFFECT_LIST
        else:
            self._attr_supported_color_modes = {ColorMode.RGB, ColorMode.COLOR_TEMP}
            self._attr_min_color_temp_kelvin = 2700
            self._attr_max_color_temp_kelvin = 6500

    # --- capabilities ---------------------------------------------------------

    @property
    def supports_pixels(self) -> bool:
        return self.protocol.supports_pixels

    @property
    def supports_white(self) -> bool:
        return self.protocol.supports_white

    # --- state plumbing -------------------------------------------------------

    def register_pixel(self, cb) -> None:
        self._pixel_listeners.append(cb)

    def _notify_pixels(self) -> None:
        for cb in list(self._pixel_listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass

    def handle_report(self, data: dict) -> None:
        """Called by the integration's MQTT message handler."""
        decoded = self.protocol.decode(data)
        self._merge(decoded)
        if (
            decoded.pixel_count
            and decoded.pixel_count != self.pixel_count
            and self.supports_pixels
        ):
            self.pixel_count = decoded.pixel_count
            self.protocol = _make_protocol(self.spec, self.pixel_count)
        self.async_write_ha_state()
        self._notify_pixels()

    def _merge(self, new: LeproState) -> None:
        s = self.state
        if new.is_on is not None:
            s.is_on = new.is_on
        if new.pixels:
            s.pixels = new.pixels
        if new.brightness is not None:
            s.brightness = new.brightness
        if new.color_temp_kelvin is not None:
            s.color_temp_kelvin = new.color_temp_kelvin
        s.is_white_mode = new.is_white_mode
        if new.pixel_count is not None:
            s.pixel_count = new.pixel_count
        if new.effect is not None:
            s.effect = new.effect

    # --- HA light properties --------------------------------------------------

    @property
    def is_on(self) -> bool | None:
        return self.state.is_on

    @property
    def brightness(self) -> int | None:
        return self.state.brightness

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self.state.pixels[0] if self.state.pixels else None

    @property
    def color_temp_kelvin(self) -> int | None:
        return self.state.color_temp_kelvin

    @property
    def color_mode(self) -> ColorMode:
        if self.supports_pixels:
            return ColorMode.RGB
        return ColorMode.COLOR_TEMP if self.state.is_white_mode else ColorMode.RGB

    @property
    def effect(self) -> str | None:
        if not self.supports_pixels:
            return None
        return self.state.effect or EFFECT_NONE

    # --- turn on/off ----------------------------------------------------------

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.state.brightness)

        if self.supports_pixels:
            if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] != EFFECT_NONE:
                await self.async_apply_effect(kwargs[ATTR_EFFECT], brightness)
                return
            if ATTR_RGB_COLOR in kwargs:
                rgb = tuple(int(c) for c in kwargs[ATTR_RGB_COLOR])
                await self.async_apply_pixels([rgb] * self.pixel_count, brightness)
                return
            if ATTR_BRIGHTNESS in kwargs:
                pixels = self.state.pixels or [(255, 255, 255)] * self.pixel_count
                if len(pixels) != self.pixel_count:
                    pixels = (pixels + [pixels[-1]] * self.pixel_count)[: self.pixel_count]
                await self.async_apply_pixels(pixels, brightness)
                return
            await self.async_apply_power(True)
            return

        # bulb (d5)
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self.async_apply_white(int(kwargs[ATTR_COLOR_TEMP_KELVIN]), brightness)
            return
        if ATTR_RGB_COLOR in kwargs:
            await self.async_apply_rgb(tuple(int(c) for c in kwargs[ATTR_RGB_COLOR]), brightness)
            return
        if ATTR_BRIGHTNESS in kwargs:
            if self.state.is_white_mode and self.state.color_temp_kelvin:
                await self.async_apply_white(self.state.color_temp_kelvin, brightness)
            else:
                await self.async_apply_rgb(self.rgb_color or (255, 255, 255), brightness)
            return
        await self.async_apply_power(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.async_apply_power(False)

    # --- apply methods (also called by pixel/number/switch/services) ----------

    async def async_apply_power(self, on: bool) -> None:
        await self.api.async_publish(self.did, self.protocol.encode_power(on))
        self.state.is_on = on
        self.async_write_ha_state()
        self._notify_pixels()

    async def async_apply_pixels(self, pixels, brightness=None) -> None:
        payload = self.protocol.encode_pixels(pixels, brightness)
        await self.api.async_publish(self.did, payload)
        self.state.pixels = pixels
        self.state.is_on = True
        if brightness is not None:
            self.state.brightness = brightness
        self.async_write_ha_state()
        self._notify_pixels()

    async def async_apply_rgb(self, rgb, brightness=None) -> None:
        payload = self.protocol.encode_rgb(rgb, brightness)
        await self.api.async_publish(self.did, payload)
        self.state.pixels = [rgb]
        self.state.is_on = True
        self.state.is_white_mode = False
        if brightness is not None:
            self.state.brightness = brightness
        self.async_write_ha_state()

    async def async_apply_white(self, kelvin, brightness=None) -> None:
        payload = self.protocol.encode_white(kelvin, brightness)
        await self.api.async_publish(self.did, payload)
        self.state.is_white_mode = True
        self.state.color_temp_kelvin = kelvin
        self.state.is_on = True
        if brightness is not None:
            self.state.brightness = brightness
        self.async_write_ha_state()

    async def async_apply_effect(self, effect, brightness=None) -> None:
        prefix = SPECIAL_EFFECT_TO_D60_PREFIX.get(effect)
        if not prefix:
            _LOGGER.warning("unknown effect %s for %s", effect, self.did)
            return
        hex_val = max(0, min(0x63, round(self.sensitivity / 100 * 0x63)))
        payload = {"d1": 1, "d2": 3, "d60": f"{prefix}{hex_val:02X}0000"}
        if brightness is not None:
            payload["d52"] = max(0, min(1000, round(brightness / 255 * 1000)))
        await self.api.async_publish(self.did, payload)
        self.state.effect = effect
        self.state.is_on = True
        self.async_write_ha_state()

    async def async_apply_speed(self, speed: int) -> None:
        self.speed = max(0, min(100, int(speed)))
        if self.state.effect in SPECIAL_EFFECT_TO_D60_PREFIX:
            await self.async_apply_effect(self.state.effect, self.state.brightness)

    async def async_apply_sensitivity(self, sensitivity: int) -> None:
        self.sensitivity = max(0, min(100, int(sensitivity)))
        if self.state.effect in SPECIAL_EFFECT_TO_D60_PREFIX:
            await self.async_apply_effect(self.state.effect, self.state.brightness)


class LeproPixelLight(LightEntity):
    """A single addressable bulb, referencing the main light. Re-sends full d50."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(self, parent: LeproLight, index: int) -> None:
        self.parent = parent
        self.index = index
        n = str(index + 1).rjust(2, "0")
        self._attr_translation_key = "pixel"
        self._attr_translation_placeholders = {"index": n}
        self._attr_unique_id = f"{parent.did}_pixel_{n}"
        self._attr_device_info = {"identifiers": {(DOMAIN, parent.did)}}

    async def async_added_to_hass(self) -> None:
        self.parent.register_pixel(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    def _current_pixels(self):
        px = list(self.parent.state.pixels)
        n = self.parent.pixel_count
        if len(px) < n:
            px = px + [(255, 255, 255)] * (n - len(px))
        elif len(px) > n:
            px = px[:n]
        return px

    @property
    def is_on(self) -> bool | None:
        return self.parent.state.is_on

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        px = self._current_pixels()
        return px[self.index] if self.index < len(px) else (255, 255, 255)

    async def async_turn_on(self, **kwargs) -> None:
        pixels = self._current_pixels()
        if ATTR_RGB_COLOR in kwargs:
            pixels[self.index] = tuple(int(c) for c in kwargs[ATTR_RGB_COLOR])
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.parent.state.brightness)
        await self.parent.async_apply_pixels(pixels, brightness)

    async def async_turn_off(self, **kwargs) -> None:
        pixels = self._current_pixels()
        pixels[self.index] = (0, 0, 0)
        await self.parent.async_apply_pixels(pixels)