"""Unloading an entry stops every Pico, even when one of them fails to."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pico_link import (
    DOMAIN,
    _pico_entity_missing_issue_id,
    async_unload_entry,
)


class _Controller:
    def __init__(self, device_id: str, *, fails: bool = False) -> None:
        self.conf = SimpleNamespace(device_id=device_id)
        self.fails = fails
        self.stopped = False

    async def async_stop(self) -> None:
        self.stopped = True

        if self.fails:
            raise RuntimeError("stop failed")


async def test_one_failing_pico_doesnt_leave_the_others_running(hass, caplog):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_ids": ["pico_1", "pico_2"], "type": "3BRL"},
        options={"lights": ["light.gym"]},
    )
    entry.add_to_hass(hass)

    failing, healthy = _Controller("pico_1", fails=True), _Controller("pico_2")
    entry.runtime_data = [failing, healthy]

    issue_id = _pico_entity_missing_issue_id(entry.entry_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="pico_entity_missing",
    )

    # Previously the first failure escaped: the unload failed outright and
    # the second Pico kept listening to its buttons.
    assert await async_unload_entry(hass, entry) is True
    assert healthy.stopped
    # The rest of the unload still ran.
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert "pico_1: error while stopping" in caplog.text
