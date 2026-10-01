"""Tests for the 2BRL profile (a 3BRL without the STOP button)."""

from __future__ import annotations

from custom_components.pico_link.const import (
    ACCENT_LIGHT_PICO_TYPES,
    ON_OFF_PICO_TYPES,
    PICO_TYPE_BUTTONS,
    PICO_TYPE_MAP,
    VALID_PICO_TYPES,
)
from custom_components.pico_link.profiles.pico_2brl import Pico2ButtonRaiseLower


class _Actions:
    def __init__(self, calls):
        self._calls = calls

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self._calls.append(name)

        return record


class _Conf:
    type = "2BRL"
    device_id = "dev"
    on_hold: list = []
    off_hold: list = []
    on_double_tap: list = []
    off_double_tap: list = []


class _Utils:
    _hold_time = 0.4

    def entity_domain(self):
        return "light"


class _Ctrl:
    def __init__(self, calls):
        self.conf = _Conf()
        self.utils = _Utils()
        self.actions = {"light": _Actions(calls)}

    def create_task(self, coro, name):
        coro.close()
        return None


def test_2brl_is_a_known_type_without_stop():
    assert PICO_TYPE_MAP["Pico2ButtonRaiseLower"] == "2BRL"
    assert "2BRL" in VALID_PICO_TYPES
    assert PICO_TYPE_BUTTONS["2BRL"] == ("on", "off", "raise", "lower")
    # STOP-only features stay out: dual-light mode needs STOP, and ON/OFF
    # are plain taps here (RAISE/LOWER do the ramping).
    assert "2BRL" not in ACCENT_LIGHT_PICO_TYPES
    assert "2BRL" not in ON_OFF_PICO_TYPES


def test_2brl_dispatches_its_four_buttons():
    calls: list[str] = []
    profile = Pico2ButtonRaiseLower(_Ctrl(calls))

    for button in ("on", "off", "raise", "lower"):
        profile.handle_press(button)
        profile.handle_release(button)

    assert calls == [
        "press_on",
        "press_off",
        "press_raise",
        "release_raise",
        "press_lower",
        "release_lower",
    ]


def test_2brl_ignores_buttons_it_does_not_have():
    calls: list[str] = []
    profile = Pico2ButtonRaiseLower(_Ctrl(calls))

    profile.handle_press("stop")
    profile.handle_release("stop")
    profile.handle_press("button_1")

    assert calls == []
