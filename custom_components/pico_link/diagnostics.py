# diagnostics.py — downloadable diagnostics for a Pico Link config entry
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import PicoLinkConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: "PicoLinkConfigEntry",
) -> dict[str, Any]:
    """
    Return diagnostics for one Pico Link config entry.

    Nothing here needs redacting: entry data/options are Pico type,
    device IDs, entity IDs, and timing/behavior values — no credentials
    or personal data.
    """
    return {
        "title": entry.title,
        "data": dict(entry.data),
        "options": dict(entry.options),
        "picos": [
            {
                "device_id": controller.conf.device_id,
                "type": controller.conf.type,
                "domain": controller.utils.entity_domain(),
            }
            for controller in entry.runtime_data
        ],
    }
