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
> This fork replaces YAML configuration with full setup and editing through
> the Home Assistant UI (Settings → Devices & Services) — see
> [Adding a Pico](#adding-a-pico) below. Development of this fork was
> AI-assisted (Claude).

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
[options](#options), and for `3BRL` Picos, a STOP-button action builder —
none of which the initial add flow asks about, since the defaults just work.
4B entries get the same button-action editor used during setup. Changes take
effect immediately and apply to every Pico in the entry; Pico Link
automatically reloads them all.

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
| `edge_lights`            | Light (P2B, 2B)      |            `[]` | Entity list                           |
| `edge_light_rgb_color`   | Light (P2B, 2B)      | `[255,255,255]` | RGB triplet                           |
| `edge_light_effect`      | Light (P2B, 2B)      |             `""` | Effect name (overrides color)         |
| `edge_light_brightness_pct` | Light (P2B, 2B)  |           `100` | `1–100` percent                       |
| `media_player_vol_step`  | Media player         |           `10` | `1–20` percent                        |

Only the fields relevant to the Pico's assigned domain are shown. Numeric
selectors are clamped to their listed range.

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

#### P2B and 2B dual-light mode

Configuring `edge_lights` (on the "Edge/ring light" options step, shown only
for a P2B/2B assigned to the light domain) puts it into dual-light mode.
Instead of turning the same light on and off, ON and OFF switch between two
separate lights — for example a center fixture and a ring/edge accent light:

| Gesture  | Action                                                           |
| -------- | ----------------------------------------------------------------- |
| ON tap   | Turn on `lights` at `light_on_pct`; turn off `edge_lights`         |
| ON hold  | Ramp `lights` brightness upward; turns off `edge_lights` once the hold threshold is crossed |
| OFF tap  | Turn on `edge_lights` at `edge_light_rgb_color`/`edge_light_effect`/`edge_light_brightness_pct`; turn off `lights` |
| OFF hold | Ramp `lights` brightness downward; once it bottoms out at `light_low_pct`, switches to `edge_lights` instead of just stopping |

`edge_lights` and `lights` are never on at the same time. `light_on_off_toggle`
is ignored in this mode, since ON and OFF already mean "select center" and
"select edge" rather than toggling a single light. If `edge_light_effect` is
set it takes priority over `edge_light_rgb_color`.

#### 3BRL

| Button | Tap                                         | Hold          |
| ------ | -------------------------------------------- | ------------- |
| ON     | Turn on at `light_on_pct` (or toggle if `light_on_off_toggle`) | — |
| OFF    | Turn off (or toggle if `light_on_off_toggle`) | —            |
| RAISE  | Increase by `light_step_pct`                | Ramp upward   |
| LOWER  | Decrease by `light_step_pct`                | Ramp downward |
| STOP   | Custom STOP actions, otherwise no action    | —             |

Brightness does not ramp below `light_low_pct`.

Rapid repeated brightness taps use the most recently requested brightness for a
short period instead of waiting for Home Assistant state to update.

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
- Ignored for a P2B/2B in dual-light mode (see above) — `edge_lights` already
  gives ON and OFF distinct, unambiguous meanings.

---

### Fans

Fan controls are always tap-only. Holding a fan button does not initiate a ramp.

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
| ON     | Open to `cover_open_pos`               | —                  |
| OFF    | Close fully                            | —                  |
| RAISE  | Increase position by `cover_step_pct`  | Open continuously  |
| LOWER  | Decrease position by `cover_step_pct`  | Close continuously |
| STOP   | Custom STOP actions, otherwise stop    | —                  |

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
| ON     | Play or pause                                 | —                         |
| OFF    | Next track                                    | —                         |
| RAISE  | Raise volume one step                         | Raise volume continuously |
| LOWER  | Lower volume one step                         | Lower volume continuously |
| STOP   | Custom STOP actions, otherwise toggle mute    | —                         |

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

Switches do not support hold behavior.

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

---

## STOP Actions and Domain Defaults

Custom STOP actions are valid only for `3BRL` Picos, configured on the
**STOP button** step.

Resolution order:

1. Custom STOP actions configured on the Pico
2. Domain-specific STOP behavior when no custom actions are configured

### Domain defaults

| Domain       | Default STOP behavior |
| ------------- | ------------------------ |
| Cover        | Stop movement         |
| Fan          | Reverse direction      |
| Light        | No action              |
| Media player | Toggle mute            |
| Switch       | No action              |

To use the domain default, leave the STOP button step empty.

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
      entity_id: light.kitchen_edge
      state: "on"
    - condition: state
      entity_id: light.kitchen_center
      state: "off"
  then:
    - action: light.turn_off
      target:
        entity_id: light.kitchen_edge
    - action: light.turn_on
      target:
        entity_id: light.kitchen_center
  else:
    - action: light.turn_on
      target:
        entity_id: light.kitchen_edge
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
**Setup failed** under **Devices & Services**, with the reason in the Pico
Link log. Other configured Picos are unaffected.

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

Check the Pico Link log entries for that device for the specific validation
error, then use **Configure** on the entry to fix it (for example,
reassigning a deleted entity).

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
