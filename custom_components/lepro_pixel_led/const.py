"""Constants for the Lepro Pixel LED integration."""

DOMAIN = "lepro_pixel_led"

# --- Cloud / auth -------------------------------------------------------------
REGIONS = {
    "eu": "api-eu-iot.lepro.com",
    "na": "api-na-iot.lepro.com",
    "fe": "api-fe-iot.lepro.com",
    "us": "api-us-iot.lepro.com",
}
LOGIN_PATH = "/user/login"
USER_PROFILE_PATH = "/user/profile"
FAMILY_LIST_PATH = "/family/list/timestamp/{timestamp}"
DEVICE_LIST_PATH = "/v3/device/list/fid/{fid}/timestamp/{timestamp}"

APP_VERSION = "1.0.9.202"
USER_AGENT = f"LE/{APP_VERSION} (HA lepro_pixel_led)"

# AWS IoT Core requires this ALPN protocol for cert-based auth on port 8883.
AWS_IOT_ALPN = "x-amzn-mqtt-ca"

# MQTT topics (per device id / did)
TOPIC_SET = "le/{did}/prp/set"
TOPIC_GET = "le/{did}/prp/get"
TOPIC_SUB = "le/{did}/prp/#"

# --- Model registry -----------------------------------------------------------
# protocol:
#   "d50" = grouped per-pixel string protocol (ZB1 family, RGB+IC)
#   "d5"  = B-series single-colour HSV (non-pixel bulbs) - not handled in v1
#
# pixels: default/expected count. Actual count is auto-detected from the
#         device's reported d50 where possible; this is the fallback.
MODELS = {
    "ZB1": {"protocol": "d50", "pixels": 15},
    # extension points - add as captures confirm them:
    # "S1-5": {"protocol": "d50", "pixels": 25},
    # "E1":   {"protocol": "d50", "pixels": 0},
}
DEFAULT_MODEL = {"protocol": "d50", "pixels": 15}

# d50 effect tail for solid / per-bulb static (confirmed from ZB1 capture)
D50_TAIL_SOLID = "U3V3000640000E1"

# --- Firmware effects via d60 (reused, proven prefixes) -----------------------
# Map HA effect name -> 7-char d60 prefix.
EFFECT_NONE = "none"
SPECIAL_EFFECT_TO_D60_PREFIX = {
    "flash":  "2000064",
    "wave_1": "2010064",
    "wave_2": "2020064",
    "wave_3": "2030064",
    "wave_4": "2040064",
    "laser_1": "2050064",
    "laser_2": "2060064",
    "laser_3": "2070064",
    "laser_4": "2080064",
}

# Config option keys
CONF_REGION = "region"
CONF_PIXEL_COUNT = "pixel_count"  # per-device override

# Service names
SERVICE_SET_PIXELS = "set_pixels"
SERVICE_SEND_DEBUG = "send_debug_command"