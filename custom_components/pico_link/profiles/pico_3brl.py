from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .gesture_timing import HoldDoubleTapGestures

if TYPE_CHECKING:
    from ..controller import PicoController

_LOGGER = logging.getLogger(__name__)


class Pico3ButtonRaiseLower(HoldDoubleTapGestures):
    """
    ON, OFF, and STOP each support an optional hold action, or an
    optional double-tap action, in addition to their normal tap/press
    behavior (a button cannot define both — see PicoConfig.validate()).
    See HoldDoubleTapGestures for how those two gestures work.

    RAISE and LOWER are unaffected by any of this: they always ramp
    brightness/position/volume on hold, exactly as before.
    """

    _HOLD_ACTION_FIELDS = {
        "on": "on_hold",
        "off": "off_hold",
        "stop": "stop_hold",
    }

    _DOUBLE_TAP_ACTION_FIELDS = {
        "on": "on_double_tap",
        "off": "off_double_tap",
        "stop": "stop_double_tap",
    }

    _TAP_METHODS = {
        "on": "press_on",
        "off": "press_off",
        "stop": "press_stop",
    }

    _LOG_NAME = "3BRL"

    def __init__(self, controller: "PicoController") -> None:
        super().__init__(controller)

    def _task_prefix(self) -> str:
        return self._LOG_NAME.lower()

    def _hold_actions_for(self, button: str) -> list[dict[str, Any]]:
        return getattr(self._ctrl.conf, self._HOLD_ACTION_FIELDS[button])

    def _double_tap_actions_for(self, button: str) -> list[dict[str, Any]]:
        return getattr(self._ctrl.conf, self._DOUBLE_TAP_ACTION_FIELDS[button])

    def _actions(self):
        domain = self._ctrl.utils.entity_domain()
        if not domain:
            _LOGGER.debug("%s: no domain configured", self._LOG_NAME)
            return None

        actions = self._ctrl.actions.get(domain)
        if not actions:
            _LOGGER.debug("%s: no action handler for domain %s", self._LOG_NAME, domain)
            return None

        return actions

    # -------------------------------------------------------------
    # PRESS
    # -------------------------------------------------------------
    def handle_press(self, button: str) -> None:
        actions = self._actions()
        if not actions:
            return

        if button in self._TAP_METHODS:
            self._handle_gesture_press(
                button,
                getattr(actions, self._TAP_METHODS[button]),
            )
            return

        match button:
            case "raise":
                actions.press_raise()
            case "lower":
                actions.press_lower()
            case _:
                _LOGGER.debug("%s: unknown press button '%s'", self._LOG_NAME, button)

    # -------------------------------------------------------------
    # RELEASE
    # -------------------------------------------------------------
    def handle_release(self, button: str) -> None:
        actions = self._actions()
        if not actions:
            return

        if button in self._TAP_METHODS:
            self._handle_gesture_release(
                button,
                getattr(actions, self._TAP_METHODS[button]),
            )
            return

        match button:
            case "raise":
                actions.release_raise()
            case "lower":
                actions.release_lower()
            case _:
                pass
