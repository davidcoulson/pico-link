# config_flow.py — UI configuration for Pico Link
from __future__ import annotations

from typing import Any, Mapping

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    DOMAIN_ENTITY_FIELDS,
    ON_OFF_PICO_TYPES,
    PICO_TYPE_MAP,
    SCENE_BUTTONS,
)

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
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="%",
        )
    )


def _milliseconds() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=100,
            max=2000,
            step=50,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="ms",
        )
    )


def _seconds() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=300,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
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
    """P2B/2B only: the accent light entities for dual-light mode."""
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


def _accent_light_appearance_schema(
    current: dict[str, Any] | None = None,
    *,
    effect_options: list[str] | None = None,
    supports_color_temp: bool = False,
    color_temp_range: tuple[int, int] | None = None,
) -> vol.Schema:
    """P2B/2B only: the accent light(s) turn-on color, effect, brightness."""
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
                [255, 255, 255],
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

    return vol.Schema(fields)


def _hold_actions_schema(
    current: dict[str, Any] | None = None,
) -> vol.Schema:
    """3BRL only: the STOP-tap action, plus ON/OFF/STOP hold actions."""
    current = current or {}

    return vol.Schema(
        {
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
        }
    )


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
                        "accent_light_effect",
                        "accent_light_color_mode",
                        "accent_light_rgb_color",
                        "accent_light_color_temp_kelvin",
                        "accent_light_brightness_pct",
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

            if self._type in ON_OFF_PICO_TYPES and self._domain == "light":
                return await self.async_step_accent_light()

            if self._type == "3BRL":
                return await self.async_step_hold_actions()

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
        """Pick the accent light entities for P2B/2B dual-light mode."""
        if user_input is not None:
            self._options["accent_lights"] = user_input.get("accent_lights", [])
            return await self.async_step_accent_light_appearance()

        return self.async_show_form(
            step_id="accent_light",
            data_schema=_accent_lights_schema(current=self._options),
        )

    async def async_step_accent_light_appearance(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """
        Pick the accent light(s) color, effect, and brightness.

        A separate step from picking the entities themselves, since the
        available effect and white-temperature choices depend on which
        light(s) were just selected there.
        """
        if user_input is not None:
            self._options.update(user_input)
            return self._async_finish()

        color_temp_range = self._accent_light_color_temp_range()

        return self.async_show_form(
            step_id="accent_light_appearance",
            data_schema=_accent_light_appearance_schema(
                current=self._options,
                effect_options=self._accent_light_effect_options(),
                supports_color_temp=color_temp_range is not None,
                color_temp_range=color_temp_range,
            ),
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

    async def async_step_hold_actions(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """3BRL only: the STOP-tap action, plus ON/OFF/STOP hold actions."""
        if user_input is not None:
            self._options["middle_button"] = user_input.get("middle_button", [])
            self._options["on_hold"] = user_input.get("on_hold", [])
            self._options["off_hold"] = user_input.get("off_hold", [])
            self._options["stop_hold"] = user_input.get("stop_hold", [])
            return self._async_finish()

        return self.async_show_form(
            step_id="hold_actions",
            data_schema=_hold_actions_schema(current=self._options),
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
            data_schema=_buttons_schema(
                current=self._options.get("buttons"),
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
