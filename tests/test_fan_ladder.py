import pytest
from homeassistant.util.percentage import ranged_value_to_percentage

from custom_components.pico_link.actions.fan import build_speed_ladder


@pytest.mark.parametrize(
    ("percentage_step", "expected"),
    [
        (100, [0, 100]),
        (50, [0, 50, 100]),
        (33.333, [0, 33, 66, 100]),
        (25, [0, 25, 50, 75, 100]),
        (16.667, [0, 16, 33, 50, 66, 83, 100]),
        (10, [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    ],
)
def test_build_speed_ladder(percentage_step, expected):
    assert build_speed_ladder(percentage_step) == expected


@pytest.mark.parametrize("speed_count", range(1, 13))
def test_ladder_matches_home_assistant_percentages(speed_count):
    """Every rung is a percentage HA reports for a fan with that many speeds."""
    percentage_step = 100 / speed_count
    expected = [0] + [
        ranged_value_to_percentage((1, speed_count), speed)
        for speed in range(1, speed_count + 1)
    ]

    assert build_speed_ladder(percentage_step) == expected


def test_ladder_top_is_reachable_downward():
    """LOWER from 100 must land on a rung HA does not map back to the top speed."""
    ladder = build_speed_ladder(33.333)

    assert ladder[-1] == 100
    assert ladder[-2] == 66
