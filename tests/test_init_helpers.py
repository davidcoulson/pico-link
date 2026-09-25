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
    _sync_pico_devices,
    _watch_for_missing_entities,
    pico_link_source_device_id,
)
from custom_components.pico_link.device_trigger import _lutron_device_id


def _lutron_device(hass, lutron_entry, key, **kwargs):
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=lutron_entry.entry_id,
        identifiers={("lutron_caseta", key)},
        manufacturer="Lutron Electronics Co., Inc",
        model="PJ2-3BRL-GWH-L01 (Pico3ButtonRaiseLower)",
        name=f"Pico {key}",
        **kwargs,
    )


def _mirrors(hass, entry):
    """{lutron device id: Pico Link mirror device} for an entry."""
    return {
        pico_link_source_device_id(device): device
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
    }


@pytest.mark.asyncio
async def test_sync_pico_devices_mirrors_the_entry_device_set(hass):
    lutron = MockConfigEntry(domain="lutron_caseta")
    lutron.add_to_hass(hass)
    dev_a = _lutron_device(hass, lutron, "a", suggested_area="Kitchen")
    dev_b = _lutron_device(hass, lutron, "b")
    registry = dr.async_get(hass)
    registry.async_update_device(dev_a.id, name_by_user="Kitchen Pico")

    entry = MockConfigEntry(
        domain=DOMAIN, data={"device_ids": [dev_a.id], "type": "3BRL"}
    )
    entry.add_to_hass(hass)

    _sync_pico_devices(hass, entry, [dev_a.id])
    mirrors = _mirrors(hass, entry)
    assert set(mirrors) == {dev_a.id}
    mirror_a = mirrors[dev_a.id]
    assert mirror_a.name == "Kitchen Pico"  # the user's name for the Pico
    assert mirror_a.model == dev_a.model
    assert mirror_a.manufacturer == dev_a.manufacturer
    assert mirror_a.area_id == registry.async_get(dev_a.id).area_id
    assert _lutron_device_id(hass, mirror_a.id) == dev_a.id

    # Idempotent: same mirror device, not a second one.
    _sync_pico_devices(hass, entry, [dev_a.id])
    assert _mirrors(hass, entry)[dev_a.id].id == mirror_a.id

    # The user moved the mirror to another room; a later setup keeps that.
    registry.async_update_device(mirror_a.id, area_id="hallway")
    _sync_pico_devices(hass, entry, [dev_a.id])
    assert registry.async_get(mirror_a.id).area_id == "hallway"

    # The devices step moved the entry from Pico a to Pico b.
    _sync_pico_devices(hass, entry, [dev_b.id])
    assert set(_mirrors(hass, entry)) == {dev_b.id}
    assert registry.async_get(mirror_a.id) is None

    # Lutron's own devices are untouched throughout.
    assert registry.async_get(dev_a.id) is not None
    assert registry.async_get(dev_b.id) is not None


@pytest.mark.asyncio
async def test_lutron_device_id_passes_unknown_and_lutron_devices_through(hass):
    lutron = MockConfigEntry(domain="lutron_caseta")
    lutron.add_to_hass(hass)
    dev = _lutron_device(hass, lutron, "a")

    assert _lutron_device_id(hass, dev.id) == dev.id
    assert _lutron_device_id(hass, "no-such-device") == "no-such-device"


@pytest.mark.asyncio
async def test_device_triggers_are_offered_on_the_mirror_device(
    hass, enable_custom_integrations
):
    lutron = MockConfigEntry(domain="lutron_caseta")
    lutron.add_to_hass(hass)
    device = _lutron_device(hass, lutron, "a")

    entry = MockConfigEntry(
        domain=DOMAIN, data={"device_ids": [device.id], "type": "P2B"}
    )
    entry.add_to_hass(hass)

    async def pico_link_triggers(device_id):
        automations = await async_get_device_automations(
            hass, DeviceAutomationType.TRIGGER, [device_id]
        )
        return sorted(
            (t["type"], t["subtype"], t["device_id"])
            for t in automations.get(device_id, [])
            if t["domain"] == DOMAIN
        )

    # Home Assistant never asks Pico Link about Lutron's own device.
    assert await pico_link_triggers(device.id) == []

    _sync_pico_devices(hass, entry, [device.id])
    mirror = _mirrors(hass, entry)[device.id]

    assert await pico_link_triggers(mirror.id) == [
        ("press", "off", mirror.id),
        ("press", "on", mirror.id),
        ("release", "off", mirror.id),
        ("release", "on", mirror.id),
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
