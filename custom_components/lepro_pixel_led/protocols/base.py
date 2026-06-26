"""Abstract protocol interface for Lepro device families.

Each Lepro hardware family speaks a different wire dialect over MQTT. A
``LeproProtocol`` subclass encapsulates ONE dialect: how to turn a desired
state (colours, brightness, temperature, power) into the ``d``-field payload
the device accepts, and how to read a device report back into state.

Protocols are pure: no Home Assistant imports, no I/O. They take and return
plain Python data so they can be unit-tested in isolation. The light entity
layer is responsible for actually publishing the payloads this produces.

Conventions
-----------
* Colours are (r, g, b) tuples, each 0-255.
* Brightness is 0-255 (HA's scale). Protocols convert to device scale.
* Colour temperature is in Kelvin (2700-6500). Protocols convert to device scale.
* A "payload" is the dict that goes in the MQTT message's ``d`` field.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LeproState:
    """Decoded device state, family-agnostic."""

    is_on: bool | None = None
    # For pixel devices: one (r,g,b) per physical pixel, in order.
    # For single-colour devices: a one-element list.
    pixels: list[tuple[int, int, int]] = field(default_factory=list)
    brightness: int | None = None          # 0-255
    color_temp_kelvin: int | None = None   # set when in white/CCT mode
    is_white_mode: bool = False
    pixel_count: int | None = None         # detected count, if known
    effect: str | None = None


class LeproProtocol(ABC):
    """Base class for a Lepro wire dialect."""

    #: Whether this family supports independent per-pixel colour.
    supports_pixels: bool = False

    #: Whether this family supports a white / colour-temperature mode.
    supports_white: bool = False

    @abstractmethod
    def encode_power(self, on: bool) -> dict:
        """Return the payload to switch the device on or off."""

    @abstractmethod
    def decode(self, data: dict) -> LeproState:
        """Read an inbound device payload (the ``d`` dict) into a LeproState.

        Implementations must ignore unknown fields (e.g. ``d30``, an
        ack/tell-back token the device emits on every change and which carries
        no controllable state).
        """

    # The following are optional per family; defaults raise so callers know
    # the family does not support the operation.

    def encode_pixels(
        self,
        pixels: list[tuple[int, int, int]],
        brightness: int | None = None,
    ) -> dict:
        """Return the payload to set each pixel's colour (pixel families only)."""
        raise NotImplementedError(f"{type(self).__name__} does not support pixels")

    def encode_rgb(
        self,
        rgb: tuple[int, int, int],
        brightness: int | None = None,
    ) -> dict:
        """Return the payload to set a single RGB colour for the whole device."""
        raise NotImplementedError(f"{type(self).__name__} does not support rgb")

    def encode_white(
        self,
        color_temp_kelvin: int,
        brightness: int | None = None,
    ) -> dict:
        """Return the payload to set white / colour-temperature mode."""
        raise NotImplementedError(f"{type(self).__name__} does not support white")