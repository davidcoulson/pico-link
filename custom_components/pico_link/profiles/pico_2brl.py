from __future__ import annotations

from .pico_3brl import Pico3ButtonRaiseLower


class Pico2ButtonRaiseLower(Pico3ButtonRaiseLower):
    """
    A 3BRL without the STOP button: ON, OFF, RAISE and LOWER only.

    ON and OFF behave exactly as they do on a 3BRL, including their
    optional hold and double-tap actions. RAISE and LOWER step and ramp
    the same way. Everything STOP-specific (custom STOP actions, STOP
    light-preset cycling, dual-light mode) needs a STOP button, so it
    doesn't apply here — see PicoConfig.validate().
    """

    _LOG_NAME = "2BRL"

    _HOLD_ACTION_FIELDS = {
        "on": "on_hold",
        "off": "off_hold",
    }

    _DOUBLE_TAP_ACTION_FIELDS = {
        "on": "on_double_tap",
        "off": "off_double_tap",
    }

    _TAP_METHODS = {
        "on": "press_on",
        "off": "press_off",
    }
