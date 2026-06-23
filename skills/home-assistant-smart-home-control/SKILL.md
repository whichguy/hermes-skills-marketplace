---
name: home-assistant-smart-home-control
description: Control and troubleshoot smart-home devices through Home Assistant (including
  Alexa-connected devices via HA) or directly via OpenHue CLI for Philips Hue.
version: 1.0.0
created_by: agent
platforms:
- linux
- macos
- windows
author: Fortified Strength
license: MIT
metadata:
  hermes:
    config:
    - key: home-assistant-smart-home-control.enabled
      description: Enable home-assistant-smart-home-control skill behavior
      default: true
      prompt: Enable home-assistant-smart-home-control skill?
    tags:
    - home
    category: productivity
---
---

# Home Assistant Smart-Home Control

Use this skill when the user asks whether Hermes can control smart-home devices, Alexa/Echo-connected devices, lights, switches, scenes, sensors, thermostats, media players, or automations through Home Assistant.

## Core model

Prefer **Home Assistant as the control layer**. Treat Alexa as a possible device/routine/media bridge, not the primary API, because Amazon Alexa device/account management APIs are private and unreliable for direct automation.

Hermes can manage devices when Home Assistant exposes them as entities/services. Typical capabilities:

- Query entity state: lights, switches, sensors, covers, climate, locks, media players.
- Call services: `turn_on`, `turn_off`, `toggle`, `set_temperature`, `set_hvac_mode`, `open_cover`, `close_cover`, `set_volume_level`, scene/script activation.
- Run scenes, scripts, and automations.
- Potentially announce or control Echo devices if the user has the Home Assistant Alexa Media Player integration configured.

## Setup checklist

1. Confirm whether Home Assistant is already running.
2. Ask for or discover only the non-secret Home Assistant URL/IP. Do **not** ask the user to paste tokens over chat unless they explicitly choose that risk.
3. Have the user create a Home Assistant Long-Lived Access Token:
   - Home Assistant → user profile/name → Long-Lived Access Tokens → Create token named `Hermes Agent`.
4. Configure Hermes environment:

```bash
HASS_TOKEN=your-long-lived-access-token
HASS_URL=http://your-home-assistant-ip:8123
```

`HASS_URL` defaults to `http://homeassistant.local:8123` if unset.

5. Restart Hermes/gateway or start a fresh session after enabling credentials/toolsets.
6. Verify by listing entities or checking a harmless state before calling control services.

## Hermes tool behavior

The Hermes Home Assistant tool reads:

- `HASS_TOKEN` — required Long-Lived Access Token.
- `HASS_URL` — optional Home Assistant base URL.

Useful tools, when available:

- `ha_list_entities(domain?, area?)`
- `ha_get_state(entity_id)`
- `ha_list_services(domain?)`
- `ha_call_service(domain, service, entity_id?, data?)`

The `homeassistant` toolset is enabled automatically when `HASS_TOKEN` is set in supported Hermes installs, but platform/toolset changes may require `/reset` or gateway restart.

## Alexa-specific guidance

When the user asks “Can you connect to Alexa devices?” answer precisely:

- **Yes, if they are exposed through Home Assistant.**
- **Not reliably as direct Alexa account/device management.**
- For Echo announcements, media controls, or Alexa routines, recommend adding the Home Assistant **Alexa Media Player** integration, then controlling the exposed `media_player`, `notify`, `script`, `scene`, or `automation` entities/services.

Do not promise direct management of Alexa account settings, voice profiles, shopping lists, or private Amazon device settings unless a configured integration exposes those actions.

## Safe operating pattern

1. For harmless state checks, act automatically once credentials exist.
2. For reversible controls like lights/switches/scenes, proceed when the user’s intent is clear.
3. Confirm before high-impact actions: locks, garage doors, alarms, HVAC extreme changes, security modes, purchases, or actions affecting other people unexpectedly.
4. Prefer exact entity IDs after discovery; do not guess entity IDs when controlling devices.
5. After any control service call, verify resulting state when possible.

## Response shape

For setup questions:

- State whether Hermes can do it in this architecture.
- Say what is currently missing: URL, token, toolset, gateway restart, or HA integration.
- Give the minimum safe next step.

For control requests:

- Discover entities if needed.
- Call the service.
- Verify state.
- Report the action and any caveat.

## References

- `references/alexa-via-home-assistant.md` — session notes on Alexa-device management through Home Assistant and Hermes environment variables.

---

## Direct Philips Hue Control (openhue CLI)

**When to use:** User has Philips Hue lights but no Home Assistant, or prefers direct control without HA. `openhue` talks directly to the Hue Bridge.

```bash
# Install
curl -sL https://github.com/openhue/openhue-cli/releases/latest/download/openhue-linux-amd64 \
  -o ~/.local/bin/openhue && chmod +x ~/.local/bin/openhue
# macOS: brew install openhue/cli/openhue-cli
```

**First-run pairing:** Press the button on your Hue Bridge when prompted.

```bash
# List lights and rooms
openhue get light          # List all lights with state
openhue get room           # List all rooms
openhue get scene          # List all scenes

# Control individual lights
openhue set light "Bedroom Lamp" --on
openhue set light "Bedroom Lamp" --off
openhue set light "Bedroom Lamp" --on --brightness 50    # 0-100
openhue set light "Bedroom Lamp" --on --temperature 300  # 153-500 mirek (warm→cool)
openhue set light "Bedroom Lamp" --on --color red
openhue set light "Bedroom Lamp" --on --rgb "#FF5500"

# Control rooms
openhue set room "Bedroom" --off
openhue set room "Bedroom" --on --brightness 30

# Activate scenes
openhue set scene "Relax" --room "Bedroom"
```

**Quick presets:**
- Bedtime: `openhue set room "Bedroom" --on --brightness 20 --temperature 450`
- Work mode: `openhue set room "Office" --on --brightness 100 --temperature 250`
- Movie: `openhue set room "Living Room" --on --brightness 10`

**Notes:** Bridge must be on the same local network. Light/room names are case-sensitive — use `openhue get light` to check. Colors only work on color-capable bulbs. Works with cron jobs for scheduled lighting.
