"""Requested targets are shared by an entry's Picos and withdrawn when a call fails.

Driven end to end through real PicoControllers: Lutron button events in,
service calls out, against fake entities that only report a new state
when told to -- like a light, cover, fan or player that's slow to report.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.components.fan import FanEntityFeature
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from custom_components.pico_link.config import PicoConfig
from custom_components.pico_link.const import PICO_EVENT_TYPE
from custom_components.pico_link.controller import PicoController
from custom_components.pico_link.memory import EntryMemory, PicoLinkStore, SharedTarget

# One RAISE tap on each domain, from the same starting point (50%).
DOMAINS = {
    "light": {
        "entity_id": "light.fixture",
        "config": "lights",
        "state": ("on", {"brightness": 128}),
        "service": "turn_on",
        "requested": lambda data: data["brightness_pct"],
    },
    "cover": {
        "entity_id": "cover.shade",
        "config": "covers",
        "state": (
            "open",
            {
                "current_position": 50,
                "supported_features": CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
                | CoverEntityFeature.SET_POSITION,
            },
        ),
        "service": "set_cover_position",
        "requested": lambda data: data["position"],
    },
    "fan": {
        "entity_id": "fan.ceiling",
        "config": "fans",
        "state": (
            "on",
            {
                "percentage": 50,
                "percentage_step": 10,
                "supported_features": FanEntityFeature.SET_SPEED
                | FanEntityFeature.TURN_ON
                | FanEntityFeature.TURN_OFF,
            },
        ),
        "service": "set_percentage",
        "requested": lambda data: data["percentage"],
    },
    "media_player": {
        "entity_id": "media_player.theater",
        "config": "media_players",
        "state": ("playing", {"volume_level": 0.5}),
        "service": "volume_set",
        "requested": lambda data: round(data["volume_level"] * 100),
    },
}


class _SlowEntity:
    """Records service calls without updating the reported state."""

    def __init__(self, hass: HomeAssistant, domain: str, *, failures: int = 0) -> None:
        spec = DOMAINS[domain]
        self.requested: list[int] = []
        self._spec = spec
        self._failures = failures

        hass.states.async_set(spec["entity_id"], *spec["state"])
        hass.services.async_register(domain, spec["service"], self._handle)

    async def _handle(self, call: ServiceCall) -> None:
        self.requested.append(self._spec["requested"](call.data))

        if self._failures:
            self._failures -= 1
            raise HomeAssistantError("device unreachable")


async def _controller(
    hass: HomeAssistant, memory: EntryMemory, domain: str, device_id: str
) -> PicoController:
    conf = PicoConfig(
        device_id=device_id,
        type="3BRL",
        **{DOMAINS[domain]["config"]: [DOMAINS[domain]["entity_id"]]},
    )
    conf.validate()

    controller = PicoController(hass, conf, memory)
    await controller.async_start()
    return controller


async def _tap_raise(hass: HomeAssistant, device_id: str) -> None:
    for action in ("press", "release"):
        hass.bus.async_fire(
            PICO_EVENT_TYPE,
            {
                "device_id": device_id,
                "type": "Pico3ButtonRaiseLower",
                "button_type": "raise",
                "action": action,
            },
        )
    await hass.async_block_till_done()


@pytest.mark.parametrize("domain", DOMAINS)
async def test_a_second_pico_steps_on_from_the_first_picos_request(hass, domain):
    """
    Two Picos in one entry control the same entities.

    Previously each kept its own target, so Pico B stepped from the
    state the entity hadn't updated yet and repeated Pico A's step.
    """
    entity = _SlowEntity(hass, domain)
    memory = EntryMemory(PicoLinkStore(hass), "entry")
    pico_a = await _controller(hass, memory, domain, "pico_a")
    pico_b = await _controller(hass, memory, domain, "pico_b")

    await _tap_raise(hass, "pico_a")
    # Pico A going away (a reload of its device, say) doesn't take back
    # what it asked for.
    await pico_a.async_stop()
    await _tap_raise(hass, "pico_b")

    assert entity.requested == [60, 70]

    await pico_b.async_stop()


@pytest.mark.parametrize("domain", DOMAINS)
async def test_a_failed_step_is_not_built_on(hass, domain):
    """
    The entity refuses the first step (unreachable, timed out).

    The next tap steps from the entity's real state again, rather than
    from the step that never happened.
    """
    entity = _SlowEntity(hass, domain, failures=1)
    memory = EntryMemory(PicoLinkStore(hass), "entry")
    pico = await _controller(hass, memory, domain, "pico")

    await _tap_raise(hass, "pico")
    await _tap_raise(hass, "pico")

    assert entity.requested == [60, 60]

    await pico.async_stop()


def test_withdrawing_a_request_leaves_a_newer_one_alone():
    """A ramp step that fails after the next was sent mustn't wipe the next."""
    runtime: dict[str, Any] = {}
    target = SharedTarget(runtime, "brightness", max_age=2.0)

    withdraw_60 = target.set(60)
    withdraw_70 = target.set(70)
    withdraw_60()
    assert target.get() == 70

    withdraw_70()
    assert target.get() is None
