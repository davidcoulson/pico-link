"""Dual-light mode: ON/STOP/OFF switch between a center light and an accent light.

Driven end to end through real PicoControllers against fake lights that
track their own state. A fake clock drives the couple of seconds after a
press during which that press, not the lights' reported state, decides
which light is showing.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.pico_link.actions import light as light_module
from custom_components.pico_link.actions.light import ACCENT_EFFECT_MEMORY_KEY
from custom_components.pico_link.config import AccentPreset, PicoConfig
from custom_components.pico_link.const import PICO_EVENT_TYPE
from custom_components.pico_link.controller import PicoController
from custom_components.pico_link.memory import EntryMemory, PicoLinkStore

CENTER = "light.center"
ACCENT = "light.accent"
ACCENT_EFFECTS = ["Aurora", "Candle", "Comet"]
AMBER = AccentPreset(rgb_color=[255, 166, 0])

LUTRON_TYPES = {"3BRL": "Pico3ButtonRaiseLower", "P2B": "PaddleSwitchPico"}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(
        light_module, "time", SimpleNamespace(monotonic=clock.monotonic)
    )
    return clock


class _Lights:
    """Fake center and accent lights that apply service calls to their state."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        # While True, calls are recorded but states don't change yet, like
        # a light that hasn't reported its new state.
        self.lagging = False
        self._state = {
            CENTER: {"on": False, "brightness": 255, "effect": None},
            ACCENT: {"on": False, "brightness": 255, "effect": None},
        }
        for entity_id in self._state:
            self._publish(entity_id)

        hass.services.async_register("light", "turn_on", self._turn_on)
        hass.services.async_register("light", "turn_off", self._turn_off)

    def set(self, entity_id: str, *, on: bool, effect: str | None = None) -> None:
        """Change a light from outside Pico Link (the app, an automation)."""
        self._state[entity_id].update(on=on, effect=effect)
        self._publish(entity_id)

    def _publish(self, entity_id: str) -> None:
        state = self._state[entity_id]
        attributes: dict[str, Any] = {}

        if entity_id == ACCENT:
            attributes["effect_list"] = ACCENT_EFFECTS

        if state["on"]:
            attributes["brightness"] = state["brightness"]
            attributes["effect"] = state["effect"]

        self.hass.states.async_set(
            entity_id, "on" if state["on"] else "off", attributes
        )

    def _apply(self, service: str, call: ServiceCall) -> None:
        data = {k: v for k, v in call.data.items() if k != "entity_id"}

        for entity_id in call.data["entity_id"]:
            self.calls.append((service, entity_id, data))

            if self.lagging:
                continue

            state = self._state[entity_id]
            state["on"] = service == "turn_on"

            if "brightness_pct" in data:
                state["brightness"] = round(data["brightness_pct"] * 255 / 100)

            if "effect" in data:
                state["effect"] = data["effect"]
            elif "rgb_color" in data:
                state["effect"] = None

            self._publish(entity_id)

    async def _turn_on(self, call: ServiceCall) -> None:
        self._apply("turn_on", call)

    async def _turn_off(self, call: ServiceCall) -> None:
        self._apply("turn_off", call)

    def is_on(self, entity_id: str) -> bool:
        return self.hass.states.get(entity_id).state == "on"

    def calls_to(self, entity_id: str) -> list[tuple[str, dict[str, Any]]]:
        return [(svc, data) for svc, eid, data in self.calls if eid == entity_id]


def _memory(hass: HomeAssistant) -> EntryMemory:
    return EntryMemory(PicoLinkStore(hass), "entry")


async def _controller(
    hass: HomeAssistant,
    memory: EntryMemory,
    *,
    device_id: str = "pico",
    pico_type: str = "3BRL",
    presets: list[AccentPreset] | None = None,
) -> PicoController:
    conf = PicoConfig(
        device_id=device_id,
        type=pico_type,
        lights=[CENTER],
        accent_lights=[ACCENT],
        accent_light_presets=presets or [AMBER],
    )
    conf.validate()

    controller = PicoController(hass, conf, memory)
    await controller.async_start()
    return controller


async def _tap(
    hass: HomeAssistant,
    button: str,
    *,
    device_id: str = "pico",
    pico_type: str = "3BRL",
) -> None:
    for action in ("press", "release"):
        hass.bus.async_fire(
            PICO_EVENT_TYPE,
            {
                "device_id": device_id,
                "type": LUTRON_TYPES[pico_type],
                "button_type": button,
                "action": action,
            },
        )
    await hass.async_block_till_done()


async def _stop(hass: HomeAssistant, *controllers: PicoController) -> None:
    for controller in controllers:
        await controller.async_stop()
    await hass.async_block_till_done()


# ----------------------------------------------------------------------
# ON / STOP / OFF
# ----------------------------------------------------------------------


async def test_on_stop_and_off_switch_between_the_lights(hass, clock):
    lights = _Lights(hass)
    controller = await _controller(hass, _memory(hass))

    await _tap(hass, "on")
    assert lights.is_on(CENTER) and not lights.is_on(ACCENT)

    await _tap(hass, "stop")
    assert lights.is_on(ACCENT) and not lights.is_on(CENTER)
    assert ("turn_on", {"brightness_pct": 100, "rgb_color": [255, 166, 0]}) in (
        lights.calls_to(ACCENT)
    )

    await _tap(hass, "off")
    assert not lights.is_on(CENTER) and not lights.is_on(ACCENT)

    await _stop(hass, controller)


# ----------------------------------------------------------------------
# Which light RAISE/LOWER act on
# ----------------------------------------------------------------------


async def test_raise_right_after_stop_cycles_effects_before_the_accent_reports(
    hass, clock
):
    lights = _Lights(hass)
    controller = await _controller(hass, _memory(hass))

    lights.lagging = True
    await _tap(hass, "stop")
    # The accent light hasn't reported on yet; the STOP press decides.
    assert not lights.is_on(ACCENT)

    await _tap(hass, "raise")

    assert lights.calls_to(ACCENT)[-1] == ("turn_on", {"effect": "Aurora"})
    assert all("brightness_pct" not in data for _, data in lights.calls_to(CENTER))

    await _stop(hass, controller)


async def test_after_a_couple_of_seconds_the_lights_state_decides(hass, clock):
    lights = _Lights(hass)
    controller = await _controller(hass, _memory(hass))

    await _tap(hass, "stop")
    clock.advance(5)
    await _tap(hass, "raise")

    assert lights.calls_to(ACCENT)[-1] == ("turn_on", {"effect": "Aurora"})

    await _stop(hass, controller)


async def test_accent_turned_off_elsewhere_hands_raise_back_to_the_center(hass, clock):
    lights = _Lights(hass)
    controller = await _controller(hass, _memory(hass))

    await _tap(hass, "stop")
    clock.advance(5)
    lights.set(ACCENT, on=False)
    accent_calls_before = len(lights.calls_to(ACCENT))

    await _tap(hass, "raise")

    # The accent light stays off; RAISE brightens the center instead of
    # relighting the accent with the next effect.
    assert len(lights.calls_to(ACCENT)) == accent_calls_before
    assert lights.calls_to(CENTER)[-1] == ("turn_on", {"brightness_pct": 10})

    await _stop(hass, controller)


async def test_center_turned_on_elsewhere_takes_raise_back(hass, clock):
    lights = _Lights(hass)
    controller = await _controller(hass, _memory(hass))

    await _tap(hass, "stop")
    clock.advance(5)
    lights.set(CENTER, on=True)

    await _tap(hass, "lower")

    assert lights.calls_to(CENTER)[-1] == ("turn_on", {"brightness_pct": 90})

    await _stop(hass, controller)


async def test_both_remotes_in_an_entry_share_the_stop(hass, clock):
    lights = _Lights(hass)
    memory = _memory(hass)
    pico_1 = await _controller(hass, memory, device_id="pico_1")
    pico_2 = await _controller(hass, memory, device_id="pico_2")

    lights.lagging = True
    await _tap(hass, "stop", device_id="pico_1")
    await _tap(hass, "raise", device_id="pico_2")

    assert lights.calls_to(ACCENT)[-1] == ("turn_on", {"effect": "Aurora"})

    await _stop(hass, pico_1, pico_2)


# ----------------------------------------------------------------------
# Remembered accent effect
# ----------------------------------------------------------------------


async def test_stop_brings_back_the_last_effect_after_off(hass, clock):
    lights = _Lights(hass)
    memory = _memory(hass)
    controller = await _controller(hass, memory)

    await _tap(hass, "stop")
    await _tap(hass, "raise")
    await _tap(hass, "raise")
    assert memory.get(ACCENT_EFFECT_MEMORY_KEY) == "Candle"

    await _tap(hass, "off")
    clock.advance(5)
    await _tap(hass, "stop")

    assert lights.calls_to(ACCENT)[-1] == (
        "turn_on",
        {"brightness_pct": 100, "effect": "Candle"},
    )

    await _stop(hass, controller)


async def test_a_second_stop_moves_to_the_next_preset_and_forgets_the_effect(
    hass, clock
):
    lights = _Lights(hass)
    memory = _memory(hass)
    controller = await _controller(
        hass,
        memory,
        presets=[AMBER, AccentPreset(effect="Comet", brightness_pct=50)],
    )

    await _tap(hass, "stop")
    await _tap(hass, "raise")
    assert memory.get(ACCENT_EFFECT_MEMORY_KEY) == "Aurora"

    clock.advance(5)
    await _tap(hass, "stop")

    assert lights.calls_to(ACCENT)[-1] == (
        "turn_on",
        {"brightness_pct": 50, "effect": "Comet"},
    )
    assert memory.get(ACCENT_EFFECT_MEMORY_KEY) is None

    await _stop(hass, controller)


async def test_a_remembered_effect_the_light_no_longer_has_is_dropped(hass, clock):
    lights = _Lights(hass)
    memory = _memory(hass)
    memory.set(ACCENT_EFFECT_MEMORY_KEY, "Retired")
    controller = await _controller(hass, memory)

    await _tap(hass, "stop")

    assert lights.calls_to(ACCENT)[-1] == (
        "turn_on",
        {"brightness_pct": 100, "rgb_color": [255, 166, 0]},
    )
    assert memory.get(ACCENT_EFFECT_MEMORY_KEY) is None

    await _stop(hass, controller)


# ----------------------------------------------------------------------
# P2B / 2B dual-light mode
# ----------------------------------------------------------------------


async def test_p2b_on_and_off_switch_between_the_lights(hass, clock):
    lights = _Lights(hass)
    controller = await _controller(hass, _memory(hass), pico_type="P2B")

    await _tap(hass, "on", pico_type="P2B")
    assert lights.is_on(CENTER) and not lights.is_on(ACCENT)

    await _tap(hass, "off", pico_type="P2B")
    assert lights.is_on(ACCENT) and not lights.is_on(CENTER)

    await _stop(hass, controller)
