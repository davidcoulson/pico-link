"""Editing saved accent-light and STOP light presets in the options flow.

Presets are edited one at a time. Saving partway through must keep the
presets not yet shown, and removing the last one must be able to finish.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pico_link.const import DOMAIN

EFFECTS = ["Aurora", "Candle", "Comet", "Drift"]


@pytest.fixture(autouse=True)
def _lutron_caseta_loaded(hass, enable_custom_integrations):
    """Starting a flow sets up pico_link's dependencies; Lutron's needs hardware libs."""
    hass.config.components.add("lutron_caseta")


@pytest.fixture(autouse=True)
def _lights(hass):
    attributes = {"effect_list": EFFECTS, "supported_color_modes": ["rgb"]}
    hass.states.async_set("light.center", "off", attributes)
    hass.states.async_set("light.accent", "off", attributes)


def _accent(effect: str, brightness: int = 100) -> dict[str, Any]:
    return {
        "accent_light_effect": effect,
        "accent_light_brightness_pct": brightness,
        "accent_light_rgb_color": [255, 166, 0],
    }


def _light(effect: str, brightness: int = 100) -> dict[str, Any]:
    return {
        "light_preset_effect": effect,
        "light_preset_brightness_pct": brightness,
        "light_preset_rgb_color": [255, 166, 0],
    }


def _entry(hass, **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_ids": ["pico"], "type": "3BRL"},
        options={"lights": ["light.center"], **options},
    )
    entry.add_to_hass(hass)
    return entry


async def _open_accent_presets(hass, entry: MockConfigEntry):
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(
        result["flow_id"], {"next_step_id": "accent_light_quick"}
    )
    result = await flow.async_configure(
        result["flow_id"], {"accent_lights": entry.options.get("accent_lights", [])}
    )
    return result


async def _submit(hass, result, **user_input: Any):
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )


def _effects(presets: list[dict[str, Any]], key: str) -> list[str]:
    return [preset[key] for preset in presets]


# ----------------------------------------------------------------------
# Accent presets (dual-light mode)
# ----------------------------------------------------------------------


async def test_saving_the_first_accent_preset_keeps_the_others(hass):
    entry = _entry(
        hass,
        accent_lights=["light.accent"],
        accent_light_presets=[_accent("Aurora"), _accent("Candle"), _accent("Comet")],
    )

    result = await _open_accent_presets(hass, entry)
    assert result["step_id"] == "accent_light_appearance"

    result = await _submit(hass, result, **_accent("Aurora", 60), next_action="save")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    presets = entry.options["accent_light_presets"]
    assert _effects(presets, "accent_light_effect") == ["Aurora", "Candle", "Comet"]
    # The edited one took the change; the untouched ones are unchanged.
    assert presets[0]["accent_light_brightness_pct"] == 60
    assert presets[1] == _accent("Candle")


async def test_saving_partway_through_keeps_the_rest(hass):
    entry = _entry(
        hass,
        accent_lights=["light.accent"],
        accent_light_presets=[_accent("Aurora"), _accent("Candle"), _accent("Comet")],
    )

    result = await _open_accent_presets(hass, entry)
    result = await _submit(hass, result, **_accent("Aurora"), next_action="add_another")
    result = await _submit(hass, result, **_accent("Drift"), next_action="save")

    assert _effects(entry.options["accent_light_presets"], "accent_light_effect") == [
        "Aurora",
        "Drift",
        "Comet",
    ]


async def test_removing_an_accent_preset_moves_on_to_the_next(hass):
    entry = _entry(
        hass,
        accent_lights=["light.accent"],
        accent_light_presets=[_accent("Aurora"), _accent("Candle"), _accent("Comet")],
    )

    result = await _open_accent_presets(hass, entry)
    result = await _submit(hass, result, **_accent("Aurora"), next_action="remove")
    assert result["step_id"] == "accent_light_appearance"
    result = await _submit(hass, result, **_accent("Candle"), next_action="save")

    assert _effects(entry.options["accent_light_presets"], "accent_light_effect") == [
        "Candle",
        "Comet",
    ]


async def test_removing_the_last_accent_preset_finishes(hass):
    entry = _entry(
        hass,
        accent_lights=["light.accent"],
        accent_light_presets=[_accent("Aurora"), _accent("Candle")],
    )

    result = await _open_accent_presets(hass, entry)
    result = await _submit(hass, result, **_accent("Aurora"), next_action="add_another")
    result = await _submit(hass, result, **_accent("Candle"), next_action="remove")

    # Previously this showed a blank preset that Save then added back.
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _effects(entry.options["accent_light_presets"], "accent_light_effect") == [
        "Aurora"
    ]


async def test_removing_the_only_accent_preset_asks_for_a_new_one(hass):
    entry = _entry(
        hass,
        accent_lights=["light.accent"],
        accent_light_presets=[_accent("Aurora")],
    )

    result = await _open_accent_presets(hass, entry)
    result = await _submit(hass, result, **_accent("Aurora"), next_action="remove")

    # Dual-light mode needs at least one preset, so a blank one is offered.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "accent_light_appearance"


# ----------------------------------------------------------------------
# STOP light presets (3BRL)
# ----------------------------------------------------------------------


async def test_saving_the_first_light_preset_keeps_the_others(hass):
    entry = _entry(
        hass,
        light_presets=[_light("Aurora"), _light("Candle"), _light("Comet")],
    )

    result = await _open_accent_presets(hass, entry)
    assert result["step_id"] == "light_presets"

    result = await _submit(
        hass,
        result,
        **_light("Aurora", 40),
        cycle_light_presets=True,
        next_action="save",
    )
    # A full light-presets edit continues to custom actions; save that too.
    if result["type"] is FlowResultType.FORM:
        result = await _submit(hass, result)

    presets = entry.options["light_presets"]
    assert _effects(presets, "light_preset_effect") == ["Aurora", "Candle", "Comet"]
    assert presets[0]["light_preset_brightness_pct"] == 40


async def test_removing_the_last_light_preset_finishes(hass):
    entry = _entry(hass, light_presets=[_light("Aurora"), _light("Candle")])

    result = await _open_accent_presets(hass, entry)
    result = await _submit(
        hass,
        result,
        **_light("Aurora"),
        cycle_light_presets=True,
        next_action="add_another",
    )
    result = await _submit(hass, result, **_light("Candle"), next_action="remove")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _effects(entry.options["light_presets"], "light_preset_effect") == ["Aurora"]


async def test_removing_the_only_light_preset_turns_cycling_off(hass):
    entry = _entry(hass, light_presets=[_light("Aurora")])

    result = await _open_accent_presets(hass, entry)
    result = await _submit(
        hass,
        result,
        **_light("Aurora"),
        cycle_light_presets=True,
        next_action="remove",
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["light_presets"] == []
