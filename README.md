# Pico Link

### Lutron Pico remotes as domain-aware Home Assistant controllers

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
![GitHub release](https://img.shields.io/github/v/release/davidcoulson/pico-link)
![GitHub License](https://img.shields.io/github/license/davidcoulson/pico-link)

<p align="center">
  <img src="pico.png" width="180" alt="Pico Link logo">
</p>

---

> **This is a fork of [smartqasa/pico-link](https://github.com/smartqasa/pico-link).**
> Development of this fork was AI-assisted (Claude).

### Changes in This Fork

- **UI-only configuration** — every Pico is added, edited, and removed from
  **Settings → Devices & Services**; YAML configuration has been removed
  entirely. See [Adding a Pico](#adding-a-pico).
- **Multi-Pico config entries** — group several identical Picos (e.g.
  multiple stairway remotes) under one shared, editable configuration
  instead of configuring each one separately.
- **Dual-light mode (P2B, 2B, 3BRL)** — the ON and OFF buttons can switch
  between two separate lights (e.g. a center fixture and an edge/ring accent
  light) at a configured color, white temperature, effect, and brightness,
  instead of just turning one light on and off. The effect and
  white-temperature choices are picked from what the selected accent light
  actually supports, not typed in, and repeated OFF taps can cycle through
  several saved presets, each previewable live while you configure it. See
  [Dual-light mode](#dual-light-mode).
- **Light on/off toggle option** — ON and OFF can each independently toggle
  a light's state instead of always issuing a discrete turn-on/turn-off.
- **Hold and double-tap actions (3BRL, 4B)** — ON, OFF, and STOP on a 3BRL,
  or any button on a 4B, can each run a custom action sequence when held
  (in addition to their normal tap behavior) or on two quick taps (instead
  of it) — a button can use one or the other, checked inline on the options
  step rather than deferred to a later error, and testable immediately from
  that same step. See [3BRL custom actions](#3brl-custom-actions).
- **A `pico_link_button` event, and device triggers for it** — fired for
  every mapped press/release, so automations (or a tool like Node-RED) can
  react to a Pico's normalized button/domain without re-deriving it from
  the raw Lutron event; also selectable straight from the automation
  editor's device trigger picker, no YAML required. See
  [The pico_link_button event](#the-pico_link_button-event).
- **Custom actions run through Home Assistant's real script engine** — STOP
  buttons and 4B scene buttons support the same conditions, if-then, choose,
  repeat, and templating available in the automation editor's action picker,
  not just plain service calls.
- **Calendar versioning** — releases are versioned `YYYY.MM.DD.XX` instead
  of semantic versioning. See [Versioning](#versioning).
- **Repairs and diagnostics** — a hardware type mismatch, a Pico removed
  from the Lutron bridge, or a configured entity that no longer exists shows
  up under Settings → Repairs instead of only the log, and every entry
  supports Home Assistant's standard diagnostics download. See
  [Diagnostics and Repairs](#diagnostics-and-repairs).
- **Raising from off respects `light_low_pct`** — a single RAISE (3BRL) or
  ON hold (P2B/2B) on a light that's off now lands at `light_low_pct`
  instead of a single `light_step_pct`, matching how a native Lutron dimmer
  behaves.
- **STOP light-preset cycling (3BRL)** — outside dual-light mode, STOP can
  cycle a light through several saved appearances instead of doing nothing,
  using the same preset editor (with live preview) as dual-light mode. See
  [STOP light-preset cycling](#stop-light-preset-cycling).
- **UI polish** — brightness, timing, and other percentage/duration fields
  now use Home Assistant's slider control instead of a plain number box,
  and a fresh color preset defaults to a visibly non-white color instead
  of one that looks blank against the dialog background.
- **Clearer multi-step setup/editing** — each step's button now reads
  "Next" instead of "Submit" whenever more steps follow, and a non-4B
  entry's controlled entities are appended to its title on the plain
  integration list, since it otherwise gives no hint what an entry
  controls. See [Editing a Pico](#editing-a-pico).

---

## Overview

Pico Link converts supported **Lutron Caséta Pico remotes** into configurable,
domain-aware Home Assistant controllers.

It listens for:

```text
lutron_caseta_button_event
```

and routes Pico button events to lights, fans, covers, media players, switches,
scenes, scripts, and other Home Assistant actions.

Features include:

- Fully configured through the Home Assistant UI — no YAML editing
- Group multiple identical Picos (e.g. several stairway remotes) under one
  shared configuration
- Tap-versus-hold detection where supported
- Brightness, volume, and cover-position stepping
- Continuous light, cover, and media-player ramping
- Tap-only fan speed control
- Domain-specific STOP-button behavior
- Ordered custom action execution, built with Home Assistant's native action
  picker
- Entity placeholder expansion
- Optimistic light and cover targets for responsive repeated taps
- Validation of Pico types, entities, domains, actions, and button mappings
- Protection against configuring the same physical Pico twice
- Verification that the configured Pico type matches the reported hardware type

---

## Requirements

- Home Assistant 2024.10.0 or newer
- The Home Assistant **Lutron Caséta** integration configured and working
- Pico button events available as `lutron_caseta_button_event`

Pico Link depends on the Home Assistant `lutron_caseta` integration and is
loaded after it.

---

## Supported Pico Types

| Type   | Layout                          | Buttons                                   | Supported behavior                                     |
| ------ | -------------------------------- | ------------------------------------------ | -------------------------------------------------------- |
| `P2B`  | Paddle Pico                     | `on`, `off`                               | Domain-specific ON/OFF tap and hold behavior           |
| `2B`   | Two-button Pico                 | `on`, `off`                               | Domain-specific ON/OFF tap and hold behavior           |
| `3BRL` | On / Raise / Stop / Lower / Off | `on`, `raise`, `stop`, `lower`, `off`     | Full domain control with dedicated raise/lower buttons |
| `4B`   | Four-button scene Pico          | `button_1`, `button_2`, `button_3`, `off` | Ordered custom actions only                            |

The configured type is authoritative. Pico Link verifies the hardware type
reported by Lutron events. Events are ignored when the reported hardware type
does not match the configured type.

---

## Installation

### HACS

1. Open **HACS → Integrations**.

2. Open the menu and choose **Custom repositories**.

3. Add:

   ```text
   https://github.com/davidcoulson/pico-link
   ```

4. Select **Integration** as the repository type.

5. Install **Pico Link**.

6. Restart Home Assistant.

### Manual installation

Copy the integration directory to:

```text
config/custom_components/pico_link/
```

The resulting structure should include:

```text
config/
└── custom_components/
    └── pico_link/
        ├── __init__.py
        ├── config_flow.py
        ├── manifest.json
        ├── config.py
        ├── controller.py
        ├── utilities.py
        ├── actions/
        ├── profiles/
        └── translations/
```

Restart Home Assistant after installation or updates.

---

## Adding a Pico

One config entry can hold a single Pico or several — select multiple in the
first step when they should all behave identically (for example, several
remotes for the same stairway light). They share one configuration: entities,
timing, and behavior are set once and apply to every Pico in the entry.

1. Go to **Settings → Devices & Services**.
2. Click **Add Integration** and choose **Pico Link**.
3. Pick one or more Picos from the list. Only Lutron Pico remotes that
   aren't already configured (in this or any other entry) are listed — the
   Smart Bridge, fan speed controllers, and already-configured Picos don't
   show up. Every Pico you select must be the same type; each one's type is
   read directly from the model Lutron reports, so there's nothing to select
   or get wrong.
4. **For `P2B`, `2B`, and `3BRL` Picos:** fill in the entities for the one
   domain this entry's Pico(s) control (cover, fan, light, media player, or
   switch), and leave the other fields empty. Click **Submit** and you're
   done — it starts working immediately with sensible default timing and
   behavior.
5. **For `4B` Picos:** build an action sequence for each button
   (`button_1`, `button_2`, `button_3`, `off`) using Home Assistant's action
   picker. At least one button must be configured.

The same physical Pico can only belong to one config entry — adding it a
second time (on its own or as part of a new group) is blocked automatically,
and it drops out of the device list once added.

### Editing a Pico

Open the entry under **Settings → Devices & Services** and click
**Configure**. The first step lets you add or remove Picos from the entry —
only Picos of this entry's type that aren't claimed by another entry are
offered, and at least one must remain. Non-4B entries then get the same
entity picker used during setup (you can even switch which domain it
controls here), followed by the timing and domain-specific
[options](#options), and for `3BRL` Picos, the custom actions builder —
none of which the initial add flow asks about, since the defaults just
work.
4B entries get the same button-action editor used during setup. Changes take
effect immediately and apply to every Pico in the entry; Pico Link
automatically reloads them all.

Non-4B entries (and new ones from setup) also get their controlled
entities appended to the entry's title on the plain **Settings → Devices
& Services → Pico Link** list — for example "Kitchen Pico — Kitchen
Lumary" instead of just "Kitchen Pico" — since that list otherwise gives
no hint of what an entry actually controls. This updates whenever the
entities step is submitted (including as part of any other edit), not
retroactively for entries you don't reopen.

Each step's button reads "Next" instead of "Submit" whenever more steps
follow, so it's clear before you click whether you're finishing this
Pico's configuration or continuing to another screen.

Each Pico's underlying device and its type are fixed (since the type is read
from the hardware, there's nothing to change there anyway) — a Pico can't
switch type or move to an entry of a different type. To link a different
physical Pico for the first time, add it via a new or existing entry as
above; to fully replace an entry's Pico type, remove the entry and add it
again.

### Removing a Pico

Open the Pico's entry under **Settings → Devices & Services**, click the
three-dot menu, and choose **Delete**.

---

## Entity Configuration

A domain may be assigned one entity or several. When multiple entities are
selected:

- Commands are sent to all of them.
- State-dependent calculations use the first selected entity as the
  reference.

For example, when several lights are assigned, brightness steps are
calculated from the first light and the resulting brightness is sent to all
assigned lights.

---

## Options

Every timing and domain option is configured on the **Options** step of setup
(or editing), pre-filled with these defaults:

| Field                    | Applies to          |        Default | Range or values                       |
| ------------------------ | -------------------- | --------------: | -------------------------------------- |
| `hold_time_ms`           | Light, cover, media  |          `400` | `100–2000` ms                         |
| `step_time_ms`           | Light, cover, media  |          `650` | `100–2000` ms                         |
| `cover_open_pos`         | Cover                |          `100` | `1–100` percent                       |
| `cover_step_pct`         | Cover                |           `10` | `1–25` percent                        |
| `cover_inverted`         | Cover                |        `false` | Boolean                               |
| `fan_on_pct`             | Fan                  |          `100` | `1–100` percent                       |
| `light_on_pct`           | Light                |          `100` | `1–100` percent                       |
| `light_low_pct`          | Light                |            `5` | `1–99` percent                        |
| `light_step_pct`         | Light                |           `10` | `1–25` percent                        |
| `light_transition_on`    | Light                |            `0` | `0–300` seconds                       |
| `light_transition_off`   | Light                |            `0` | `0–300` seconds                       |
| `light_on_off_toggle`    | Light                |        `false` | Boolean                               |
| `accent_lights`          | Light (P2B, 2B, 3BRL) |          `[]` | Entity list                           |
| `accent_light_presets`   | Light (P2B, 2B, 3BRL) | one default preset | List of presets (see below); cycled through on repeated OFF taps |
| `light_presets`          | Light (3BRL only)    |            `[]` | List of presets (see below); cycled through on every STOP press when non-empty |
| `media_player_vol_step`  | Media player         |           `10` | `1–20` percent                        |

Only the fields relevant to the Pico's assigned domain are shown. Numeric
selectors are clamped to their listed range.

Each entry in `accent_light_presets` or `light_presets` has its own
(`accent_light_*` / `light_preset_*` respectively):

| Field                       | Default          | Range or values                       |
| ---------------------------- | ----------------- | -------------------------------------- |
| `accent_light_color_mode`    | `rgb`            | `rgb` or `color_temp`; only offered if the accent (or, for `light_preset_*`, the first configured) light supports white temperature |
| `accent_light_rgb_color`     | `[255,255,255]`  | RGB triplet                           |
| `accent_light_color_temp_kelvin` | `2700`       | Kelvin, clamped to the light's supported range |
| `accent_light_effect`        | `""`             | Picked from the light's available effects; overrides color/white temperature when set |
| `accent_light_brightness_pct` | `100`           | `1–100` percent                       |

---

## Domain Behavior

### Lights

#### P2B and 2B

| Gesture  | Action                    |
| -------- | ------------------------- |
| ON tap   | Turn on at `light_on_pct` (or toggle if `light_on_off_toggle`) |
| ON hold  | Ramp brightness upward    |
| OFF tap  | Turn off (or toggle if `light_on_off_toggle`) |
| OFF hold | Ramp brightness downward  |

#### 3BRL

| Button | Tap                                         | Hold / double-tap (pick one, see below) |
| ------ | -------------------------------------------- | ------------- |
| ON     | Turn on at `light_on_pct` (or toggle if `light_on_off_toggle`) | Custom `on_hold` actions on hold, or `on_double_tap` actions on a second quick tap |
| OFF    | Turn off (or toggle if `light_on_off_toggle`) | Custom `off_hold` or `off_double_tap` actions |
| RAISE  | Increase by `light_step_pct`                | Ramp upward (no hold/double-tap actions apply here) |
| LOWER  | Decrease by `light_step_pct`                | Ramp downward (no hold/double-tap actions apply here) |
| STOP   | Custom STOP actions, otherwise no action    | Custom `stop_hold` or `stop_double_tap` actions |

Brightness does not ramp below `light_low_pct`, and raising a light that's
off — a single RAISE tap, or a P2B/2B ON hold — lands at `light_low_pct`
rather than a single `light_step_pct`, matching native Lutron dimmer
behavior. See [3BRL custom actions](#3brl-custom-actions) for how hold and
double-tap actions work.

#### Dual-light mode

Configuring `accent_lights` (on the "Accent light" options step, shown only
for a P2B, 2B, or 3BRL assigned to the light domain) puts it into dual-light
mode. Instead of turning the same light on and off, ON and OFF switch
between two separate lights — for example a center fixture and a ring/edge
accent light:

| Gesture  | P2B / 2B                                                         | 3BRL |
| -------- | ----------------------------------------------------------------- | ---- |
| ON tap   | Turn on `lights` at `light_on_pct`; turn off `accent_lights`       | Same |
| ON hold  | Ramp `lights` brightness upward; turns off `accent_lights` once the hold threshold is crossed | Not applicable — RAISE/LOWER ramp `lights` instead |
| OFF tap  | Turn on `accent_lights` at the current preset; turn off `lights`. A second OFF tap while the accent light is already on advances to the next preset instead of switching anything off | Same |
| OFF hold | Ramp `lights` brightness downward; once it bottoms out at `light_low_pct`, switches to `accent_lights` at the current preset instead of just stopping | Not applicable |

For a 3BRL, RAISE and LOWER always ramp `lights` regardless of dual-light
mode; ON and OFF only ever tap (they have no hold behavior of their own to
begin with — see the 3BRL table above), so they simply select center or
accent immediately. A 3BRL's ON/OFF can still separately use
`on_hold`/`off_hold`/`on_double_tap`/`off_double_tap` alongside dual-light
mode — those actions run in addition to (hold) or instead of (double-tap)
the center/accent switch, exactly as they would outside dual-light mode.

`accent_lights` and `lights` are never on at the same time. `light_on_off_toggle`
is ignored in this mode, since ON and OFF already mean "select center" and
"select accent" rather than toggling a single light.

The accent light's appearance is configured on one or more "Accent light
appearance" steps — one per preset — after the accent light(s) are selected,
since the available choices depend on what that light supports:

- **Effect** — picked from a dropdown of the first accent light's actual
  supported effects (`effect_list`, alphabetized), instead of typing a
  name. Leave it on "No effect" to use color or white temperature
  instead. When set, it takes priority over both.
- **White temperature** — only offered when the first accent light supports
  color temperature; lets you pick "Color" (RGB) or "White temperature"
  (Kelvin, clamped to that light's supported range) as the preset's
  appearance when no effect is selected.
- **Color** — a plain RGB color, used when neither an effect nor white
  temperature is selected.

Checking **Try it** on that step turns the accent light(s) on right away
with whatever's currently filled in, so you can see a preset before
continuing — it re-shows the same step afterward with your values kept, and
doesn't count as finishing the preset.

Checking "Add another preset" on that step repeats it to build a list
(`accent_light_presets`, up to 5). With only one preset, OFF always shows
the same appearance, exactly as if presets didn't exist. With more than
one, ON always resets back to the first preset — only repeated OFF taps
advance through the list, wrapping back to the first after the last.

When editing an entry that already has more than one preset, each existing
preset's step also offers "Remove this preset" — checking it drops that
preset and shifts any later ones up, so a list can be shrunk without
clearing `accent_lights` and rebuilding dual-light mode from scratch.

Rapid repeated brightness taps use the most recently requested brightness for a
short period instead of waiting for Home Assistant state to update.

### STOP light-preset cycling

For a `3BRL` assigned to the light domain and **not** in dual-light mode
(`accent_lights` empty), STOP can instead cycle `lights` through one or
more saved appearances — for example switching a LIFX bulb between white
temperatures with the middle button. Configured on the "Light presets"
options step (shown only when there's no accent light), which offers the
same "Try it" preview, "Remove this preset", and "Add another preset"
(up to 5) controls as dual-light presets, plus a leading "Cycle light
appearance from STOP" checkbox — leaving it unchecked configures nothing,
and STOP keeps its normal behavior instead.

Every STOP press advances to the next preset, wrapping back to the first
after the last; turning the light on or off via ON/OFF resets the cycle
back to the first preset. This is mutually exclusive with both
`accent_lights` and custom STOP actions (`middle_button`) — configuring
one clears the others, and the options flow won't let both be set at
once.

### Light transitions

`light_transition_on` and `light_transition_off` apply only to ON and OFF tap
actions. When a transition is `0`, the transition field is omitted from the
action call. Brightness steps and ramps do not use transitions.

### Light toggle mode

Enabling `light_on_off_toggle` (a checkbox on the light options screen)
changes both the ON and OFF buttons from discrete turn-on/turn-off actions
into a toggle: each checks the light's current state and flips it. This is
useful when one Pico controls a single light or light group and you want
either button to work correctly regardless of which state it's currently in
— handy in the dark, when you can't see which button is which.

- P2B / 2B: tap toggles; holding still ramps in its original direction
  (ON hold always ramps up, OFF hold always ramps down), unaffected by this
  setting.
- 3BRL: both ON and OFF simply toggle, since they have no hold behavior of
  their own.
- Off by default — existing Picos are unaffected until you turn it on.
- Ignored for a P2B/2B in dual-light mode (see above) — `accent_lights`
  already gives ON and OFF distinct, unambiguous meanings.

---

### Fans

Fan controls are always tap-only. Holding ON, OFF, RAISE, or LOWER does not
initiate a ramp. A 3BRL fan Pico can still use
`on_hold`/`off_hold`/`stop_hold` or `on_double_tap`/`off_double_tap`/
`stop_double_tap` to run custom actions on a hold or a double-tap; see
[3BRL custom actions](#3brl-custom-actions).

| Button | Action                                              |
| ------ | ---------------------------------------------------- |
| ON     | Set speed to `fan_on_pct`                           |
| OFF    | Turn off                                            |
| RAISE  | Move up one available fan speed                     |
| LOWER  | Move down one available fan speed                   |
| STOP   | Custom STOP actions, otherwise reverse direction    |

Fan speed steps are calculated from the entity's `percentage_step` attribute.

If the fan is off, RAISE moves it to the first nonzero speed.

If the fan does not expose a usable `percentage_step`, Pico Link falls back to:

```text
0 → 100
```

---

### Covers

#### P2B and 2B

| Gesture                | Action                                 |
| ------------------------ | ----------------------------------------- |
| ON tap                 | Open to `cover_open_pos`               |
| ON hold                | Move continuously in the ON direction  |
| OFF tap                | Close fully                            |
| OFF hold               | Move continuously in the OFF direction |
| ON or OFF while moving | Stop movement                          |

When `cover_inverted` is enabled, ON and OFF tap and hold directions are
reversed.

#### 3BRL

| Button | Tap                                    | Hold               |
| ------ | ---------------------------------------- | -------------------- |
| ON     | Open to `cover_open_pos`               | Custom `on_hold` actions, if configured |
| OFF    | Close fully                            | Custom `off_hold` actions, if configured |
| RAISE  | Increase position by `cover_step_pct`  | Open continuously  |
| LOWER  | Decrease position by `cover_step_pct`  | Close continuously |
| STOP   | Custom STOP actions, otherwise stop    | Custom `stop_hold` actions, if configured |

Rapid repeated cover taps use the most recently requested target position for a
short period instead of waiting for `current_position` to update.

When changing direction after continuous movement, Pico Link waits for
`stop_cover` to complete before submitting the next position command.

---

### Media Players

#### P2B and 2B

| Gesture  | Action                    |
| -------- | ------------------------- |
| ON tap   | Play or pause             |
| ON hold  | Raise volume continuously |
| OFF tap  | Next track                |
| OFF hold | Lower volume continuously |

#### 3BRL

| Button | Tap                                           | Hold                      |
| ------ | ------------------------------------------------ | --------------------------- |
| ON     | Play or pause                                 | Custom `on_hold` actions, if configured |
| OFF    | Next track                                    | Custom `off_hold` actions, if configured |
| RAISE  | Raise volume one step                         | Raise volume continuously |
| LOWER  | Lower volume one step                         | Lower volume continuously |
| STOP   | Custom STOP actions, otherwise toggle mute    | Custom `stop_hold` actions, if configured |

The volume step is configured as a percentage via `media_player_vol_step`.
Volume commands are clamped between `0.0` and `1.0`.

---

### Switches

| Button | Action                                      |
| ------ | -------------------------------------------- |
| ON     | Turn on                                     |
| OFF    | Turn off                                    |
| STOP   | Custom STOP actions, otherwise no action    |
| RAISE  | No action                                   |
| LOWER  | No action                                   |

Switches have no domain-specific hold behavior — holding ON, OFF, RAISE, or
LOWER does nothing extra by itself. A 3BRL switch Pico can still use
`on_hold`/`off_hold`/`stop_hold` or `on_double_tap`/`off_double_tap`/
`stop_double_tap` to run custom actions on a hold or a double-tap; see
[3BRL custom actions](#3brl-custom-actions).

---

### 4B Scene Controllers

A 4B Pico does not control a domain directly. Each button executes an action
sequence built with Home Assistant's action picker during setup or editing.

Supported buttons:

```text
button_1
button_2
button_3
off
```

At least one button must have actions configured. Actions execute
sequentially in the order they were added; each action completes before the
next one begins.

Each button can also optionally define a hold action or a double-tap
action (not both), configured on the **Scene hold and double-tap actions**
step in the options flow. These follow the same rules as
[3BRL custom actions](#3brl-custom-actions): a hold action runs in addition
to the button's scene action once held past `hold_time_ms`; a double-tap
action replaces the scene action on two quick taps, which delays that
specific button's scene action by up to `DOUBLE_TAP_WINDOW_MS` (400ms) to
confirm a second tap didn't follow — buttons without one configured are
completely unaffected.

---

## STOP Actions and Domain Defaults

Custom STOP actions (`middle_button`) are valid only for `3BRL` Picos,
configured on the **Custom actions** step.

Resolution order:

1. Custom STOP actions configured on the Pico
2. For a light-domain 3BRL outside dual-light mode: cycling through
   `light_presets`, if configured (see
   [STOP light-preset cycling](#stop-light-preset-cycling))
3. Domain-specific STOP behavior when none of the above is configured

### Domain defaults

| Domain       | Default STOP behavior |
| ------------- | ------------------------ |
| Cover        | Stop movement         |
| Fan          | Reverse direction      |
| Light        | No action              |
| Media player | Toggle mute            |
| Switch       | No action              |

To use the domain default, leave STOP actions empty on that step.

### 3BRL custom actions

On the **Custom actions** step, ON, OFF, and STOP can each additionally run
a custom action sequence — either on a hold, or on a double tap, but not
both on the same button. Filling in both for one button is caught right on
this step (an inline error naming the conflict), not deferred to a later
**Setup failed**. Leave a button's fields empty to skip it entirely; with
nothing configured, no timer is created and there's no behavior change at
all.

- **Hold** (`on_hold` / `off_hold` / `stop_hold`) — runs once that button
  has been held past `hold_time_ms`, in addition to its normal tap/press
  behavior (including custom STOP actions), which always still fires
  immediately on press, unchanged. This is how you can, for example, have
  ON turn on one light on a tap but a whole room on a hold.
- **Double tap** (`on_double_tap` / `off_double_tap` / `stop_double_tap`) —
  runs instead of that button's normal tap/press behavior when two taps
  land within `DOUBLE_TAP_WINDOW_MS` (400ms, not configurable) of each
  other. Configuring this changes that button's timing: since Pico Link
  can't know a second tap won't follow until the window passes, that
  button's own normal action is delayed by up to 400ms so it can be
  replaced by the double-tap action if one comes. Buttons without a
  double-tap action configured are completely unaffected — this delay
  only ever applies to a button you've explicitly set one up for. This is
  how you can, for example, have OFF turn off one light on a tap but a
  whole room on a double tap.

**Test an action** on this step (and on 4B's equivalent step) picks one of
the fields above and runs it immediately with whatever's currently filled
in when you submit, re-showing this same step with your values kept
afterward — so a STOP/hold/double-tap action can be checked before you save
and walk over to the physical remote.

---

## Custom Actions: Full Home Assistant Action Support

STOP-button and 4B button actions are validated and run with Home Assistant's
own action engine — the same one behind automations and scripts — not just a
plain list of service calls. That means the action editor's "Building
Blocks" are available too: **If-then**, **Choose**, **Repeat**, **Wait**,
**Delay**, and templates in service data.

This makes state-dependent behavior possible without any code changes. For
example, a STOP button that turns on only one of two lights when both are
off, but swaps them when exactly one is already on:

```yaml
- if:
    - condition: state
      entity_id: light.kitchen_accent
      state: "on"
    - condition: state
      entity_id: light.kitchen_center
      state: "off"
  then:
    - action: light.turn_off
      target:
        entity_id: light.kitchen_accent
    - action: light.turn_on
      target:
        entity_id: light.kitchen_center
  else:
    - action: light.turn_on
      target:
        entity_id: light.kitchen_accent
    - action: light.turn_off
      target:
        entity_id: light.kitchen_center
```

Build this with **+ Add action → Building blocks → If-then** in the STOP
button editor; conditions and both branches use the same pickers as a plain
action.

---

## Entity Placeholders

Within a 3BRL STOP action, these values can be used as a `target.entity_id`
(including inside nested if-then/choose branches):

| Placeholder     | Expands to                           |
| ----------------- | --------------------------------------- |
| `covers`        | All configured cover entities        |
| `fans`          | All configured fan entities          |
| `lights`        | All configured light entities        |
| `media_players` | All configured media-player entities |
| `switches`      | All configured switch entities       |

Because these placeholders are not real entity IDs, Home Assistant's visual
entity picker inside the action editor won't offer them. Use the action
editor's **Edit in YAML** toggle for that action to type a placeholder
directly, for example:

```yaml
action: light.turn_on
target:
  entity_id: lights
```

A placeholder can also be mixed with explicit entities in the same list, and
other target fields (like `area_id`) are preserved during expansion.

---

## Validation and Error Handling

Pico Link validates each Pico's configuration as it is entered, before the
step can be submitted:

- Exactly one domain's entities must be filled in (non-4B), or at least one
  4B button must have actions, before continuing.
- Entities are restricted to the correct domain by the entity picker itself.
- Numeric fields are clamped to their allowed range by the field itself.
- The same physical Pico cannot be configured more than once, and the type is
  read from the hardware, so it can never be entered incorrectly.

If a Pico's configuration becomes invalid after an update (for example, an
assigned entity was deleted), Home Assistant marks that Pico's entry as
**Setup failed** under **Devices & Services**, with the specific reason
shown right on the entry (also logged). Other configured Picos are
unaffected. Mutually-exclusive fields (a button's hold and double-tap
actions) are additionally caught inline on the options step itself, before
they ever reach this point.

---

## Diagnostics and Repairs

### Repairs

Two problems, once detected, show up under **Settings → Repairs** instead of
only in the log:

- **Hardware type mismatch** — a configured Pico's events keep arriving with
  a different or unrecognized hardware type. This means the physical device
  changed, or the wrong type was configured; that Pico's events are ignored
  until it's resolved. Clears itself automatically the next time a matching
  event arrives.
- **Pico removed from the bridge** — a configured Pico's device no longer
  exists in Home Assistant's device registry (it was removed or re-paired on
  the Lutron bridge, or someone deleted the device entry directly). Checked
  once at startup and again on every device registry change, so it's caught
  even if it happened while Home Assistant was offline. Clears itself if the
  device reappears; otherwise, edit or remove the affected Pico Link entry.
- **A configured entity no longer exists** — a light, cover, fan, media
  player, switch, or accent light assigned to a Pico was deleted or renamed.
  Button presses that target it otherwise fail silently. Checked once Home
  Assistant has finished starting (so a slower-loading integration isn't
  flagged before it's registered its entities) and again on every entity
  registry change; clears itself once every listed entity exists again.

None of these repairs are "fixable" through a guided flow — each points you
at what to check, since the fix (correcting the configured type, re-adding
the Pico, or pointing the entry at the right entities) happens outside Pico
Link.

### Diagnostics

Every Pico Link entry supports Home Assistant's standard diagnostics
download (its "⋮" menu under **Settings → Devices & Services** →
**Download diagnostics**). The dump includes the entry's configuration and,
for each Pico in it, its device ID, configured type, and controlled domain
— useful for your own troubleshooting or for filing a sharper bug report.
Nothing in it needs redacting: no credentials or personal data, just entity
IDs, device IDs, and configuration values.

---

## The pico_link_button event

Pico Link fires a `pico_link_button` event on the bus for every press and
release that passes device, hardware-type, and button validation —
regardless of what (if anything) it goes on to control. This lets an
automation, a Node-RED flow, or anything else listening on the event bus
react to a Pico's normalized semantics directly, without re-deriving them
from the raw `lutron_caseta_button_event` (device ID → configured type →
normalized button name).

Event data:

| Field       | Description                                                    |
| ----------- | ---------------------------------------------------------------- |
| `device_id` | The Pico's Home Assistant device ID                            |
| `type`      | Configured Pico type (`P2B`, `2B`, `3BRL`, or `4B`)             |
| `button`    | Normalized button name (`on`, `off`, `stop`, `raise`, `lower`, `button_1`, `button_2`, `button_3`) |
| `action`    | `press` or `release`                                            |
| `domain`    | The domain this Pico controls (`light`, `cover`, `fan`, `media_player`, `switch`), or `null` for a 4B Pico |

This fires alongside — not instead of — Pico Link's own configured
behavior; it's an additional hook, not a replacement for `middle_button`,
`on_hold`, or any other configured action. Example automation trigger:

```yaml
trigger:
  - platform: event
    event_type: pico_link_button
    event_data:
      device_id: <your Pico's device ID>
      button: "on"
      action: press
```

### Device triggers

For the same thing without writing YAML by hand, use the automation
editor's own trigger picker: **Add Trigger → Device → (your Pico) →** and
choose one of the listed "`<button>` pressed" / "`<button>` released"
options. This builds the same event trigger shown above — it's a UI
shortcut over `pico_link_button`, not a separate mechanism, and only
offers the buttons that Pico's type actually has (e.g. a P2B only offers
ON/OFF; a 4B offers its four scene buttons).

---

## Troubleshooting

### Pico Link loads but no buttons work

Confirm:

1. The Lutron Caséta integration is loaded.
2. The Pico emits `lutron_caseta_button_event`.
3. The Pico device selected during setup matches the physical remote sending
   the event.
4. The configured type matches the type reported in the event.
5. The assigned entities still exist and use the correct domain.

### A Pico's entry shows "Setup failed"

The specific validation error is shown right on the entry (expand it under
**Settings → Devices & Services**), not just in the log — for example, a
reassigned/deleted entity, or (for 3BRL/4B) a button with both a hold and a
double-tap action configured. Use **Configure** on the entry to fix it.

### Configured and reported Pico types do not match

Since the type is read from the hardware at setup time, this should only
happen if a Pico was physically swapped at the same Lutron device
registration without being re-paired. Remove the integration entry and add
the Pico again to re-detect its type.

### Rapid cover or light taps

Pico Link retains recent requested brightness and cover-position targets so
repeated taps do not depend on immediate entity-state updates.

When behavior appears out of sync after an external change, wait briefly before
the next tap so Pico Link resynchronizes from Home Assistant.

### Fan holds do not ramp

This is intentional. Fan controls are tap-only.

---

## Updating

### Versioning

Releases use calendar versioning: `YYYY.MM.DD.XX` (e.g. `2026.09.06.01`).
`XX` starts at `01` each day and increments for additional releases on that
same date.

After installing an updated version:

1. Restart Home Assistant.
2. Check **Settings → Devices & Services** for any Pico Link entry showing
   **Setup failed** or a repair notification.
3. Test ON, OFF, RAISE, LOWER, STOP, and custom actions for each configured
   Pico type.

Editing a Pico's options through **Configure** reloads only that Pico and does
not require a Home Assistant restart.

---

## Support Development

<a href="https://buymeacoffee.com/smartqasa" target="_blank">
  <img src="https://www.buymeacoffee.com/assets/img/custom_images/yellow_img.png" height="60" alt="Support development">
</a>
