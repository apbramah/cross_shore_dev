# Lessons Learnt: Fuji Tester Parity

## Purpose
Prevent drift when porting proven behavior from `ENG Lens Testing/CanonLensTester.py` and `ENG Lens Testing/canon_lens_tester/*` into MicroPython payload code.

## Non-Negotiable Rule
When asked for **exact parity**, do not implement "equivalent" behavior.
Only adapt serial I/O API differences (PySerial -> SoftUART).

## Exact Means
- Same state machine steps.
- Same command ordering.
- Same retry boundaries.
- Same parser semantics.
- Same timing intent (intervals and step delays).
- No additional commands in critical windows.

## Required Porting Protocol
1. Map tester functions to payload functions one-to-one.
2. Keep a parity table (`tester step` -> `payload step`) while coding.
3. Mark any unavoidable mismatch explicitly with reason.
4. Do not claim "exact" unless every row matches or is documented as unavoidable.

## Critical Fuji Sequence (from tester connect path)
1. `CONNECT`
2. `CONNECT`
3. Discovery burst `0x10..0x17`
4. `Switch4 Host`
5. Start name poll (`LENS_NAME_1` immediate, then 300 ms tick, max 20)
6. Start keepalive (100 ms tick, SW4 reassert every 5 ticks, poll `0x54,0x53,0x52,0x30..0x35`)
7. `Switch4 Pos Req`
8. Start BIT sequence

## Name Handling Rules
- On RX `0x11` with 15-byte payload, request `0x12`.
- Build lens name as tester does: part1 then append part2.
- Do not suppress valid `0x12` that belongs to current name exchange.

## Response Discipline For This Agent Session
Before each user-facing reply in this session:
1. Re-check this file.
2. State clearly whether parity is exact, partial, or broken.
3. If partial/broken, list concrete mismatches without spin.
