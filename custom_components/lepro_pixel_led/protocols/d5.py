"""d5 protocol: Lepro single-colour bulbs (E27 family).

Confirmed from live E27 captures.

RGB mode (d2=1):
    d5 = HHHHSSSSVVVV  (each 4 hex)
        H = hue in degrees, 0-360   (e.g. 0x0155 = 341)
        S = saturation, 0-1000
        V = value/brightness, 0-1000   <-- brightness lives here
    A brightness-only change keeps H and S, moves V (proven: 019A -> 03E8).

White / CCT mode (d2=0):
    d3 = brightness, 0-1000
    d4 = colour temperature, 0-1000  (0 = 2700K warm, 1000 = 6500K cool)

d30 appears on every report; it is an ack/tell-back token with no controllable
state and is ignored. Writes do not include it.
"""

from __future__ import annotations

import colorsys

from .base import LeproProtocol, LeproState

_KELVIN_MIN = 2700
_KELVIN_MAX = 6500


class D5Protocol(LeproProtocol):
    supports_pixels = False
    supports_white = True

    def encode_power(self, on: bool) -> dict:
        return {"d1": 1 if on else 0}

    # --- RGB ------------------------------------------------------------------

    def encode_rgb(
        self,
        rgb: tuple[int, int, int],
        brightness: int | None = None,
    ) -> dict:
        r, g, b = (max(0, min(255, int(c))) for c in rgb)
        h, s, _v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        hue_deg = int(round(h * 360)) % 360
        sat = int(round(s * 1000))
        if brightness is None:
            val = 1000
        else:
            val = max(0, min(1000, round(brightness / 255 * 1000)))
        d5 = f"{hue_deg:04X}{sat:04X}{val:04X}"
        return {"d1": 1, "d2": 1, "d5": d5}

    # --- White / CCT ----------------------------------------------------------

    def encode_white(
        self,
        color_temp_kelvin: int,
        brightness: int | None = None,
    ) -> dict:
        d4 = self._kelvin_to_d4(color_temp_kelvin)
        d3 = 1000 if brightness is None else max(0, min(1000, round(brightness / 255 * 1000)))
        return {"d1": 1, "d2": 0, "d3": d3, "d4": d4}

    # --- decoding -------------------------------------------------------------

    def decode(self, data: dict) -> LeproState:
        state = LeproState()
        if "d1" in data:
            state.is_on = bool(data["d1"])

        mode = data.get("d2")
        if mode == 0:
            # white / CCT
            state.is_white_mode = True
            if "d4" in data:
                state.color_temp_kelvin = self._d4_to_kelvin(int(data["d4"]))
            if "d3" in data:
                state.brightness = max(0, min(255, round(int(data["d3"]) / 1000 * 255)))
        elif mode == 1 or "d5" in data:
            d5 = data.get("d5")
            if isinstance(d5, str) and len(d5) >= 12:
                hue = int(d5[0:4], 16) % 360
                sat = int(d5[4:8], 16) / 1000.0
                val = int(d5[8:12], 16)
                # reconstruct display colour at full value; brightness tracked separately
                r, g, b = colorsys.hsv_to_rgb(hue / 360.0, max(0.0, min(1.0, sat)), 1.0)
                state.pixels = [(round(r * 255), round(g * 255), round(b * 255))]
                state.brightness = max(0, min(255, round(val / 1000 * 255)))
                state.is_white_mode = False
        return state

    # --- helpers --------------------------------------------------------------

    @staticmethod
    def _kelvin_to_d4(kelvin: int) -> int:
        kelvin = max(_KELVIN_MIN, min(_KELVIN_MAX, int(kelvin)))
        return round((kelvin - _KELVIN_MIN) * 1000 / (_KELVIN_MAX - _KELVIN_MIN))

    @staticmethod
    def _d4_to_kelvin(d4: int) -> int:
        d4 = max(0, min(1000, int(d4)))
        return round(_KELVIN_MIN + d4 * (_KELVIN_MAX - _KELVIN_MIN) / 1000)