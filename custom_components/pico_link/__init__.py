# __init__.py — Integration entry point
from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED

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


_ENTITY_FIELDS = (
    "covers",
    "fans",
    "lights",
    "media_players",
    "switches",
    "accent_lights",
)


def _entry_entity_ids(entry: PicoLinkConfigEntry) -> list[str]:
    """Return every entity ID configured in a Pico Link entry's options."""
    entity_ids: list[str] = []

    for field in _ENTITY_FIELDS:
        value = entry.options.get(field)

        if isinstance(value, list):
            entity_ids.extend(value)

    return entity_ids


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
    entry.async_on_unload(_watch_for_missing_entities(hass, entry))

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


def _pico_entity_missing_issue_id(entry_id: str) -> str:
    return f"pico_entity_missing_{entry_id}"


def _watch_for_missing_entities(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> Callable[[], None]:
    """
    Raise a repair issue for any configured entity no longer in the entity registry.

    A deleted or renamed light/cover/fan/media player/switch (including
    an accent light) otherwise fails silently — the service call this
    entry's Picos make against it just does nothing. The initial check
    waits for Home Assistant to finish starting so slower-loading
    integrations aren't flagged as "missing" before they've registered
    their entities; it runs immediately for an entry set up (or reloaded)
    after that, and again whenever the entity registry changes.
    """
    tracked = set(_entry_entity_ids(entry))
    issue_id = _pico_entity_missing_issue_id(entry.entry_id)

    if not tracked:
        return lambda: None

    entity_registry = er.async_get(hass)

    def _check() -> None:
        missing = sorted(
            entity_id for entity_id in tracked if entity_registry.async_get(entity_id) is None
        )

        if missing:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="pico_entity_missing",
                translation_placeholders={
                    "title": entry.title,
                    "entities": ", ".join(missing),
                },
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    if hass.is_running:
        _check()
    else:
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED,
            lambda _event: _check(),
        )

    @callback
    def _handle_entity_registry_updated(event: Event) -> None:
        if (
            event.data.get("entity_id") in tracked
            or event.data.get("old_entity_id") in tracked
        ):
            _check()

    return hass.bus.async_listen(
        EVENT_ENTITY_REGISTRY_UPDATED,
        _handle_entity_registry_updated,
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

    ir.async_delete_issue(hass, DOMAIN, _pico_entity_missing_issue_id(entry.entry_id))

    return True


async def _async_update_listener(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> None:
    """Reload a Pico when its options are edited."""
    await hass.config_entries.async_reload(entry.entry_id)
