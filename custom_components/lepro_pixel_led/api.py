"""Cloud + MQTT connection layer for Lepro Pixel LED.

This reproduces the exact flow proven by the standalone sniffer:

  1. REST login to the regional Lepro API  -> bearer token
  2. GET /user/profile                       -> MQTT host/port + cert URLs
  3. download root CA + client cert          -> on disk
  4. build SSL context with AWS IoT ALPN ('x-amzn-mqtt-ca')
  5. connect mTLS MQTT on :8883, subscribe le/<did>/prp/#
  6. publish writes to le/<did>/prp/set, reads via le/<did>/prp/get

No Home Assistant entity logic here; this is pure connection/transport. The
integration setup (__init__.py) owns an instance and wires the callback.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import ssl
import time
from collections.abc import Awaitable, Callable

import aiohttp
from aiomqtt import Client, MqttError

from .const import (
    APP_VERSION,
    AWS_IOT_ALPN,
    DEVICE_LIST_PATH,
    FAMILY_LIST_PATH,
    LOGIN_PATH,
    REGIONS,
    TOPIC_GET,
    TOPIC_SET,
    TOPIC_SUB,
    USER_AGENT,
    USER_PROFILE_PATH,
)

_LOGGER = logging.getLogger(__name__)

MessageCallback = Callable[[str, dict], Awaitable[None]]


class LeproAuthError(Exception):
    """Login or profile retrieval failed."""


class LeproApi:
    """Owns the REST login + AWS IoT MQTT connection for one Lepro account."""

    def __init__(
        self,
        hass_config_dir: str,
        entry_id: str,
        account: str,
        password: str,
        region: str = "eu",
    ) -> None:
        self._config_dir = hass_config_dir
        self._entry_id = entry_id
        self._account = account
        self._password = password
        self._region = region if region in REGIONS else "eu"

        self._api_host = REGIONS[self._region]
        self._cert_dir = os.path.join(hass_config_dir, ".lepro_pixel_led")
        self._root_ca = os.path.join(self._cert_dir, f"{entry_id}_root_ca.pem")
        self._client_cert = os.path.join(self._cert_dir, f"{entry_id}_client_cert.pem")
        # client key ships with the integration package
        self._key_path = os.path.join(os.path.dirname(__file__), "client_key.pem")

        self._mqtt_host: str | None = None
        self._mqtt_port: int | None = None
        self._ssl_context: ssl.SSLContext | None = None

        self._client: Client | None = None
        self._loop_task: asyncio.Task | None = None
        self._message_cb: MessageCallback | None = None
        self._subscriptions: set[str] = set()
        self._pending_messages: list[tuple[str, str]] = []
        self._stop = asyncio.Event()
        self._connected = asyncio.Event()

    # --- public API -----------------------------------------------------------

    def set_message_callback(self, cb: MessageCallback) -> None:
        self._message_cb = cb

    async def async_setup(self) -> list[dict]:
        """Login, fetch profile + certs + device list. Returns raw device dicts."""
        async with aiohttp.ClientSession() as session:
            token = await self._login(session)
            headers = self._auth_headers(token)
            profile = await self._get_json(session, USER_PROFILE_PATH, headers)
            mqtt = profile["data"]["mqtt"]
            self._mqtt_host = mqtt["host"]
            self._mqtt_port = int(mqtt["port"])

            os.makedirs(self._cert_dir, exist_ok=True)
            await self._download(session, mqtt["root"], self._root_ca, headers)
            await self._download(session, mqtt["cert"], self._client_cert, headers)

            ts = str(int(time.time()))
            fam = await self._get_json(
                session, FAMILY_LIST_PATH.format(timestamp=ts), headers
            )
            fid = fam["data"]["list"][0]["fid"]

            ts = str(int(time.time()))
            dev = await self._get_json(
                session,
                DEVICE_LIST_PATH.format(fid=fid, timestamp=ts),
                self._auth_headers(token, ts),
            )
            return dev.get("data", {}).get("list", [])

    async def async_connect(self) -> None:
        """Build SSL context, start the MQTT loop, and wait until connected."""
        self._ssl_context = await asyncio.get_running_loop().run_in_executor(
            None, self._build_ssl_context
        )
        self._stop.clear()
        self._connected.clear()
        self._loop_task = asyncio.create_task(self._run())
        # wait for the first successful connection so callers can publish safely
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=15)
        except asyncio.TimeoutError:
            _LOGGER.warning("MQTT did not connect within 15s; continuing anyway")

    async def async_subscribe_device(self, did: str) -> None:
        topic = TOPIC_SUB.format(did=did)
        self._subscriptions.add(topic)
        if self._client is not None:
            await self._client.subscribe(topic)

    async def async_publish(self, did: str, payload: dict) -> None:
        """Publish a write to le/<did>/prp/set in the device envelope."""
        topic = TOPIC_SET.format(did=did)
        envelope = {
            "id": random.randint(0, 1_000_000_000),
            "t": int(time.time()),
            "d": payload,
        }
        await self._raw_publish(topic, json.dumps(envelope))

    async def async_request_state(self, did: str, keys: list[str]) -> None:
        topic = TOPIC_GET.format(did=did)
        await self._raw_publish(topic, json.dumps({"d": keys}))

    async def async_disconnect(self) -> None:
        self._stop.set()
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    # --- REST helpers ---------------------------------------------------------

    def _base_headers(self, ts: str) -> dict:
        return {
            "Content-Type": "application/json",
            "App-Version": APP_VERSION,
            "Device-Model": "ha_integration",
            "Device-System": "custom",
            "GMT": "+0",
            "Host": self._api_host,
            "Language": "en",
            "Platform": "2",
            "Screen-Size": "1536*2048",
            "Slanguage": "en",
            "Timestamp": ts,
            "User-Agent": USER_AGENT,
        }

    def _auth_headers(self, token: str, ts: str | None = None) -> dict:
        ts = ts or str(int(time.time()))
        h = self._base_headers(ts)
        h["Authorization"] = f"Bearer {token}"
        return h

    async def _login(self, session: aiohttp.ClientSession) -> str:
        ts = str(int(time.time()))
        mac_hash = hashlib.md5(self._account.encode()).hexdigest()
        mac = (
            f"02:{mac_hash[0:2]}:{mac_hash[2:4]}:{mac_hash[4:6]}:"
            f"{mac_hash[6:8]}:{mac_hash[8:10]}"
        )
        payload = {
            "platform": "2",
            "account": self._account,
            "password": self._password,
            "mac": mac,
            "timestamp": ts,
            "language": "en",
            "fcmToken": "",
        }
        url = f"https://{self._api_host}{LOGIN_PATH}"
        async with session.post(url, json=payload, headers=self._base_headers(ts)) as r:
            data = await r.json()
        if data.get("code") != 0:
            raise LeproAuthError(f"Login failed: {data.get('msg')}")
        return data["data"]["token"]

    async def _get_json(
        self, session: aiohttp.ClientSession, path: str, headers: dict
    ) -> dict:
        url = f"https://{self._api_host}{path}"
        async with session.get(url, headers=headers) as r:
            if r.status != 200:
                raise LeproAuthError(f"GET {path} -> HTTP {r.status}")
            return await r.json()

    async def _download(
        self, session: aiohttp.ClientSession, url: str, dest: str, headers: dict
    ) -> None:
        async with session.get(url, headers=headers) as r:
            if r.status != 200:
                raise LeproAuthError(f"cert download {url} -> HTTP {r.status}")
            data = await r.read()
        # file write is blocking; run it off the event loop
        await asyncio.get_running_loop().run_in_executor(
            None, self._write_file, dest, data
        )

    @staticmethod
    def _write_file(dest: str, data: bytes) -> None:
        with open(dest, "wb") as f:
            f.write(data)

    # --- MQTT -----------------------------------------------------------------

    def _build_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cafile=self._root_ca)
        ctx.load_cert_chain(certfile=self._client_cert, keyfile=self._key_path)
        ctx.set_alpn_protocols([AWS_IOT_ALPN])
        return ctx

    def _client_id(self) -> str:
        suffix = hashlib.sha256(self._entry_id.encode()).hexdigest()[:32]
        return f"lepro-app-{suffix}"

    async def _raw_publish(self, topic: str, payload: str) -> None:
        if self._client is None:
            # not connected yet: queue and flush once connected (mirrors the
            # original integration's MQTTClientWrapper behaviour)
            self._pending_messages.append((topic, payload))
            return
        try:
            await self._client.publish(topic, payload)
        except MqttError as e:
            _LOGGER.error("MQTT publish failed (%s): %s", topic, e)

    async def _run(self) -> None:
        """Maintain the MQTT connection, reconnecting on failure."""
        backoff = 1
        while not self._stop.is_set():
            try:
                async with Client(
                    hostname=self._mqtt_host,
                    port=self._mqtt_port,
                    identifier=self._client_id(),
                    tls_context=self._ssl_context,
                ) as client:
                    self._client = client
                    self._connected.set()
                    backoff = 1
                    for topic in self._subscriptions:
                        await client.subscribe(topic)
                    # flush any messages queued before the connection was ready
                    if self._pending_messages:
                        pending = self._pending_messages
                        self._pending_messages = []
                        for topic, payload in pending:
                            try:
                                await client.publish(topic, payload)
                            except MqttError as e:
                                _LOGGER.error("MQTT flush publish failed (%s): %s", topic, e)
                    async for message in client.messages:
                        await self._handle(message)
            except MqttError as e:
                _LOGGER.warning("MQTT connection lost: %s (retry in %ss)", e, backoff)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                _LOGGER.exception("Unexpected MQTT loop error: %s", e)
            finally:
                self._client = None
                self._connected.clear()
            if self._stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _handle(self, message) -> None:
        topic = message.topic.value
        try:
            payload = json.loads(message.payload.decode())
        except Exception:  # noqa: BLE001
            return
        if self._message_cb is None:
            return
        # topic: le/<did>/prp/<type>
        parts = topic.split("/")
        if len(parts) < 4 or parts[0] != "le":
            return
        did = parts[1]
        msg_type = parts[3]
        if msg_type not in ("rpt", "set", "getr"):
            return
        data = payload.get("d")
        if isinstance(data, dict):
            await self._message_cb(did, data)