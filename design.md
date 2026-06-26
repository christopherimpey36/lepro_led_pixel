# Product Requirements Document: Lepro Pixel LED (HACS Integration)

## 1. Project Overview
A modern, reliable, and educational Home Assistant custom integration for Lepro smart lighting. This integration provides true per-bulb control for modern RGB+IC addressable pixel strings, maintains backward compatibility with legacy Lepro bulbs, and serves as an open learning tool for the Home Assistant community to explore and reverse-engineer IoT MQTT protocols.

## 2. Core Architecture
The integration uses a hybrid modular approach to maximize reliability and maintainability:
* **The Transport Layer (Legacy Core):** Retains the proven, rock-solid AWS IoT mTLS connection, certificate downloading, and authentication loop from the original repository. 
* **The Protocol Layer (Modular):** Extracts all messy hex-math and payload generation into isolated, testable Python classes (`D5Protocol`, `D50Protocol`).
* **The Model Registry:** Uses a centralized dictionary (`MODELS` in `const.py`) to map hardware strings (e.g., "ZB1", "E1", "B1") to their respective protocols and expected pixel counts.

## 3. Supported Hardware & Mapping
* **Modern Addressable (d50 Protocol):** ZB1, E1, N1, S1, S2, TB1.
    * *Behavior:* Pixel count is set to `0` (auto-detect). The integration reads the string length from the first MQTT `d50` payload and dynamically spawns the exact number of required bulb entities.
* **Legacy Pixel Strips (d50 Protocol):** S1-5.
    * *Behavior:* Hardcoded to 25 pixels to preserve the original integration's expected behavior.
* **Legacy Single-Color/White (d5 Protocol):** B1, BC1, B2, B3, T1, SE1.
    * *Behavior:* Mapped to a 1-pixel expectation. Handles standard `HHHHSSSSVVVV` math and Kelvin conversions natively.

## 4. Entity Structure
* **Main Light (`LeproLight`):** Controls master power, overall brightness, full-string fill color, and native firmware effects (Flash, Wave, Laser).
* **Segment Lights (`LeproPixelLight`):** Dynamically generated child entities (`Pixel 01` ... `Pixel N`) for true individual bulb color targeting.
* **Configuration Entities:** Speed and Sensitivity sliders (`NumberEntity`) mapped dynamically based on hardware capabilities.

## 5. Community Learning & Debugging Tools
To foster a community-driven reverse-engineering environment, the integration must expose native tools that bypass the need for external packet sniffers:
* **`send_debug_command` Service:** Allows users to inject raw JSON payloads directly into the device's `prp/set` MQTT topic.
* **`request_debug_state` Service:** Allows users to request raw state fields from the `prp/get` topic and observe the raw hex strings the device reports back.
* *Note:* All documentation and service examples must use generic placeholder IDs (e.g., `1234567890`) to protect user privacy.

## 6. Native Themes & AI Compatibility
The integration will bypass the reliance on the Lepro Cloud AI for effects by baking mathematical themes natively into the backend:
* **Pre-baked Themes:** Inclusion of custom algorithmic palettes (e.g., Cyberpunk, The Hulk, Hulk Hogan, Christmas, Halloween).
* **Theme API (`set_theme` Service):** A Home Assistant Action allowing users to pass an array of custom RGB values and application styles (solid, alternate, gradient).
* **Voice/AI Readiness:** By exposing themes through standard HA Actions, local LLMs and HA Assist can trigger complex visual states via natural language, inclucing being able to on the fly make new themese from just a voice prompt.
### 6.1 Themes

each theme should have a selection of effects from none, to laser across all the effects classes:
* Cyberpunk
* Incredible Hulk
* Superman
* Batman
* Spiderman
* iron man
* Captain America
* Captain Britain
* Wonderwoman
* Avengers
* Justice League
* Star Wars
* Star Trek Enterprise Bridge
* Klingon Bird of Prey
* Romulan War Bird
* Christmas
* Halloween
* Ramadan
* Easter
* Diwali
* Hanuka
* Hawiana Beach Party
* Ibiza Beach Party
* Country Estate
* Nightclub Party

## 7. Frontend
* **Custom Lovelace Card:** A dedicated Lit-based JavaScript frontend card (distributed alongside the backend) that mimics the Lepro App UI, automatically rendering the correct number of interactive bulb icons based on the `pixel_count` state attribute.