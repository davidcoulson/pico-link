"""The options flow's handling of light_hold_color_temp and light_effects."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pico_link.const import DOMAIN

_ACTION = [{"action": "light.turn_on", "target": {"entity_id": "light.lamp"}}]


@pytest.fixture(autouse=True)
def _lutron_caseta_loaded(hass):
    """Starting a flow sets up pico_link's dependencies; Lutron's needs hardware libs."""
    hass.config.components.add("lutron_caseta")


def _entry(hass, pico_type: str, **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_ids": ["pico"], "type": pico_type},
        options={"lights": ["light.gym"], **options},
    )
    entry.add_to_hass(hass)
    return entry


async def _menu(hass, entry: MockConfigEntry) -> list[str]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    menu = list(result["menu_options"])
    hass.config_entries.options.async_abort(result["flow_id"])
    return menu


async def _timing_and_behavior(hass, entry: MockConfigEntry, **user_input: Any):
    """Open Timing & behavior from the menu and submit it."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "options_quick"}
    )
    assert result["step_id"] == "options"

    return result, await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )


async def test_toggle_offered_only_on_raise_lower_picos(
    hass, enable_custom_integrations
):
    for pico_type, offered in (("2BRL", True), ("3BRL", True), ("P2B", False)):
        entry = _entry(hass, pico_type)

        form, _ = await _timing_and_behavior(hass, entry)

        assert ("light_hold_color_temp" in form["data_schema"].schema) is offered


async def test_enabling_saves_and_hides_a_2brls_empty_custom_actions(
    hass, enable_custom_integrations
):
    entry = _entry(hass, "2BRL")
    assert "custom_actions" in await _menu(hass, entry)

    _, result = await _timing_and_behavior(hass, entry, light_hold_color_temp=True)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["light_hold_color_temp"] is True
    # Every 2BRL custom action is an ON/OFF one, so nothing is left.
    assert "custom_actions" not in await _menu(hass, entry)


async def test_enabling_is_refused_while_on_off_custom_actions_exist(
    hass, enable_custom_integrations
):
    entry = _entry(hass, "2BRL", on_hold=_ACTION)

    _, result = await _timing_and_behavior(hass, entry, light_hold_color_temp=True)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "hold_color_temp_custom_actions_conflict"}
    assert "light_hold_color_temp" not in entry.options


async def test_enabling_is_refused_alongside_an_accent_light(
    hass, enable_custom_integrations
):
    entry = _entry(hass, "3BRL", accent_lights=["light.accent"])

    _, result = await _timing_and_behavior(hass, entry, light_hold_color_temp=True)

    assert result["errors"] == {"base": "hold_color_temp_accent_light_conflict"}


async def test_3brl_custom_actions_keep_stop_and_drop_on_off(
    hass, enable_custom_integrations
):
    entry = _entry(hass, "3BRL", light_hold_color_temp=True)
    assert "custom_actions" in await _menu(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "custom_actions"}
    )
    fields = {str(key) for key in result["data_schema"].schema}

    assert {"middle_button", "stop_hold", "stop_double_tap"} <= fields
    assert not fields & {"on_hold", "off_hold", "on_double_tap", "off_double_tap"}

    # Saving it keeps the toggle and STOP's actions.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"middle_button": _ACTION}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["light_hold_color_temp"] is True
    assert entry.options["middle_button"] == _ACTION


async def test_accent_light_refused_once_enabled(hass, enable_custom_integrations):
    entry = _entry(hass, "3BRL", light_hold_color_temp=True)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "accent_light_quick"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"accent_lights": ["light.accent"]}
    )

    assert result["errors"] == {"base": "hold_color_temp_accent_light_conflict"}


def _light_with_effects(hass, effects: list[str] | None) -> None:
    attributes = {"effect_list": effects} if effects is not None else {}
    hass.states.async_set("light.gym", "on", attributes)


async def test_effects_picker_offers_the_lights_own_effects(
    hass, enable_custom_integrations
):
    _light_with_effects(hass, ["Solid", "aurora", "Candle"])

    for pico_type, offered in (("2BRL", True), ("3BRL", True), ("P2B", False)):
        form, _ = await _timing_and_behavior(hass, _entry(hass, pico_type))
        schema = form["data_schema"].schema

        assert ("light_effects" in schema) is offered

        if offered:
            picker = next(v for k, v in schema.items() if k == "light_effects")
            # Sorted case-insensitively, like the other effect pickers.
            assert picker.config["options"] == ["aurora", "Candle", "Solid"]


async def test_effects_picker_hidden_for_a_light_without_effects(
    hass, enable_custom_integrations
):
    _light_with_effects(hass, None)

    form, _ = await _timing_and_behavior(hass, _entry(hass, "3BRL"))

    assert "light_effects" not in form["data_schema"].schema


async def test_effects_save_in_the_order_picked(hass, enable_custom_integrations):
    _light_with_effects(hass, ["Aurora", "Candle", "Solid"])
    entry = _entry(hass, "3BRL")

    _, result = await _timing_and_behavior(
        hass, entry, light_effects=["Solid", "Candle", "Aurora"]
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["light_effects"] == ["Solid", "Candle", "Aurora"]


async def test_a_saved_effect_the_light_dropped_stays_selectable(
    hass, enable_custom_integrations
):
    _light_with_effects(hass, ["Aurora", "Solid"])
    entry = _entry(hass, "3BRL", light_effects=["Solid", "Retired"])

    form, result = await _timing_and_behavior(
        hass, entry, light_effects=["Solid", "Retired"]
    )

    picker = next(
        v for k, v in form["data_schema"].schema.items() if k == "light_effects"
    )
    assert "Retired" in picker.config["options"]
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_effects_refused_alongside_an_accent_light(
    hass, enable_custom_integrations
):
    _light_with_effects(hass, ["Aurora", "Solid"])
    entry = _entry(hass, "3BRL", accent_lights=["light.accent"])

    _, result = await _timing_and_behavior(hass, entry, light_effects=["Solid"])

    assert result["errors"] == {"base": "light_effects_accent_light_conflict"}


async def test_accent_light_refused_once_effects_are_set(
    hass, enable_custom_integrations
):
    entry = _entry(hass, "3BRL", light_effects=["Solid"])

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "accent_light_quick"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"accent_lights": ["light.accent"]}
    )

    assert result["errors"] == {"base": "light_effects_accent_light_conflict"}
