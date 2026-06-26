import asyncio
import aiohttp
import logging
import time
import json
import random
import ssl
import os
import hashlib
import re
import colorsys

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    LightEntity,
    ColorMode,
    LightEntityFeature,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from aiomqtt import Client, MqttError
import aiofiles

from .const import (
    DOMAIN,
    REGIONS,
    LOGIN_PATH,
    FAMILY_LIST_PATH,
    USER_PROFILE_PATH,
    DEVICE_LIST_PATH,
    MODELS,
    DEFAULT_MODEL,
    THEMES,
    SPECIAL_EFFECT_TO_D60_PREFIX,
    EFFECT_NONE,
)
from .protocols.base import LeproState
from .protocols.d5 import D5Protocol
from .protocols.d50 import D50Protocol

_LOGGER = logging.getLogger(__name__)

# --- Pristine Core Connection Layer (Do Not Separate Into api.py) -------------
class MQTTClientWrapper:
    def __init__(self, hass, host, port, ssl_context, client_id):
        self.hass = hass
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.client_id = client_id
        self.client = None
        self._message_callback = None
        self._loop_task = None
        self._pending_subscriptions = []
        self._pending_messages = []

    async def _connect_and_run(self):
        try:
            async with Client(
                hostname=self.host,
                port=self.port,
                identifier=self.client_id,
                tls_context=self.ssl_context,
                clean_session=True
            ) as client:
                self.client = client
                for topic in self._pending_subscriptions:
                    await client.subscribe(topic)
                self._pending_subscriptions = []
                for topic, payload in self._pending_messages:
                    await client.publish(topic, payload)
                self._pending_messages = []
                async for message in client.messages:
                    if self._message_callback:
                        await self._message_callback(message)
        except MqttError as e:
            _LOGGER.error("MQTT error: %s", e)
        finally:
            self.client = None

    async def connect(self):
        if self._loop_task and not self._loop_task.done():
            return
        self._pending_subscriptions = []
        self._pending_messages = []
        self._loop_task = asyncio.create_task(self._connect_and_run())

    async def subscribe(self, topic):
        if self.client:
            await self.client.subscribe(topic)
        else:
            self._pending_subscriptions.append(topic)
            if not self._loop_task or self._loop_task.done():
                await self.connect()

    async def publish(self, topic, payload):
        if self.client:
            await self.client.publish(topic, payload)
        else:
            self._pending_messages.append((topic, payload))
            if not self._loop_task or self._loop_task.done():
                await self.connect()

    def set_message_callback(self, callback):
        self._message_callback = callback

    async def disconnect(self):
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

async def async_login(session, account, password, mac, login_url, api_host, language="en", fcm_token=""):
    timestamp = str(int(time.time()))
    payload = {
        "platform": "2",
        "account": account,
        "password": password,
        "mac": mac,
        "timestamp": timestamp,
        "language": language,
        "fcmToken": fcm_token,
    }
    headers = {
        "Content-Type": "application/json",
        "App-Version": "1.0.9.202",
        "Device-Model": "custom_integration",
        "Device-System": "custom",
        "GMT": "+0",
        "Host": api_host,
        "Language": language,
        "Platform": "2",
        "Screen-Size": "1536*2048",
        "Slanguage": language,
        "Timestamp": timestamp,
        "User-Agent": "LE/1.0.9.202 (Custom Integration)",
    }
    async with session.post(login_url, json=payload, headers=headers) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        if data.get("code") != 0:
            return None
        return data.get("data", {}).get("token")

async def download_cert_file(session, url, path, headers):
    async with session.get(url, headers=headers) as resp:
        if resp.status != 200:
            raise Exception(f"Failed to download {url}: {resp.status}")
        data = await resp.read()
        async with aiofiles.open(path, 'wb') as f:
            await f.write(data)

def create_ssl_context(root_ca_path, client_cert_path, keyfile_path):
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=root_ca_path)
    context.load_cert_chain(certfile=client_cert_path, keyfile=keyfile_path)
    return context

# --- Refactored Stateful Core Entities ----------------------------------------
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

class LeproLight(LightEntity):
    """Main, stateful parent entity for a Lepro Smart Device."""
    _attr_has_entity_name = True

    def __init__(self, device, mqtt_client, entry_id, pixel_override=None):
        self.mqtt_client = mqtt_client
        self._entry_id = entry_id
        self._did = str(device["did"])
        self.name_raw = device.get("name", f"Lepro {self._did}")
        self.series = device.get("series", "") or ""

        self.spec = _resolve_model(self.series)
        self.pixel_count = pixel_override or self.spec.get("pixels", 1) or 1
        self.protocol = _make_protocol(self.spec, self.pixel_count)

        self.state_store = LeproState()
        self._speed = 50
        self._sensitivity = 50
        self._pixel_listeners = []

        self._attr_unique_id = f"{self._did}_string" if self.supports_pixels else f"{self._did}_bulb"
        self._attr_translation_key = "string" if self.supports_pixels else "bulb"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._did)},
            "name": self.name_raw,
            "manufacturer": "Lepro",
            "model": self.series or "Lepro LED",
            "serial_number": self._did,
            "sw_version": device.get("fwVersion", "Unknown"),
            "hw_version": device.get("hwVersion", "Unknown"),
        }

        # Dynamically set features depending on protocol mapping[cite: 13, 14]
        if self.supports_pixels:
            self._attr_color_mode = ColorMode.RGB
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_supported_features = LightEntityFeature.EFFECT
            # Merge both native firmware FX and custom math themes into the selection list
            self._attr_effect_list = [EFFECT_NONE] + list(SPECIAL_EFFECT_TO_D60_PREFIX.keys()) + list(THEMES.keys())
        else:
            self._attr_supported_color_modes = {ColorMode.RGB, ColorMode.COLOR_TEMP}
            self._attr_min_color_temp_kelvin = 2700
            self._attr_max_color_temp_kelvin = 6500

    @property
    def supports_pixels(self) -> bool:
        return self.protocol.supports_pixels

    @property
    def is_on(self) -> bool | None:
        return self.state_store.is_on

    @property
    def brightness(self) -> int | None:
        return self.state_store.brightness

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self.state_store.pixels[0] if self.state_store.pixels else (255, 255, 255)

    @property
    def color_temp_kelvin(self) -> int | None:
        return self.state_store.color_temp_kelvin

    @property
    def color_mode(self) -> ColorMode:
        if self.supports_pixels:
            return ColorMode.RGB
        return ColorMode.COLOR_TEMP if self.state_store.is_white_mode else ColorMode.RGB

    @property
    def effect(self) -> str | None:
        return self.state_store.effect or EFFECT_NONE

    def register_pixel(self, cb):
        self._pixel_listeners.append(cb)

    def _notify_pixels(self):
        for cb in list(self._pixel_listeners):
            try: cb()
            except Exception: pass

    def handle_report(self, data: dict, hass_add_job=None):
        """Processes live incoming payloads safely routed via MQTT message handler[cite: 2]."""
        decoded = self.protocol.decode(data)
        
        # Safe merge[cite: 7]
        if decoded.is_on is not None: self.state_store.is_on = decoded.is_on
        if decoded.pixels: self.state_store.pixels = decoded.pixels
        if decoded.brightness is not None: self.state_store.brightness = decoded.brightness
        if decoded.color_temp_kelvin is not None: self.state_store.color_temp_kelvin = decoded.color_temp_kelvin
        self.state_store.is_white_mode = decoded.is_white_mode
        if decoded.effect is not None: self.state_store.effect = decoded.effect

        # Dynamic Auto-Detection of expanded lengths on modern d50 strings[cite: 7]
        if decoded.pixel_count and decoded.pixel_count != self.pixel_count and self.supports_pixels and self.spec.get("pixels") == 0:
            self.pixel_count = decoded.pixel_count
            self.protocol = _make_protocol(self.spec, self.pixel_count)
            # Request spawning of new child bulb entities onto the active setup track safely[cite: 7]
            if hass_add_job:
                new_entities = [LeproPixelLight(self, idx) for idx in range(self.pixel_count)]
                hass_add_job(new_entities)

        self.async_write_ha_state()
        self._notify_pixels()

    async def async_turn_on(self, **kwargs):
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.state_store.brightness or 255)

        if self.supports_pixels:
            if ATTR_EFFECT in kwargs:
                eff = kwargs[ATTR_EFFECT]
                if eff in THEMES:
                    await self.async_apply_theme(eff, brightness)
                else:
                    await self.async_apply_effect(eff, brightness)
                return
            if ATTR_RGB_COLOR in kwargs:
                rgb = tuple(int(c) for c in kwargs[ATTR_RGB_COLOR])
                await self.async_apply_pixels([rgb] * self.pixel_count, brightness)
                return
            
            # Brightness tracking slider update[cite: 7]
            pixels = self.state_store.pixels or [(255, 255, 255)] * self.pixel_count
            if len(pixels) != self.pixel_count:
                pixels = (pixels + [(255,255,255)] * self.pixel_count)[:self.pixel_count]
            await self.async_apply_pixels(pixels, brightness)
            return

        # Legacy Bulb Routing (d5)[cite: 7, 13]
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self.async_apply_white(int(kwargs[ATTR_COLOR_TEMP_KELVIN]), brightness)
            return
        if ATTR_RGB_COLOR in kwargs:
            await self.async_apply_rgb(tuple(int(c) for c in kwargs[ATTR_RGB_COLOR]), brightness)
            return
        if self.state_store.is_white_mode and self.state_store.color_temp_kelvin:
            await self.async_apply_white(self.state_store.color_temp_kelvin, brightness)
        else:
            await self.async_apply_rgb(self.rgb_color or (255, 255, 255), brightness)

    async def async_turn_off(self, **kwargs):
        await self._send_command(self.protocol.encode_power(False))
        self.state_store.is_on = False
        self.async_write_ha_state()
        self._notify_pixels()

    async def async_apply_pixels(self, pixels, brightness=None):
        await self._send_command(self.protocol.encode_pixels(pixels, brightness))
        self.state_store.pixels = pixels
        self.state_store.is_on = True
        self.state_store.effect = EFFECT_NONE
        if brightness is not None: self.state_store.brightness = brightness
        self.async_write_ha_state()
        self._notify_pixels()

    async def async_apply_rgb(self, rgb, brightness=None):
        await self._send_command(self.protocol.encode_rgb(rgb, brightness))
        self.state_store.pixels = [rgb]
        self.state_store.is_on = True
        self.state_store.is_white_mode = False
        if brightness is not None: self.state_store.brightness = brightness
        self.async_write_ha_state()

    async def async_apply_white(self, kelvin, brightness=None):
        await self._send_command(self.protocol.encode_white(kelvin, brightness))
        self.state_store.is_white_mode = True
        self.state_store.color_temp_kelvin = kelvin
        self.state_store.is_on = True
        if brightness is not None: self.state_store.brightness = brightness
        self.async_write_ha_state()

    async def async_apply_effect(self, effect, brightness=None):
        if effect == EFFECT_NONE:
            await self.async_apply_pixels(self.state_store.pixels or [(255,255,255)]*self.pixel_count, brightness)
            return
        prefix = SPECIAL_EFFECT_TO_D60_PREFIX.get(effect)
        if not prefix: return
        
        # Calculate hex response based on active sensitivity mapping[cite: 7]
        hex_val = max(0, min(0x63, round(self._sensitivity / 100 * 0x63)))
        payload = {"d1": 1, "d2": 3, "d60": f"{prefix}{hex_val:02X}0000"}
        if brightness is not None:
            payload["d52"] = max(0, min(1000, round(brightness / 255 * 1000)))
        await self._send_command(payload)
        self.state_store.effect = effect
        self.state_store.is_on = True
        self.async_write_ha_state()

    async def async_apply_theme(self, theme_name, brightness=None):
        palette = THEMES.get(theme_name)
        if not palette: return
        
        # Algorithmic repetition over true decoded string length[cite: 7]
        pixels = []
        for idx in range(self.pixel_count):
            pixels.append(palette[idx % len(palette)])
        
        await self._send_command(self.protocol.encode_pixels(pixels, brightness))
        self.state_store.pixels = pixels
        self.state_store.is_on = True
        self.state_store.effect = theme_name
        if brightness is not None: self.state_store.brightness = brightness
        self.async_write_ha_state()
        self._notify_pixels()

    async def _send_command(self, payload):
        topic = f"le/{self._did}/prp/set"
        envelope = {
            "id": random.randint(0, 1000000000),
            "t": int(time.time()),
            "d": payload
        }
        try:
            await self.mqtt_client.publish(topic, json.dumps(envelope))
        except Exception as e:
            _LOGGER.error("Failed command routing: %s", e)

class LeproPixelLight(LightEntity):
    """Dynamic child entity for true standalone control over an individual bulb[cite: 7]."""
    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(self, parent: LeproLight, index: int):
        self.parent = parent
        self.index = index
        n = str(index + 1).rjust(2, "0")
        self._attr_translation_key = "pixel"
        self._attr_unique_id = f"{parent._did}_pixel_{n}"
        self._attr_device_info = {"identifiers": {(DOMAIN, parent._did)}}

    @property
    def translation_placeholders(self) -> dict:
        return {"index": str(self.index + 1).rjust(2, "0")}

    async def async_added_to_hass(self):
        self.parent.register_pixel(self._handle_update)

    @callback
    def _handle_update(self):
        self.async_write_ha_state()

    def _get_expanded_pixels(self):
        px = list(self.parent.state_store.pixels)
        n = self.parent.pixel_count
        if len(px) < n: px = px + [(255, 255, 255)] * (n - len(px))
        return px[:n]

    @property
    def is_on(self) -> bool | None:
        return self.parent.state_store.is_on

    @property
    def brightness(self) -> int | None:
        return self.parent.state_store.brightness

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        px = self._get_expanded_pixels()
        return px[self.index] if self.index < len(px) else (255, 255, 255)

    async def async_turn_on(self, **kwargs):
        pixels = self._get_expanded_pixels()
        if ATTR_RGB_COLOR in kwargs:
            pixels[self.index] = tuple(int(c) for c in kwargs[ATTR_RGB_COLOR])
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.parent.state_store.brightness)
        await self.parent.async_apply_pixels(pixels, brightness)

    async def async_turn_off(self, **kwargs):
        pixels = self._get_expanded_pixels()
        pixels[self.index] = (0, 0, 0)
        await self.parent.async_apply_pixels(pixels)

# --- Active Registration Setup Entry Hook -------------------------------------
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    config = hass.data[DOMAIN][entry.entry_id]
    account = config["account"]
    password = config["password"]
    
    config_data = dict(config)
    if "persistent_mac" not in config_data:
        mac_hash = hashlib.md5(config_data["account"].encode()).hexdigest()
        persistent_mac = f"02:{mac_hash[0:2]}:{mac_hash[2:4]}:{mac_hash[4:6]}:{mac_hash[6:8]}:{mac_hash[8:10]}"
        config_data["persistent_mac"] = persistent_mac
        hass.config_entries.async_update_entry(entry, data=config_data)

    mac = config_data["persistent_mac"]
    language = config_data.get("language", "en")
    api_host = REGIONS.get(config_data.get("region", "eu"), REGIONS["eu"])

    cert_dir = os.path.join(hass.config.config_dir, ".lepro_pixel_led")
    if not os.path.exists(cert_dir):
        await hass.async_add_executor_job(os.makedirs, cert_dir)

    root_ca_path = os.path.join(cert_dir, f"{entry.entry_id}_root_ca.pem")
    client_cert_path = os.path.join(cert_dir, f"{entry.entry_id}_client_cert.pem")
    keyfile_path = os.path.join(os.path.dirname(__file__), "client_key.pem")

    async with aiohttp.ClientSession() as session:
        bearer_token = await async_login(session, account, password, mac, f"https://{api_host}{LOGIN_PATH}", api_host, language)
        if not bearer_token: return

        headers = {"Authorization": f"Bearer {bearer_token}", "App-Version": "1.0.9.202", "Host": api_host, "Language": language, "Platform": "2"}
        
        timestamp = str(int(time.time()))
        headers["Timestamp"] = timestamp
        async with session.get(f"https://{api_host}{USER_PROFILE_PATH}", headers=headers) as resp:
            user_data = await resp.json()
        
        uid = user_data["data"]["uid"]
        mqtt_info = user_data["data"]["mqtt"]

        await download_cert_file(session, mqtt_info["root"], root_ca_path, headers)
        await download_cert_file(session, mqtt_info["cert"], client_cert_path, headers)

        async with session.get(f"https://{api_host}{FAMILY_LIST_PATH.format(timestamp=timestamp)}", headers=headers) as resp:
            family_data = await resp.json()
        fid = family_data["data"]["list"][0]["fid"]

        timestamp = str(int(time.time()))
        headers["Timestamp"] = timestamp
        async with session.get(f"https://{api_host}{DEVICE_LIST_PATH.format(fid=fid, timestamp=timestamp)}", headers=headers) as resp:
            device_data = await resp.json()
        devices = device_data.get("data", {}).get("list", [])

    ssl_context = await hass.async_add_executor_job(create_ssl_context, root_ca_path, client_cert_path, keyfile_path)
    client_id_suffix = hashlib.sha256(entry.entry_id.encode()).hexdigest()[:32]
    
    mqtt_client = MQTTClientWrapper(hass, host=mqtt_info["host"], port=int(mqtt_info["port"]), ssl_context=ssl_context, client_id=f"lepro-app-{client_id_suffix}")
    await mqtt_client.connect()

    entities = []
    device_entity_map = {}
    for device in devices:
        entity = LeproLight(device, mqtt_client, entry.entry_id)
        entities.append(entity)
        device_entity_map[str(device['did'])] = entity
        
        # If model expects pixel generation up-front (legacy static size overrides)[cite: 7]
        if entity.supports_pixels and entity.pixel_count > 0 and entity.spec.get("pixels", 0) > 0:
            for idx in range(entity.pixel_count):
                entities.append(LeproPixelLight(entity, idx))

    async def handle_mqtt_message(message):
        try:
            topic = message.topic.value
            payload = json.loads(message.payload.decode())
            parts = topic.split('/')
            if len(parts) < 4 or parts[0] != "le": return
            
            did = parts[1]
            msg_type = parts[3]
            entity = device_entity_map.get(did)
            if not entity: return

            if msg_type in ["rpt", "set", "getr"]:
                data = payload.get('d', {})
                # Execute runtime injection updates context-safely via schedule job tracks[cite: 2]
                entity.handle_report(data, hass_add_job=async_add_entities)
        except Exception as e:
            _LOGGER.error("MQTT subscription decoding failure: %s", e)

    mqtt_client.set_message_callback(handle_mqtt_message)
    await mqtt_client.subscribe(f"le/{client_id_suffix}/act/app/exe")
    for did in device_entity_map.keys():
        await mqtt_client.subscribe(f"le/{did}/prp/#")

    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    store.update({'mqtt_client': mqtt_client, 'entities': entities, 'device_map': device_entity_map})
    
    async_add_entities(entities)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].get(entry.entry_id)
    if data:
        await data['mqtt_client'].disconnect()
    return True