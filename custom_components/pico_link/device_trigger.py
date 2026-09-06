# device_trigger.py — device triggers for the pico_link_button event
#
# Mirrors homeassistant.components.lutron_caseta's own device_trigger.py
# (same trigger_type=press/release, trigger_subtype=button name pattern),
# but built on our own pico_link_button event instead of Lutron's raw
# LEAP/keypad data, since Pico Link already knows each configured
# device's type and the buttons that go with it.
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from . import _entry_device_ids
from .const import DOMAIN, PICO_BUTTON_EVENT, PICO_TYPE_BUTTONS

CONF_SUBTYPE = "subtype"

TRIGGER_TYPES = ("press", "release")

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
        vol.Required(CONF_SUBTYPE): str,
    }
)


def _entry_for_device(hass: HomeAssistant, device_id: str):
    """Return the Pico Link config entry that includes this device, if any."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if device_id in _entry_device_ids(entry):
            return entry

    return None


async def async_get_triggers(
    hass: HomeAssistant,
    device_id: str,
) -> list[dict[str, Any]]:
    """List device triggers for a configured Pico."""
    entry = _entry_for_device(hass, device_id)

    if entry is None:
        return []

    buttons = PICO_TYPE_BUTTONS.get(entry.data.get("type"), ())

    return [
        {
            CONF_PLATFORM: "device",
            CONF_DEVICE_ID: device_id,
            CONF_DOMAIN: DOMAIN,
            CONF_TYPE: trigger_type,
            CONF_SUBTYPE: button,
        }
        for trigger_type in TRIGGER_TYPES
        for button in buttons
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger for one Pico button press or release."""
    return await event_trigger.async_attach_trigger(
        hass,
        event_trigger.TRIGGER_SCHEMA(
            {
                event_trigger.CONF_PLATFORM: "event",
                event_trigger.CONF_EVENT_TYPE: PICO_BUTTON_EVENT,
                event_trigger.CONF_EVENT_DATA: {
                    CONF_DEVICE_ID: config[CONF_DEVICE_ID],
                    "action": config[CONF_TYPE],
                    "button": config[CONF_SUBTYPE],
                },
            }
        ),
        action,
        trigger_info,
        platform_type="device",
    )
