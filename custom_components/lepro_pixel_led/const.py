"""Constants for the Lepro Pixel LED integration."""

DOMAIN = "lepro_pixel_led"

# --- Cloud / Auth Paths -------------------------------------------------------
REGIONS = {
    "eu": "api-eu-iot.lepro.com",
    "na": "api-na-iot.lepro.com",
    "fe": "api-fe-iot.lepro.com",
    "us": "api-us-iot.lepro.com",
}
LOGIN_PATH = "/user/login"
FAMILY_LIST_PATH = "/family/list/timestamp/{timestamp}"
USER_PROFILE_PATH = "/user/profile"
DEVICE_LIST_PATH = "/v3/device/list/fid/{fid}/timestamp/{timestamp}"

# --- Model Protocol Registry --------------------------------------------------
# protocol: 
#   "d50" = grouped per-pixel string protocol (RGBIC devices)
#   "d5"  = single-colour HSV / Kelvin (bulbs and standard RGB strips)
#
# pixels: Default length. 0 means dynamic auto-detect directly from d50 payload.
MODELS = {
    # Modern Addressable (RGBIC) Devices
    "ZB1":  {"protocol": "d50", "pixels": 0},  
    "E1":   {"protocol": "d50", "pixels": 0},  
    "N1":   {"protocol": "d50", "pixels": 0},  
    "S1":   {"protocol": "d50", "pixels": 0},
    "S2":   {"protocol": "d50", "pixels": 0},
    "TB1":  {"protocol": "d50", "pixels": 0},

    # Legacy Hardcoded Pixel Strips
    "S1-5": {"protocol": "d50", "pixels": 25}, 
    
    # Legacy Single-Colour Bulbs & Strips
    "B1":   {"protocol": "d5", "pixels": 1},
    "BC1":  {"protocol": "d5", "pixels": 1},
    "B2":   {"protocol": "d5", "pixels": 1},
    "B3":   {"protocol": "d5", "pixels": 1},
    "T1":   {"protocol": "d5", "pixels": 1},
    "SE1":  {"protocol": "d5", "pixels": 1},
}
DEFAULT_MODEL = {"protocol": "d50", "pixels": 15}

# --- Firmare Effects via d60 Prefix (Hardware Audio / Visual) ----------------
EFFECT_NONE = "none"
SPECIAL_EFFECT_TO_D60_PREFIX = {
    "flash":   "2000064",
    "wave_1":  "2010064",
    "wave_2":  "2020064",
    "wave_3":  "2030064",
    "wave_4":  "2040064",
    "laser_1": "2050064",
    "laser_2": "2060064",
    "laser_3": "2070064",
    "laser_4": "2080064",
    "music":   "3000064",  # Hardware mic mode activation payload
}

# --- Native Algorithmic Custom Themes -----------------------------------------
THEMES = {
    "cyberpunk": [(255, 0, 255), (0, 255, 255), (255, 191, 0), (138, 43, 226)],
    "incredible_hulk": [(50, 205, 50), (128, 0, 128)],
    "superman": [(0, 0, 255), (255, 0, 0), (255, 255, 0)],
    "batman": [(0, 0, 0), (255, 215, 0), (50, 50, 50)],
    "spiderman": [(255, 0, 0), (0, 0, 255), (255, 255, 255)],
    "iron_man": [(255, 0, 0), (255, 215, 0)],
    "captain_america": [(0, 0, 255), (255, 255, 255), (255, 0, 0)],
    "captain_britain": [(0, 0, 128), (255, 255, 255), (255, 0, 0)],
    "wonderwoman": [(255, 0, 0), (0, 0, 255), (255, 215, 0)],
    "avengers": [(255, 0, 0), (255, 215, 0), (50, 205, 50), (0, 0, 255)],
    "justice_league": [(0, 0, 255), (255, 0, 0), (0, 0, 0), (255, 215, 0)],
    "star_wars": [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)],
    "star_trek_enterprise_bridge": [(200, 200, 255), (255, 0, 0), (255, 165, 0)],
    "klingon_bird_of_prey": [(139, 0, 0), (0, 100, 0), (169, 169, 169)],
    "romulan_war_bird": [(0, 128, 0), (0, 255, 128), (105, 105, 105)],
    "christmas": [(255, 0, 0), (0, 255, 0), (255, 255, 255)],
    "halloween": [(255, 100, 0), (75, 0, 130), (0, 255, 0)],
    "ramadan": [(0, 128, 128), (255, 215, 0), (255, 255, 240)],
    "easter": [(255, 179, 186), (255, 223, 186), (255, 255, 186), (186, 255, 201)],
    "diwali": [(255, 69, 0), (255, 140, 0), (255, 215, 0)],
    "hanuka": [(0, 0, 255), (255, 255, 255), (30, 144, 255)],
    "hawaiian_beach_party": [(255, 112, 166), (255, 230, 109), (0, 201, 167)],
    "ibiza_beach_party": [(147, 112, 219), (255, 20, 147), (0, 255, 255)],
    "country_estate": [(85, 107, 47), (139, 69, 19), (245, 245, 220)],
    "nightclub_party": [(255, 0, 128), (0, 0, 0), (128, 0, 255), (0, 255, 0)],
}

# --- Service/Config Configuration Keys ----------------------------------------
CONF_PIXEL_COUNT = "pixel_count"
SERVICE_SET_PIXELS = "set_pixels"
SERVICE_SET_THEME = "set_theme"
SERVICE_SEND_DEBUG = "send_debug_command"
SERVICE_REQUEST_DEBUG = "request_debug_state"