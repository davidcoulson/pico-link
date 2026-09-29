"""Custom actions, target preservation, sequencing and service failure recovery."""

import asyncio

import pytest
from homeassistant.exceptions import HomeAssistantError


async def test_unassigned_scene_button_is_ignored(pico):
    assert await pico.setup(
        [
            {
                "device_id": "pico",
                "type": "4B",
                "buttons": {
                    "button_1": [{"action": "scene.turn_on"}],
                },
            }
        ]
    )
    pico.tap("button_2", kind="4B")
    await pico.drain()
    assert pico.calls == []


@pytest.mark.parametrize("button", ["button_1", "button_2", "button_3", "off"])
async def test_every_scene_button_runs_its_assigned_action_once(pico, button):
    buttons = {
        name: [
            {
                "action": "scene.turn_on",
                "target": {
                    "entity_id": f"scene.{name}",
                },
            }
        ]
        for name in ("button_1", "button_2", "button_3", "off")
    }
    assert await pico.setup([{"device_id": "pico", "type": "4B", "buttons": buttons}])
    pico.tap(button, kind="4B")
    await pico.drain()
    assert pico.calls == [("scene", "turn_on", {"entity_id": f"scene.{button}"})]


@pytest.mark.parametrize("kind,button", [("3BRL", "stop"), ("4B", "button_1")])
async def test_actions_wait_for_previous_completion_and_preserve_targets(
    pico, kind, button
):
    complete_first = asyncio.Event()

    async def slow_scene(call):
        await complete_first.wait()

    pico.register("scene", "turn_on", slow_scene)
    actions = [
        {
            "action": "scene.turn_on",
            "target": {"entity_id": "scene.relax"},
            "data": {"transition": 2},
        },
        {
            "action": "script.turn_on",
            "target": {"entity_id": "script.evening"},
            "data": {"variables": {"room": "office"}},
        },
    ]
    options = (
        {"lights": "light.test", "middle_button": actions}
        if kind == "3BRL"
        else {"buttons": {button: actions}}
    )
    assert await pico.setup([{"device_id": "pico", "type": kind, **options}])
    pico.tap(button, kind=kind)
    assert await pico.next_call() == (
        "scene",
        "turn_on",
        {
            "entity_id": "scene.relax",
            "transition": 2,
        },
    )
    assert len(pico.calls) == 1
    complete_first.set()
    await pico.drain()
    assert pico.calls[1:] == [
        (
            "script",
            "turn_on",
            {
                "entity_id": "script.evening",
                "variables": {"room": "office"},
            },
        )
    ]


@pytest.mark.parametrize(
    "key,entity",
    [
        ("lights", "light.test"),
        ("covers", "cover.test"),
        ("fans", "fan.test"),
        ("media_players", "media_player.test"),
        ("switches", "switch.test"),
    ],
)
async def test_custom_middle_button_overrides_each_domains_default(pico, key, entity):
    pico.hass.states.async_set(
        entity, "on", {"direction": "forward", "is_volume_muted": False}
    )
    assert await pico.setup(
        [
            {
                "device_id": "pico",
                "type": "3BRL",
                key: entity,
                "middle_button": [
                    {"action": "scene.turn_on", "target": {"entity_id": "scene.relax"}}
                ],
            }
        ]
    )
    pico.tap("stop")
    await pico.drain()
    assert pico.calls == [("scene", "turn_on", {"entity_id": "scene.relax"})]


async def test_shared_middle_action_expands_targets_without_losing_area(pico):
    actions = [
        {
            "action": "light.turn_on",
            "target": {
                "entity_id": "lights",
                "area_id": "office",
            },
            "data": {"brightness_pct": 60},
        }
    ]
    assert await pico.setup(
        [
            {
                "device_id": "pico",
                "type": "3BRL",
                "lights": ["light.desk", "light.wall"],
                "middle_button": "default",
            }
        ],
        {"middle_button": actions},
    )
    pico.tap("stop")
    await pico.drain()
    assert pico.calls == [
        (
            "light",
            "turn_on",
            {
                "entity_id": ["light.desk", "light.wall"],
                "area_id": "office",
                "brightness_pct": 60,
            },
        )
    ]


async def test_failed_action_is_logged_and_later_actions_and_presses_still_work(
    pico, caplog
):
    async def fail(call):
        raise HomeAssistantError("Test device is unavailable")

    pico.register("scene", "turn_on", fail)
    assert await pico.setup(
        [
            {
                "device_id": "pico",
                "type": "4B",
                "buttons": {
                    "button_1": [
                        {"action": "scene.turn_on"},
                        {"action": "script.turn_on"},
                    ],
                },
            }
        ]
    )
    pico.tap("button_1", kind="4B")
    await pico.drain()
    pico.tap("button_1", kind="4B")
    await pico.drain()
    assert [(domain, service) for domain, service, _ in pico.calls] == [
        ("scene", "turn_on"),
        ("script", "turn_on"),
        ("scene", "turn_on"),
        ("script", "turn_on"),
    ]
    assert "error calling scene.turn_on" in caplog.text


async def test_missing_service_does_not_disable_remote(pico, caplog):
    assert await pico.setup(
        [
            {
                "device_id": "pico",
                "type": "4B",
                "buttons": {
                    "button_1": [{"action": "scene.not_registered"}],
                    "button_2": [{"action": "script.turn_on"}],
                },
            }
        ]
    )
    pico.tap("button_1", kind="4B")
    await pico.drain()
    pico.tap("button_2", kind="4B")
    await pico.drain()
    assert pico.calls == [("script", "turn_on", {})]
    assert "error calling scene.not_registered" in caplog.text


async def test_shutdown_cancels_pending_sequence_before_next_action(pico):
    first_cancelled = asyncio.Event()

    async def pending(call):
        try:
            await asyncio.Event().wait()
        finally:
            first_cancelled.set()

    pico.register("script", "turn_on", pending)
    assert await pico.setup(
        [
            {
                "device_id": "pico",
                "type": "4B",
                "buttons": {
                    "button_1": [
                        {"action": "script.turn_on"},
                        {"action": "scene.turn_on"},
                    ],
                },
            }
        ]
    )
    pico.tap("button_1", kind="4B")
    await pico.next_call()
    await pico.stop()
    assert first_cancelled.is_set()
    assert pico.calls == [("script", "turn_on", {})]
