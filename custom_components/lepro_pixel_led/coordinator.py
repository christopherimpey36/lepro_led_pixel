"""Coordinator: ties the API connection to per-device state and protocols.

Responsibilities:
  * own the LeproApi connection
  * for each device, pick the right protocol (d50 / d5) from the model registry
  * receive inbound device reports, decode them via the protocol into state
  * hold current state per device and notify subscribed entities
  * provide a typed write surface entities call (set pixels / rgb / white / power)

Entities never touch the API or wire format directly; they go through here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .api import LeproApi
from .const import (
    CONF_PIXEL_COUNT,
    DEFAULT_MODEL,
    MODELS,
    SPECIAL_EFFECT_TO_D60_PREFIX,
)
from .protocols.base import LeproProtocol, LeproState
from .protocols.d5 import D5Protocol
from .protocols.d50 import D50Protocol

_LOGGER = logging.getLogger(__name__)

# Fields we ask the device to report.
STATE_KEYS = ["d1", "d2", "d3", "d4", "d5", "d50", "d52", "d60", "online"]


def _resolve_model(series: str) -> dict:
    series_u = (series or "").upper()
    for key, spec in MODELS.items():
        if key.upper() in series_u:
            return spec
    return DEFAULT_MODEL


def _make_protocol(spec: dict, pixel_count: int) -> LeproProtocol:
    if spec["protocol"] == "d50":
        return D50Protocol(default_pixels=pixel_count)
    return D5Protocol()


class LeproDevice:
    """Per-device state holder + protocol binding."""

    def __init__(self, raw: dict, pixel_override: int | None = None) -> None:
        self.raw = raw
        self.did = str(raw["did"])
        self.name = raw.get("name", f"Lepro {self.did}")
        self.series = raw.get("series", "") or ""
        self.fw = raw.get("fwVersion", "Unknown")
        self.hw = raw.get("hwVersion", "Unknown")

        self.spec = _resolve_model(self.series)
        # pixel count: explicit override > model default > detected later
        self.pixel_count = pixel_override or self.spec.get("pixels", 1) or 1
        self.protocol = _make_protocol(self.spec, self.pixel_count)

        self.state = LeproState()
        # seed from the device list payload if it carried state
        seeded = self.protocol.decode(raw)
        self._merge(seeded)

        self._listeners: list[Callable[[], None]] = []

    @property
    def supports_pixels(self) -> bool:
        return self.protocol.supports_pixels

    @property
    def supports_white(self) -> bool:
        return self.protocol.supports_white

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    def notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("listener error for %s", self.did)

    def apply_report(self, data: dict) -> None:
        decoded = self.protocol.decode(data)
        self._merge(decoded)
        # auto-detect pixel count from a reported pixel list, if longer/known
        if decoded.pixel_count and decoded.pixel_count != self.pixel_count:
            # only grow to detected count for pixel devices; keep override if set
            if self.supports_pixels:
                self.pixel_count = decoded.pixel_count
                self.protocol = _make_protocol(self.spec, self.pixel_count)
        self.notify()

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


class LeproCoordinator:
    """Owns the connection and all devices for one config entry."""

    def __init__(
        self,
        api: LeproApi,
        pixel_overrides: dict[str, int] | None = None,
    ) -> None:
        self.api = api
        self.devices: dict[str, LeproDevice] = {}
        self._pixel_overrides = pixel_overrides or {}
        api.set_message_callback(self._on_message)

    async def async_setup(self) -> None:
        raw_devices = await self.api.async_setup()
        for raw in raw_devices:
            did = str(raw["did"])
            override = self._pixel_overrides.get(did)
            self.devices[did] = LeproDevice(raw, pixel_override=override)
        await self.api.async_connect()
        for did in self.devices:
            await self.api.async_subscribe_device(did)
            await self.api.async_request_state(did, STATE_KEYS)

    async def async_shutdown(self) -> None:
        await self.api.async_disconnect()

    async def _on_message(self, did: str, data: dict) -> None:
        dev = self.devices.get(did)
        if dev is None:
            return
        dev.apply_report(data)

    # --- write surface used by entities --------------------------------------

    async def async_set_power(self, did: str, on: bool) -> None:
        dev = self.devices[did]
        await self.api.async_publish(did, dev.protocol.encode_power(on))
        dev.state.is_on = on
        dev.notify()

    async def async_set_pixels(
        self, did: str, pixels: list[tuple[int, int, int]], brightness: int | None = None
    ) -> None:
        dev = self.devices[did]
        payload = dev.protocol.encode_pixels(pixels, brightness)
        await self.api.async_publish(did, payload)
        dev.state.pixels = pixels
        dev.state.is_on = True
        if brightness is not None:
            dev.state.brightness = brightness
        dev.notify()

    async def async_set_rgb(
        self, did: str, rgb: tuple[int, int, int], brightness: int | None = None
    ) -> None:
        dev = self.devices[did]
        payload = dev.protocol.encode_rgb(rgb, brightness)
        await self.api.async_publish(did, payload)
        dev.state.pixels = [rgb]
        dev.state.is_on = True
        dev.state.is_white_mode = False
        if brightness is not None:
            dev.state.brightness = brightness
        dev.notify()

    async def async_set_white(
        self, did: str, kelvin: int, brightness: int | None = None
    ) -> None:
        dev = self.devices[did]
        payload = dev.protocol.encode_white(kelvin, brightness)
        await self.api.async_publish(did, payload)
        dev.state.is_white_mode = True
        dev.state.color_temp_kelvin = kelvin
        dev.state.is_on = True
        if brightness is not None:
            dev.state.brightness = brightness
        dev.notify()

    async def async_set_effect(
        self, did: str, effect: str, brightness: int | None = None
    ) -> None:
        """Firmware effects via d60 (pixel devices)."""
        prefix = SPECIAL_EFFECT_TO_D60_PREFIX.get(effect)
        if not prefix:
            _LOGGER.warning("unknown effect %s for %s", effect, did)
            return
        dev = self.devices[did]
        # sensitivity defaults to 50% -> 0x32; d60 = prefix + sens_hex + 0000
        sens_hex = f"{round(0.5 * 0x63):02X}"
        payload = {"d1": 1, "d2": 3, "d60": f"{prefix}{sens_hex}0000"}
        if brightness is not None:
            payload["d52"] = max(0, min(1000, round(brightness / 255 * 1000)))
        await self.api.async_publish(did, payload)
        dev.state.effect = effect
        dev.state.is_on = True
        dev.notify()