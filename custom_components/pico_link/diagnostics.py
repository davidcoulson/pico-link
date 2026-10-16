# diagnostics.py — downloadable diagnostics for a Pico Link config entry
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN_ENTITY_FIELDS

if TYPE_CHECKING:
    from . import PicoLinkConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: "PicoLinkConfigEntry",
) -> dict[str, Any]:
    """
    Return diagnostics for one Pico Link config entry.

    Only export device and entity selections from configuration. Action
    trees may contain secrets under arbitrary keys, so an allowlist keeps
    their contents (including future action fields) out of diagnostics.
    Free-text setup failure reasons can contain action data too.

    Works for an entry that failed to set up too -- when diagnostics are
    most wanted -- which has no runtime_data, so no running Picos.
    """
    controllers = getattr(entry, "runtime_data", None) or []

    return {
        "title": entry.title,
        "state": entry.state.value,
        "data": {
            key: entry.data[key]
            for key in ("device_ids", "device_id", "type")
            if key in entry.data
        },
        "options": {
            key: entry.options[key]
            for key in (*DOMAIN_ENTITY_FIELDS.values(), "accent_lights")
            if key in entry.options
        },
        "picos": [
            {
                "device_id": controller.conf.device_id,
                "type": controller.conf.type,
                "domain": controller.utils.entity_domain(),
            }
            for controller in controllers
        ],
    }
