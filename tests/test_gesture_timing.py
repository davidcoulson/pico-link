"""Pure-asyncio tests for the hold / double-tap gesture state machines."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from custom_components.pico_link.profiles import gesture_timing
from custom_components.pico_link.profiles.gesture_timing import (
    HoldDoubleTapGestures,
    OnOffDoubleTapGestures,
)

HOLD_S = 0.03
WINDOW_MS = 40
SETTLE_S = 0.02


class FakeUtils:
    def __init__(self) -> None:
        self._hold_time = HOLD_S
        self.executed: list[tuple[str, list[dict[str, Any]]]] = []
        # Lets a test make an action sequence take a while, to prove a
        # release no longer aborts a hold action mid-run.
        self.action_delay = 0.0

    async def execute_button_action(self, actions, *, name="pico_link_action"):
        await asyncio.sleep(self.action_delay)
        self.executed.append((name, actions))


class FakeController:
    def __init__(self) -> None:
        self.utils = FakeUtils()
        self.tasks: list[asyncio.Task[Any]] = []

    def create_task(self, coro, name):
        task = asyncio.get_running_loop().create_task(coro, name=name)
        self.tasks.append(task)
        return task


HOLD = [{"action": "light.turn_on", "target": {"entity_id": "light.hold"}}]
DOUBLE = [{"action": "light.turn_on", "target": {"entity_id": "light.double"}}]


class Profile(HoldDoubleTapGestures):
    def __init__(self, ctrl, *, hold=None, double=None):
        super().__init__(ctrl)
        self.hold = hold or {}
        self.double = double or {}
        self.taps: list[str] = []

    def _hold_actions_for(self, button):
        return self.hold.get(button, [])

    def _double_tap_actions_for(self, button):
        return self.double.get(button, [])

    def _task_prefix(self):
        return "test"

    def press(self, button):
        self._handle_gesture_press(button, lambda: self.taps.append(button))

    def release(self, button):
        self._handle_gesture_release(button, lambda: self.taps.append(button))


@pytest.fixture(autouse=True)
def short_double_tap_window(monkeypatch):
    monkeypatch.setattr(gesture_timing, "DOUBLE_TAP_WINDOW_MS", WINDOW_MS)


@pytest.mark.asyncio
async def test_hold_fires_after_threshold_and_survives_release():
    if True:
        ctrl = FakeController()
        ctrl.utils.action_delay = HOLD_S * 3
        profile = Profile(ctrl, hold={"on": HOLD})

        profile.press("on")
        assert profile.taps == ["on"]  # tap is immediate, hold is extra

        await asyncio.sleep(HOLD_S + SETTLE_S)  # threshold crossed, action running
        profile.release("on")  # must not cancel the running sequence
        await asyncio.sleep(HOLD_S * 3 + SETTLE_S)

        assert ctrl.utils.executed == [("pico_link_on_hold", HOLD)]
        assert profile._hold_task is None


@pytest.mark.asyncio
async def test_release_before_threshold_cancels_hold():
    if True:
        ctrl = FakeController()
        profile = Profile(ctrl, hold={"on": HOLD})

        profile.press("on")
        await asyncio.sleep(HOLD_S / 3)
        profile.release("on")
        await asyncio.sleep(HOLD_S + SETTLE_S)

        assert profile.taps == ["on"]
        assert ctrl.utils.executed == []


@pytest.mark.asyncio
async def test_single_tap_with_double_tap_configured_fires_after_window():
    if True:
        ctrl = FakeController()
        profile = Profile(ctrl, double={"stop": DOUBLE})

        profile.press("stop")
        profile.release("stop")
        assert profile.taps == []  # deferred until the window closes

        await asyncio.sleep(WINDOW_MS / 1000 + SETTLE_S)

        assert profile.taps == ["stop"]
        assert ctrl.utils.executed == []


@pytest.mark.asyncio
async def test_double_tap_replaces_both_taps():
    if True:
        ctrl = FakeController()
        profile = Profile(ctrl, double={"stop": DOUBLE})

        profile.press("stop")
        profile.release("stop")
        await asyncio.sleep(WINDOW_MS / 2000)
        profile.press("stop")
        profile.release("stop")
        await asyncio.sleep(WINDOW_MS / 1000 + SETTLE_S)

        assert profile.taps == []
        assert ctrl.utils.executed == [("pico_link_stop_double_tap", DOUBLE)]


@pytest.mark.asyncio
async def test_pending_taps_are_tracked_per_button():
    if True:
        ctrl = FakeController()
        profile = Profile(ctrl, double={"on": DOUBLE, "off": DOUBLE})

        profile.press("on")
        profile.release("on")
        profile.press("off")
        profile.release("off")
        await asyncio.sleep(WINDOW_MS / 1000 + SETTLE_S)

        # Two different buttons are two single taps, not a double tap.
        assert sorted(profile.taps) == ["off", "on"]
        assert ctrl.utils.executed == []


class OnOffProfile(OnOffDoubleTapGestures):
    def __init__(self, ctrl, *, double=None):
        super().__init__(ctrl)
        self.double = double or {}
        self.forwarded: list[str] = []

    def _double_tap_actions_for(self, button):
        return self.double.get(button, [])

    def _task_prefix(self):
        return "test"

    def press(self, button):
        self._handle_double_tap_press(
            button,
            lambda: self.forwarded.append(f"press:{button}"),
            lambda: self.forwarded.append(f"release:{button}"),
        )

    def release(self, button):
        self._handle_double_tap_release(
            button,
            lambda: self.forwarded.append(f"press:{button}"),
            lambda: self.forwarded.append(f"release:{button}"),
        )


@pytest.mark.asyncio
async def test_onoff_without_double_tap_forwards_immediately():
    if True:
        profile = OnOffProfile(FakeController())

        profile.press("on")
        profile.release("on")

        assert profile.forwarded == ["press:on", "release:on"]


@pytest.mark.asyncio
async def test_onoff_quick_tap_is_forwarded_after_window_in_order():
    if True:
        profile = OnOffProfile(FakeController(), double={"on": DOUBLE})

        profile.press("on")
        profile.release("on")
        assert profile.forwarded == []

        await asyncio.sleep(WINDOW_MS / 1000 + SETTLE_S)

        assert profile.forwarded == ["press:on", "release:on"]


@pytest.mark.asyncio
async def test_onoff_long_press_forwards_release_when_it_happens():
    if True:
        profile = OnOffProfile(FakeController(), double={"on": DOUBLE})

        profile.press("on")
        await asyncio.sleep(WINDOW_MS / 1000 + SETTLE_S)
        assert profile.forwarded == ["press:on"]  # domain layer now timing a hold

        profile.release("on")
        assert profile.forwarded == ["press:on", "release:on"]


@pytest.mark.asyncio
async def test_onoff_double_tap_swallows_both_presses():
    if True:
        ctrl = FakeController()
        profile = OnOffProfile(ctrl, double={"on": DOUBLE})

        profile.press("on")
        profile.release("on")
        profile.press("on")
        profile.release("on")
        await asyncio.sleep(WINDOW_MS / 1000 + SETTLE_S)

        assert profile.forwarded == []
        assert ctrl.utils.executed == [("pico_link_on_double_tap", DOUBLE)]
