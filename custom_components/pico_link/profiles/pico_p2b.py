# profiles/profile_p2b.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .gesture_timing import OnOffDoubleTapGestures

if TYPE_CHECKING:
    from ..controller import PicoController

_LOGGER = logging.getLogger(__name__)


class PaddleSwitchPico(OnOffDoubleTapGestures):
    """
    ON and OFF each support an optional double-tap action, in addition
    to their normal domain-specific tap/hold behavior. A double tap
    replaces that gesture rather than running alongside it -- see
    OnOffDoubleTapGestures for how that works.
    """

    _DOUBLE_TAP_ACTION_FIELDS = {
        "on": "on_double_tap",
        "off": "off_double_tap",
    }

    def __init__(self, controller: "PicoController") -> None:
        super().__init__(controller)

    def _task_prefix(self) -> str:
        return "p2b"

    def _double_tap_actions_for(self, button: str) -> list[dict[str, Any]]:
        return getattr(self._ctrl.conf, self._DOUBLE_TAP_ACTION_FIELDS[button])

    def _actions(self):
        domain = self._ctrl.utils.entity_domain()
        if not domain:
            return None

        actions = self._ctrl.actions.get(domain)
        if not actions:
            _LOGGER.debug("P2B: No action handler available for domain %s", domain)
            return None

        return actions

    # -------------------------------------------------------------
    # PRESS
    # -------------------------------------------------------------
    def handle_press(self, button: str) -> None:
        actions = self._actions()
        if not actions:
            return

        match button:
            case "on":
                self._handle_double_tap_press(
                    "on", actions.press_on, actions.release_on
                )
            case "off":
                self._handle_double_tap_press(
                    "off", actions.press_off, actions.release_off
                )
            case _:
                _LOGGER.debug("P2B: Ignoring unexpected press button '%s'", button)

    # -------------------------------------------------------------
    # RELEASE
    # -------------------------------------------------------------
    def handle_release(self, button: str) -> None:
        actions = self._actions()
        if not actions:
            return

        match button:
            case "on":
                self._handle_double_tap_release(
                    "on", actions.press_on, actions.release_on
                )
            case "off":
                self._handle_double_tap_release(
                    "off", actions.press_off, actions.release_off
                )
            case _:
                _LOGGER.debug("P2B: Ignoring unexpected release button '%s'", button)
