"""Media-player behavior, driven through real PicoControllers.

3BRL: ON plays/pauses, OFF skips, RAISE/LOWER step volume (and ramp on
hold), STOP mutes. P2B/2B: ON/OFF taps play/pause and skip, holds ramp
volume.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.pico_link.config import PicoConfig
from custom_components.pico_link.const import PICO_EVENT_TYPE
from custom_components.pico_link.controller import PicoController
from custom_components.pico_link.memory import EntryMemory, PicoLinkStore

PLAYER = "media_player.theater"

HOLD_MS = 20
STEP_MS = 30

LUTRON_TYPES = {"3BRL": "Pico3ButtonRaiseLower", "P2B": "PaddleSwitchPico"}


class _Player:
    """Records media_player service calls and tracks volume and mute."""

    def __init__(self, hass: HomeAssistant, *, volume: float = 0.5) -> None:
        self.hass = hass
        self.calls: list[tuple[str, dict[str, Any]]] = []
        # While True, calls are recorded but the reported volume doesn't
        # change yet -- like Sonos or Cast reporting a new level late.
        self.lagging = False
        self._volume = volume
        self._muted = False
        self._publish()

        for service in (
            "media_play_pause",
            "media_next_track",
            "volume_set",
            "volume_mute",
        ):
            hass.services.async_register("media_player", service, self._handle)

        hass.services.async_register("script", "movie_mode", self._script)

    def _publish(self) -> None:
        self.hass.states.async_set(
            PLAYER,
            "playing",
            {"volume_level": self._volume, "is_volume_muted": self._muted},
        )

    async def _handle(self, call: ServiceCall) -> None:
        data = {k: v for k, v in call.data.items() if k != "entity_id"}
        self.calls.append((call.service, data))

        if call.service == "volume_set":
            if self.lagging:
                return
            self._volume = data["volume_level"]
        elif call.service == "volume_mute":
            self._muted = data["is_volume_muted"]

        self._publish()

    async def _script(self, call: ServiceCall) -> None:
        self.calls.append(("script.movie_mode", {}))

    def services(self) -> list[str]:
        return [service for service, _ in self.calls]

    def volumes(self) -> list[float]:
        return [data["volume_level"] for svc, data in self.calls if svc == "volume_set"]


async def _controller(
    hass: HomeAssistant,
    *,
    pico_type: str = "3BRL",
    **overrides: Any,
) -> PicoController:
    conf = PicoConfig(
        device_id="pico",
        type=pico_type,
        media_players=[PLAYER],
        hold_time_ms=HOLD_MS,
        step_time_ms=STEP_MS,
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
    hass: HomeAssistant, button: str, steps: int, pico_type: str = "3BRL"
) -> None:
    """Hold past the threshold for a few ramp steps, then let go."""
    _fire(hass, button, "press", pico_type)
    await asyncio.sleep((HOLD_MS + steps * STEP_MS) / 1000)
    _fire(hass, button, "release", pico_type)
    await hass.async_block_till_done()


async def _stop(hass: HomeAssistant, controller: PicoController) -> None:
    await controller.async_stop()
    await hass.async_block_till_done()


async def test_3brl_on_off_and_stop_taps(hass):
    player = _Player(hass)
    controller = await _controller(hass)

    await _tap(hass, "on")
    await _tap(hass, "off")
    await _tap(hass, "stop")

    assert player.calls == [
        ("media_play_pause", {}),
        ("media_next_track", {}),
        ("volume_mute", {"is_volume_muted": True}),
    ]

    await _stop(hass, controller)


async def test_3brl_raise_and_lower_taps_step_volume(hass):
    player = _Player(hass, volume=0.5)
    controller = await _controller(hass)

    await _tap(hass, "raise")
    await _tap(hass, "lower")
    await _tap(hass, "lower")

    assert player.volumes() == [0.6, 0.5, 0.4]

    await _stop(hass, controller)


async def test_rapid_taps_build_on_the_requested_level_not_lagging_state(hass):
    player = _Player(hass, volume=0.5)
    player.lagging = True
    controller = await _controller(hass)

    await _tap(hass, "raise")
    await _tap(hass, "raise")

    # The player still reports 0.5; the second tap goes on from 0.6.
    assert player.volumes() == [0.6, 0.7]

    await _stop(hass, controller)


async def test_volume_stops_at_the_top(hass):
    player = _Player(hass, volume=1.0)
    controller = await _controller(hass)

    await _tap(hass, "raise")

    assert player.calls == []

    await _stop(hass, controller)


async def test_3brl_holding_raise_ramps_until_released(hass):
    player = _Player(hass, volume=0.2)
    controller = await _controller(hass)

    await _hold(hass, "raise", steps=2)

    volumes = player.volumes()
    # The tap's immediate step, then the ramp, still short of the top.
    assert len(volumes) >= 3
    assert volumes == sorted(volumes)
    assert volumes[-1] < 1.0

    await _stop(hass, controller)


async def test_stop_runs_custom_actions_instead_of_muting(hass):
    player = _Player(hass)
    controller = await _controller(
        hass, middle_button=[{"action": "script.movie_mode"}]
    )

    await _tap(hass, "stop")

    assert player.services() == ["script.movie_mode"]

    await _stop(hass, controller)


async def test_p2b_taps_play_pause_and_skip(hass):
    player = _Player(hass)
    controller = await _controller(hass, pico_type="P2B")

    await _tap(hass, "on", pico_type="P2B")
    await _tap(hass, "off", pico_type="P2B")

    assert player.services() == ["media_play_pause", "media_next_track"]

    await _stop(hass, controller)


async def test_p2b_holds_ramp_volume_without_playing_or_skipping(hass):
    player = _Player(hass, volume=0.5)
    controller = await _controller(hass, pico_type="P2B")

    await _hold(hass, "on", steps=2, pico_type="P2B")
    up = player.volumes()
    # A hold is never also a tap.
    assert "media_play_pause" not in player.services()

    player.calls.clear()
    await _hold(hass, "off", steps=2, pico_type="P2B")
    down = player.volumes()
    assert "media_next_track" not in player.services()

    assert up and up == sorted(up) and up[0] > 0.5
    assert down and down == sorted(down, reverse=True)

    await _stop(hass, controller)
