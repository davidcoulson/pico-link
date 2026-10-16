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


async def test_diagnostics_omit_arbitrary_action_trees_and_failure_text(hass):
    import json

    secret = "dummy-secret-123"
    action = [
        {"variables": {"innocent_name": secret}},
        {
            "action": "rest_command.test",
            "data": {
                "url": f"https://example.invalid/{secret}",
                "nested": [{"pin": secret}],
            },
        },
    ]
    options = {
        **OPTIONS,
        **{
            field: action
            for field in (
                "middle_button",
                "on_hold",
                "off_hold",
                "stop_hold",
                "on_double_tap",
                "off_double_tap",
                "stop_double_tap",
            )
        },
        **{
            field: {"button_1": action}
            for field in ("buttons", "button_hold", "button_double_tap")
        },
        # Unknown future action fields must not accidentally be exported.
        "future_action_field": action,
    }
    entry = MockConfigEntry(
        domain="pico_link", data=DATA, options=options, reason=secret
    )
    entry.add_to_hass(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert secret not in json.dumps(diagnostics)
    assert "innocent_name" not in json.dumps(diagnostics)
    assert diagnostics["options"]["lights"] == OPTIONS["lights"]
