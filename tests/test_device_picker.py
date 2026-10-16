"""The Pico pickers in the config and options flows."""

from __future__ import annotations

import pytest
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pico_link.config_flow import _eligible_pico_devices
from custom_components.pico_link.const import DOMAIN

MODEL_3BRL = "PJ2-3BRL-GXX-X01 (Pico3ButtonRaiseLower)"


@pytest.fixture(autouse=True)
def _lutron_caseta_loaded(hass, enable_custom_integrations):
    """Starting a flow sets up pico_link's dependencies; Lutron's needs hardware libs."""
    hass.config.components.add("lutron_caseta")


@pytest.fixture
def lutron(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain="lutron_caseta")
    entry.add_to_hass(hass)
    return entry


def _pico(hass, lutron, serial: int, name: str, model: str = MODEL_3BRL):
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=lutron.entry_id,
        identifiers={("lutron_caseta", serial)},
        manufacturer="Lutron Electronics Co., Inc",
        model=model,
        name=name,
    )


def _labels(result) -> list[str]:
    selector = result["data_schema"].schema["device_ids"]
    return sorted(option["label"] for option in selector.config["options"])


async def test_same_named_picos_are_told_apart_by_serial(hass, lutron):
    # The 2026-10-01 case: a replaced remote left in the registry under the
    # same name as its replacement.
    _pico(hass, lutron, 82414504, "Master Bedroom Pico 2")
    _pico(hass, lutron, 91787661, "Master Bedroom Pico 2")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )

    assert _labels(result) == [
        "Master Bedroom Pico 2 (3BRL · #82414504)",
        "Master Bedroom Pico 2 (3BRL · #91787661)",
    ]


async def test_options_picker_shows_serials_too(hass, lutron):
    pico_1 = _pico(hass, lutron, 91787708, "Master Bedroom Pico 1")
    _pico(hass, lutron, 91787661, "Master Bedroom Pico 2")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_ids": [pico_1.id], "type": "3BRL"},
        options={"lights": ["light.wled"]},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "devices"}
    )

    assert _labels(result) == [
        "Master Bedroom Pico 1 (#91787708)",
        "Master Bedroom Pico 2 (#91787661)",
    ]


def test_a_model_without_the_type_in_parentheses_still_reads_2brl(hass, lutron):
    """ "Pico2Button" is a substring of "Pico2ButtonRaiseLower"; the longer must win."""
    device = _pico(
        hass, lutron, 140643429, "Gym Pico", model="PJ2-2BRL Pico2ButtonRaiseLower"
    )

    assert _eligible_pico_devices(hass)[device.id].pico_type == "2BRL"


@pytest.mark.parametrize("pending", [False, True])
async def test_overlapping_add_flows_recheck_each_device_at_save(hass, lutron, pending):
    import asyncio
    from unittest.mock import AsyncMock, patch

    from homeassistant.data_entry_flow import FlowResultType

    pico_a = _pico(hass, lutron, 1001, "A")
    pico_b = _pico(hass, lutron, 1002, "B")
    manager = hass.config_entries.flow
    first = await manager.async_init(DOMAIN, context={"source": "user"})
    second = await manager.async_init(DOMAIN, context={"source": "user"})
    first = await manager.async_configure(first["flow_id"], {"device_ids": [pico_a.id]})
    second = await manager.async_configure(
        second["flow_id"], {"device_ids": [pico_a.id, pico_b.id]}
    )
    finishing = asyncio.Event()
    release = asyncio.Event()
    finish_flow = manager.async_finish_flow

    async def delayed_finish(flow, result):
        if pending and flow.flow_id == first["flow_id"]:
            finishing.set()
            await release.wait()
        return await finish_flow(flow, result)

    async def setup(hass, entry):
        entry.runtime_data = []
        return True

    with (
        patch(
            "custom_components.pico_link.async_setup_entry",
            new=AsyncMock(side_effect=setup),
        ),
        patch.object(manager, "async_finish_flow", side_effect=delayed_finish),
    ):
        first_task = asyncio.create_task(
            manager.async_configure(first["flow_id"], {"lights": ["light.one"]})
        )
        if pending:
            await finishing.wait()
            assert not hass.config_entries.async_entries(DOMAIN)
        else:
            await first_task
        try:
            second = await manager.async_configure(
                second["flow_id"], {"lights": ["light.two"]}
            )
        finally:
            release.set()
            first = await first_task
    assert first["type"] is FlowResultType.CREATE_ENTRY
    assert second["type"] is FlowResultType.FORM
    assert second["errors"] == {"base": "device_already_configured"}
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
