"""Exercise brightness commands through Pico events and Home Assistant services."""

import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from custom_components.pico_link.config import parse_pico_config
from custom_components.pico_link.const import PICO_EVENT_TYPE, PICO_TYPE_MAP
from custom_components.pico_link.controller import PicoController

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def remote(hass, request, type_setting, register_pico):
    """Create a remote with real event dispatch and recorded light commands."""
    pico_type = getattr(request, "param", "3BRL")
    raw = {
        "device_id": "test-pico",
        "type": pico_type,
        "lights": "light.test",
        "light_low_pct": 25,
        "light_step_pct": 10,
        "light_on_pct": 80,
        "hold_time_ms": 100,
        "step_time_ms": 100,
    }
    if type_setting == "detected":
        raw_type = next(raw for raw, kind in PICO_TYPE_MAP.items() if kind == pico_type)
        device = register_pico(model=f"Test model ({raw_type})")
        raw["device_id"] = device.id
        raw.pop("type")
    conf = parse_pico_config(hass, {}, raw)
    commands = []
    received = asyncio.Queue()

    async def record_command(call):
        commands.append((call.service, dict(call.data)))
        received.put_nowait(commands[-1])

    hass.services.async_register("light", "turn_on", record_command)
    hass.services.async_register("light", "turn_off", record_command)
    # An off light may retain its previous brightness in HA.
    hass.states.async_set("light.test", "off", {"brightness": 204})
    controller = PicoController(hass, conf)
    await controller.async_start()
    raw_type = next(raw for raw, kind in PICO_TYPE_MAP.items() if kind == pico_type)

    def fire(button, action):
        hass.bus.async_fire(
            PICO_EVENT_TYPE,
            {
                "device_id": conf.device_id,
                "type": raw_type,
                "button_type": button,
                "action": action,
            },
        )

    async def next_command():
        return await asyncio.wait_for(received.get(), timeout=2)

    yield SimpleNamespace(
        conf=conf,
        commands=commands,
        fire=fire,
        next_command=next_command,
    )

    await controller.async_stop()


def tap(remote, button):
    remote.fire(button, "press")
    remote.fire(button, "release")


@pytest.mark.parametrize("low,step", [(25, 10), (5, 10), (25, 5), (99, 25)])
async def test_raise_from_off_starts_at_minimum(hass, remote, low, step):
    remote.conf.light_low_pct = low
    remote.conf.light_step_pct = step

    tap(remote, "raise")
    await hass.async_block_till_done()

    assert remote.commands == [
        ("turn_on", {"brightness_pct": low, "entity_id": ["light.test"]})
    ]


async def test_rapid_raise_taps_continue_from_minimum_with_stale_state(hass, remote):
    for _ in range(3):
        tap(remote, "raise")
    await hass.async_block_till_done()

    assert [data["brightness_pct"] for _, data in remote.commands] == [25, 35, 45]
    assert hass.states.get("light.test").state == "off"


@pytest.mark.parametrize("remote", ["3BRL", "P2B", "2B"], indirect=True)
async def test_upward_hold_starts_at_minimum_and_stops_on_release(hass, remote):
    button = "raise" if remote.conf.type == "3BRL" else "on"
    remote.fire(button, "press")
    first = await remote.next_command()
    second = await remote.next_command()
    remote.fire(button, "release")
    await hass.async_block_till_done()

    assert [data["brightness_pct"] for _, data in (first, second)] == [25, 35]
    assert remote.commands == [first, second]


@pytest.mark.parametrize("remote", ["3BRL", "P2B", "2B"], indirect=True)
async def test_on_tap_still_uses_light_on_pct(hass, remote):
    tap(remote, "on")
    await hass.async_block_till_done()

    assert remote.commands == [
        ("turn_on", {"brightness_pct": 80, "entity_id": ["light.test"]})
    ]


async def test_lower_from_off_does_not_turn_on(hass, remote):
    tap(remote, "lower")
    await hass.async_block_till_done()

    assert remote.commands == []


@pytest.mark.parametrize(
    "button,brightness,expected",
    [("raise", 102, 50), ("raise", 245, 100), ("lower", 77, 25)],
)
async def test_existing_steps_keep_their_limits(
    hass, remote, button, brightness, expected
):
    hass.states.async_set("light.test", "on", {"brightness": brightness})

    tap(remote, button)
    await hass.async_block_till_done()

    assert remote.commands == [
        ("turn_on", {"brightness_pct": expected, "entity_id": ["light.test"]})
    ]
