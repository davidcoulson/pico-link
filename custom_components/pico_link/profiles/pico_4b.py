from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..controller import PicoController

_LOGGER = logging.getLogger(__name__)


class Pico4ButtonScene:
    """
    Pico 4-button scene controller:
    - Each button maps to a configured list of HA action calls.
    - Executes each action in order.
    """

    def __init__(self, controller: "PicoController") -> None:
        self._ctrl = controller

    # -------------------------------------------------------------
    # PRESS
    # -------------------------------------------------------------
    def handle_press(self, button: str) -> None:
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
    # RELEASE
    # -------------------------------------------------------------
    def handle_release(self, button: str) -> None:
        """Scene buttons do nothing on release."""
        return
