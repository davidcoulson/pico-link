# __init__.py — Integration entry point
from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.helpers.event import async_track_state_change_event

from .config import parse_pico_config
from .const import DOMAIN
from .controller import PicoController, type_mismatch_issue_id
from .memory import EntryMemory, PicoLinkStore

type PicoLinkConfigEntry = ConfigEntry[list[PicoController]]


async def _async_get_store(hass: HomeAssistant) -> PicoLinkStore:
    """
    Return the store shared by every Pico Link entry, loading it once.

    Entries set up concurrently would each see no store yet, load their
    own copy of the same file and then overwrite each other's writes, so
    the first caller parks the load as a task in hass.data and every
    other caller awaits that same task.
    """
    load_task: asyncio.Task[PicoLinkStore] | None = hass.data.get(DOMAIN)

    if load_task is None:
        load_task = hass.async_create_task(_async_load_store(hass))
        hass.data[DOMAIN] = load_task

    try:
        return await load_task
    except Exception:
        # Leave nothing behind so the next setup attempt retries the
        # load instead of re-raising this failure forever.
        if hass.data.get(DOMAIN) is load_task:
            hass.data.pop(DOMAIN)

        raise


async def _async_load_store(hass: HomeAssistant) -> PicoLinkStore:
    store = PicoLinkStore(hass)
    await store.async_load()

    return store


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

    store = await _async_get_store(hass)
    memory = EntryMemory(store, entry.entry_id)
    device_ids = _entry_device_ids(entry)

    # Every Pico in an entry shares the same options, so validate them
    # once (action validation walks the whole action tree) and stamp
    # each device ID onto a copy instead of re-parsing per Pico.
    try:
        shared_config = await parse_pico_config(
            hass,
            {
                "device_id": device_ids[0],
                "type": entry.data["type"],
                **entry.options,
            },
        )
    except ValueError as err:
        # ConfigEntryError surfaces str(err) directly on the entry
        # (visible in the UI and via ha_get_integration's "reason"),
        # instead of only a bare "Setup failed" that requires checking
        # the log. Home Assistant logs the full exception itself when
        # it catches this.
        raise ConfigEntryError(f"Invalid configuration: {err}") from err

    _sync_device_links(hass, entry, device_ids)

    try:
        for device_id in device_ids:
            controller = PicoController(
                hass,
                dataclasses.replace(shared_config, device_id=device_id),
                memory,
            )

            await controller.async_start()
            controllers.append(controller)
    except Exception:
        # Whatever failed for a later device (config, construction or
        # start), the controllers already started would otherwise keep
        # their bus subscriptions alive with no entry to unload them.
        for started in controllers:
            await started.async_stop()

        raise

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


def _sync_device_links(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
    device_ids: list[str],
) -> None:
    """
    Link this entry to its Pico devices in the device registry.

    Home Assistant only offers an integration's device triggers for
    devices that carry one of its config entries (or its entities).
    The Picos themselves belong to lutron_caseta, so without this link
    device_trigger.py is never consulted and the "Device -> <Pico> ->
    button pressed" options never appear in the automation editor. A
    Pico dropped from the entry on the devices step is unlinked here
    too; deleting the entry unlinks everything via Home Assistant's own
    config-entry cleanup.
    """
    device_registry = dr.async_get(hass)
    wanted = set(device_ids)

    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if device.id not in wanted:
            device_registry.async_update_device(
                device.id,
                remove_config_entry_id=entry.entry_id,
            )

    for device_id in device_ids:
        device = device_registry.async_get(device_id)

        # A Pico removed from Lutron is reported by _watch_for_removed_devices.
        if device is None or entry.entry_id in device.config_entries:
            continue

        device_registry.async_update_device(
            device_id,
            add_config_entry_id=entry.entry_id,
        )


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
    def _handle_device_registry_updated(_event: Event) -> None:
        _check()

    # Filtered inline in the bus so other devices' registry events don't
    # schedule a callback per entry.
    @callback
    def _is_tracked_device(event_data: Mapping[str, Any]) -> bool:
        return event_data.get("device_id") in device_ids

    return hass.bus.async_listen(
        EVENT_DEVICE_REGISTRY_UPDATED,
        _handle_device_registry_updated,
        event_filter=_is_tracked_device,
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
    after that, and again whenever the entity registry changes or a
    tracked entity appears in or disappears from the state machine.

    An entity counts as present if either the entity registry or the
    state machine knows it: entities without a unique_id (YAML template
    lights, some groups) never get a registry entry but work fine.
    """
    tracked = set(_entry_entity_ids(entry))
    issue_id = _pico_entity_missing_issue_id(entry.entry_id)

    if not tracked:
        return lambda: None

    entity_registry = er.async_get(hass)

    def _is_present(entity_id: str) -> bool:
        return (
            entity_registry.async_get(entity_id) is not None
            or hass.states.get(entity_id) is not None
        )

    def _check() -> None:
        missing = sorted(entity_id for entity_id in tracked if not _is_present(entity_id))

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

    unsub_started: Callable[[], None] | None = None

    @callback
    def _handle_started(_event: Event) -> None:
        # Fired: the handle is spent, and Home Assistant logs an error
        # for a once-listener removed a second time.
        nonlocal unsub_started
        unsub_started = None
        _check()

    if hass.is_running:
        _check()
    else:
        unsub_started = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED,
            _handle_started,
        )

    @callback
    def _handle_entity_registry_updated(_event: Event) -> None:
        _check()

    # Filtered inline in the bus so other entities' registry events
    # don't schedule a callback per entry.
    @callback
    def _is_tracked_entity(event_data: Mapping[str, Any]) -> bool:
        return (
            event_data.get("entity_id") in tracked
            or event_data.get("old_entity_id") in tracked
        )

    unsub_registry = hass.bus.async_listen(
        EVENT_ENTITY_REGISTRY_UPDATED,
        _handle_entity_registry_updated,
        event_filter=_is_tracked_entity,
    )

    @callback
    def _handle_state_changed(event: Event) -> None:
        # Only an entity appearing or disappearing matters here, not
        # its ordinary on/off/brightness changes.
        if event.data.get("old_state") is None or event.data.get("new_state") is None:
            _check()

    unsub_states = async_track_state_change_event(
        hass,
        tracked,
        _handle_state_changed,
    )

    @callback
    def _unsubscribe() -> None:
        # Drop the pending startup check too, so an entry unloaded before
        # Home Assistant finished starting doesn't run it later against
        # this stale tracked set.
        if unsub_started is not None:
            unsub_started()

        unsub_registry()
        unsub_states()

    return _unsubscribe


async def async_unload_entry(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> bool:
    """Unload a Pico config entry."""
    for controller in entry.runtime_data:
        await controller.async_stop()

    for device_id in _entry_device_ids(entry):
        ir.async_delete_issue(hass, DOMAIN, _pico_removed_issue_id(device_id))
        ir.async_delete_issue(hass, DOMAIN, type_mismatch_issue_id(device_id))

    ir.async_delete_issue(hass, DOMAIN, _pico_entity_missing_issue_id(entry.entry_id))

    return True


async def async_remove_entry(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> None:
    """Forget a deleted entry's remembered state."""
    store = await _async_get_store(hass)

    store.remove_entry(entry.entry_id)


async def _async_update_listener(
    hass: HomeAssistant,
    entry: PicoLinkConfigEntry,
) -> None:
    """Reload a Pico when its options are edited."""
    await hass.config_entries.async_reload(entry.entry_id)
