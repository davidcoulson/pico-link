"""The options flow's "Test an action" runs actions exactly as the Pico would."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pico_link.const import DOMAIN


@pytest.fixture(autouse=True)
def _lutron_caseta_loaded(hass, enable_custom_integrations):
    """Starting a flow sets up pico_link's dependencies; Lutron's needs hardware libs."""
    hass.config.components.add("lutron_caseta")


@pytest.fixture
def light_calls(hass) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def turn_on(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("light", "turn_on", turn_on)
    hass.states.async_set("light.gym", "on")
    return calls


async def _test_from_custom_actions(hass, field: str, actions: list[dict[str, Any]]):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_ids": ["pico"], "type": "3BRL"},
        options={"lights": ["light.gym"]},
    )
    entry.add_to_hass(hass)

    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(
        result["flow_id"], {"next_step_id": "custom_actions"}
    )
    result = await flow.async_configure(
        result["flow_id"], {field: actions, "test_action": field}
    )
    await hass.async_block_till_done()
    return result


async def test_a_placeholder_target_expands_like_it_does_at_runtime(hass, light_calls):
    result = await _test_from_custom_actions(
        hass,
        "middle_button",
        [{"action": "light.turn_on", "target": {"entity_id": "lights"}}],
    )

    # Previously: "Template rendered invalid entity IDs: lights".
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    assert light_calls == [{"entity_id": ["light.gym"]}]


async def test_a_template_is_rendered_not_sent_as_text(hass, light_calls):
    result = await _test_from_custom_actions(
        hass,
        "stop_hold",
        [
            {
                "action": "light.turn_on",
                "target": {"entity_id": "light.gym"},
                "data": {"brightness_pct": "{{ 40 + 10 }}"},
            }
        ],
    )

    assert result["errors"] == {}
    # Previously the light received the literal string "{{ 40 + 10 }}".
    assert light_calls == [{"entity_id": ["light.gym"], "brightness_pct": 50}]


async def test_an_invalid_action_reports_failure_without_running(hass, light_calls):
    result = await _test_from_custom_actions(
        hass,
        "middle_button",
        [{"action": "light.turn_on", "target": {"entity_id": "not an entity"}}],
    )

    assert result["errors"] == {"base": "test_action_failed"}
    assert light_calls == []


async def test_4b_scene_actions_get_no_placeholder_expansion(hass, light_calls):
    """A 4B controls no entities, so "lights" isn't a placeholder there at runtime."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_ids": ["pico"], "type": "4B"},
        options={"buttons": {"button_1": [{"action": "light.turn_on"}]}},
    )
    entry.add_to_hass(hass)

    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(
        result["flow_id"], {"next_step_id": "scene_hold_actions"}
    )
    result = await flow.async_configure(
        result["flow_id"],
        {
            "button_1_hold": [
                {"action": "light.turn_on", "target": {"entity_id": "lights"}}
            ],
            "test_action": "button_1_hold",
        },
    )
    await hass.async_block_till_done()

    # Saving this would fail validation too, so the preview agrees.
    assert result["errors"] == {"base": "test_action_failed"}
    assert light_calls == []
