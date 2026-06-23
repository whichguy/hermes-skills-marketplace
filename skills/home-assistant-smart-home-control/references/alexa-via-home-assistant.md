# Alexa devices through Home Assistant

Session-derived notes for future smart-home setup/control conversations.

## Key lesson

When a user asks whether Hermes can connect to or manage Alexa devices, the durable answer is architecture-specific:

- Hermes should control smart-home devices through **Home Assistant** when possible.
- Alexa/Echo devices are manageable only to the extent that Home Assistant exposes them as entities/services.
- Direct Alexa account/device management via Amazon private APIs should not be promised as reliable.

## Hermes/Home Assistant configuration anchors

Hermes' Home Assistant tool expects these environment variables:

```bash
HASS_TOKEN=your-long-lived-access-token
HASS_URL=http://your-home-assistant-ip:8123
```

`HASS_URL` is optional if `http://homeassistant.local:8123` resolves. `HASS_TOKEN` is required and should be added locally to Hermes' `.env`, not pasted into chat unless the user explicitly accepts that risk.

The relevant Hermes tools, when the `homeassistant` toolset is active, are:

- `ha_list_entities`
- `ha_get_state`
- `ha_list_services`
- `ha_call_service`

## Alexa/Echo integration notes

For Echo announcements, media controls, or Alexa routines, recommend configuring Home Assistant's Alexa Media Player integration or equivalent community integration, then controlling whatever entities/services it exposes.

Likely exposed classes:

- `media_player.*` Echo devices
- `notify.*` services for announcements, if configured
- `script.*`, `scene.*`, or `automation.*` wrappers for routines

## Safe answer pattern

If credentials are missing, say:

> Yes, I can manage Alexa-connected smart devices if they are exposed through Home Assistant. This Hermes session needs Home Assistant credentials (`HASS_TOKEN`, optionally `HASS_URL`) before I can control them.

Then provide the token creation path:

1. Home Assistant → Profile/name.
2. Long-Lived Access Tokens.
3. Create token named `Hermes Agent`.
4. Add it locally to Hermes `.env`.
5. Restart Hermes/gateway or start a new session.

## Safety boundaries

Proceed automatically for harmless reads and reversible controls when intent is clear. Ask before locks, alarms, garage doors, HVAC extremes, or anything that may surprise people in the home.
