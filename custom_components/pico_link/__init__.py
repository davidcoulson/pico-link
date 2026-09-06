# __init__.py — Integration entry point
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback

from .config import parse_pico_config
from .const import DOMAIN
from .controller import PicoController

_LOGGER = logging.getLogger(__name__)

type PicoLinkConfigEntry = ConfigEntry[list[PicoController]]


def _entry_device_ids(entry: PicoLinkConfigEntry) -> list[str]:
    """
    Return the device IDs a config entry represents.

    Entries created before multi-device support stored a single
    "device_id"; current entries store a "device_ids" list. Both are
    supported here so existing entries keep working without migration.
    """
    device_ids = entry.data.get("device_ids")

    if device_ids:
        return device_ids

    return [entry.data["device_id"]]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> bool:
    """Set up every identically-configured Pico in a config entry."""
    controllers: list[PicoController] = []

    for device_id in _entry_device_ids(entry):
        device_raw = {
            "device_id": device_id,
            "type": entry.data["type"],
            **entry.options,
        }

        try:
            pico_config = await parse_pico_config(
                hass,
                device_raw,
            )
        except ValueError as err:
            _LOGGER.error(
                "%s: invalid configuration for entry %s (device %s): %s",
                DOMAIN,
                entry.entry_id,
                device_id,
                err,
            )

            for started in controllers:
                await started.async_stop()

            return False

        controller = PicoController(
            hass,
            pico_config,
        )

        await controller.async_start()
        controllers.append(controller)

    entry.runtime_data = controllers

    # Make sure Pico work is unsubscribed and stopped on a clean HA
    # shutdown, not just on entry unload. Must be a @callback so the
    # event bus invokes it directly on the event loop rather than in
    # an executor thread, since it calls hass.async_create_task.
    @callback
    def _handle_stop(_event: Event) -> None:
        for controller in controllers:
            hass.async_create_task(controller.async_stop())

    unsub_stop = hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP,
        _handle_stop,
    )
    entry.async_on_unload(unsub_stop)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> bool:
    """Unload a Pico config entry."""
    for controller in entry.runtime_data:
        await controller.async_stop()

    return True


async def _async_update_listener(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> None:
    """Reload a Pico when its options are edited."""
    await hass.config_entries.async_reload(entry.entry_id)
