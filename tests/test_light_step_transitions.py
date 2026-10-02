"""Brightness steps transition without changing discrete ON/OFF behavior.

Driven end to end through real PicoControllers: Lutron button events in,
light service calls out, against a fake light that tracks its own state.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.pico_link.config import PicoConfig
from custom_components.pico_link.const import PICO_EVENT_TYPE
from custom_components.pico_link.controller import PicoController
from custom_components.pico_link.memory import EntryMemory, PicoLinkStore

LIGHT = "light.fixture"
HOLD_MS = 20

LUTRON_TYPES = {"3BRL": "Pico3ButtonRaiseLower", "P2B": "PaddleSwitchPico"}


class _FakeLight:
    """Records light service calls and updates the light's state like a real one."""

    def __init__(self, hass: HomeAssistant, *, effect: str | None = None) -> None:
        self.hass = hass
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._on = True
        self._brightness = 128  # 50%
        self._effect = effect
        self._publish()

        hass.services.async_register("light", "turn_on", self._turn_on)
        hass.services.async_register("light", "turn_off", self._turn_off)

    def _publish(self) -> None:
        attributes: dict[str, Any] = {}

        if self._effect is not None:
            attributes["effect_list"] = ["Solid", "Candle"]

        if self._on:
            attributes["brightness"] = self._brightness
            attributes["effect"] = self._effect

        self.hass.states.async_set(LIGHT, "on" if self._on else "off", attributes)

    async def _turn_on(self, call: ServiceCall) -> None:
        data = {k: v for k, v in call.data.items() if k != "entity_id"}
        self.calls.append(("turn_on", data))
        self._on = True

        if "brightness_pct" in data:
            self._brightness = round(data["brightness_pct"] * 255 / 100)

        if "effect" in data:
            self._effect = data["effect"]

        self._publish()

    async def _turn_off(self, call: ServiceCall) -> None:
        data = {k: v for k, v in call.data.items() if k != "entity_id"}
        self.calls.append(("turn_off", data))
        self._on = False
        self._publish()


async def _controller(
    hass: HomeAssistant,
    *,
    transition_ms: int,
    step_ms: int = 650,
    pico_type: str = "3BRL",
    **overrides: Any,
) -> PicoController:
    conf = PicoConfig(
        device_id="pico",
        type=pico_type,
        lights=[LIGHT],
        hold_time_ms=HOLD_MS,
        step_time_ms=step_ms,
        light_transition_step_ms=transition_ms,
        light_transition_on=1,
        light_transition_off=2,
        **overrides,
    )
    conf.validate()

    controller = PicoController(hass, conf, EntryMemory(PicoLinkStore(hass), "entry"))
    await controller.async_start()
    return controller


def _fire(hass: HomeAssistant, button: str, action: str, pico_type: str) -> None:
    hass.bus.async_fire(
        PICO_EVENT_TYPE,
        {
            "device_id": "pico",
            "type": LUTRON_TYPES[pico_type],
            "button_type": button,
            "action": action,
        },
    )


async def _tap(hass: HomeAssistant, button: str, pico_type: str = "3BRL") -> None:
    _fire(hass, button, "press", pico_type)
    _fire(hass, button, "release", pico_type)
    await hass.async_block_till_done()


async def _hold(
    hass: HomeAssistant,
    button: str,
    *,
    held_ms: int,
    pico_type: str = "3BRL",
) -> None:
    _fire(hass, button, "press", pico_type)
    await asyncio.sleep(held_ms / 1000)
    _fire(hass, button, "release", pico_type)
    await hass.async_block_till_done()


async def _stop(hass: HomeAssistant, controller: PicoController) -> None:
    await controller.async_stop()
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("transition_ms", "expected_transition"),
    # 1200 ms is capped at step_time_ms (650).
    [(0, None), (500, 0.5), (1200, 0.65)],
)
async def test_single_steps_use_optional_capped_transition_without_changing_on_off(
    hass, transition_ms, expected_transition
):
    light = _FakeLight(hass)
    controller = await _controller(hass, transition_ms=transition_ms)

    await _tap(hass, "raise")
    await _tap(hass, "on")
    await _tap(hass, "off")

    assert light.calls == [
        (
            "turn_on",
            {
                "brightness_pct": 60,
                **({"transition": expected_transition} if expected_transition else {}),
            },
        ),
        # ON/OFF taps keep their own light_transition_on/off.
        ("turn_on", {"brightness_pct": 100, "transition": 1}),
        ("turn_off", {"transition": 2}),
    ]

    await _stop(hass, controller)


async def test_hold_steps_transition_to_next_target_and_stop_after_release(hass):
    light = _FakeLight(hass)
    controller = await _controller(hass, transition_ms=500, step_ms=100)

    # Past the hold threshold and through the ramp's first step, released
    # well before its second (at HOLD_MS + 100 ms).
    await _hold(hass, "lower", held_ms=HOLD_MS + 50)

    # The tap's immediate step, then one ramp step; each transition capped
    # at step_time_ms so the ramp never requests one longer than its steps.
    assert light.calls == [
        ("turn_on", {"brightness_pct": 40, "transition": 0.1}),
        ("turn_on", {"brightness_pct": 30, "transition": 0.1}),
    ]

    await _stop(hass, controller)


async def test_p2b_on_hold_ramp_uses_the_transition(hass):
    """The README covers P2B/2B ON/OFF holds too: they ramp through the same step."""
    light = _FakeLight(hass)
    controller = await _controller(
        hass, transition_ms=500, step_ms=100, pico_type="P2B"
    )

    await _hold(hass, "on", held_ms=HOLD_MS + 50, pico_type="P2B")

    # One ramp step, and the hold is never also an ON tap.
    assert light.calls == [("turn_on", {"brightness_pct": 60, "transition": 0.1})]

    await _stop(hass, controller)


async def test_with_light_effects_taps_step_effects_and_holds_ramp_with_transition(
    hass,
):
    light = _FakeLight(hass, effect="Solid")
    controller = await _controller(
        hass,
        transition_ms=500,
        step_ms=100,
        light_effects=["Solid", "Candle"],
    )

    await _tap(hass, "raise")
    assert light.calls == [("turn_on", {"effect": "Candle"})]

    light.calls.clear()
    await _hold(hass, "raise", held_ms=HOLD_MS + 50)
    assert light.calls == [("turn_on", {"brightness_pct": 60, "transition": 0.1})]

    await _stop(hass, controller)
