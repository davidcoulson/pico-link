"""Tests for the pure config normalizers and PicoConfig.validate()."""

from __future__ import annotations

import pytest

from custom_components.pico_link.config import (
    PicoConfig,
    _expand_placeholders,
    _normalize_entities,
    _normalize_int,
    _normalize_rgb_color,
    parse_pico_config,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (50, 50),
        ("50", 50),
        (0, 10),  # zero means "use the default"
        (None, 10),
        ("abc", 10),
        (True, 10),  # bools are not ints here
        (-5, 1),  # clamped
        (999, 100),  # clamped
    ],
)
def test_normalize_int(raw, expected):
    assert _normalize_int(raw, default=10, min_val=1, max_val=100) == expected


def test_normalize_entities_accepts_string_list_and_dedupes():
    assert _normalize_entities("light.a", key="lights", domain="light") == ["light.a"]
    assert _normalize_entities(
        [" light.a ", "light.b", "light.a"], key="lights", domain="light"
    ) == ["light.a", "light.b"]
    assert _normalize_entities(None, key="lights", domain="light") == []


@pytest.mark.parametrize(
    "bad",
    [
        ["switch.a"],  # wrong domain
        ["not an entity id"],
        [42],
        {"light.a": 1},
    ],
)
def test_normalize_entities_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        _normalize_entities(bad, key="lights", domain="light")


def test_normalize_rgb_color():
    assert _normalize_rgb_color(None, key="c", default=[1, 2, 3]) == [1, 2, 3]
    assert _normalize_rgb_color([255, 128.0, 0], key="c", default=[1, 2, 3]) == [
        255,
        128,
        0,
    ]

    with pytest.raises(ValueError):
        _normalize_rgb_color([1, 2], key="c", default=[1, 2, 3])

    with pytest.raises(ValueError):
        _normalize_rgb_color([1, 2, 300], key="c", default=[1, 2, 3])


def test_expand_placeholders_walks_nested_actions():
    placeholders = {"lights": ["light.a", "light.b"]}
    actions = [
        {"action": "light.turn_on", "target": {"entity_id": "lights"}},
        {
            "if": [{"condition": "state", "entity_id": "light.a", "state": "on"}],
            "then": [
                {
                    "action": "light.turn_off",
                    "target": {"entity_id": ["lights", "light.c"]},
                }
            ],
        },
    ]

    expanded = _expand_placeholders(actions, placeholders)

    assert expanded[0]["target"]["entity_id"] == ["light.a", "light.b"]
    assert expanded[1]["then"][0]["target"]["entity_id"] == [
        "light.a",
        "light.b",
        "light.c",
    ]
    # A real entity ID that isn't a placeholder passes through untouched.
    assert expanded[1]["if"][0]["entity_id"] == "light.a"
    # The input is not mutated.
    assert actions[0]["target"]["entity_id"] == "lights"


def _config(**overrides) -> PicoConfig:
    base = {"device_id": "dev", "type": "3BRL", "lights": ["light.a"]}
    base.update(overrides)
    return PicoConfig(**base)


def test_validate_requires_exactly_one_domain():
    with pytest.raises(ValueError, match="exactly one"):
        _config(lights=[]).validate()

    with pytest.raises(ValueError, match="multiple entity domains"):
        _config(fans=["fan.a"]).validate()


def test_validate_accent_and_light_presets_exclusivity():
    _config(accent_lights=["light.b"]).validate()

    with pytest.raises(ValueError, match="both 'lights'"):
        _config(accent_lights=["light.a"]).validate()

    with pytest.raises(ValueError, match="'middle_button' and 'accent_lights'"):
        _config(accent_lights=["light.b"], middle_button=[{"action": "x.y"}]).validate()

    with pytest.raises(ValueError, match="'accent_lights' and 'light_presets'"):
        _config(accent_lights=["light.b"], light_presets=[object()]).validate()

    with pytest.raises(ValueError, match="Only 3BRL"):
        _config(type="P2B", light_presets=[object()]).validate()


def test_validate_hold_and_double_tap_are_exclusive_per_button():
    with pytest.raises(ValueError, match="'on_hold' and 'on_double_tap'"):
        _config(
            on_hold=[{"action": "x.y"}], on_double_tap=[{"action": "x.y"}]
        ).validate()


def test_validate_4b_rules():
    with pytest.raises(ValueError, match="non-empty 'buttons'"):
        PicoConfig(device_id="dev", type="4B").validate()

    with pytest.raises(ValueError, match="cannot define entity domains"):
        PicoConfig(device_id="dev", type="4B", lights=["light.a"]).validate()

    with pytest.raises(ValueError, match="both 'button_hold' and 'button_double_tap'"):
        PicoConfig(
            device_id="dev",
            type="4B",
            buttons={"button_1": [{"action": "x.y"}]},
            button_hold={"button_1": [{"action": "x.y"}]},
            button_double_tap={"button_1": [{"action": "x.y"}]},
        ).validate()


@pytest.mark.asyncio
async def test_parse_pico_config_without_custom_actions_needs_no_hass():
    """Action validation is the only part that touches hass; skip it and the parse is pure."""
    config = await parse_pico_config(
        None,
        {
            "device_id": " dev ",
            "type": "3brl",
            "lights": ["light.a"],
            "light_on_pct": "80",
            "hold_time_ms": 0,
            "light_transition_step_ms": "500",
            "light_on_off_toggle": "yes",
            "accent_light_presets": [{"accent_light_rgb_color": [1, 2, 3]}],
        },
    )

    assert config.device_id == "dev"
    assert config.type == "3BRL"
    assert config.light_on_pct == 80
    assert config.hold_time_ms == 400
    assert config.light_on_off_toggle is False
    assert config.light_transition_step_ms == 500
    assert config.accent_light_presets[0].rgb_color == [1, 2, 3]
    assert config.middle_button == []


@pytest.mark.asyncio
async def test_step_transition_default_and_upper_bound():
    base = {"device_id": "dev", "type": "3BRL", "lights": ["light.a"]}
    default = await parse_pico_config(None, base)
    capped = await parse_pico_config(None, {**base, "light_transition_step_ms": 4000})

    assert default.light_transition_step_ms == 0
    assert capped.light_transition_step_ms == 2000
