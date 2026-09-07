# config_flow.py — UI configuration for Pico Link
from __future__ import annotations

import logging
from typing import Any, Mapping

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import Context, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector
from homeassistant.helpers.script import Script

from .const import (
    ACCENT_LIGHT_PICO_TYPES,
    DOMAIN,
    DOMAIN_ENTITY_FIELDS,
    PICO_TYPE_MAP,
    SCENE_BUTTONS,
)

_LOGGER = logging.getLogger(__name__)


async def _run_test_action(
    hass: Any,
    actions: list[dict[str, Any]],
    name: str,
) -> bool:
    """
    Run a configured action sequence immediately, to preview it while editing.

    Returns False (and logs) if the sequence itself raised; this is a
    best-effort preview, not the authoritative validation (that already
    happened when the actions were built with the action picker).
    """
    if not actions:
        return True

    script = Script(hass, actions, name, DOMAIN)

    try:
        await script.async_run(context=Context())
    except Exception:
        _LOGGER.exception("Error running test action %r", name)
        return False

    return True


# ================================================================
# SHARED SCHEMA BUILDERS
#
# Used by both the initial config flow and the options flow so a
# Pico's settings look and validate identically whether it is being
# created or edited.
# ================================================================


def _percent(
    min_val: int,
    max_val: int,
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_val,
            max=max_val,
            step=1,
            mode=selector.NumberSelectorMode.SLIDER,
            unit_of_measurement="%",
        )
    )


def _milliseconds() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=100,
            max=2000,
            step=50,
            mode=selector.NumberSelectorMode.SLIDER,
            unit_of_measurement="ms",
        )
    )


def _seconds() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=300,
            step=1,
            mode=selector.NumberSelectorMode.SLIDER,
            unit_of_measurement="s",
        )
    )


def _entities_schema(
    current: dict[str, Any] | None = None,
) -> vol.Schema:
    """
    One optional entity picker per controllable domain.

    Fill in exactly one to both pick the domain and its entities in a
    single step.
    """
    current = current or {}

    return vol.Schema(
        {
            vol.Optional(
                field,
                default=list(current.get(field, [])),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=domain,
                    multiple=True,
                )
            )
            for domain, field in DOMAIN_ENTITY_FIELDS.items()
        }
    )


def _chosen_domain(
    user_input: dict[str, Any],
) -> tuple[str, str] | None:
    """Return the (domain, field) with entities filled in, or None."""
    chosen = [
        (domain, field)
        for domain, field in DOMAIN_ENTITY_FIELDS.items()
        if user_input.get(field)
    ]

    if len(chosen) != 1:
        return None

    return chosen[0]


def _options_schema(
    domain: str,
    current: dict[str, Any] | None = None,
) -> vol.Schema:
    current = current or {}
    fields: dict[Any, Any] = {}

    if domain in ("cover", "light", "media_player"):
        fields[
            vol.Optional(
                "hold_time_ms",
                default=current.get(
                    "hold_time_ms",
                    400,
                ),
            )
        ] = _milliseconds()

        fields[
            vol.Optional(
                "step_time_ms",
                default=current.get(
                    "step_time_ms",
                    650,
                ),
            )
        ] = _milliseconds()

    if domain == "cover":
        fields[
            vol.Optional(
                "cover_open_pos",
                default=current.get(
                    "cover_open_pos",
                    100,
                ),
            )
        ] = _percent(1, 100)

        fields[
            vol.Optional(
                "cover_step_pct",
                default=current.get(
                    "cover_step_pct",
                    10,
                ),
            )
        ] = _percent(1, 25)

        fields[
            vol.Optional(
                "cover_inverted",
                default=current.get(
                    "cover_inverted",
                    False,
                ),
            )
        ] = selector.BooleanSelector()

    elif domain == "fan":
        fields[
            vol.Optional(
                "fan_on_pct",
                default=current.get(
                    "fan_on_pct",
                    100,
                ),
            )
        ] = _percent(1, 100)

    elif domain == "light":
        fields[
            vol.Optional(
                "light_on_pct",
                default=current.get(
                    "light_on_pct",
                    100,
                ),
            )
        ] = _percent(1, 100)

        fields[
            vol.Optional(
                "light_low_pct",
                default=current.get(
                    "light_low_pct",
                    5,
                ),
            )
        ] = _percent(1, 99)

        fields[
            vol.Optional(
                "light_step_pct",
                default=current.get(
                    "light_step_pct",
                    10,
                ),
            )
        ] = _percent(1, 25)

        fields[
            vol.Optional(
                "light_transition_on",
                default=current.get(
                    "light_transition_on",
                    0,
                ),
            )
        ] = _seconds()

        fields[
            vol.Optional(
                "light_transition_off",
                default=current.get(
                    "light_transition_off",
                    0,
                ),
            )
        ] = _seconds()

        fields[
            vol.Optional(
                "light_on_off_toggle",
                default=current.get(
                    "light_on_off_toggle",
                    False,
                ),
            )
        ] = selector.BooleanSelector()

    elif domain == "media_player":
        fields[
            vol.Optional(
                "media_player_vol_step",
                default=current.get(
                    "media_player_vol_step",
                    10,
                ),
            )
        ] = _percent(1, 20)

    return vol.Schema(fields)


def _accent_lights_schema(
    current: dict[str, Any] | None = None,
) -> vol.Schema:
    """P2B/2B/3BRL only: the accent light entities for dual-light mode."""
    current = current or {}

    return vol.Schema(
        {
            vol.Optional(
                "accent_lights",
                default=list(current.get("accent_lights", [])),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="light",
                    multiple=True,
                )
            ),
        }
    )


_NO_EFFECT = ""
_ACCENT_COLOR_MODE_RGB = "rgb"
_ACCENT_COLOR_MODE_TEMP = "color_temp"

# A visibly non-white default for a fresh preset's color swatch — plain
# white renders indistinguishably from an empty field against the
# dialog's own white background.
_DEFAULT_PRESET_RGB_COLOR = [255, 166, 0]


def _accent_preview_service_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """
    Build a light.turn_on payload for previewing an in-progress preset.

    Mirrors LightActions._accent_light_data()'s effect > color_temp >
    rgb_color precedence, but works directly off the raw form values
    since nothing has been normalized into a PicoConfig yet.
    """
    data: dict[str, Any] = {
        "brightness_pct": user_input.get("accent_light_brightness_pct", 100),
    }

    effect = user_input.get("accent_light_effect", "")

    if effect:
        data["effect"] = effect
    elif user_input.get("accent_light_color_mode") == _ACCENT_COLOR_MODE_TEMP:
        data["color_temp_kelvin"] = user_input.get(
            "accent_light_color_temp_kelvin",
            2700,
        )
    else:
        data["rgb_color"] = user_input.get(
            "accent_light_rgb_color",
            _DEFAULT_PRESET_RGB_COLOR,
        )

    return data


def _accent_light_appearance_schema(
    current: dict[str, Any] | None = None,
    *,
    effect_options: list[str] | None = None,
    supports_color_temp: bool = False,
    color_temp_range: tuple[int, int] | None = None,
    offer_add_another: bool = False,
    offer_remove: bool = False,
) -> vol.Schema:
    """P2B/2B/3BRL only: one accent-light preset's color, effect, and brightness."""
    current = current or {}
    effect_options = effect_options or []

    current_effect = current.get("accent_light_effect", _NO_EFFECT)

    effect_choices = [
        selector.SelectOptionDict(
            value=_NO_EFFECT,
            label="No effect (use color)",
        ),
        *(
            selector.SelectOptionDict(value=effect, label=effect)
            for effect in effect_options
        ),
    ]

    # Keep a previously configured effect selectable even if it isn't in
    # the current effect list (e.g. the accent light changed, or is
    # temporarily unavailable), so editing this entry never silently
    # discards it.
    if current_effect != _NO_EFFECT and current_effect not in effect_options:
        effect_choices.append(
            selector.SelectOptionDict(
                value=current_effect,
                label=f"{current_effect} (not currently available)",
            )
        )

    fields: dict[Any, Any] = {
        vol.Optional(
            "accent_light_rgb_color",
            default=current.get(
                "accent_light_rgb_color",
                _DEFAULT_PRESET_RGB_COLOR,
            ),
        ): selector.ColorRGBSelector(),
    }

    # Only offer a white-temperature choice when the first configured
    # accent light actually supports it.
    if supports_color_temp:
        min_kelvin, max_kelvin = color_temp_range or (2000, 6535)

        fields[
            vol.Optional(
                "accent_light_color_mode",
                default=current.get(
                    "accent_light_color_mode",
                    _ACCENT_COLOR_MODE_RGB,
                ),
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=_ACCENT_COLOR_MODE_RGB,
                        label="Color",
                    ),
                    selector.SelectOptionDict(
                        value=_ACCENT_COLOR_MODE_TEMP,
                        label="White temperature",
                    ),
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

        fields[
            vol.Optional(
                "accent_light_color_temp_kelvin",
                default=current.get(
                    "accent_light_color_temp_kelvin",
                    2700,
                ),
            )
        ] = selector.ColorTempSelector(
            selector.ColorTempSelectorConfig(
                unit=selector.ColorTempSelectorUnit.KELVIN,
                min=min_kelvin,
                max=max_kelvin,
            )
        )

    fields[
        vol.Optional(
            "accent_light_effect",
            default=current_effect,
        )
    ] = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=effect_choices,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )

    fields[
        vol.Optional(
            "accent_light_brightness_pct",
            default=current.get(
                "accent_light_brightness_pct",
                100,
            ),
        )
    ] = _percent(1, 100)

    fields[
        vol.Optional(
            "preview_this_preset",
            default=False,
        )
    ] = selector.BooleanSelector()

    if offer_remove:
        fields[
            vol.Optional(
                "remove_this_preset",
                default=False,
            )
        ] = selector.BooleanSelector()

    if offer_add_another:
        fields[
            vol.Optional(
                "add_another_preset",
                default=False,
            )
        ] = selector.BooleanSelector()

    return vol.Schema(fields)


def _light_preview_service_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Build a light.turn_on payload for previewing an in-progress light preset."""
    data: dict[str, Any] = {
        "brightness_pct": user_input.get("light_preset_brightness_pct", 100),
    }

    effect = user_input.get("light_preset_effect", "")

    if effect:
        data["effect"] = effect
    elif user_input.get("light_preset_color_mode") == _ACCENT_COLOR_MODE_TEMP:
        data["color_temp_kelvin"] = user_input.get(
            "light_preset_color_temp_kelvin",
            2700,
        )
    else:
        data["rgb_color"] = user_input.get(
            "light_preset_rgb_color",
            _DEFAULT_PRESET_RGB_COLOR,
        )

    return data


def _light_preset_appearance_schema(
    current: dict[str, Any] | None = None,
    *,
    effect_options: list[str] | None = None,
    supports_color_temp: bool = False,
    color_temp_range: tuple[int, int] | None = None,
    offer_add_another: bool = False,
    offer_remove: bool = False,
    offer_enable_toggle: bool = False,
    enable_default: bool = False,
) -> vol.Schema:
    """
    3BRL only: one STOP-cycled light-appearance preset.

    Parallels _accent_light_appearance_schema for `lights` instead of
    `accent_lights`. offer_enable_toggle adds the leading
    "cycle_light_presets" opt-in field, shown only on the first preset —
    leaving it unchecked there skips the feature entirely.
    """
    current = current or {}
    effect_options = effect_options or []

    fields: dict[Any, Any] = {}

    if offer_enable_toggle:
        fields[
            vol.Optional(
                "cycle_light_presets",
                default=enable_default,
            )
        ] = selector.BooleanSelector()

    current_effect = current.get("light_preset_effect", _NO_EFFECT)

    effect_choices = [
        selector.SelectOptionDict(
            value=_NO_EFFECT,
            label="No effect (use color)",
        ),
        *(
            selector.SelectOptionDict(value=effect, label=effect)
            for effect in effect_options
        ),
    ]

    if current_effect != _NO_EFFECT and current_effect not in effect_options:
        effect_choices.append(
            selector.SelectOptionDict(
                value=current_effect,
                label=f"{current_effect} (not currently available)",
            )
        )

    fields[
        vol.Optional(
            "light_preset_rgb_color",
            default=current.get(
                "light_preset_rgb_color",
                _DEFAULT_PRESET_RGB_COLOR,
            ),
        )
    ] = selector.ColorRGBSelector()

    if supports_color_temp:
        min_kelvin, max_kelvin = color_temp_range or (2000, 6535)

        fields[
            vol.Optional(
                "light_preset_color_mode",
                default=current.get(
                    "light_preset_color_mode",
                    _ACCENT_COLOR_MODE_RGB,
                ),
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=_ACCENT_COLOR_MODE_RGB,
                        label="Color",
                    ),
                    selector.SelectOptionDict(
                        value=_ACCENT_COLOR_MODE_TEMP,
                        label="White temperature",
                    ),
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

        fields[
            vol.Optional(
                "light_preset_color_temp_kelvin",
                default=current.get(
                    "light_preset_color_temp_kelvin",
                    2700,
                ),
            )
        ] = selector.ColorTempSelector(
            selector.ColorTempSelectorConfig(
                unit=selector.ColorTempSelectorUnit.KELVIN,
                min=min_kelvin,
                max=max_kelvin,
            )
        )

    fields[
        vol.Optional(
            "light_preset_effect",
            default=current_effect,
        )
    ] = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=effect_choices,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )

    fields[
        vol.Optional(
            "light_preset_brightness_pct",
            default=current.get(
                "light_preset_brightness_pct",
                100,
            ),
        )
    ] = _percent(1, 100)

    fields[
        vol.Optional(
            "preview_this_preset",
            default=False,
        )
    ] = selector.BooleanSelector()

    if offer_remove:
        fields[
            vol.Optional(
                "remove_this_preset",
                default=False,
            )
        ] = selector.BooleanSelector()

    if offer_add_another:
        fields[
            vol.Optional(
                "add_another_preset",
                default=False,
            )
        ] = selector.BooleanSelector()

    return vol.Schema(fields)


_TEST_ACTION_NONE = "none"


def _test_action_field(labels: dict[str, str]) -> selector.SelectSelector:
    """Build a 'test which action?' dropdown for a custom-actions step."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=_TEST_ACTION_NONE,
                    label="Don't test anything",
                ),
                *(
                    selector.SelectOptionDict(value=field, label=label)
                    for field, label in labels.items()
                ),
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _custom_actions_schema(
    current: dict[str, Any] | None = None,
) -> vol.Schema:
    """
    3BRL only: the STOP-tap action, plus ON/OFF/STOP hold and double-tap actions.

    A button's hold and double-tap fields are mutually exclusive
    (checked on submit — see PicoLinkOptionsFlow.async_step_custom_actions).
    """
    current = current or {}

    fields: dict[Any, Any] = {
        vol.Optional(
            "middle_button",
            default=list(current.get("middle_button", [])),
        ): selector.ActionSelector(),
        vol.Optional(
            "on_hold",
            default=list(current.get("on_hold", [])),
        ): selector.ActionSelector(),
        vol.Optional(
            "off_hold",
            default=list(current.get("off_hold", [])),
        ): selector.ActionSelector(),
        vol.Optional(
            "stop_hold",
            default=list(current.get("stop_hold", [])),
        ): selector.ActionSelector(),
        vol.Optional(
            "on_double_tap",
            default=list(current.get("on_double_tap", [])),
        ): selector.ActionSelector(),
        vol.Optional(
            "off_double_tap",
            default=list(current.get("off_double_tap", [])),
        ): selector.ActionSelector(),
        vol.Optional(
            "stop_double_tap",
            default=list(current.get("stop_double_tap", [])),
        ): selector.ActionSelector(),
    }

    fields[
        vol.Optional(
            "test_action",
            default=_TEST_ACTION_NONE,
        )
    ] = _test_action_field(
        {
            "middle_button": "STOP actions",
            "on_hold": "ON hold actions",
            "off_hold": "OFF hold actions",
            "stop_hold": "STOP hold actions",
            "on_double_tap": "ON double-tap actions",
            "off_double_tap": "OFF double-tap actions",
            "stop_double_tap": "STOP double-tap actions",
        }
    )

    return vol.Schema(fields)


def _buttons_schema(
    current: dict[str, list[dict[str, Any]]] | None = None,
) -> vol.Schema:
    current = current or {}

    return vol.Schema(
        {
            vol.Optional(
                name,
                default=list(current.get(name, [])),
            ): selector.ActionSelector()
            for name in SCENE_BUTTONS
        }
    )


def _scene_hold_actions_schema(
    current: dict[str, Any] | None = None,
) -> vol.Schema:
    """
    4B only: optional hold/double-tap actions per scene button.

    A button's hold and double-tap fields are mutually exclusive
    (checked on submit — see
    PicoLinkOptionsFlow.async_step_scene_hold_actions).
    """
    current = current or {}
    button_hold = current.get("button_hold") or {}
    button_double_tap = current.get("button_double_tap") or {}

    fields: dict[Any, Any] = {}
    test_labels: dict[str, str] = {}

    for name in SCENE_BUTTONS:
        label = "Off button" if name == "off" else name.replace("_", " ").title()

        fields[
            vol.Optional(
                f"{name}_hold",
                default=list(button_hold.get(name, [])),
            )
        ] = selector.ActionSelector()
        test_labels[f"{name}_hold"] = f"{label} hold actions"

        fields[
            vol.Optional(
                f"{name}_double_tap",
                default=list(button_double_tap.get(name, [])),
            )
        ] = selector.ActionSelector()
        test_labels[f"{name}_double_tap"] = f"{label} double-tap actions"

    fields[
        vol.Optional(
            "test_action",
            default=_TEST_ACTION_NONE,
        )
    ] = _test_action_field(test_labels)

    return vol.Schema(fields)


def _entry_device_ids(
    entry_data: Mapping[str, Any],
) -> list[str]:
    """Return the device IDs a Pico Link entry's data represents."""
    device_ids = entry_data.get("device_ids")

    if isinstance(device_ids, list):
        return device_ids

    single = entry_data.get("device_id")

    return [single] if single else []


def _configured_device_ids(
    hass: Any,
    *,
    exclude_entry_id: str | None = None,
) -> set[str]:
    """Return every device ID already claimed by another Pico Link entry."""
    configured: set[str] = set()

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue

        configured.update(_entry_device_ids(entry.data))

    return configured


def _eligible_pico_devices(
    hass: Any,
    *,
    exclude_entry_id: str | None = None,
) -> dict[str, tuple[str, str]]:
    """
    Find Lutron Pico remotes that aren't claimed by another entry.

    Returns {device_id: (display_name, pico_type)}. The Pico type is
    read directly from the model Lutron reports, so it never needs to
    be entered by hand and can never disagree with the hardware.
    Passing exclude_entry_id leaves that entry's own devices eligible,
    so an options flow can offer them back for re-selection.
    """
    device_registry = dr.async_get(hass)

    lutron_entry_ids = {
        entry.entry_id for entry in hass.config_entries.async_entries("lutron_caseta")
    }

    configured_device_ids = _configured_device_ids(
        hass,
        exclude_entry_id=exclude_entry_id,
    )

    devices: dict[str, tuple[str, str]] = {}

    for device in device_registry.devices.values():
        if not device.config_entries & lutron_entry_ids:
            continue

        if device.id in configured_device_ids:
            continue

        model = device.model or ""
        pico_type = next(
            (code for raw, code in PICO_TYPE_MAP.items() if raw in model),
            None,
        )

        if pico_type is None:
            # Not a Pico (e.g. the Smart Bridge or a Fan Speed Controller).
            continue

        devices[device.id] = (
            device.name_by_user or device.name or device.id,
            pico_type,
        )

    return devices


# ================================================================
# CONFIG FLOW (add a new Pico)
# ================================================================


class PicoLinkConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle adding one or more identically-behaving Picos as one config entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._device_ids: list[str] = []
        self._type: str | None = None
        self._domain: str = ""
        self._title: str = ""
        self._options: dict[str, Any] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        devices = _eligible_pico_devices(self.hass)

        if not devices:
            return self.async_abort(reason="no_devices_found")

        errors: dict[str, str] = {}

        if user_input is not None:
            device_ids = user_input["device_ids"]
            types = {devices[device_id][1] for device_id in device_ids}

            if len(types) > 1:
                errors["base"] = "mixed_pico_types"
            else:
                unique_id = "+".join(sorted(device_ids))

                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                self._device_ids = device_ids
                self._type = types.pop()
                self._title = ", ".join(
                    devices[device_id][0]
                    for device_id in sorted(
                        device_ids,
                        key=lambda device_id: devices[device_id][0],
                    )
                )

                if self._type == "4B":
                    return await self.async_step_buttons()

                return await self.async_step_entities()

        schema = vol.Schema(
            {
                vol.Required("device_ids"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=device_id,
                                label=f"{title} ({pico_type})",
                            )
                            for device_id, (title, pico_type) in sorted(
                                devices.items(),
                                key=lambda item: item[1][0],
                            )
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        multiple=True,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_entities(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            chosen = _chosen_domain(user_input)

            if chosen is None:
                errors["base"] = "single_domain_required"
            else:
                domain, field = chosen
                self._domain = domain
                self._options = {field: user_input[field]}
                return self._async_finish()

        return self.async_show_form(
            step_id="entities",
            data_schema=_entities_schema(),
            errors=errors,
        )

    async def async_step_buttons(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            buttons = {
                name: actions for name, actions in user_input.items() if actions
            }

            if not buttons:
                errors["base"] = "buttons_required"
            else:
                self._options["buttons"] = buttons
                return self._async_finish()

        return self.async_show_form(
            step_id="buttons",
            data_schema=_buttons_schema(),
            errors=errors,
        )

    def _async_finish(self) -> FlowResult:
        return self.async_create_entry(
            title=self._title,
            data={
                "device_ids": self._device_ids,
                "type": self._type,
            },
            options=self._options,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "PicoLinkOptionsFlow":
        return PicoLinkOptionsFlow(config_entry)


# ================================================================
# OPTIONS FLOW (edit an existing Pico)
#
# Editing still exposes the timing/behavior options and the 3BRL STOP
# button, which the initial add flow skips in favor of sensible
# defaults.
# ================================================================


class PicoLinkOptionsFlow(config_entries.OptionsFlow):
    """Handle editing an existing Pico's entities, buttons, and options."""

    MAX_ACCENT_PRESETS = 5

    def __init__(
        self,
        config_entry: config_entries.ConfigEntry,
    ) -> None:
        self._entry = config_entry
        self._type: str = config_entry.data["type"]
        self._device_ids: list[str] = _entry_device_ids(config_entry.data)
        self._title: str = config_entry.title
        self._domain: str = ""
        self._options: dict[str, Any] = dict(config_entry.options)
        self._accent_presets: list[dict[str, Any]] = []
        self._accent_preset_read_index = 0
        self._preview_prefill: dict[str, Any] | None = None
        self._light_presets: list[dict[str, Any]] = []
        self._light_preset_read_index = 0
        self._light_preset_prefill: dict[str, Any] | None = None
        self._custom_actions_prefill: dict[str, Any] | None = None
        self._scene_hold_prefill: dict[str, Any] | None = None

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        return await self.async_step_devices()

    async def async_step_devices(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Edit which Pico(s) of this entry's type belong to this entry."""
        eligible = {
            device_id: info
            for device_id, info in _eligible_pico_devices(
                self.hass,
                exclude_entry_id=self._entry.entry_id,
            ).items()
            if info[1] == self._type
        }

        errors: dict[str, str] = {}

        if user_input is not None:
            device_ids = user_input["device_ids"]

            if not device_ids:
                errors["base"] = "at_least_one_device_required"
            else:
                self._device_ids = device_ids
                self._title = ", ".join(
                    eligible[device_id][0]
                    for device_id in sorted(
                        device_ids,
                        key=lambda device_id: eligible[device_id][0],
                    )
                )

                if self._type == "4B":
                    return await self.async_step_buttons()

                return await self.async_step_entities()

        schema = vol.Schema(
            {
                vol.Required(
                    "device_ids",
                    default=[
                        device_id
                        for device_id in self._device_ids
                        if device_id in eligible
                    ],
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=device_id,
                                label=title,
                            )
                            for device_id, (title, _pico_type) in sorted(
                                eligible.items(),
                                key=lambda item: item[1][0],
                            )
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        multiple=True,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="devices",
            data_schema=schema,
            errors=errors,
            description_placeholders={"pico_type": self._type},
        )

    async def async_step_entities(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            chosen = _chosen_domain(user_input)

            if chosen is None:
                errors["base"] = "single_domain_required"
            else:
                domain, field = chosen

                # Drop any other domain's entities if the domain changed.
                for other_field in DOMAIN_ENTITY_FIELDS.values():
                    if other_field != field:
                        self._options.pop(other_field, None)

                # Accent lights are only meaningful alongside the light domain.
                if field != "lights":
                    for accent_field in (
                        "accent_lights",
                        "accent_light_presets",
                    ):
                        self._options.pop(accent_field, None)

                self._domain = domain
                self._options[field] = user_input[field]
                return await self.async_step_options()

        return self.async_show_form(
            step_id="entities",
            data_schema=_entities_schema(current=self._options),
            errors=errors,
        )

    async def async_step_options(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        if user_input is not None:
            self._options.update(user_input)

            if self._type in ACCENT_LIGHT_PICO_TYPES and self._domain == "light":
                return await self.async_step_accent_light()

            if self._type == "3BRL":
                return await self.async_step_custom_actions()

            return self._async_finish()

        return self.async_show_form(
            step_id="options",
            data_schema=_options_schema(
                self._domain,
                current=self._options,
            ),
            description_placeholders={"domain": self._domain},
        )

    async def async_step_accent_light(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """
        Pick the accent light entities for dual-light mode.

        Leaving this empty skips dual-light mode. For a 3BRL, that
        instead offers the (also optional) STOP light-preset cycling
        step — the two are mutually exclusive, so choosing one clears
        any leftover configuration from the other.
        """
        errors: dict[str, str] = {}
        current = self._options

        if user_input is not None:
            accent_lights = user_input.get("accent_lights", [])
            overlap = set(accent_lights) & set(self._options.get("lights", []))

            if overlap:
                errors["base"] = "accent_light_overlap"
                current = {**self._options, "accent_lights": accent_lights}
            else:
                self._options["accent_lights"] = accent_lights

                if accent_lights:
                    self._options.pop("light_presets", None)
                    return await self.async_step_accent_light_appearance()

                self._options.pop("accent_light_presets", None)

                if self._type == "3BRL":
                    return await self.async_step_light_presets()

                return self._async_finish()

        return self.async_show_form(
            step_id="accent_light",
            data_schema=_accent_lights_schema(current=current),
            errors=errors,
        )

    async def async_step_accent_light_appearance(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """
        Pick one accent-light preset's color, effect, and brightness.

        A separate step from picking the entities themselves, since the
        available effect and white-temperature choices depend on which
        light(s) were just selected there. Checking "add another preset"
        repeats this step to build accent_light_presets, which the
        accent light cycles through on repeated OFF taps. Checking
        "Try it" turns the accent light(s) on with whatever's currently
        filled in and re-shows this same step, so a preset can be
        checked by eye before moving on. Checking "Remove this preset"
        (only offered for a preset that already exists) drops it instead
        of keeping it, shifting any later presets up by one.
        """
        existing = self._options.get("accent_light_presets") or []

        if user_input is not None:
            if user_input.pop("preview_this_preset", False):
                await self._preview_accent_preset(user_input)
                self._preview_prefill = user_input
                return await self.async_step_accent_light_appearance()

            self._preview_prefill = None

            if user_input.pop("remove_this_preset", False):
                self._accent_preset_read_index += 1
                return await self.async_step_accent_light_appearance()

            self._accent_preset_read_index += 1
            add_another = user_input.pop("add_another_preset", False)
            self._accent_presets.append(user_input)

            if add_another and len(self._accent_presets) < self.MAX_ACCENT_PRESETS:
                return await self.async_step_accent_light_appearance()

            self._options["accent_light_presets"] = self._accent_presets

            if self._type == "3BRL":
                return await self.async_step_custom_actions()

            return self._async_finish()

        color_temp_range = self._accent_light_color_temp_range()
        preset_number = len(self._accent_presets) + 1

        return self.async_show_form(
            step_id="accent_light_appearance",
            data_schema=_accent_light_appearance_schema(
                current=self._preview_prefill or self._current_accent_preset_default(),
                effect_options=self._accent_light_effect_options(),
                supports_color_temp=color_temp_range is not None,
                color_temp_range=color_temp_range,
                offer_add_another=preset_number < self.MAX_ACCENT_PRESETS,
                offer_remove=self._accent_preset_read_index < len(existing),
            ),
            description_placeholders={"preset_number": str(preset_number)},
        )

    def _current_accent_preset_default(self) -> dict[str, Any]:
        """Prefill defaults for the preset currently being edited/added."""
        existing = self._options.get("accent_light_presets") or []
        index = self._accent_preset_read_index

        return existing[index] if index < len(existing) else {}

    async def _preview_accent_preset(self, user_input: dict[str, Any]) -> None:
        """Turn on the accent light(s) with an in-progress preset, for a live look."""
        accent_lights = self._options.get("accent_lights") or []

        if not accent_lights:
            return

        await self.hass.services.async_call(
            "light",
            "turn_on",
            {
                **_accent_preview_service_data(user_input),
                "entity_id": accent_lights,
            },
            blocking=False,
        )

    def _accent_light_effect_options(self) -> list[str]:
        """Return the effect names supported by the first accent light."""
        accent_lights = self._options.get("accent_lights") or []

        if not accent_lights:
            return []

        state = self.hass.states.get(accent_lights[0])

        if not state:
            return []

        effect_list = state.attributes.get("effect_list")

        if not isinstance(effect_list, list):
            return []

        return [effect for effect in effect_list if isinstance(effect, str)]

    def _accent_light_color_temp_range(self) -> tuple[int, int] | None:
        """
        Return the first accent light's (min, max) Kelvin range.

        None when there's no accent light selected yet, or the first one
        doesn't support color temperature.
        """
        accent_lights = self._options.get("accent_lights") or []

        if not accent_lights:
            return None

        state = self.hass.states.get(accent_lights[0])

        if not state:
            return None

        supported_color_modes = state.attributes.get("supported_color_modes")

        if (
            not isinstance(supported_color_modes, list)
            or "color_temp" not in supported_color_modes
        ):
            return None

        min_kelvin = state.attributes.get("min_color_temp_kelvin")
        max_kelvin = state.attributes.get("max_color_temp_kelvin")

        if not isinstance(min_kelvin, (int, float)) or not isinstance(
            max_kelvin,
            (int, float),
        ):
            return (2000, 6535)

        return (int(min_kelvin), int(max_kelvin))

    async def async_step_light_presets(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """
        3BRL only: optional STOP-button cycling through light appearances.

        Only reached when accent_lights was left empty (see
        async_step_accent_light) — dual-light mode and this are
        mutually exclusive. The first preset's form also carries the
        "cycle_light_presets" opt-in; leaving it unchecked there
        configures nothing and STOP keeps its normal behavior
        (middle_button, or no action). Checking "Try it" applies
        what's filled in immediately; "Remove this preset" (existing
        presets only) drops one; "Add another preset" builds a list
        STOP advances through on every press, wrapping after the last.
        """
        existing = self._options.get("light_presets") or []

        if user_input is not None:
            if user_input.pop("preview_this_preset", False):
                await self._preview_light_preset(user_input)
                self._light_preset_prefill = user_input
                return await self.async_step_light_presets()

            self._light_preset_prefill = None

            if not self._light_presets and not user_input.pop(
                "cycle_light_presets", False
            ):
                self._options["light_presets"] = []
                return await self.async_step_custom_actions()

            if user_input.pop("remove_this_preset", False):
                self._light_preset_read_index += 1
                return await self.async_step_light_presets()

            self._light_preset_read_index += 1
            add_another = user_input.pop("add_another_preset", False)
            self._light_presets.append(user_input)

            if add_another and len(self._light_presets) < self.MAX_ACCENT_PRESETS:
                return await self.async_step_light_presets()

            self._options["light_presets"] = self._light_presets
            return await self.async_step_custom_actions()

        color_temp_range = self._light_color_temp_range()
        index = len(self._light_presets)
        preset_number = index + 1

        return self.async_show_form(
            step_id="light_presets",
            data_schema=_light_preset_appearance_schema(
                current=self._light_preset_prefill or self._current_light_preset_default(),
                effect_options=self._light_effect_options(),
                supports_color_temp=color_temp_range is not None,
                color_temp_range=color_temp_range,
                offer_add_another=preset_number < self.MAX_ACCENT_PRESETS,
                offer_remove=self._light_preset_read_index < len(existing),
                offer_enable_toggle=index == 0,
                enable_default=bool(existing),
            ),
            description_placeholders={"preset_number": str(preset_number)},
        )

    def _current_light_preset_default(self) -> dict[str, Any]:
        """Prefill defaults for the light preset currently being edited/added."""
        existing = self._options.get("light_presets") or []
        index = self._light_preset_read_index

        return existing[index] if index < len(existing) else {}

    async def _preview_light_preset(self, user_input: dict[str, Any]) -> None:
        """Turn on `lights` with an in-progress light preset, for a live look."""
        lights = self._options.get("lights") or []

        if not lights:
            return

        await self.hass.services.async_call(
            "light",
            "turn_on",
            {
                **_light_preview_service_data(user_input),
                "entity_id": lights,
            },
            blocking=False,
        )

    def _light_effect_options(self) -> list[str]:
        """Return the effect names supported by the first configured light."""
        lights = self._options.get("lights") or []

        if not lights:
            return []

        state = self.hass.states.get(lights[0])

        if not state:
            return []

        effect_list = state.attributes.get("effect_list")

        if not isinstance(effect_list, list):
            return []

        return [effect for effect in effect_list if isinstance(effect, str)]

    def _light_color_temp_range(self) -> tuple[int, int] | None:
        """
        Return the first configured light's (min, max) Kelvin range.

        None when there's no light selected yet, or the first one
        doesn't support color temperature.
        """
        lights = self._options.get("lights") or []

        if not lights:
            return None

        state = self.hass.states.get(lights[0])

        if not state:
            return None

        supported_color_modes = state.attributes.get("supported_color_modes")

        if (
            not isinstance(supported_color_modes, list)
            or "color_temp" not in supported_color_modes
        ):
            return None

        min_kelvin = state.attributes.get("min_color_temp_kelvin")
        max_kelvin = state.attributes.get("max_color_temp_kelvin")

        if not isinstance(min_kelvin, (int, float)) or not isinstance(
            max_kelvin,
            (int, float),
        ):
            return (2000, 6535)

        return (int(min_kelvin), int(max_kelvin))

    async def async_step_custom_actions(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """3BRL only: the STOP-tap action, plus ON/OFF/STOP hold and double-tap actions."""
        errors: dict[str, str] = {}

        if user_input is not None:
            test_action = user_input.pop("test_action", _TEST_ACTION_NONE)

            if test_action != _TEST_ACTION_NONE:
                success = await _run_test_action(
                    self.hass,
                    user_input.get(test_action) or [],
                    f"pico_link_test_{test_action}",
                )

                if not success:
                    errors["base"] = "test_action_failed"

                self._custom_actions_prefill = user_input
            else:
                conflicts = [
                    button
                    for button, hold_field, tap_field in (
                        ("ON", "on_hold", "on_double_tap"),
                        ("OFF", "off_hold", "off_double_tap"),
                        ("STOP", "stop_hold", "stop_double_tap"),
                    )
                    if user_input.get(hold_field) and user_input.get(tap_field)
                ]

                if conflicts:
                    errors["base"] = "hold_and_double_tap_conflict"
                    self._custom_actions_prefill = user_input
                elif user_input.get("middle_button") and self._options.get(
                    "light_presets"
                ):
                    errors["base"] = "middle_button_light_presets_conflict"
                    self._custom_actions_prefill = user_input
                else:
                    for field_name in (
                        "middle_button",
                        "on_hold",
                        "off_hold",
                        "stop_hold",
                        "on_double_tap",
                        "off_double_tap",
                        "stop_double_tap",
                    ):
                        self._options[field_name] = user_input.get(field_name, [])

                    self._custom_actions_prefill = None
                    return self._async_finish()

        return self.async_show_form(
            step_id="custom_actions",
            data_schema=_custom_actions_schema(
                current=self._custom_actions_prefill or self._options,
            ),
            errors=errors,
        )

    async def async_step_buttons(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            buttons = {
                name: actions for name, actions in user_input.items() if actions
            }

            if not buttons:
                errors["base"] = "buttons_required"
            else:
                self._options["buttons"] = buttons
                return await self.async_step_scene_hold_actions()

        return self.async_show_form(
            step_id="buttons",
            data_schema=_buttons_schema(
                current=self._options.get("buttons"),
            ),
            errors=errors,
        )

    async def async_step_scene_hold_actions(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """4B only: optional hold/double-tap actions per scene button."""
        errors: dict[str, str] = {}

        if user_input is not None:
            test_action = user_input.pop("test_action", _TEST_ACTION_NONE)

            if test_action != _TEST_ACTION_NONE:
                success = await _run_test_action(
                    self.hass,
                    user_input.get(test_action) or [],
                    f"pico_link_test_{test_action}",
                )

                if not success:
                    errors["base"] = "test_action_failed"

                self._scene_hold_prefill = user_input
            else:
                conflicts = [
                    name
                    for name in SCENE_BUTTONS
                    if user_input.get(f"{name}_hold")
                    and user_input.get(f"{name}_double_tap")
                ]

                if conflicts:
                    errors["base"] = "hold_and_double_tap_conflict"
                    self._scene_hold_prefill = user_input
                else:
                    button_hold: dict[str, Any] = {}
                    button_double_tap: dict[str, Any] = {}

                    for name in SCENE_BUTTONS:
                        hold_actions = user_input.get(f"{name}_hold") or []
                        double_tap_actions = user_input.get(f"{name}_double_tap") or []

                        if hold_actions:
                            button_hold[name] = hold_actions

                        if double_tap_actions:
                            button_double_tap[name] = double_tap_actions

                    self._options["button_hold"] = button_hold
                    self._options["button_double_tap"] = button_double_tap

                    self._scene_hold_prefill = None
                    return self._async_finish()

        return self.async_show_form(
            step_id="scene_hold_actions",
            data_schema=_scene_hold_actions_schema(
                current=self._scene_hold_prefill or self._options,
            ),
            errors=errors,
        )

    def _async_finish(self) -> FlowResult:
        # Update data/title and options together so this is one reload,
        # not two — async_create_entry below would otherwise reapply
        # the same options a second time via its own update_entry call.
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={
                "device_ids": self._device_ids,
                "type": self._type,
            },
            options=self._options,
            title=self._title,
        )

        return self.async_create_entry(
            title="",
            data=self._options,
        )
