from types import SimpleNamespace

import pytest
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.core import State

from custom_components.pico_link.actions.cover import CoverActions


def _supports(attributes):
    return CoverActions(
        ctrl=SimpleNamespace(memory=SimpleNamespace(runtime={}))
    )._supports_set_position(State("cover.test", "open", attributes))


def test_set_position_feature_detection():
    assert _supports({"supported_features": CoverEntityFeature.SET_POSITION}) is True
    assert (
        _supports(
            {"supported_features": CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE}
        )
        is False
    )
    # Unknown or malformed feature flags are treated as "can position",
    # matching the previous behaviour.
    assert _supports({}) is True
    assert _supports({"supported_features": "3"}) is True
    assert _supports({"supported_features": True}) is True


@pytest.mark.parametrize("released", [False, True])
@pytest.mark.parametrize(("pico_type", "button"), [("3BRL", "raise"), ("2B", "on")])
async def test_unload_stops_only_continuous_motion_started_by_this_controller(
    hass, released, pico_type, button
):
    import asyncio

    from custom_components.pico_link.config import PicoConfig
    from custom_components.pico_link.controller import PicoController
    from custom_components.pico_link.memory import EntryMemory, PicoLinkStore

    calls = []
    started = asyncio.Event()

    async def service(call):
        calls.append(call.service)
        if call.service == "open_cover":
            started.set()

    for name in ("open_cover", "stop_cover"):
        hass.services.async_register("cover", name, service)

    def controller():
        ctrl = PicoController(
            hass,
            PicoConfig(device_id="pico", type=pico_type, covers=["cover.test"]),
            EntryMemory(PicoLinkStore(hass), "entry"),
        )
        ctrl.utils._hold_time = 0
        return ctrl

    idle = controller()
    await idle.async_stop()
    assert calls == []
    ctrl = controller()
    actions = ctrl.actions["cover"]
    # Start a real hold without an initial position step.
    actions._active_button = button
    await actions._hold_lifecycle(button, actions._gesture_generation)
    await started.wait()
    if released:
        getattr(actions, f"release_{button}")()
    await ctrl.async_stop()
    assert calls == ["open_cover", "stop_cover"]
    assert not ctrl._tasks


async def test_unload_cover_stop_is_bounded(hass, monkeypatch):
    import asyncio

    from custom_components.pico_link.actions import cover
    from custom_components.pico_link.config import PicoConfig
    from custom_components.pico_link.controller import PicoController
    from custom_components.pico_link.memory import EntryMemory, PicoLinkStore

    monkeypatch.setattr(cover, "SHUTDOWN_STOP_TIMEOUT", 0.01, raising=False)
    stopped = asyncio.Event()

    async def stop(call):
        stopped.set()
        await asyncio.Event().wait()

    async def open_cover(call):
        pass

    hass.services.async_register("cover", "open_cover", open_cover)
    hass.services.async_register("cover", "stop_cover", stop)
    ctrl = PicoController(
        hass,
        PicoConfig(device_id="pico", type="3BRL", covers=["cover.test"]),
        EntryMemory(PicoLinkStore(hass), "entry"),
    )
    ctrl.utils._hold_time = 0
    actions = ctrl.actions["cover"]
    actions._active_button = "raise"
    await actions._hold_lifecycle("raise", actions._gesture_generation)
    await hass.async_block_till_done()
    async with asyncio.timeout(0.5):
        await ctrl.async_stop()
    assert stopped.is_set()
    assert not ctrl._tasks
