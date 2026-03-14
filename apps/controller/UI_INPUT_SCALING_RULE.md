# UI Input Scaling Rule (Controller UI)

## Purpose

Standardize all operator-facing UI/input values so encoder behavior is predictable,
non-wrapping, and consistent across pages.

## Core Rule

- Default UI scale for editable values: **0..10 (integer steps)**.
- Optional high-resolution mode: **0.0..10.0 (step 0.1)**.
- **No wrapping** at bounds (always clamp).

## Input Behavior

- One accepted encoder event = one value step.
- CW increases, CCW decreases.
- At bounds:
  - if value == max and CW -> stays max
  - if value == min and CCW -> stays min
- Debounce/lockout filtering must run before value mutation.

## Field Modes

Each editable field must declare:

- `min`
- `max`
- `step`
- `high_res` (bool)
- `wrap` (must be `false`)

### Defaults

- Coarse/default:
  - `min: 0`
  - `max: 10`
  - `step: 1`
  - `high_res: false`
  - `wrap: false`

- High-res:
  - `min: 0.0`
  - `max: 10.0`
  - `step: 0.1`
  - `high_res: true`
  - `wrap: false`

## Internal Mapping Rule

UI may use normalized 0..10 while backend uses engineering units.

- Keep engineering units internal.
- Use deterministic mapping functions in one place.
- UI display should reflect normalized scale unless explicitly in engineering view.

## Step/Clamp Definition

Given `current`, `delta_steps` (`+1`/`-1`), `step`, `min`, `max`:

`next = clamp(current + delta_steps * step, min, max)`

No modulo/wrap logic is permitted.

## Rounding and Display

- Coarse mode: integer display (`0..10`).
- High-res mode: fixed one decimal (`0.0..10.0`).
- Internally, store numeric values; formatting is presentation-only.

## Acceptance Criteria

1. No field wraps when turned past min/max.
2. All coarse fields move in exact integer steps.
3. High-res fields move in exact 0.1 steps.
4. Same encoder event handling semantics across all UI tabs.
5. Any cross-talk filtering changes only event acceptance, never step size logic.

## Migration Guidance

When migrating existing fields:

1. Classify each field as `coarse` or `high_res`.
2. If engineering range differs, define explicit map:
   - UI `0..10` -> engineering min..max
3. Add automated tests for:
   - clamp at boundaries
   - no wrap
   - exact step increments
