from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .gesture_timing import HoldDoubleTapGestures

if TYPE_CHECKING:
    from ..controller import PicoController

_LOGGER = logging.getLogger(__name__)


class Pico4ButtonScene(HoldDoubleTapGestures):
    """
    Pico 4-button scene controller:
    - Each button maps to a configured list of HA action calls, run on
      tap.
    - A button can additionally define a hold action (button_hold; runs
      once held past hold_time_ms, in addition to its tap) or a
      double-tap action (button_double_tap; runs instead of its tap on
      two quick taps), but not both — see HoldDoubleTapGestures and
      PicoConfig.validate().
    """

    def __init__(self, controller: "PicoController") -> None:
        super().__init__(controller)

    def _task_prefix(self) -> str:
        return "4b"

    def _hold_actions_for(self, button: str) -> list[dict[str, Any]]:
        return self._ctrl.conf.button_hold.get(button, [])

    def _double_tap_actions_for(self, button: str) -> list[dict[str, Any]]:
        return self._ctrl.conf.button_double_tap.get(button, [])

    def _run_button_actions(self, button: str) -> None:
        # PicoConfig.buttons is validated when the config entry is set
        # up, so every value here is already a well-formed action list.
        scene_map = self._ctrl.conf.buttons

        if button not in scene_map:
            _LOGGER.debug(
                "Pico4B: button '%s' has no configured actions for device %s",
                button,
                self._ctrl.conf.device_id,
            )
            return

        self._ctrl.create_task(
            self._ctrl.utils.execute_button_action(scene_map[button]),
            f"4b-{button}",
        )

    # -------------------------------------------------------------
    # PRESS
    # -------------------------------------------------------------
    def handle_press(self, button: str) -> None:
        self._handle_gesture_press(
            button,
            lambda: self._run_button_actions(button),
        )

    # -------------------------------------------------------------
    # RELEASE
    # -------------------------------------------------------------
    def handle_release(self, button: str) -> None:
        self._handle_gesture_release(
            button,
            lambda: self._run_button_actions(button),
        )
