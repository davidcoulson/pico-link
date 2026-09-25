"""Entry-point helpers exercised against a real (test) Home Assistant instance."""

from __future__ import annotations

import pytest
from homeassistant.components.device_automation import (
    DeviceAutomationType,
    async_get_device_automations,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pico_link import (
    DOMAIN,
    _pico_entity_missing_issue_id,
    _sync_device_links,
    _watch_for_missing_entities,
)


def _lutron_device(hass, lutron_entry, key):
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=lutron_entry.entry_id,
        identifiers={("lutron_caseta", key)},
        model="PJ2-3BRL-GWH-L01 (Pico3ButtonRaiseLower)",
        name=f"Pico {key}",
    )


@pytest.mark.asyncio
async def test_sync_device_links_follows_the_entry_device_set(hass):
    lutron = MockConfigEntry(domain="lutron_caseta")
    lutron.add_to_hass(hass)
    dev_a = _lutron_device(hass, lutron, "a")
    dev_b = _lutron_device(hass, lutron, "b")

    entry = MockConfigEntry(
        domain=DOMAIN, data={"device_ids": [dev_a.id], "type": "3BRL"}
    )
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)

    _sync_device_links(hass, entry, [dev_a.id])
    assert entry.entry_id in registry.async_get(dev_a.id).config_entries
    assert entry.entry_id not in registry.async_get(dev_b.id).config_entries

    # Idempotent.
    _sync_device_links(hass, entry, [dev_a.id])

    # The devices step moved the entry from Pico a to Pico b.
    _sync_device_links(hass, entry, [dev_b.id])
    assert entry.entry_id not in registry.async_get(dev_a.id).config_entries
    assert entry.entry_id in registry.async_get(dev_b.id).config_entries

    # Lutron's own ownership is untouched throughout.
    assert lutron.entry_id in registry.async_get(dev_a.id).config_entries
    assert registry.async_get(dev_a.id).primary_config_entry == lutron.entry_id


@pytest.mark.asyncio
async def test_device_triggers_are_offered_once_linked(
    hass, enable_custom_integrations
):
    lutron = MockConfigEntry(domain="lutron_caseta")
    lutron.add_to_hass(hass)
    device = _lutron_device(hass, lutron, "a")

    entry = MockConfigEntry(
        domain=DOMAIN, data={"device_ids": [device.id], "type": "P2B"}
    )
    entry.add_to_hass(hass)

    async def pico_link_triggers():
        automations = await async_get_device_automations(
            hass, DeviceAutomationType.TRIGGER, [device.id]
        )
        return sorted(
            (t["type"], t["subtype"])
            for t in automations.get(device.id, [])
            if t["domain"] == DOMAIN
        )

    # Without the link Home Assistant never asks Pico Link about this device.
    assert await pico_link_triggers() == []

    _sync_device_links(hass, entry, [device.id])

    assert await pico_link_triggers() == [
        ("press", "off"),
        ("press", "on"),
        ("release", "off"),
        ("release", "on"),
    ]


@pytest.mark.asyncio
async def test_missing_entity_watch_accepts_state_only_entities(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_ids": ["dev"], "type": "3BRL"},
        options={"lights": ["light.yaml_template"]},
        title="Test Pico",
    )
    entry.add_to_hass(hass)
    issue_id = _pico_entity_missing_issue_id(entry.entry_id)
    registry = ir.async_get(hass)

    # Exists in the state machine only (no unique_id -> no registry entry).
    hass.states.async_set("light.yaml_template", "on")
    await hass.async_block_till_done()

    unsub = _watch_for_missing_entities(hass, entry)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None

    # It disappears: flagged.
    hass.states.async_remove("light.yaml_template")
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    # It comes back: cleared.
    hass.states.async_set("light.yaml_template", "off")
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None

    # Ordinary state changes don't re-run the check (no error either way).
    hass.states.async_set("light.yaml_template", "on")
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None

    unsub()
