"""Exercise real startup, event filtering, independent remotes and shutdown."""

import pytest
from homeassistant.setup import async_setup_component


async def test_invalid_and_duplicate_entries_do_not_disable_valid_remotes(pico, caplog):
    assert await pico.setup(
        [
            None,
            {"device_id": "invalid", "type": "2B", "lights": "fan.wrong"},
            {"device_id": "pico", "type": "2B", "switches": "switch.first"},
            {"device_id": "pico", "type": "2B", "switches": "switch.duplicate"},
            {"device_id": "other", "type": "2B", "switches": "switch.other"},
        ]
    )
    pico.tap("on", kind="2B")
    pico.tap("off", kind="2B", device="other")
    await pico.drain()
    assert pico.calls == [
        ("switch", "turn_on", {"entity_id": ["switch.first"]}),
        ("switch", "turn_off", {"entity_id": ["switch.other"]}),
    ]
    assert "already configured" in caplog.text
    assert "Invalid pico_link device entry" in caplog.text


@pytest.mark.parametrize(
    "root", [[], "invalid", {"devices": {}}, {"devices": [], "defaults": []}]
)
async def test_malformed_root_configuration_fails_setup(pico, root):
    assert not await async_setup_component(pico.hass, "pico_link", {"pico_link": root})


async def test_no_configuration_is_a_noop(pico):
    assert await async_setup_component(pico.hass, "pico_link", {})
    pico.tap("on")
    await pico.drain()
    assert pico.calls == []


@pytest.mark.parametrize(
    "data",
    [
        {"device_id": "someone-else"},
        {"type": "Pico2Button"},
        {"type": None},
        {"type": "unsupported"},
        {"button_type": None},
        {"button_type": "unknown"},
        {"action": None},
        {"action": "repeat"},
    ],
)
async def test_unrelated_or_malformed_events_do_not_operate_devices(pico, data):
    assert await pico.setup(
        [{"device_id": "pico", "type": "3BRL", "switches": "switch.desk"}]
    )
    pico.fire("on", **data)
    await pico.drain()
    assert pico.calls == []
    # A bad event must not disable subsequent valid input.
    pico.tap("ON")
    await pico.drain()
    assert pico.calls == [("switch", "turn_on", {"entity_id": ["switch.desk"]})]


async def test_multiple_lights_use_first_state_and_receive_one_command(pico):
    pico.hass.states.async_set("light.first", "on", {"brightness": 102})
    pico.hass.states.async_set("light.second", "on", {"brightness": 230})
    assert await pico.setup(
        [
            {
                "device_id": "pico",
                "type": "3BRL",
                "lights": ["light.first", "light.second", "light.first"],
            }
        ]
    )
    pico.tap("raise")
    await pico.drain()
    assert pico.calls == [
        (
            "light",
            "turn_on",
            {
                "entity_id": ["light.first", "light.second"],
                "brightness_pct": 50,
            },
        )
    ]


@pytest.mark.parametrize(
    "domain,key,attributes",
    [
        ("light", "lights", {"brightness": 102}),
        ("media_player", "media_players", {"volume_level": 0.4}),
    ],
)
async def test_shutdown_removes_listener_and_cancels_active_ramp(
    pico, domain, key, attributes
):
    pico.hass.states.async_set(f"{domain}.desk", "on", attributes)
    assert await pico.setup(
        [{"device_id": "pico", "type": "3BRL", key: f"{domain}.desk"}]
    )
    pico.fire("raise")
    await pico.next_call()
    await pico.next_call()
    await pico.stop()
    completed = list(pico.calls)
    pico.tap("on")
    await pico.drain()
    assert pico.calls == completed
    assert len(completed) == 2


@pytest.mark.parametrize(
    "domain,key",
    [
        ("light", "lights"),
        ("cover", "covers"),
        ("media_player", "media_players"),
    ],
)
async def test_shutdown_before_hold_threshold_prevents_delayed_commands(
    pico, domain, key
):
    pico.hass.states.async_set(
        f"{domain}.desk",
        "on",
        {
            "brightness": 102,
            "current_position": 40,
            "volume_level": 0.4,
        },
    )
    assert await pico.setup(
        [{"device_id": "pico", "type": "2B", key: f"{domain}.desk"}]
    )
    pico.fire("on", kind="2B")
    await pico.stop()
    assert pico.calls == []
