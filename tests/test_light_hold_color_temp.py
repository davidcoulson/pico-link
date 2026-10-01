"""light_hold_color_temp: holding ON/OFF on a 2BRL/3BRL ramps color temperature.

Driven end to end through a real PicoController: Lutron button events in,
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

LIGHT = "light.gym"
MIN_K = 3000
MAX_K = 6350
# light_step_pct (10%) of the 3350 K range.
STEP_K = 335

HOLD_MS = 20
STEP_MS = 30

LUTRON_TYPES = {
    "2BRL": "Pico2ButtonRaiseLower",
    "3BRL": "Pico3ButtonRaiseLower",
}


class _FakeLight:
    """Records light service calls and updates the light's state like a real one."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        on: bool,
        kelvin: int | None = 4000,
        color_temp: bool = True,
    ) -> None:
        self.hass = hass
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._color_temp = color_temp
        self._on = on
        self._brightness = 255
        self._kelvin = kelvin
        self._publish()

        hass.services.async_register("light", "turn_on", self._turn_on)
        hass.services.async_register("light", "turn_off", self._turn_off)

    def _publish(self) -> None:
        attributes: dict[str, Any] = {}

        if self._color_temp:
            # Capability attributes: reported whether the light is on or off.
            attributes["min_color_temp_kelvin"] = MIN_K
            attributes["max_color_temp_kelvin"] = MAX_K

        if self._on:
            attributes["brightness"] = self._brightness

            if self._color_temp and self._kelvin is not None:
                attributes["color_temp_kelvin"] = self._kelvin

        self.hass.states.async_set(LIGHT, "on" if self._on else "off", attributes)

    async def _turn_on(self, call: ServiceCall) -> None:
        data = {k: v for k, v in call.data.items() if k != "entity_id"}
        self.calls.append(("turn_on", data))
        self._on = True

        if "brightness_pct" in data:
            self._brightness = round(data["brightness_pct"] * 255 / 100)

        if "color_temp_kelvin" in data:
            self._kelvin = data["color_temp_kelvin"]

        self._publish()

    async def _turn_off(self, call: ServiceCall) -> None:
        data = {k: v for k, v in call.data.items() if k != "entity_id"}
        self.calls.append(("turn_off", data))
        self._on = False
        self._publish()

    def kelvins(self) -> list[int]:
        return [
            data["color_temp_kelvin"]
            for service, data in self.calls
            if "color_temp_kelvin" in data
        ]


async def _controller(
    hass: HomeAssistant,
    *,
    pico_type: str = "2BRL",
    **overrides: Any,
) -> PicoController:
    conf = PicoConfig(
        device_id="pico",
        type=pico_type,
        lights=[LIGHT],
        light_hold_color_temp=True,
        hold_time_ms=HOLD_MS,
        step_time_ms=STEP_MS,
        **overrides,
    )
    conf.validate()

    controller = PicoController(
        hass,
        conf,
        EntryMemory(PicoLinkStore(hass), "entry"),
    )
    await controller.async_start()

    return controller


def _fire(hass: HomeAssistant, pico_type: str, button: str, action: str) -> None:
    hass.bus.async_fire(
        PICO_EVENT_TYPE,
        {
            "device_id": "pico",
            "type": LUTRON_TYPES[pico_type],
            "button_type": button,
            "action": action,
        },
    )


async def _tap(hass: HomeAssistant, pico_type: str, button: str) -> None:
    _fire(hass, pico_type, button, "press")
    _fire(hass, pico_type, button, "release")
    await hass.async_block_till_done()


async def _hold_to_the_end(hass: HomeAssistant, pico_type: str, button: str) -> None:
    """Hold until the ramp stops on its own, then let go."""
    _fire(hass, pico_type, button, "press")
    await hass.async_block_till_done()
    _fire(hass, pico_type, button, "release")
    await hass.async_block_till_done()


async def _stop(controller: PicoController, hass: HomeAssistant) -> None:
    await controller.async_stop()
    await hass.async_block_till_done()


async def test_taps_still_turn_the_light_on_and_off(hass):
    light = _FakeLight(hass, on=False)
    controller = await _controller(hass)

    await _tap(hass, "2BRL", "on")
    await _tap(hass, "2BRL", "off")

    assert light.calls == [
        ("turn_on", {"brightness_pct": 100}),
        ("turn_off", {}),
    ]

    await _stop(controller, hass)


@pytest.mark.parametrize("pico_type", ["2BRL", "3BRL"])
async def test_hold_on_ramps_cooler_to_the_end_of_the_range(hass, pico_type):
    light = _FakeLight(hass, on=True, kelvin=4000)
    controller = await _controller(hass, pico_type=pico_type)

    await _hold_to_the_end(hass, pico_type, "on")

    kelvins = light.kelvins()
    assert kelvins[:3] == [4000 + STEP_K, 4000 + 2 * STEP_K, 4000 + 3 * STEP_K]
    assert kelvins[-1] == MAX_K
    assert kelvins == sorted(kelvins)
    # Only color temperature changed: no ON tap reset brightness on the
    # way, and nothing turned the light off.
    assert all(set(data) == {"color_temp_kelvin"} for _, data in light.calls)

    await _stop(controller, hass)


async def test_hold_off_ramps_warmer_without_turning_the_light_off(hass):
    light = _FakeLight(hass, on=True, kelvin=5000)
    controller = await _controller(hass)

    await _hold_to_the_end(hass, "2BRL", "off")

    kelvins = light.kelvins()
    assert kelvins[0] == 5000 - STEP_K
    assert kelvins[-1] == MIN_K
    assert kelvins == sorted(kelvins, reverse=True)
    assert all(service == "turn_on" for service, _ in light.calls)
    assert hass.states.get(LIGHT).state == "on"

    await _stop(controller, hass)


async def test_hold_on_while_off_turns_the_light_on_then_ramps(hass):
    light = _FakeLight(hass, on=False, kelvin=3500)
    controller = await _controller(hass)

    await _hold_to_the_end(hass, "2BRL", "on")

    assert light.calls[0] == ("turn_on", {"brightness_pct": 100})
    # Ramps from what the light reported once it came on.
    assert light.kelvins()[0] == 3500 + STEP_K
    assert light.kelvins()[-1] == MAX_K

    await _stop(controller, hass)


async def test_hold_off_while_off_does_nothing(hass):
    light = _FakeLight(hass, on=False)
    controller = await _controller(hass)

    await _hold_to_the_end(hass, "2BRL", "off")

    assert light.calls == []

    await _stop(controller, hass)


async def test_releasing_stops_the_ramp_partway(hass):
    light = _FakeLight(hass, on=True, kelvin=MIN_K)
    controller = await _controller(hass)

    _fire(hass, "2BRL", "on", "press")
    # Past the hold threshold and a couple of steps in, well short of the
    # ten steps it takes to cross the whole range.
    await asyncio.sleep((HOLD_MS + 2 * STEP_MS) / 1000)
    _fire(hass, "2BRL", "on", "release")
    await hass.async_block_till_done()

    kelvins = light.kelvins()
    assert kelvins
    assert MIN_K < kelvins[-1] < MAX_K
    # The release of a hold must not also count as an ON tap.
    assert all("brightness_pct" not in data for _, data in light.calls)

    await _stop(controller, hass)


async def test_light_in_rgb_mode_ramps_from_the_middle(hass):
    light = _FakeLight(hass, on=True, kelvin=None)
    controller = await _controller(hass)

    await _hold_to_the_end(hass, "2BRL", "on")

    assert light.kelvins()[0] == (MIN_K + MAX_K) // 2 + STEP_K

    await _stop(controller, hass)


async def test_light_without_color_temp_ignores_holds(hass):
    light = _FakeLight(hass, on=True, color_temp=False)
    controller = await _controller(hass)

    await _hold_to_the_end(hass, "2BRL", "on")
    await _hold_to_the_end(hass, "2BRL", "off")

    assert light.calls == []

    await _stop(controller, hass)


async def test_raise_and_lower_still_adjust_brightness(hass):
    light = _FakeLight(hass, on=True, kelvin=4000)
    controller = await _controller(hass)

    await _tap(hass, "2BRL", "lower")

    assert light.calls == [("turn_on", {"brightness_pct": 90})]

    await _stop(controller, hass)
