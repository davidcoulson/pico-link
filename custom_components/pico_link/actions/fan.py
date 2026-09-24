# fan_actions.py
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from homeassistant.core import State

if TYPE_CHECKING:
    from ..controller import PicoController


class FanActions:
    """
    Tap-only fan controller for all supported Pico profiles.

    Behaviors:
        ON tap     -> turn on to fan_on_pct
        OFF tap    -> turn off
        RAISE tap  -> move to the next higher speed
        LOWER tap  -> move to the next lower speed
        STOP tap   -> reverse direction or execute middle_button actions

    If the fan is off, RAISE moves it to the first available speed.
    """

    TARGET_CACHE_SECONDS = 2.0

    # FanEntityFeature.SET_SPEED
    SET_SPEED_FEATURE = 1

    def __init__(self, ctrl: "PicoController") -> None:
        self.ctrl = ctrl

        # Track the most recently requested percentage so rapid taps do
        # not depend on immediate Home Assistant state updates.
        self._target_percentage: Optional[int] = None
        self._target_updated_at = 0.0

    # =============================================================
    # PROFILE ENTRY POINTS
    # =============================================================

    def press_on(self) -> None:
        state = self.ctrl.utils.get_entity_state()

        # fan.set_percentage is refused for fans without SET_SPEED, so
        # plain on/off fans get turn_on without a percentage instead.
        if not self._supports_set_speed(state):
            self._clear_percentage_target()
            self.ctrl.create_task(
                self._turn_on(),
                "fan-turn-on",
            )
            return

        percentage = self.ctrl.conf.fan_on_pct
        self._set_percentage_target(percentage)

        self.ctrl.create_task(
            self._set_percentage(percentage),
            "fan-turn-on",
        )

    def release_on(self) -> None:
        pass

    def press_off(self) -> None:
        self._set_percentage_target(0)

        self.ctrl.create_task(
            self._turn_off(),
            "fan-turn-off",
        )

    def release_off(self) -> None:
        pass

    def press_stop(self) -> None:
        actions = self.ctrl.conf.middle_button

        if actions:
            # Custom middle-button actions may change the speed outside
            # this handler, so resynchronize on the next step.
            self._clear_percentage_target()
            self.ctrl.create_task(
                self.ctrl.utils.execute_button_action(actions),
                "fan-middle-button",
            )
            return

        self.ctrl.create_task(
            self._reverse_direction(),
            "fan-reverse-direction",
        )

    def release_stop(self) -> None:
        pass

    def press_raise(self) -> None:
        self._schedule_step(
            1,
            task_name="fan-step-up",
        )

    def release_raise(self) -> None:
        pass

    def press_lower(self) -> None:
        self._schedule_step(
            -1,
            task_name="fan-step-down",
        )

    def release_lower(self) -> None:
        pass

    # =============================================================
    # FAN OPERATIONS
    # =============================================================

    async def _turn_on(self) -> None:
        await self.ctrl.utils.call_service(
            "turn_on",
            {},
            domain="fan",
        )

    async def _set_percentage(self, percentage: int) -> None:
        await self.ctrl.utils.call_service(
            "set_percentage",
            {"percentage": percentage},
            domain="fan",
        )

    async def _turn_off(self) -> None:
        await self.ctrl.utils.call_service(
            "turn_off",
            {},
            domain="fan",
        )

    async def _reverse_direction(self) -> None:
        state = self.ctrl.utils.get_entity_state()

        if not state:
            return

        current_direction = state.attributes.get("direction")

        if current_direction not in ("forward", "reverse"):
            return

        new_direction = "reverse" if current_direction == "forward" else "forward"

        await self.ctrl.utils.call_service(
            "set_direction",
            {"direction": new_direction},
            domain="fan",
        )

    # =============================================================
    # DISCRETE SPEED STEPPING
    # =============================================================

    def _schedule_step(
        self,
        direction: int,
        *,
        task_name: str,
    ) -> None:
        """
        Move the fan one step up or down its discrete speed ladder.

        If the fan is off, stepping upward selects the first nonzero
        speed. The step is calculated and stored synchronously so rapid
        taps build on the previous requested speed.
        """
        state = self.ctrl.utils.get_entity_state()

        if not state:
            return

        speed_ladder = self._get_speed_ladder(state)
        current_percentage = self._percentage_for_step(state)

        if current_percentage == 0 and direction > 0:
            # The ladder always contains at least [0, 100].
            new_percentage = speed_ladder[1]
        else:
            current_index = min(
                range(len(speed_ladder)),
                key=lambda index: abs(speed_ladder[index] - current_percentage),
            )

            new_index = max(
                0,
                min(
                    len(speed_ladder) - 1,
                    current_index + direction,
                ),
            )

            new_percentage = speed_ladder[new_index]

        # Avoid redundant calls at the top or bottom of the ladder.
        if new_percentage == current_percentage:
            return

        self._set_percentage_target(new_percentage)

        # Plain on/off fans reject set_percentage; the ladder is [0, 100].
        if not self._supports_set_speed(state):
            self.ctrl.create_task(
                self._turn_on() if new_percentage > 0 else self._turn_off(),
                task_name,
            )
            return

        self.ctrl.create_task(
            self._set_percentage(new_percentage),
            task_name,
        )

    # =============================================================
    # PERCENTAGE TARGET STATE
    # =============================================================

    def _set_percentage_target(self, percentage: int) -> None:
        """Store the latest requested fan percentage."""
        self._target_percentage = max(
            0,
            min(100, percentage),
        )
        self._target_updated_at = time.monotonic()

    def _clear_percentage_target(self) -> None:
        """Discard the optimistic percentage target."""
        self._target_percentage = None
        self._target_updated_at = 0.0

    def _percentage_for_step(self, state: State) -> int:
        """
        Return the recent requested percentage or resynchronize from HA.

        The short cache lets rapid taps build on the previous command
        without keeping an optimistic value authoritative indefinitely.
        """
        now = time.monotonic()

        if (
            self._target_percentage is not None
            and now - self._target_updated_at <= self.TARGET_CACHE_SECONDS
        ):
            return self._target_percentage

        percentage = self._get_current_percentage(state)
        self._set_percentage_target(percentage)

        return percentage

    # =============================================================
    # SPEED HELPERS
    # =============================================================

    def _supports_set_speed(self, state: Optional[State]) -> bool:
        """Return True unless the fan reports it has no SET_SPEED feature."""
        if not state:
            return True

        features = state.attributes.get("supported_features")

        if isinstance(features, bool) or not isinstance(features, int):
            return True

        return bool(features & self.SET_SPEED_FEATURE)

    def _get_speed_ladder(self, state: State) -> list[int]:
        """
        Build a discrete speed ladder from percentage_step.

        The ladder is derived from the speed count the same way Home
        Assistant maps speeds to percentages, so every rung is a value
        the fan actually reports. Accumulating the float step instead
        would give 33.33 -> [0, 33, 66, 99, 100], and HA maps 99 back to
        the top speed, leaving LOWER stuck at 100.

        Examples:
            percentage_step=25    -> [0, 25, 50, 75, 100]
            percentage_step=33.33 -> [0, 33, 66, 100]
        """
        raw_step = state.attributes.get("percentage_step")

        if (
            isinstance(raw_step, bool)
            or not isinstance(raw_step, (int, float))
            or raw_step <= 0
        ):
            return [0, 100]

        return build_speed_ladder(raw_step)

    def _get_current_percentage(self, state: State) -> int:
        """Return the current fan percentage, treating OFF as zero."""
        if state.state == "off":
            return 0

        raw_percentage = state.attributes.get("percentage")

        if raw_percentage is None:
            return 0

        if isinstance(raw_percentage, bool) or not isinstance(
            raw_percentage,
            (int, float, str),
        ):
            return 0

        try:
            percentage = int(float(raw_percentage))
        except ValueError:
            return 0

        return max(
            0,
            min(100, percentage),
        )

    # =============================================================
    # LIFECYCLE
    # =============================================================

    def reset_state(self) -> None:
        """Clear the optimistic percentage target."""
        self._clear_percentage_target()


def build_speed_ladder(percentage_step: float) -> list[int]:
    """
    Return [0, ..., 100] for a fan whose speeds are percentage_step apart.

    Matches homeassistant.util.percentage.ranged_value_to_percentage for
    each speed 1..speed_count, so the rungs are exactly the percentages
    HA reports for a fan with that many speeds.
    """
    speed_count = max(1, round(100 / percentage_step))

    return [0] + [
        int(speed * 100 // speed_count) for speed in range(1, speed_count + 1)
    ]
