"""Brightness steps transition without changing discrete ON/OFF behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.pico_link.actions.light import LightActions
from custom_components.pico_link.config import PicoConfig


class LightController:
    def __init__(self, *, transition_ms: int, step_ms: int = 650) -> None:
        self.conf = PicoConfig(
            device_id="pico",
            type="3BRL",
            lights=["light.fixture"],
            step_time_ms=step_ms,
            light_transition_step_ms=transition_ms,
            light_transition_on=1,
            light_transition_off=2,
        )
        self.calls: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()
        self.tasks: list[asyncio.Task] = []
        self.utils = SimpleNamespace(
            _hold_time=0.01,
            _step_time=step_ms / 1000,
            get_entity_state=lambda: SimpleNamespace(
                state="on", attributes={"brightness": 128}
            ),
            call_service=self.call_service,
        )

    async def call_service(self, service: str, data: dict, *, domain: str) -> None:
        assert domain == "light"
        await self.calls.put((service, data))

    def create_task(self, coro, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self.tasks.append(task)
        return task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transition_ms", "expected_transition"),
    [(0, None), (500, 0.5), (1200, 0.65)],
)
async def test_single_steps_use_optional_capped_transition_without_changing_on_off(
    transition_ms, expected_transition
):
    ctrl = LightController(transition_ms=transition_ms)
    light = LightActions(ctrl)

    light.press_raise()
    light.release_raise()
    service, data = await asyncio.wait_for(ctrl.calls.get(), 1)
    assert service == "turn_on"
    assert data == {
        "brightness_pct": 60,
        **({"transition": expected_transition} if expected_transition else {}),
    }

    light.press_on()
    assert await asyncio.wait_for(ctrl.calls.get(), 1) == (
        "turn_on",
        {"brightness_pct": 100, "transition": 1},
    )
    light.press_off()
    assert await asyncio.wait_for(ctrl.calls.get(), 1) == (
        "turn_off",
        {"transition": 2},
    )
    results = await asyncio.gather(*ctrl.tasks, return_exceptions=True)
    assert all(
        result is None or isinstance(result, asyncio.CancelledError)
        for result in results
    )


@pytest.mark.asyncio
async def test_hold_steps_transition_to_next_target_and_stop_after_release():
    ctrl = LightController(transition_ms=500, step_ms=100)
    light = LightActions(ctrl)

    light.press_lower()
    assert await asyncio.wait_for(ctrl.calls.get(), 1) == (
        "turn_on",
        {"brightness_pct": 40, "transition": 0.1},
    )
    assert await asyncio.wait_for(ctrl.calls.get(), 1) == (
        "turn_on",
        {"brightness_pct": 30, "transition": 0.1},
    )
    light.release_lower()
    await asyncio.gather(*ctrl.tasks)
    assert ctrl.calls.empty()
