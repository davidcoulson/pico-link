"""light_effects: a RAISE/LOWER tap on a 2BRL/3BRL steps through favorite effects.

Driven end to end through real PicoControllers: Lutron button events in,
light service calls out, against a fake light that tracks its own state.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.pico_link.actions.light import LIGHT_EFFECT_MEMORY_KEY
from custom_components.pico_link.config import PicoConfig
from custom_components.pico_link.const import PICO_EVENT_TYPE
from custom_components.pico_link.controller import PicoController
from custom_components.pico_link.memory import EntryMemory, PicoLinkStore

LIGHT = "light.wled"
FAVORITES = ["Solid", "Candle", "Aurora", "Fire 2012", "Twinklefox"]
# What the light itself offers: every favorite plus things nobody picked.
OFFERED = ["Aurora", "Blink", "Candle", "Fire 2012", "Rainbow", "Solid", "Twinklefox"]

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
        effect: str | None = "Solid",
        offered: list[str] | None = None,
    ) -> None:
        self.hass = hass
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._on = on
        self._brightness = 128
        self._effect = effect
        self._offered = OFFERED if offered is None else offered
        self._publish()

        hass.services.async_register("light", "turn_on", self._turn_on)
        hass.services.async_register("light", "turn_off", self._turn_off)

    def _publish(self) -> None:
        # effect_list is a capability attribute: reported on or off.
        attributes: dict[str, Any] = {"effect_list": self._offered}

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
        self.calls.append(("turn_off", {}))
        self._on = False
        self._publish()

    def effects(self) -> list[str]:
        return [data["effect"] for _, data in self.calls if "effect" in data]


def _memory(hass: HomeAssistant) -> EntryMemory:
    return EntryMemory(PicoLinkStore(hass), "entry")


async def _controller(
    hass: HomeAssistant,
    *,
    device_id: str = "pico",
    pico_type: str = "3BRL",
    memory: EntryMemory | None = None,
    **overrides: Any,
) -> PicoController:
    settings: dict[str, Any] = {
        "light_effects": FAVORITES,
        "hold_time_ms": HOLD_MS,
        "step_time_ms": STEP_MS,
        **overrides,
    }
    conf = PicoConfig(device_id=device_id, type=pico_type, lights=[LIGHT], **settings)
    conf.validate()

    controller = PicoController(hass, conf, memory or _memory(hass))
    await controller.async_start()

    return controller


def _fire(
    hass: HomeAssistant,
    button: str,
    action: str,
    *,
    device_id: str = "pico",
    pico_type: str = "3BRL",
) -> None:
    hass.bus.async_fire(
        PICO_EVENT_TYPE,
        {
            "device_id": device_id,
            "type": LUTRON_TYPES[pico_type],
            "button_type": button,
            "action": action,
        },
    )


async def _tap(hass: HomeAssistant, button: str, **kwargs: Any) -> None:
    _fire(hass, button, "press", **kwargs)
    _fire(hass, button, "release", **kwargs)
    await hass.async_block_till_done()


async def _stop(hass: HomeAssistant, *controllers: PicoController) -> None:
    for controller in controllers:
        await controller.async_stop()

    await hass.async_block_till_done()


@pytest.mark.parametrize("pico_type", ["2BRL", "3BRL"])
async def test_raise_taps_step_through_the_favorites_in_order(hass, pico_type):
    light = _FakeLight(hass, on=True, effect="Solid")
    controller = await _controller(hass, pico_type=pico_type)

    for _ in range(3):
        await _tap(hass, "raise", pico_type=pico_type)

    assert light.effects() == ["Candle", "Aurora", "Fire 2012"]
    # Brightness is left alone: a tap is purely an effect change.
    assert all(set(data) == {"effect"} for _, data in light.calls)

    await _stop(hass, controller)


async def test_lower_steps_back_and_both_directions_wrap(hass):
    light = _FakeLight(hass, on=True, effect="Solid")
    controller = await _controller(hass)

    await _tap(hass, "lower")
    await _tap(hass, "raise")
    await _tap(hass, "raise")

    # Solid is first, so LOWER wraps to the last favorite and RAISE wraps back.
    assert light.effects() == ["Twinklefox", "Solid", "Candle"]

    await _stop(hass, controller)


async def test_raise_from_an_effect_outside_the_favorites_starts_at_the_first(
    hass,
):
    light = _FakeLight(hass, on=True, effect="Rainbow")
    controller = await _controller(hass)

    await _tap(hass, "raise")

    assert light.effects() == ["Solid"]

    await _stop(hass, controller)


async def test_lower_from_an_effect_outside_the_favorites_starts_at_the_last(hass):
    light = _FakeLight(hass, on=True, effect="Rainbow")
    controller = await _controller(hass)

    await _tap(hass, "lower")

    assert light.effects() == ["Twinklefox"]

    await _stop(hass, controller)


async def test_holding_still_ramps_brightness_and_changes_no_effect(hass):
    light = _FakeLight(hass, on=True, effect="Candle")
    controller = await _controller(hass)

    _fire(hass, "raise", "press")
    await asyncio.sleep((HOLD_MS + 2 * STEP_MS) / 1000)
    _fire(hass, "raise", "release")
    await hass.async_block_till_done()

    assert light.calls
    assert all(set(data) == {"brightness_pct"} for _, data in light.calls)
    # Releasing a hold must not also count as a tap.
    assert light.effects() == []

    await _stop(hass, controller)


async def test_raise_while_off_turns_on_with_the_effect_after_the_last_one(hass):
    light = _FakeLight(hass, on=False)
    memory = _memory(hass)
    memory.set(LIGHT_EFFECT_MEMORY_KEY, "Aurora")
    controller = await _controller(hass, memory=memory)

    await _tap(hass, "raise")

    assert light.calls == [("turn_on", {"effect": "Fire 2012", "brightness_pct": 100})]
    assert memory.get(LIGHT_EFFECT_MEMORY_KEY) == "Fire 2012"

    await _stop(hass, controller)


async def test_raise_while_off_with_nothing_remembered_starts_at_the_first(hass):
    light = _FakeLight(hass, on=False)
    controller = await _controller(hass)

    await _tap(hass, "raise")

    assert light.calls == [("turn_on", {"effect": "Solid", "brightness_pct": 100})]

    await _stop(hass, controller)


async def test_lower_while_off_does_nothing(hass):
    light = _FakeLight(hass, on=False)
    controller = await _controller(hass)

    await _tap(hass, "lower")

    assert light.calls == []

    await _stop(hass, controller)


async def test_favorites_the_light_no_longer_offers_are_skipped(hass):
    light = _FakeLight(hass, on=True, effect="Solid", offered=["Solid", "Aurora"])
    controller = await _controller(hass)

    await _tap(hass, "raise")
    await _tap(hass, "raise")

    # Candle, Fire 2012 and Twinklefox are gone from the light's list.
    assert light.effects() == ["Aurora", "Solid"]

    await _stop(hass, controller)


async def test_both_remotes_in_an_entry_share_the_cycle(hass):
    light = _FakeLight(hass, on=True, effect="Solid")
    memory = _memory(hass)
    pico_1 = await _controller(hass, device_id="pico_1", memory=memory)
    pico_2 = await _controller(hass, device_id="pico_2", memory=memory)

    await _tap(hass, "raise", device_id="pico_1")
    await _tap(hass, "raise", device_id="pico_2")

    # Pico 2 picks up where Pico 1 left the light, not where it started.
    assert light.effects() == ["Candle", "Aurora"]

    await _stop(hass, pico_1, pico_2)


async def test_without_favorites_a_raise_tap_still_steps_brightness(hass):
    light = _FakeLight(hass, on=True, effect="Solid")
    controller = await _controller(hass, light_effects=[])

    await _tap(hass, "raise")

    # 128/255 is 50%; one light_step_pct (10%) up, as before this option.
    assert light.calls == [("turn_on", {"brightness_pct": 60})]

    await _stop(hass, controller)
