from __future__ import annotations

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
