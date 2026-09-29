"""Optional gesture routing; unconfigured buttons keep their original path."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .config import PICO_BUTTONS

if TYPE_CHECKING:
    from .controller import PicoController


@dataclass
class Gesture:
    button: str
    held: bool = False
    native_hold: bool = False
    tap_consumed: bool = False


@dataclass
class DeferredPress:
    button: str
    released: bool = False
    started: bool = False
    canceled: bool = False


class ButtonOverrides:
    """Recognize one gesture per Pico without serializing different remotes."""

    def __init__(self, ctrl: PicoController) -> None:
        self.ctrl = ctrl
        self.actions = ctrl.conf.overrides
        self.buttons = {key.rsplit("_", 1)[0] for key in self.actions}
        self.domain = ctrl.utils.entity_domain()
        self.handler = ctrl.actions.get(self.domain)
        self.gesture: Gesture | None = None
        self.timer: asyncio.Task[Any] | None = None
        self.stops: set[asyncio.Task[Any]] = set()
        self.deferred: list[Callable[[], None]] = []
        self.drain_task: asyncio.Task[Any] | None = None
        self.pending_press: DeferredPress | None = None

    def reset(self) -> None:
        """Invalidate pending detection; completed custom holds keep running."""
        self.gesture = None
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None

    def _has_native_hold(self, button: str) -> bool:
        if self.domain not in {"light", "cover", "media_player"}:
            return False
        return button in (
            {"on", "off"}
            if self.ctrl.conf.type in {"P2B", "2B"}
            else {"raise", "lower"}
            if self.ctrl.conf.type == "3BRL"
            else set()
        )

    def _after_stops(self, callback: Callable[[], None]) -> None:
        """Order new commands after stopping a previous continuous cover hold."""
        if not self._waiting_for_stop():
            callback()
            return

        self.deferred.append(callback)
        if self.drain_task is not None:
            return

        async def finish() -> None:
            try:
                while stops := tuple(task for task in self.stops if not task.done()):
                    await asyncio.gather(*(asyncio.shield(task) for task in stops))
                pending, self.deferred = self.deferred, []
                for pending_callback in pending:
                    pending_callback()
            finally:
                self.deferred.clear()
                self.drain_task = None

        self.drain_task = self.ctrl.create_task(finish(), "override-after-cover-stop")

    def _waiting_for_stop(self) -> bool:
        return self.drain_task is not None or any(
            not task.done() for task in self.stops
        )

    def handle(self, button: str, action: str) -> bool:
        """Return whether an event was handled by the optional override path."""
        if button not in PICO_BUTTONS[self.ctrl.conf.type]:
            return False
        if action == "press":
            if self.pending_press is not None:
                # An unreleased press superseded during a slow cover STOP
                # must never start a delayed native ramp afterward.
                if not self.pending_press.started and not self.pending_press.released:
                    self.pending_press.canceled = True
                self.pending_press = None
            self.reset()

        if button not in self.buttons:
            # Normally fall straight through. Only an in-flight cover STOP
            # requires ordering, including a quick following press/release.
            if self._waiting_for_stop():
                self._defer_native(button, action)
                return True
            return False

        if action == "press":
            gesture = Gesture(button)
            self.gesture = gesture
            prepare = getattr(self.handler, "prepare_override", None)
            if prepare is not None:
                stop, gesture.tap_consumed = prepare(
                    button, default_tap=f"{button}_tap" not in self.actions
                )
                if stop is not None:
                    self.stops.add(stop)
                    stop.add_done_callback(self.stops.discard)
            if f"{button}_hold" in self.actions or self._has_native_hold(button):
                self.timer = self.ctrl.create_task(self._hold(gesture), "override-hold")
            else:
                # Without a competing hold action there is no reason to wait.
                gesture.held = True
                self._tap(gesture)
            return True

        gesture = self.gesture
        if gesture is None or gesture.button != button:
            return True
        self.reset()
        if gesture.native_hold:
            self.ctrl._behavior.handle_release(button)
        elif not gesture.held:
            self._tap(gesture)
        return True

    def _defer_native(self, button: str, action: str) -> None:
        if action == "press":
            press = DeferredPress(button)
            self.pending_press = press

            def begin() -> None:
                if press.canceled:
                    return
                press.started = True
                self.ctrl._behavior.handle_press(button)
                if press.released:
                    self.ctrl._behavior.handle_release(button)

            self._after_stops(begin)
        elif (
            self.pending_press is not None
            and self.pending_press.button == button
            and not self.pending_press.started
        ):
            self.pending_press.released = True
        else:
            self._after_stops(lambda: self.ctrl._behavior.handle_release(button))

    def _tap(self, gesture: Gesture) -> None:
        key = f"{gesture.button}_tap"
        if key in self.actions:
            self._custom(key)
        elif not gesture.tap_consumed:

            def native_tap() -> None:
                self.ctrl._behavior.handle_press(gesture.button)
                self.ctrl._behavior.handle_release(gesture.button)

            self._after_stops(native_tap)

    async def _hold(self, gesture: Gesture) -> None:
        await asyncio.sleep(self.ctrl.utils._hold_time)
        if self.gesture is not gesture:
            return
        self.timer = None
        gesture.held = True
        key = f"{gesture.button}_hold"
        if key in self.actions:
            self._custom(key)
        elif not gesture.tap_consumed:

            def native_hold() -> None:
                if self.gesture is gesture:
                    gesture.native_hold = True
                    self.handler.start_hold(gesture.button)

            self._after_stops(native_hold)

    def _custom(self, key: str) -> None:
        # A custom service may change the target, so the next native gesture
        # must resynchronize. Do not cancel an already recognized sequence
        # on release; the controller still cancels it during shutdown.
        invalidate = getattr(self.handler, "invalidate_target", None)
        if invalidate is not None:
            invalidate()
        self._after_stops(
            lambda: self.ctrl.create_task(
                self.ctrl.utils.execute_button_action(self.actions[key]),
                f"override-{key}",
            )
        )
