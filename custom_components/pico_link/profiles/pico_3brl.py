from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from ..const import DOUBLE_TAP_WINDOW_MS

if TYPE_CHECKING:
    from ..controller import PicoController

_LOGGER = logging.getLogger(__name__)


class Pico3ButtonRaiseLower:
    """
    ON, OFF, and STOP each support an optional hold action, or an
    optional double-tap action, in addition to their normal tap/press
    behavior (a button cannot define both — see PicoConfig.validate()).

    Hold: the domain's press behavior always still runs immediately on
    press, unchanged; if that button's on_hold/off_hold/stop_hold is
    configured and the button is still held once hold_time_ms elapses,
    that action sequence also runs.

    Double tap: when a button's on_double_tap/off_double_tap/
    stop_double_tap is configured, its tap no longer fires on press.
    Instead, each release waits up to DOUBLE_TAP_WINDOW_MS to see
    whether a second tap follows: if one does, the double-tap actions
    run instead; otherwise the normal press behavior runs once the
    window elapses.

    With nothing configured for a button, no timer is created at all
    and its tap fires immediately on press exactly as before, so
    unconfigured Picos are unaffected.
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

    def __init__(self, controller: "PicoController") -> None:
        self._ctrl = controller

        # Only one button's hold can be active at a time.
        self._hold_button: Optional[str] = None
        self._hold_task: Optional[asyncio.Task[Any]] = None
        self._hold_generation = 0

        # Double-tap detection, tracked per button so a tap on one
        # button never affects a pending tap on a different one.
        self._pending_tap_tasks: dict[str, asyncio.Task[Any]] = {}
        self._pending_tap_generations: dict[str, int] = {}

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

    def _double_tap_actions(self, button: str) -> list[dict[str, Any]]:
        return getattr(self._ctrl.conf, self._DOUBLE_TAP_ACTION_FIELDS[button])

    # -------------------------------------------------------------
    # PRESS
    # -------------------------------------------------------------
    def handle_press(self, button: str) -> None:
        actions = self._actions()
        if not actions:
            return

        match button:
            case "on" | "off" | "stop":
                if self._double_tap_actions(button):
                    # Resolved entirely on release, once we know
                    # whether a second tap follows.
                    return

                getattr(actions, self._TAP_METHODS[button])()
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
                if self._double_tap_actions(button):
                    self._resolve_tap_or_double_tap(button, actions)
                else:
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

    # -------------------------------------------------------------
    # ON / OFF / STOP DOUBLE-TAP ACTIONS
    # -------------------------------------------------------------

    def _resolve_tap_or_double_tap(self, button: str, actions: Any) -> None:
        """Complete a tap on a button with double-tap actions configured."""
        if button in self._pending_tap_tasks:
            # A tap was already pending for this button: this release
            # completes a double tap instead of a plain second tap.
            self._cancel_pending_tap(button)

            double_tap_actions = self._double_tap_actions(button)

            self._ctrl.create_task(
                self._ctrl.utils.execute_button_action(
                    double_tap_actions,
                    name=f"pico_link_{button}_double_tap",
                ),
                f"3brl-{button}-double-tap",
            )
            return

        generation = self._pending_tap_generations.get(button, 0) + 1
        self._pending_tap_generations[button] = generation

        self._pending_tap_tasks[button] = self._ctrl.create_task(
            self._fire_single_tap_after_window(
                button,
                actions,
                generation,
            ),
            f"3brl-{button}-tap-window",
        )

    async def _fire_single_tap_after_window(
        self,
        button: str,
        actions: Any,
        generation: int,
    ) -> None:
        """Fire the plain tap once the double-tap window elapses unmatched."""
        try:
            await asyncio.sleep(DOUBLE_TAP_WINDOW_MS / 1000)

            if self._pending_tap_generations.get(button) != generation:
                return

            self._pending_tap_tasks.pop(button, None)
            getattr(actions, self._TAP_METHODS[button])()
        except asyncio.CancelledError:
            # Expected when a second tap arrives within the window.
            pass

    def _cancel_pending_tap(self, button: str) -> None:
        # Bump the generation too, not just cancel the task: this
        # invalidates the pending coroutine's captured generation even
        # if cancellation loses the race with its sleep completing.
        self._pending_tap_generations[button] = (
            self._pending_tap_generations.get(button, 0) + 1
        )

        task = self._pending_tap_tasks.pop(button, None)

        if task and not task.done():
            task.cancel()
