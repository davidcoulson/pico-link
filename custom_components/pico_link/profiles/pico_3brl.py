from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..controller import PicoController

_LOGGER = logging.getLogger(__name__)


class Pico3ButtonRaiseLower:
    """
    ON, OFF, and STOP each support an optional hold action in addition
    to their normal tap/press behavior. The domain's press behavior
    always still runs immediately on press, unchanged; if that
    button's on_hold/off_hold/stop_hold is configured and the button
    is still held once hold_time_ms elapses, that action sequence also
    runs. With nothing configured for a button, no timer is created at
    all, so unconfigured Picos are unaffected.
    """

    _HOLD_ACTION_FIELDS = {
        "on": "on_hold",
        "off": "off_hold",
        "stop": "stop_hold",
    }

    def __init__(self, controller: "PicoController") -> None:
        self._ctrl = controller

        # Only one button's hold can be active at a time.
        self._hold_button: Optional[str] = None
        self._hold_task: Optional[asyncio.Task[Any]] = None
        self._hold_generation = 0

    def _actions(self):
        domain = self._ctrl.utils.entity_domain()
        if not domain:
            _LOGGER.debug("3BRL: no domain configured")
            return None

        actions = self._ctrl.actions.get(domain)
        if not actions:
            _LOGGER.debug("3BRL: no action handler for domain %s", domain)
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
                actions.press_on()
                self._arm_hold(button)
            case "off":
                actions.press_off()
                self._arm_hold(button)
            case "stop":
                actions.press_stop()
                self._arm_hold(button)
            case "raise":
                actions.press_raise()
            case "lower":
                actions.press_lower()
            case _:
                _LOGGER.debug("3BRL: unknown press button '%s'", button)

    # -------------------------------------------------------------
    # RELEASE
    # -------------------------------------------------------------
    def handle_release(self, button: str) -> None:
        actions = self._actions()
        if not actions:
            return

        match button:
            case "raise":
                actions.release_raise()
            case "lower":
                actions.release_lower()
            case "on" | "off" | "stop":
                self._cancel_hold(button)
            case _:
                pass

    # -------------------------------------------------------------
    # ON / OFF / STOP HOLD ACTIONS
    # -------------------------------------------------------------

    def _arm_hold(self, button: str) -> None:
        """Start a hold timer for this button, if it has hold actions configured."""
        hold_actions = getattr(self._ctrl.conf, self._HOLD_ACTION_FIELDS[button])

        if not hold_actions:
            return

        self._cancel_hold(button)

        self._hold_button = button
        self._hold_generation += 1
        generation = self._hold_generation

        self._hold_task = self._ctrl.create_task(
            self._hold_lifecycle(
                button,
                hold_actions,
                generation,
            ),
            f"3brl-{button}-hold",
        )

    def _cancel_hold(self, button: str) -> None:
        """Cancel button's hold timer, if it's the one currently active."""
        if self._hold_button != button:
            return

        self._hold_button = None

        if self._hold_task and not self._hold_task.done():
            self._hold_task.cancel()

        self._hold_task = None

    async def _hold_lifecycle(
        self,
        button: str,
        hold_actions: list[dict[str, Any]],
        generation: int,
    ) -> None:
        """Run this button's hold actions once the hold threshold elapses."""
        try:
            await asyncio.sleep(self._ctrl.utils._hold_time)

            if self._hold_generation != generation or self._hold_button != button:
                return

            await self._ctrl.utils.execute_button_action(
                hold_actions,
                name=f"pico_link_{button}_hold",
            )
        except asyncio.CancelledError:
            # Expected when released before the hold threshold.
            pass
