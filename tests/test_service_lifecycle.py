"""Controller-owned service work is canceled on unload and bounded in time."""

import asyncio
from unittest.mock import Mock

import pytest

from custom_components.pico_link.config import PicoConfig
from custom_components.pico_link.controller import PicoController
from custom_components.pico_link.memory import EntryMemory, PicoLinkStore


def _controller(hass):
    return PicoController(
        hass,
        PicoConfig(device_id="pico", type="3BRL", lights=["light.test"]),
        EntryMemory(PicoLinkStore(hass), "entry"),
    )


@pytest.mark.parametrize("failure_aware", [False, True])
async def test_unload_cancels_pending_service_before_it_can_take_effect(
    hass, failure_aware
):
    controller = _controller(hass)
    started = asyncio.Event()
    release = asyncio.Event()
    canceled = asyncio.Event()
    applied = []

    async def slow_service(call):
        started.set()
        try:
            await release.wait()
            applied.append(call)
        except asyncio.CancelledError:
            canceled.set()
            raise

    hass.services.async_register("light", "turn_on", slow_service)
    await controller.utils.call_service(
        "turn_on", {}, domain="light", on_failure=Mock() if failure_aware else None
    )
    await started.wait()
    await controller.async_stop()
    was_canceled = canceled.is_set()
    release.set()
    await hass.async_block_till_done()
    assert was_canceled
    assert not applied
    assert not controller._tasks


async def test_stalled_service_times_out_and_notifies_failure(hass, monkeypatch):
    from custom_components.pico_link import utilities

    monkeypatch.setattr(utilities, "SERVICE_CALL_TIMEOUT", 0.01, raising=False)
    controller = _controller(hass)
    canceled = asyncio.Event()
    failed = asyncio.Event()

    async def stalled_service(call):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            canceled.set()
            raise

    hass.services.async_register("light", "turn_on", stalled_service)
    await controller.utils.call_service(
        "turn_on", {}, domain="light", on_failure=failed.set
    )
    try:
        async with asyncio.timeout(0.5):
            await failed.wait()
        assert canceled.is_set()
        await hass.async_block_till_done()
        assert not controller._tasks
    finally:
        await controller.async_stop()
