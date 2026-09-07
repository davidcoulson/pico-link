from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

from ..const import ON_OFF_PICO_TYPES

if TYPE_CHECKING:
    from ..config import AccentPreset
    from ..controller import PicoController

_LOGGER = logging.getLogger(__name__)

TapAction = Callable[[], None]


class LightActions:
    """
    Light behavior for all supported Pico profiles.

    P2B / 2B:
        ON tap   -> turn on to light_on_pct
        ON hold  -> ramp brightness upward
        OFF tap  -> turn off
        OFF hold -> ramp brightness downward

    P2B / 2B dual-light mode (accent_lights configured):
        ON tap   -> switch to the center light(s) at light_on_pct;
                    turn off the accent light(s)
        ON hold  -> ramp the center light(s) brightness upward,
                    turning off the accent light(s) once the hold
                    threshold is crossed
        OFF tap  -> switch to the accent light(s) at their configured
                    color/effect; turn off the center light(s)
        OFF hold -> ramp the center light(s) brightness downward;
                    once it bottoms out at light_low_pct, switch to
                    the accent light(s) instead of just stopping
        The center and accent lights are never on at the same time.

    3BRL:
        ON tap      -> turn on to light_on_pct
        OFF tap     -> turn off
        RAISE tap   -> one brightness step up
        RAISE hold  -> ramp brightness upward
        LOWER tap   -> one brightness step down
        LOWER hold  -> ramp brightness downward
        STOP tap    -> execute middle_button actions, otherwise no-op
    """

    MAX_RAMP_STEPS = 50
    TARGET_CACHE_SECONDS = 2.0

    def __init__(self, ctrl: "PicoController") -> None:
        self.ctrl = ctrl

        # Only one ON/OFF/RAISE/LOWER gesture may be active at a time.
        self._active_button: Optional[str] = None
        self._is_holding = False
        self._gesture_generation = 0

        # Retain the delayed hold task so a release or newer press can
        # cancel it before or during a ramp.
        self._hold_task: Optional[asyncio.Task[Any]] = None

        # Track the most recently requested brightness so rapid taps and
        # ramps do not depend on immediate Home Assistant state updates.
        self._target_brightness_pct: Optional[int] = None
        self._target_updated_at = 0.0

        # Dual-light mode: which accent preset is currently showing.
        # None means the accent light isn't (to our knowledge) active,
        # so the next switch-to-accent starts over at preset 0.
        self._accent_preset_index: Optional[int] = None

    # =============================================================
    # PROFILE HELPERS
    # =============================================================

    def _supports_onoff_hold(self) -> bool:
        """Return True when ON/OFF must distinguish taps from holds."""
        return self.ctrl.conf.type in ON_OFF_PICO_TYPES

    def _dual_light_mode(self) -> bool:
        """Return True when ON/OFF switch between center and accent lights."""
        return bool(self.ctrl.conf.accent_lights)

    def _transition_data(
        self,
        *,
        turning_on: bool,
    ) -> dict[str, int]:
        """Return the configured transition data for a tap action."""
        transition = (
            self.ctrl.conf.light_transition_on
            if turning_on
            else self.ctrl.conf.light_transition_off
        )

        return {"transition": transition} if transition > 0 else {}

    # =============================================================
    # GESTURE STATE
    # =============================================================

    def _clear_gesture(self) -> bool:
        """
        Cancel the active gesture.

        Returns True when the gesture had crossed the hold threshold.
        """
        was_holding = self._is_holding

        self._gesture_generation += 1
        self._active_button = None
        self._is_holding = False

        if self._hold_task and not self._hold_task.done():
            self._hold_task.cancel()

        self._hold_task = None

        return was_holding

    def _begin_gesture(self, button: str) -> int:
        """Cancel the previous gesture and activate a new one."""
        self._clear_gesture()
        self._active_button = button

        return self._gesture_generation

    def _gesture_is_current(
        self,
        button: str,
        generation: int,
    ) -> bool:
        """Return True when a task still belongs to the active gesture."""
        return generation == self._gesture_generation and self._active_button == button

    def _arm_hold(
        self,
        button: str,
        direction: int,
        generation: int,
    ) -> None:
        """Schedule hold detection for the active gesture."""
        self._hold_task = self.ctrl.create_task(
            self._hold_lifecycle(
                button,
                direction,
                generation,
            ),
            f"light-{button}-hold",
        )

    # =============================================================
    # BRIGHTNESS TARGET STATE
    # =============================================================

    def _set_brightness_target(self, percentage: int) -> None:
        """Store the latest requested brightness percentage."""
        self._target_brightness_pct = max(
            0,
            min(100, percentage),
        )
        self._target_updated_at = time.monotonic()

    def _clear_brightness_target(self) -> None:
        """Discard the optimistic brightness target."""
        self._target_brightness_pct = None
        self._target_updated_at = 0.0

    def _brightness_for_step(self) -> Optional[int]:
        """
        Return the recent requested brightness or resynchronize from HA.

        The short cache lets rapid taps build on the previous command
        without keeping an optimistic value authoritative indefinitely.
        """
        now = time.monotonic()

        if (
            self._target_brightness_pct is not None
            and now - self._target_updated_at <= self.TARGET_CACHE_SECONDS
        ):
            return self._target_brightness_pct

        percentage = self._get_current_brightness_pct()

        if percentage is not None:
            self._set_brightness_target(percentage)

        return percentage

    def _get_current_brightness_pct(self) -> Optional[int]:
        """Return the current brightness percentage of the primary light."""
        state = self.ctrl.utils.get_entity_state()

        if not state:
            return None

        if state.state == "off":
            return 0

        raw_brightness = state.attributes.get("brightness")

        if raw_brightness is None:
            return 0

        if isinstance(raw_brightness, bool) or not isinstance(
            raw_brightness,
            (int, float, str),
        ):
            return 0

        try:
            brightness = float(raw_brightness)
        except ValueError:
            return 0

        return max(
            0,
            min(
                100,
                round((brightness / 255.0) * 100),
            ),
        )

    def _calculate_next_brightness(
        self,
        current_percentage: int,
        direction: int,
    ) -> int:
        """Return the next clamped brightness percentage."""
        new_percentage = current_percentage + (
            self.ctrl.conf.light_step_pct * direction
        )

        if direction < 0:
            # LOWER while the light is off should not turn it on.
            if current_percentage == 0:
                return 0

            new_percentage = max(
                self.ctrl.conf.light_low_pct,
                new_percentage,
            )
        elif current_percentage == 0:
            # RAISE (or an ON hold ramp) from off should land at least at
            # light_low_pct, matching native Lutron dimmer behavior,
            # instead of a single light_step_pct.
            new_percentage = max(
                self.ctrl.conf.light_low_pct,
                new_percentage,
            )

        return max(
            1,
            min(100, new_percentage),
        )

    # =============================================================
    # TAP ACTION SCHEDULING
    # =============================================================

    def _schedule_turn_on(
        self,
        task_name: str = "light-turn-on",
    ) -> None:
        """Set the optimistic target and schedule the ON tap action."""
        percentage = self.ctrl.conf.light_on_pct
        self._set_brightness_target(percentage)

        self.ctrl.create_task(
            self._turn_on(percentage),
            task_name,
        )

    def _schedule_turn_off(
        self,
        task_name: str = "light-turn-off",
    ) -> None:
        """Set the optimistic target to OFF and schedule the tap action."""
        self._set_brightness_target(0)

        self.ctrl.create_task(
            self._turn_off(),
            task_name,
        )

    def _schedule_toggle(
        self,
        task_name: str = "light-toggle",
    ) -> None:
        """Read current state synchronously, then schedule on or off."""
        state = self.ctrl.utils.get_entity_state()
        is_on = bool(state) and state.state == "on"

        if is_on:
            self._schedule_turn_off(task_name)
        else:
            self._schedule_turn_on(task_name)

    def _tap_on(
        self,
        task_name: str = "light-turn-on",
    ) -> None:
        """Resolve the ON tap action per dual-light mode / light_on_off_toggle."""
        if self._dual_light_mode():
            self._schedule_switch_to_center(task_name)
        elif self.ctrl.conf.light_on_off_toggle:
            self._schedule_toggle(task_name)
        else:
            self._schedule_turn_on(task_name)

    def _tap_off(
        self,
        task_name: str = "light-turn-off",
    ) -> None:
        """Resolve the OFF tap action per dual-light mode / light_on_off_toggle."""
        if self._dual_light_mode():
            self._schedule_switch_to_accent(task_name)
        elif self.ctrl.conf.light_on_off_toggle:
            self._schedule_toggle(task_name)
        else:
            self._schedule_turn_off(task_name)

    # =============================================================
    # P2B / 2B DUAL-LIGHT MODE
    # =============================================================

    def _current_accent_preset(self) -> "AccentPreset":
        """Return the accent preset the light is currently (or about to be) on."""
        presets = self.ctrl.conf.accent_light_presets
        index = self._accent_preset_index if self._accent_preset_index is not None else 0

        return presets[min(index, len(presets) - 1)]

    def _advance_accent_preset(self) -> None:
        """
        Move to the next accent preset, or the first if switching from center.

        With a single configured preset this always resolves to index 0,
        so it's a no-op unless more than one preset is configured.
        """
        presets = self.ctrl.conf.accent_light_presets

        if self._accent_preset_index is None:
            self._accent_preset_index = 0
        else:
            self._accent_preset_index = (self._accent_preset_index + 1) % len(presets)

    def _accent_light_data(self) -> dict[str, Any]:
        """Return the current accent preset's turn-on data."""
        preset = self._current_accent_preset()
        data: dict[str, Any] = {"brightness_pct": preset.brightness_pct}

        if preset.effect:
            data["effect"] = preset.effect
        elif preset.color_mode == "color_temp":
            data["color_temp_kelvin"] = preset.color_temp_kelvin
        else:
            data["rgb_color"] = list(preset.rgb_color)

        return data

    def _schedule_switch_to_center(
        self,
        task_name: str = "light-switch-center",
    ) -> None:
        """Set the optimistic target and schedule the switch-to-center action."""
        percentage = self.ctrl.conf.light_on_pct
        self._set_brightness_target(percentage)
        self._accent_preset_index = None

        self.ctrl.create_task(
            self._switch_to_center(percentage),
            task_name,
        )

    def _schedule_switch_to_accent(
        self,
        task_name: str = "light-switch-accent",
    ) -> None:
        """
        Discard the optimistic brightness target and switch to the accent light(s).

        Advances to the next accent preset first, so repeated OFF taps
        while the accent light is already showing cycle through
        accent_light_presets instead of reapplying the same one.
        """
        self._clear_brightness_target()
        self._advance_accent_preset()

        self.ctrl.create_task(
            self._switch_to_accent(),
            task_name,
        )

    async def _switch_to_center(self, percentage: int) -> None:
        """Turn on the center light(s) and turn off the accent light(s)."""
        await asyncio.gather(
            self._turn_on(percentage),
            self._turn_off_accent(),
        )

    async def _switch_to_accent(self) -> None:
        """Turn off the center light(s) and turn on the accent light(s)."""
        await asyncio.gather(
            self._turn_off(),
            self._turn_on_accent(),
        )

    async def _turn_on_accent(self) -> None:
        data = self._accent_light_data()
        data.update(self._transition_data(turning_on=True))

        await self.ctrl.utils.call_service_for_entities(
            "turn_on",
            data,
            self.ctrl.conf.accent_lights,
            domain="light",
        )

    async def _turn_off_accent(self) -> None:
        await self.ctrl.utils.call_service_for_entities(
            "turn_off",
            self._transition_data(turning_on=False),
            self.ctrl.conf.accent_lights,
            domain="light",
        )

    # =============================================================
    # PROFILE ENTRY POINTS
    # =============================================================

    def press_on(self) -> None:
        if self._supports_onoff_hold():
            self._start_onoff_gesture(
                "on",
                direction=1,
            )
            return

        self._clear_gesture()
        self._tap_on()

    def release_on(self) -> None:
        if self._supports_onoff_hold():
            self._release_onoff_gesture(
                "on",
                tap_action=lambda: self._tap_on("light-on-tap"),
            )

    def press_off(self) -> None:
        if self._supports_onoff_hold():
            self._start_onoff_gesture(
                "off",
                direction=-1,
            )
            return

        self._clear_gesture()
        self._tap_off()

    def release_off(self) -> None:
        if self._supports_onoff_hold():
            self._release_onoff_gesture(
                "off",
                tap_action=lambda: self._tap_off("light-off-tap"),
            )

    def press_stop(self) -> None:
        self._clear_gesture()

        # Custom middle-button actions may change brightness outside
        # this handler, so resynchronize on the next brightness action.
        self._clear_brightness_target()

        actions = self.ctrl.conf.middle_button

        if not actions:
            _LOGGER.debug("Light STOP pressed: no middle_button actions configured")
            return

        self.ctrl.create_task(
            self.ctrl.utils.execute_button_action(actions),
            "light-middle-button",
        )

    def release_stop(self) -> None:
        pass

    def press_raise(self) -> None:
        self._start_raise_lower(
            "raise",
            direction=1,
        )

    def release_raise(self) -> None:
        self._release_raise_lower("raise")

    def press_lower(self) -> None:
        self._start_raise_lower(
            "lower",
            direction=-1,
        )

    def release_lower(self) -> None:
        self._release_raise_lower("lower")

    # =============================================================
    # ON / OFF TAP-HOLD GESTURES
    # =============================================================

    def _start_onoff_gesture(
        self,
        button: str,
        direction: int,
    ) -> None:
        """Start a P2B/2B ON or OFF tap-versus-hold gesture."""
        generation = self._begin_gesture(button)

        self._arm_hold(
            button,
            direction,
            generation,
        )

    def _release_onoff_gesture(
        self,
        button: str,
        *,
        tap_action: TapAction,
    ) -> None:
        """Complete a P2B/2B ON or OFF gesture."""
        # Ignore a release belonging to an older gesture.
        if self._active_button != button:
            return

        was_holding = self._clear_gesture()

        if not was_holding:
            tap_action()

    # =============================================================
    # RAISE / LOWER GESTURES
    # =============================================================

    def _start_raise_lower(
        self,
        button: str,
        direction: int,
    ) -> None:
        """Perform one immediate step and arm continuous ramping."""
        generation = self._begin_gesture(button)

        self._schedule_brightness_step(
            direction,
            task_name=f"light-{button}-step",
        )

        self._arm_hold(
            button,
            direction,
            generation,
        )

    def _release_raise_lower(self, button: str) -> None:
        """Complete the active RAISE or LOWER gesture."""
        # Ignore a release belonging to an older or superseded gesture.
        if self._active_button != button:
            return

        self._clear_gesture()

    # =============================================================
    # HOLD / RAMP LIFECYCLE
    # =============================================================

    async def _hold_lifecycle(
        self,
        button: str,
        direction: int,
        generation: int,
    ) -> None:
        """Begin continuous ramping after the hold threshold."""
        try:
            await asyncio.sleep(self.ctrl.utils._hold_time)

            if not self._gesture_is_current(
                button,
                generation,
            ):
                return

            self._is_holding = True

            # An ON hold ramps the center light, so the accent light
            # must not remain on at the same time. The next OFF should
            # start over at the first preset, not resume mid-cycle.
            if button == "on" and self._dual_light_mode():
                self._accent_preset_index = None
                self.ctrl.create_task(
                    self._turn_off_accent(),
                    "light-on-hold-accent-off",
                )

            for _ in range(self.MAX_RAMP_STEPS):
                if not self._gesture_is_current(
                    button,
                    generation,
                ):
                    return

                current_percentage = self._brightness_for_step()

                if current_percentage is None:
                    return

                new_percentage = self._calculate_next_brightness(
                    current_percentage,
                    direction,
                )

                # Stop naturally at the configured endpoint. In
                # dual-light mode, an OFF hold that bottoms out at
                # light_low_pct switches over to the accent light(s)
                # instead of just stopping.
                if new_percentage == current_percentage:
                    if button == "off" and self._dual_light_mode():
                        self._clear_brightness_target()
                        self._advance_accent_preset()
                        self.ctrl.create_task(
                            self._switch_to_accent(),
                            "light-off-hold-accent-switch",
                        )

                    return

                self._set_brightness_target(new_percentage)

                await self._set_brightness(new_percentage)

                if not self._gesture_is_current(
                    button,
                    generation,
                ):
                    return

                await asyncio.sleep(self.ctrl.utils._step_time)

            if self._gesture_is_current(
                button,
                generation,
            ):
                _LOGGER.warning(
                    "Light ramp stopped after %s steps for device %s button %s",
                    self.MAX_RAMP_STEPS,
                    self.ctrl.conf.device_id,
                    button,
                )

        except asyncio.CancelledError:
            # Expected when released or superseded by another command.
            pass

    # =============================================================
    # LIGHT OPERATIONS
    # =============================================================

    def _schedule_brightness_step(
        self,
        direction: int,
        *,
        task_name: str,
    ) -> None:
        """
        Calculate and store a step synchronously, then submit it.

        Updating the target before task creation lets rapid taps build
        on the previous requested brightness.
        """
        current_percentage = self._brightness_for_step()

        if current_percentage is None:
            return

        new_percentage = self._calculate_next_brightness(
            current_percentage,
            direction,
        )

        if new_percentage == current_percentage:
            return

        self._set_brightness_target(new_percentage)

        self.ctrl.create_task(
            self._set_brightness(new_percentage),
            task_name,
        )

    async def _turn_on(self, percentage: int) -> None:
        await self.ctrl.utils.call_service(
            "turn_on",
            {
                "brightness_pct": percentage,
                **self._transition_data(turning_on=True),
            },
            domain="light",
        )

    async def _turn_off(self) -> None:
        await self.ctrl.utils.call_service(
            "turn_off",
            self._transition_data(turning_on=False),
            domain="light",
        )

    async def _set_brightness(
        self,
        percentage: int,
    ) -> None:
        await self.ctrl.utils.call_service(
            "turn_on",
            {"brightness_pct": percentage},
            domain="light",
        )

    # =============================================================
    # LIFECYCLE
    # =============================================================

    def reset_state(self) -> None:
        """Cancel the active gesture and clear optimistic state."""
        self._clear_gesture()
        self._clear_brightness_target()
        self._accent_preset_index = None
