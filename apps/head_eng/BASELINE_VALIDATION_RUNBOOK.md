# ADC Fast Path Baseline Validation Runbook

Use this runbook to verify no avoidable bit loss and fast-only actuation after the ADC Fast Path Cleanup. Setup: Windows controller (ADC bridge) + head on LAN (head_eng on Pico).

## Prerequisites

- Controller: ADC bridge running with default passthrough profile (no deadband/expo/LPF/slew).
- Head: `ENABLE_DUAL_CHANNEL=True` (v2 fast decode), lens/BGC driven from fast UDP only.
- Optional: enable observability for logging.
  - Controller: `MVP_FAST_DEBUG=1` or `--fast-debug` (sends + last axes every 5s).
  - Head: set `MVP_FAST_DEBUG = True` in `main.py` (recvs + last fields every 5s).

## 1. No-motion baseline (idle jitter)

**Goal:** Capture idle min/max/jitter for all six axes at bridge send and head decode.

**Steps:**

1. Do not move any stick or control. Ensure ADC stream is live (bridge connected to Teensy).
2. On controller, enable fast debug and run for ~30s. Note send count and the reported axes (should be near 0 or center; small jitter is expected).
3. On head, enable fast debug and run for ~30s. Note recv count and last decoded field ranges (yaw, pitch, roll, zoom, focus, iris).
4. **Pass:** Recv count ≈ send count (within packet loss tolerance). Idle axes stay in a small band; no large jumps.

## 2. Stimulus sweep (full-range and small-step)

**Goal:** Verify monotonicity and no missing steps.

**Steps:**

1. **Full-range per axis:** Move one axis at a time (pan, tilt, roll, zoom, focus, iris) from min to max. Confirm head response follows smoothly and reaches both ends.
2. **Small-step:** Move each axis in small steps (e.g. focus/iris by small increments). Confirm no “sticky” regions where small changes are dropped (baseline mode uses zero hold threshold and zero zoom deadband).
3. **Pass:** No avoidable quantization; small inputs produce proportional response.

## 3. Transport proof (fast-only actuation)

**Goal:** Confirm control still works from fast UDP path only (slow channel not required for axis data).

**Steps:**

1. Temporarily disable slow handling on the head (e.g. set `ENABLE_SLOW_CHANNEL = False` or do not bind/recv slow port).
2. Run ADC bridge as usual; send fast packets only (slow can still be sent but head ignores them).
3. Move all axes; confirm BGC and lens respond from fast packets alone.
4. **Pass:** Pan/tilt/roll and zoom/focus/iris all respond; no dependency on slow channel for control.
5. Re-enable slow channel when done (needed for config such as motors_on, control_mode, lens_select).

## Verification checklist (from plan)

- [ ] Fast packet contains all demanded control fields with expected range and no legacy compatibility remap.
- [ ] No controller-side deadband/expo/LPF/slew active in baseline mode.
- [ ] No downstream lens/BGC thresholds causing avoidable quantization loss for baseline mode.
- [ ] Head motion/lens response confirmed from fast UDP path only.
- [ ] Sequence/cadence stable at target rate without packet parse/drop issues.
