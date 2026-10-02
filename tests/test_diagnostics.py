"""Downloadable diagnostics for a Pico Link entry."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pico_link.config import PicoConfig
from custom_components.pico_link.controller import PicoController
from custom_components.pico_link.diagnostics import async_get_config_entry_diagnostics
from custom_components.pico_link.memory import EntryMemory, PicoLinkStore

DATA = {"device_ids": ["pico"], "type": "3BRL"}
OPTIONS = {"lights": ["light.gym"]}


async def test_an_entry_that_failed_to_set_up_still_gives_diagnostics(hass):
    """No runtime_data exists then, which previously raised AttributeError."""
    entry = MockConfigEntry(
        domain="pico_link",
        data=DATA,
        options=OPTIONS,
        state=ConfigEntryState.SETUP_ERROR,
    )
    entry.add_to_hass(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["state"] == "setup_error"
    assert diagnostics["options"] == OPTIONS
    assert diagnostics["picos"] == []


async def test_a_loaded_entry_lists_its_picos(hass):
    entry = MockConfigEntry(
        domain="pico_link",
        data=DATA,
        options=OPTIONS,
        state=ConfigEntryState.LOADED,
    )
    entry.add_to_hass(hass)

    conf = PicoConfig(device_id="pico", type="3BRL", lights=["light.gym"])
    entry.runtime_data = [
        PicoController(hass, conf, EntryMemory(PicoLinkStore(hass), entry.entry_id))
    ]

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["state"] == "loaded"
    assert diagnostics["picos"] == [
        {"device_id": "pico", "type": "3BRL", "domain": "light"}
    ]
