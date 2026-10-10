from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_KEY = f"{DOMAIN}.memory"
STORAGE_VERSION = 1
SAVE_DELAY_SECONDS = 5


class PicoLinkStore:
    """Small persisted state, keyed by config entry, that survives HA restarts."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        self._data = await self._store.async_load() or {}

    def get(self, entry_id: str, key: str) -> Any:
        return self._data.get(entry_id, {}).get(key)

    def set(self, entry_id: str, key: str, value: Any) -> None:
        entry = self._data.setdefault(entry_id, {})

        if entry.get(key) == value:
            return

        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value

        # Delayed saves are flushed on HA shutdown, so rapid RAISE/LOWER
        # taps coalesce into one write without losing the last one.
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY_SECONDS)

    def remove_entry(self, entry_id: str) -> None:
        if self._data.pop(entry_id, None) is not None:
            self._store.async_delay_save(self._data_to_save, SAVE_DELAY_SECONDS)

    def _data_to_save(self) -> dict[str, dict[str, Any]]:
        # Store serialises in an executor thread, so hand it a snapshot
        # rather than the live dicts: a set() landing on the event loop
        # mid-serialisation would otherwise raise "dictionary changed
        # size during iteration" and lose the save. Values are scalars,
        # so a copy one level down is enough.
        return {entry_id: dict(entry) for entry_id, entry in self._data.items()}


class EntryMemory:
    """One config entry's view of PicoLinkStore, shared by all its Picos."""

    def __init__(self, store: PicoLinkStore, entry_id: str) -> None:
        self._store = store
        self._entry_id = entry_id

        # Shared by the entry's Picos but not persisted; starts empty
        # after a restart or reload.
        self.runtime: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._store.get(self._entry_id, key)

    def set(self, key: str, value: Any) -> None:
        self._store.set(self._entry_id, key, value)


class SharedTarget:
    """
    What this entry's Picos last asked an entity for, trusted only briefly.

    Lights, fans, covers and players can take a moment to report a new
    state, so a quick second tap steps on from what was last requested
    instead of repeating the first step from the old state. The request
    is shared by all of the entry's Picos, which control the same
    entities, so that holds whichever remote sent it. After max_age
    seconds the entity's reported state decides again.

    Kept in the entry's runtime dict, so it starts empty after a restart
    or reload.
    """

    def __init__(self, runtime: dict[str, Any], key: str, max_age: float) -> None:
        self._runtime = runtime
        self._key = key
        self._max_age = max_age

    def get(self) -> Any:
        """Return the last requested value while it's fresh, else None."""
        request = self._runtime.get(self._key)

        if request is None or time.monotonic() - request[1] > self._max_age:
            return None

        return request[0]

    def set(self, value: Any) -> Callable[[], None]:
        """
        Record a new request, and return a callable that withdraws it.

        Pass that to the service call as on_failure: a step that didn't
        happen mustn't be built on. It withdraws only this request, never
        a newer one made since.
        """
        request = (value, time.monotonic())
        self._runtime[self._key] = request

        def withdraw() -> None:
            if self._runtime.get(self._key) is request:
                del self._runtime[self._key]

        return withdraw

    def clear(self) -> None:
        """Forget the request, so the entity's reported state decides."""
        self._runtime.pop(self._key, None)
