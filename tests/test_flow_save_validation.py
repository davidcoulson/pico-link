"""Final saves validate configuration and current Pico ownership offline."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pico_link.config import parse_pico_config
from custom_components.pico_link.config_flow import (
    PicoLinkConfigFlow,
    PicoLinkOptionsFlow,
)
from custom_components.pico_link.const import DOMAIN


def _entry(hass, devices=None, **options):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_ids": devices or ["pico"], "type": "3BRL"},
        options={"lights": ["light.lamp"], **options},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize("setting", ["light_hold_color_temp", "light_effects"])
async def test_leaving_lights_removes_light_only_settings(hass, setting):
    entry = _entry(hass, **{setting: True if setting.endswith("temp") else ["Candle"]})
    flow = PicoLinkOptionsFlow(entry)
    flow.hass = hass
    await flow.async_step_entities({"fans": ["fan.test"]})
    await parse_pico_config(
        hass, {**flow._options, "device_id": "pico", "type": "3BRL"}
    )
    assert setting not in flow._options


@pytest.mark.parametrize("field", ["middle_button", "on_hold", "off_double_tap"])
async def test_options_reject_invalid_actions_without_overwriting(hass, field):
    entry = _entry(hass)
    flow = PicoLinkOptionsFlow(entry)
    flow.hass = hass
    invalid = [{"action": "notvalid"}]
    result = await flow.async_step_custom_actions({field: invalid})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_configuration"}
    assert field not in entry.options
    assert flow._options[field] == invalid


async def test_new_scene_rejects_invalid_nested_actions(hass):
    flow = PicoLinkConfigFlow()
    flow.hass = hass
    flow._device_ids = ["pico"]
    flow._type = "4B"
    result = await flow.async_step_buttons({"button_1": [{"action": "notvalid"}]})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_configuration"}


@pytest.mark.parametrize("editing", [False, True])
async def test_save_rechecks_ownership_after_async_validation(hass, editing):
    entry = _entry(hass) if editing else None
    flow = PicoLinkOptionsFlow(entry) if editing else PicoLinkConfigFlow()
    flow.hass = hass
    flow._device_ids = ["pico", "other"]
    flow._type = "3BRL"
    flow._options = {"lights": ["light.lamp"]}

    async def claim(*args, **kwargs):
        _entry(hass, devices=["pico", "third"])

    # Another flow finishes while HA validates this one's actions.
    with patch(
        "custom_components.pico_link.config_flow.parse_pico_config",
        new=AsyncMock(side_effect=claim),
        create=True,
    ):
        result = (
            await flow.async_step_custom_actions({})
            if editing
            else await flow.async_step_entities({"lights": ["light.lamp"]})
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "device_already_configured"}
    if entry:
        assert entry.data["device_ids"] == ["pico"]


async def test_valid_action_is_prepared_but_never_executed_on_save(hass):
    entry = _entry(hass)
    flow = PicoLinkOptionsFlow(entry)
    flow.hass = hass
    with patch("homeassistant.helpers.script.Script.async_run") as run:
        result = await flow.async_step_custom_actions(
            {
                "middle_button": [
                    {"action": "light.turn_on", "target": {"entity_id": "lights"}}
                ]
            }
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    run.assert_not_called()
