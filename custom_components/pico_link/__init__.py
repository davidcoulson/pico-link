# __init__.py — Integration entry point
from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED

from .config import parse_pico_config
from .const import DOMAIN
from .controller import PicoController

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
            for started in controllers:
                await started.async_stop()

            # ConfigEntryError surfaces str(err) directly on the entry
            # (visible in the UI and via ha_get_integration's "reason"),
            # instead of only a bare "Setup failed" that requires
            # checking the log. Home Assistant logs the full exception
            # itself when it catches this.
            raise ConfigEntryError(
                f"Invalid configuration for device {device_id}: {err}"
            ) from err

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
    entry.async_on_unload(_watch_for_removed_devices(hass, entry))

    return True


def _pico_removed_issue_id(device_id: str) -> str:
    return f"pico_removed_{device_id}"


def _watch_for_removed_devices(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> Callable[[], None]:
    """
    Raise a repair issue for any configured Pico no longer in the device registry.

    Checks once immediately (catching a Pico removed while HA was
    offline, or before this check existed) and again whenever the
    device registry changes, so a repair issue appears if a Pico's
    device is removed and clears itself if the device comes back.
    """
    device_ids = set(_entry_device_ids(entry))
    device_registry = dr.async_get(hass)

    def _check() -> None:
        for device_id in device_ids:
            issue_id = _pico_removed_issue_id(device_id)

            if device_registry.async_get(device_id) is None:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="pico_removed",
                    translation_placeholders={
                        "title": entry.title,
                        "device_id": device_id,
                    },
                )
            else:
                ir.async_delete_issue(hass, DOMAIN, issue_id)

    _check()

    @callback
    def _handle_device_registry_updated(event: Event) -> None:
        if event.data.get("device_id") in device_ids:
            _check()

    return hass.bus.async_listen(
        EVENT_DEVICE_REGISTRY_UPDATED,
        _handle_device_registry_updated,
    )


async def async_unload_entry(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> bool:
    """Unload a Pico config entry."""
    for controller in entry.runtime_data:
        await controller.async_stop()

    for device_id in _entry_device_ids(entry):
        ir.async_delete_issue(hass, DOMAIN, _pico_removed_issue_id(device_id))

    return True


async def _async_update_listener(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> None:
    """Reload a Pico when its options are edited."""
    await hass.config_entries.async_reload(entry.entry_id)
