from homeassistant.components.cover import CoverEntityFeature
from homeassistant.core import State

from custom_components.pico_link.actions.cover import CoverActions


def _supports(attributes):
    return CoverActions(ctrl=None)._supports_set_position(
        State("cover.test", "open", attributes)
    )


def test_set_position_feature_detection():
    assert _supports({"supported_features": CoverEntityFeature.SET_POSITION}) is True
    assert (
        _supports(
            {"supported_features": CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE}
        )
        is False
    )
    # Unknown or malformed feature flags are treated as "can position",
    # matching the previous behaviour.
    assert _supports({}) is True
    assert _supports({"supported_features": "3"}) is True
    assert _supports({"supported_features": True}) is True
