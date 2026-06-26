"""d50 protocol: Lepro RGB+IC addressable strings (ZB1 family).

Confirmed from live ZB1 captures. The per-pixel static format is::

    N01:P1000{N}{colours}F21000{N}{lengths}U3V3000640000E1;

where:
    N        bulb/group count as lowercase hex (15 -> 'f', 30 -> '1e')
    colours  N concatenated RRGGBB (uppercase)
    lengths  N concatenated 4-hex run-lengths (0001 each = one pixel per group)
    tail     U3V3000640000E1  (solid / effect-none)

The device also emits run-length-grouped reports (consecutive same-colour
pixels collapsed into one group with a longer length) and richer effect
strings (breath/gradient/music, containing tokens like U705/X6/R3/M2S2 and an
``N02:`` dual-block form). v1 decodes the static/grouped colour form for state;
effect-string decoding is best-effort and falls back gracefully.

E1 and N1 are the same RGB+IC family and are expected to share this protocol,
but have not yet been captured. They reuse this class until a capture proves a
difference.
"""

from __future__ import annotations

import re

from .base import LeproProtocol, LeproState

_TAIL_SOLID = "U3V3000640000E1"
_HEADER = "N01:P1000"
_SEP = "F21000"


class D50Protocol(LeproProtocol):
    supports_pixels = True
    supports_white = False  # white handled by app's "warm white" tab; v1 = RGB pixels

    def __init__(self, default_pixels: int = 15):
        self.default_pixels = default_pixels

    # --- encoding -------------------------------------------------------------

    def encode_power(self, on: bool) -> dict:
        return {"d1": 1 if on else 0}

    def encode_pixels(
        self,
        pixels: list[tuple[int, int, int]],
        brightness: int | None = None,
    ) -> dict:
        """Build a per-pixel static d50 write.

        Every pixel is emitted as its own group (length 0001), which the device
        accepts directly (proven on ZB1). brightness maps to d52 (0-1000).
        """
        if not pixels:
            raise ValueError("encode_pixels requires at least one pixel")
        d50 = self.build_d50(pixels)
        payload: dict = {"d1": 1, "d2": 2, "d50": d50}
        if brightness is not None:
            payload["d52"] = self._bri_to_device(brightness)
        else:
            payload["d52"] = 1000
        return payload

    @staticmethod
    def build_d50(pixels: list[tuple[int, int, int]]) -> str:
        """Pure d50 string builder (no HA, fully testable)."""
        n = len(pixels)
        n_hex = format(n, "x")
        colours = "".join(f"{r:02X}{g:02X}{b:02X}" for (r, g, b) in pixels)
        lengths = "0001" * n
        return f"{_HEADER}{n_hex}{colours}{_SEP}{n_hex}{lengths}{_TAIL_SOLID};"

    @staticmethod
    def _bri_to_device(brightness: int) -> int:
        return max(0, min(1000, round(brightness / 255 * 1000)))

    @staticmethod
    def _bri_from_device(value: int) -> int:
        return max(0, min(255, round(value / 1000 * 255)))

    # --- decoding -------------------------------------------------------------

    def decode(self, data: dict) -> LeproState:
        state = LeproState()
        if "d1" in data:
            state.is_on = bool(data["d1"])
        if "d52" in data:
            state.brightness = self._bri_from_device(int(data["d52"]))

        d50 = data.get("d50")
        if isinstance(d50, str):
            pixels = self._decode_d50_colours(d50)
            if pixels:
                state.pixels = pixels
                state.pixel_count = len(pixels)
        return state

    @classmethod
    def _decode_d50_colours(cls, d50: str) -> list[tuple[int, int, int]]:
        """Extract the per-pixel colour list from a reported d50.

        Handles the single-block ``N01:`` form with the
        P1000{N}{colours}F21000{N}{lengths} layout, expanding run-lengths.
        Multi-block (``N02:``) and effect-only strings return [] (best-effort).
        """
        try:
            p = d50.find("P1000")
            sep = d50.find(_SEP, p) if p != -1 else -1
            if p == -1 or sep == -1:
                return []

            block = d50[p + len("P1000"):sep]
            # count is leading hex; determine its width by checking the colour
            # body that follows is a multiple of 6 per group.
            n, k = cls._read_count(block)
            if n is None:
                return []
            colours_hex = block[k:k + 6 * n]
            if len(colours_hex) < 6 * n:
                return []
            colours = [
                (
                    int(colours_hex[i * 6:i * 6 + 2], 16),
                    int(colours_hex[i * 6 + 2:i * 6 + 4], 16),
                    int(colours_hex[i * 6 + 4:i * 6 + 6], 16),
                )
                for i in range(n)
            ]

            # lengths follow the separator: same count, then n*4 hex
            after = d50[sep + len(_SEP):]
            n2, k2 = cls._read_count(after)
            lengths = []
            if n2 == n:
                lh = after[k2:k2 + 4 * n]
                if len(lh) >= 4 * n:
                    lengths = [int(lh[i * 4:i * 4 + 4], 16) for i in range(n)]

            if not lengths:
                # no usable lengths: treat each group as a single pixel
                return colours

            expanded: list[tuple[int, int, int]] = []
            for col, cnt in zip(colours, lengths):
                expanded.extend([col] * max(1, cnt))
            return expanded
        except Exception:
            return []

    @staticmethod
    def _read_count(s: str) -> tuple[int | None, int]:
        """Read a leading hex count of unknown width (1-3 hex digits).

        Returns (count, num_hex_chars_consumed). Picks the width whose implied
        colour body (6 hex per group) fits what's available.
        """
        for k in (1, 2, 3):
            head = s[:k]
            if not re.fullmatch(r"[0-9A-Fa-f]+", head or ""):
                break
            try:
                n = int(head, 16)
            except ValueError:
                continue
            # plausibility: there must be at least 6*n colour chars after
            if n > 0 and len(s) - k >= 6 * n:
                return n, k
        return None, 0