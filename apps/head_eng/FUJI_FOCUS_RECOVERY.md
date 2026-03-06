# Fuji Focus Recovery

This note tracks the current focus-recovery process while preserving known-good BGC and zoom behavior.

## Current Runtime Policy

- Focus command policy is instrumentation-only:
  - Sends focus command on meaningful input change.
  - No periodic focus re-drive loop.
- SW4 ownership safety remains active.
- Zoom smoothing changes remain active.

## Active Debug Signals

- Zoom TX: `[LENS][Fuji][ZOOM] TX t=<ms> delta=<d> target=<u16>`
- Zoom RX: `[LENS][Fuji][ZOOM] RX t=<ms> pos=<u16>`
- Focus TX: `[LENS][Fuji][FOCUS] TX t=<ms> target=<u16>`
- Focus RX: `[LENS][Fuji][FOCUS] RX t=<ms> pos=<u16> target=<u16> err=<s32>`
- SW4 ownership:
  - `TX SW4_CONTROL bits=...`
  - `RX SW4_POSITION bits=... desired=...`
  - `SW4 mismatch -> reassert host control`

## Focus Test Matrix

Run each pattern for ~2 minutes and capture a short serial log slice.

1. Step input (single move then hold)
2. Slow ramp
3. End-stop approach/hold

For each pattern, evaluate:

- No unintended continuous focus movement after input settles.
- No iris jump correlated with focus-only operation.
- SW4 mismatch events are infrequent and quickly reasserted.
- BGC and zoom behavior remain unchanged.

## Pass/Fail Record (fill during bench)

- Step input: PASS / FAIL
- Slow ramp: PASS / FAIL
- End-stop: PASS / FAIL

Notes:
- ...

## Optional Next Knob (only if needed)

If focus still misses occasional single commands after this baseline,
introduce a bounded assist as a standalone change:

- short assist window
- low retry count cap
- fixed retry interval

Do not combine assist tuning with SW4 cadence changes in the same run.

## Parity Matrix vs `fuji_control_calibration.py` (2026-03-02)

| Area | Runtime `fuji_lens.py` | Calibrator `fuji_control_calibration.py` | Result |
|---|---|---|---|
| Loop command order | In scheduled mode: consume RX -> SW4 poll -> conditional connect keepalive -> axis control TX | In sweep/stress/gamepad loops: consume RX -> SW4 poll -> conditional connect keepalive -> axis control TX | SAME (for scheduled mode) |
| Timing constants | `SW4_POLL_MS=300`, `CONNECT_KEEPALIVE_MS=1000`, `DEMAND_ACTIVE_WINDOW_MS=800`, `CONTROL_TX_PERIOD_MS=50`; recovery uses connect timeout `800`, verify timeout `300`, retries `3/3` | `SW4_POLL_MS=300`, `CONNECT_KEEPALIVE_MS=1000`, `DEMAND_ACTIVE_WINDOW_MS=800`, update tick `UPDATE_MS=50`; connect wait `1200`, retries `3` | DIFFERENT (recovery/ACK waits) |
| ACK waits / timeouts / retries | Mixed: keepalive is fire-and-forget; SW4 recovery connect uses ACK wait (`_send_and_wait`) with retries; startup/BIT also use `_send_and_wait` | Connect uses ACK wait with retries; control ACK waits depend on `TX_MODE` (`burst` none, `strict/semi_strict` with timeout) | DIFFERENT (runtime mixed paths, calibrator mode-driven) |
| SW4 desired bits policy | Dynamic `desired = SW4_HOST_ALL` with per-axis camera/off bits added (`bit0/1/2`) | Fixed `SW4_DESIRED_BITS = SW4_HOST_ALL` for bench utility | DIFFERENT |
| SW4 mismatch/recovery sequence | Mismatch -> cooldown gate -> connect ACK wait -> SW4 control -> bounded SW4 verify retries -> fail streak -> fault latch | Mismatch -> optional one-shot recovery attempt (`_connect` + `_force_sw4_pc`) with no explicit verify loop | DIFFERENT |
| Connect keepalive behavior | Every `1000ms`, skipped while recent control demand is active (`<800ms`) | Same: every `1000ms`, skipped while demand active (`<800ms`) | SAME |
| Poll request set | Scheduled mode polls SW4 only; non-scheduled mode polls SW4 + zoom (+focus/iris when idle) | Watchdog polls SW4 position only | DIFFERENT (runtime non-scheduled path broader) |
