# Lepro Pixel LED

A Home Assistant integration for Lepro RGB+IC and smart bulb lighting, with
**true per-bulb control** of addressable strings.

Built by reverse-engineering the Lepro cloud MQTT protocol. Unlike app-only
control, this exposes each individual pixel of a string as its own entity.

## Supported devices

| Model | Type | Protocol | Status |
|-------|------|----------|--------|
| ZB1 (AI Festoon 15m) | Addressable RGB+IC string | `d50` | ✅ Verified |
| E27 (AI Smart Bulb) | Single colour + white | `d5` | ✅ Verified |
| E1 (Permanent Outdoor 30m) | Addressable RGB+IC | `d50` | ⚠️ Untested (same family) |
| N1 (Neon Rope 10m) | Addressable RGB+IC | `d50` | ⚠️ Untested (same family) |

"Verified" means captured live from real hardware and tested. Untested models
use the same protocol family and are expected to work; please report results.

## What you get

**Pixel strings (ZB1/E1/N1):**
- A **main light**: on/off, whole-string fill colour, brightness, firmware
  effects (Flash, Wave 1-4, Laser 1-4).
- **One light entity per bulb** (`Pixel 01` … `Pixel N`), each independently
  colourable. Pixel count is auto-detected (and overridable).
- A **`lepro_pixel_led.set_pixels` service** to paint the whole string in one
  call (ideal for automations and custom effects).

**Bulbs (E27):**
- A single light with RGB **and** warm-to-cool colour temperature (2700–6500K),
  matching the app's two tabs.

## Installation (HACS)

1. HACS → ⋮ → Custom repositories → add this repo, category *Integration*.
2. Install **Lepro Pixel LED**.
3. **Copy `client_key.pem`** into
   `custom_components/lepro_pixel_led/` (see note below).
4. Restart Home Assistant.
5. Settings → Devices & Services → Add Integration → *Lepro Pixel LED*.
6. Sign in with your Lepro app email, password, and region.

### About `client_key.pem`

The integration authenticates to Lepro's AWS IoT broker with mutual TLS. The
client private key is the same one the Lepro app uses. It is **not** bundled
here. If you already run the original `lepro_led` integration, copy its
`client_key.pem` into this integration's folder. (A clean first-run download of
this key may be added in a future release.)

## Services

### `lepro_pixel_led.set_pixels`
Set every pixel at once.
```yaml
action: lepro_pixel_led.set_pixels
data:
  device_id: "1748632475"
  colors:
    - [255, 0, 0]
    - [0, 255, 0]
    - [0, 0, 255]
  brightness: 200
```

### `lepro_pixel_led.send_debug_command`
Publish a raw payload — for protocol work on unverified models.
```yaml
action: lepro_pixel_led.send_debug_command
data:
  device_id: "1748632475"
  payload: {"d1": 1, "d2": 1, "d5": "000003E803E8"}
```

## Protocol notes

- **d50** (pixel strings): `N01:P1000{N}{colours}F21000{N}{lengths}U3V3000640000E1;`
  — count is variable-width hex, colours are `RRGGBB`, lengths are 4-hex
  run-lengths. Per-bulb = every group length `0001`.
- **d5** (bulbs): `HHHHSSSSVVVV` (hue 0–360, sat 0–1000, value/brightness
  0–1000) in RGB mode; `d3` brightness + `d4` colour temp in white mode.
- **d30**: an ack/tell-back token the device emits on every change. Carries no
  controllable state; read and ignored, never sent.

## Contributing a new model

Run the included capture approach, set a known pattern in the app, read the
device's reported `d50`/`d5`, and add a protocol class under `protocols/` plus a
registry entry in `const.py`. Captures from E1 and N1 especially welcome.

## Disclaimer

Unofficial. Not affiliated with Lepro. Uses the Lepro cloud; if Lepro change
their API or broker, this may break.