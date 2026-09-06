from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

from ..const import DOUBLE_TAP_WINDOW_MS

if TYPE_CHECKING:
    from ..controller import PicoController


class HoldDoubleTapGestures:
    """
    Shared per-button hold-timer / double-tap-window state machine.

    A button's tap fires immediately on press, unchanged, unless that
    button has a double-tap action configured — then it defers to
    release, waiting up to DOUBLE_TAP_WINDOW_MS to see whether a second
    tap follows, so a plain single tap and a double tap resolve to
    different outcomes. A button's hold action (if configured) runs
    once held past hold_time_ms, in addition to its normal tap. A
    button cannot have both a hold and a double-tap action configured
    (enforced in PicoConfig.validate()), so the two never have to
    interact for the same button.

    With nothing configured for a button, no timer is created at all
    and its tap fires immediately on press exactly as if this mixin
    didn't exist.

    Subclasses implement _hold_actions_for(button) and
    _double_tap_actions_for(button) (returning that button's
    configured action list, or an empty one), a _task_prefix() for
    readable task names, and call _handle_gesture_press /
    _handle_gesture_release from their own handle_press/handle_release
    for whichever buttons participate in this state machine, passing a
    zero-argument callable that performs that button's normal tap.
    """

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

    def _hold_actions_for(self, button: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _double_tap_actions_for(self, button: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _task_prefix(self) -> str:
        raise NotImplementedError

    # -------------------------------------------------------------
    # PRESS / RELEASE ENTRY POINTS
    # -------------------------------------------------------------

    def _handle_gesture_press(
        self,
        button: str,
        tap_fn: Callable[[], None],
    ) -> None:
        if self._double_tap_actions_for(button):
            # Resolved entirely on release, once we know whether a
            # second tap follows.
            return

        tap_fn()
        self._arm_hold(button)

    def _handle_gesture_release(
        self,
        button: str,
        tap_fn: Callable[[], None],
    ) -> None:
        if self._double_tap_actions_for(button):
            self._resolve_tap_or_double_tap(button, tap_fn)
        else:
            self._cancel_hold(button)

    # -------------------------------------------------------------
    # HOLD ACTIONS
    # -------------------------------------------------------------

    def _arm_hold(self, button: str) -> None:
        """Start a hold timer for this button, if it has hold actions configured."""
        hold_actions = self._hold_actions_for(button)

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
            f"{self._task_prefix()}-{button}-hold",
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
    # DOUBLE-TAP ACTIONS
    # -------------------------------------------------------------

    def _resolve_tap_or_double_tap(
        self,
        button: str,
        tap_fn: Callable[[], None],
    ) -> None:
        """Complete a tap on a button with double-tap actions configured."""
        if button in self._pending_tap_tasks:
            # A tap was already pending for this button: this release
            # completes a double tap instead of a plain second tap.
            self._cancel_pending_tap(button)

            double_tap_actions = self._double_tap_actions_for(button)

            self._ctrl.create_task(
                self._ctrl.utils.execute_button_action(
                    double_tap_actions,
                    name=f"pico_link_{button}_double_tap",
                ),
                f"{self._task_prefix()}-{button}-double-tap",
            )
            return

        generation = self._pending_tap_generations.get(button, 0) + 1
        self._pending_tap_generations[button] = generation

        self._pending_tap_tasks[button] = self._ctrl.create_task(
            self._fire_tap_after_window(
                button,
                tap_fn,
                generation,
            ),
            f"{self._task_prefix()}-{button}-tap-window",
        )

    async def _fire_tap_after_window(
        self,
        button: str,
        tap_fn: Callable[[], None],
        generation: int,
    ) -> None:
        """Fire the plain tap once the double-tap window elapses unmatched."""
        try:
            await asyncio.sleep(DOUBLE_TAP_WINDOW_MS / 1000)

            if self._pending_tap_generations.get(button) != generation:
                return

            self._pending_tap_tasks.pop(button, None)
            tap_fn()
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
