# Control Resolution Budget (Endpoint-First)

Purpose: define the **full available UART command range per controlled axis**, then trace backward through the current pipeline to show where resolution is preserved or reduced.

Quick range summary (decimal-first):
- BGC (current code payload fields): signed int16 little-endian per axis (`<3h`); center `0`, range `-500..+500`; `-10000` = undefined/signal lost (SimpleBGC CMD 45 Speed mode). Head converts v2 u16 (0..65535, center 32768) to this range before sending.
- Fuji control commands (`20h/21h/22h`): `0..65535` (`0x0000..0xFFFF`).
- Fuji zoom speed command (`26h`): `0` = wide max speed (`0x0000`), `32768` = stop (`0x8000`), `65535` = tele max speed (`0xFFFF`).
- Canon zoom/focus position: `0..60000`.
- Canon iris reference points: `32768` = F16 (`0x8000`), `53248` = F2.8 (`0xD000`), with `4096` (`0x1000`) per F-stop.
- Input device (Teensy 4.1 ADC feeding gamepad axes `0..5`): ADC is configured to 12-bit (`analogReadResolution(12)`), so each analog channel is sampled as `0..4095` (4096 discrete counts) before HID scaling.
- Input axis source mapping (firmware pins -> HID axes): `A5->X`, `A7->Y`, `A6->Z`, `A17->Rx (focus)`, `A16->Ry (iris)`, `A0->Rz (zoom)`; browser mapping used by UI defaults to `0->X`, `1->Y`, `2->Z`, `3->Xrotate`, `4->Yrotate`, `5->Zrotate`.
- Teensy HID axis range: signed `-32768..32767` per axis (int16); browser Gamepad API exposes normalized floats (typically near `-1.0..+1.0`).
- Practical noise note: ADC quantization floor is 1 raw count, but idle float jitter is expected from analog noise/pot wiper noise; no ADC averaging call is present in firmware (`analogReadAveraging(...)` not found).
- Engineering estimate for browser step size: 12-bit raw full-scale step is about `1/4095 ~= 0.000244`; after 12-bit-to-int16 scaling and browser normalization, ideal per-count float movement near center is on the order of `~0.0005` (before additional browser/input-stack filtering/noise).

Ideal and Realistic Control Resolution (input side):
- Professional reference basis: ideal quantization behavior uses `SNR ~= 6.02N + 1.76 dB` for an `N`-bit ADC (Analog Devices MT-001), and practical resolution is best tracked as noise-free bits / effective resolution in raw counts (TI precision ADC guidance on effective resolution/noise-free resolution terminology).
- Ideal target (physics/math limit for current firmware ADC setting): with `N=12`, one raw code is `1/4095 ~= 0.000244` of full scale; quantization-limited behavior means monotonic 12-bit response with no missing codes and 1-count minimum step.
- Realistic target for this controller (high-quality Hall joystick + cermet pots, USB-powered from Pi5): validate by measurement in raw counts at rest per axis (fixed window, e.g., 1 s):
  - Preferred: `<= 2 counts p-p` (about 11 noise-free bits, since `log2(4096/2)=11`).
  - Acceptable: `<= 4 counts p-p` (about 10 noise-free bits, since `log2(4096/4)=10`).
  - Investigate: `> 8 counts p-p` (below 9 noise-free bits, since `log2(4096/8)=9`).
- Browser float equivalence for quick sanity checks: `2` counts is about `0.00049` FS, `4` counts about `0.00098` FS, `8` counts about `0.00195` FS (before browser-side filtering/normalization effects).

- Based on the preferred `<= 2 counts p-p` input target, current end-to-end command resolution is currently limited mostly by software mapping, not ADC hardware: BGC is limited by bridge quantization to about `-512..+512` (`1025` levels) before UART (`apps/controller/mvp_protocol.py::build_udp_packet`), Fuji focus/iris are limited to about `0..64` (`65` levels) by `map_focus/map_iris` right-shift mapping before lens normalization (`apps/controller/mvp_protocol.py::build_udp_packet`), and Fuji zoom is limited by delta-style command shaping (`zoom_gain`, deadband, expo) rather than full absolute-position command coverage (`apps/head_eng/fuji_lens_from_calibration.py::move_zoom`).

Known issue:
- Side-by-side Chromium testing on Pi5 shows this custom gamepad device currently at `> 8 counts p-p` idle jitter, while an off-the-shelf game controller is `<= 2 counts p-p` under the same test conditions. This places the custom device in the "Investigate" band in this document and below the preferred input-resolution target. See `Teensey Gamepad/JITTER_INVESTIGATION_REPORT.md`.

Scope evidence files:
- `apps/head_eng/bgc.py`
- `apps/head_eng/lens_controller.py`
- `apps/head_eng/fuji_lens_from_calibration.py`
- `apps/head_eng/fuji_protocol.py`
- `apps/head_eng/canon_lens.py`
- `apps/head_eng/canon_protocol.py`
- `apps/controller/mvp_protocol.py`
- `apps/controller/mvp_ui.html`

External protocol references requested:
- `C:/Users/andre/Downloads/SimpleBGC_2_6_Serial_Protocol_Specification (1).pdf`
- `C:/Users/andre/Downloads/CanonBCTVlens_SerialCommunicationProtocol_Rev021 01a.pdf`
- `C:/Users/andre/Cross-shore Dropbox/A Chandler/EX-CAMERAS/Bought Ins/Fuji/L10 Protocol ver. 1.80.pdf`

## 1) UART Output Targets (full envelope)

These are the maximum ranges the current UART command builders/transports can carry, based on code.

| UART path | Axis/command | Wire field width | Full wire value envelope to target | Source evidence (code) | External protocol reference |
|---|---|---:|---|---|---|
| BGC UART (`UART_ID=1`, `115200`) | `yaw`,`pitch`,`roll` via `CMD_API_VIRT_CH_CONTROL` mapping | 16 bits each (`>3H`) in current code payload | `0..65535` each axis in current code | `apps/head_eng/bgc.py::BGC.send_joystick_control` | SimpleBGC spec: Data type `2s` and axis arrays in `ROLL,PITCH,YAW` order; see “Data type notation” and `CMD_API_VIRT_CH_CONTROL`/`CMD_API_VIRT_CH_HIGH_RES` sections in `SimpleBGC_2_6_Serial_Protocol_Specification (1).pdf` |
| Lens UART Fuji (`UART_ID=0`, `38400`, `8`, `None`, `1`) | `ZOOM_CONTROL` (`0x21`) | 16 bits (`[hi][lo]`) | `0x0000..0xFFFF` | `apps/head_eng/fuji_protocol.py::FUNC_ZOOM_CONTROL`, `build_zoom_control`; `apps/head_eng/fuji_lens_from_calibration.py::FujiLens.baud/bits/parity/stop` | Fuji L10 v1.80 excerpt: “21h ZOOM CONTROL” variable range `0000H` through `FFFFH` (`L10 Protocol ver. 1.80.pdf`) |
| Lens UART Fuji | `FOCUS_CONTROL` (`0x22`) | 16 bits (`[hi][lo]`) | `0x0000..0xFFFF` | `apps/head_eng/fuji_protocol.py::FUNC_FOCUS_CONTROL`, `build_focus_control` | Fuji L10 v1.80 excerpt: “22h FOCUS CONTROL” variable range `0000H` through `FFFFH` (`L10 Protocol ver. 1.80.pdf`) |
| Lens UART Fuji | `IRIS_CONTROL` (`0x20`) | 16 bits (`[hi][lo]`) | `0x0000..0xFFFF` | `apps/head_eng/fuji_protocol.py::FUNC_IRIS_CONTROL`, `build_iris_control` | Fuji L10 v1.80 excerpt: “20h IRIS CONTROL” variable range `0000H` through `FFFFH` (`L10 Protocol ver. 1.80.pdf`) |
| Lens UART Fuji | `ZOOM_SPEED_CONTROL` (`0x26`) | 16 bits (spec value) | `0x0000` = wide max speed, `0x8000` = stop, `0xFFFF` = tele max speed | not implemented in scoped runtime code (`apps/head_eng/fuji_protocol.py` has no `FUNC_ZOOM_SPEED_CONTROL`/builder) | Fuji L10 v1.80 excerpt: “26h ZOOM SPEED CONTROL” mapping as above (`L10 Protocol ver. 1.80.pdf`) |
| Lens UART Canon (`UART_ID=0`, `19200`, `8`, even parity, `1`) | `CMD_ZOOM_POS` Type-B (`0x87`,`C0`) | 16-bit value encoded into `2+7+7` payload bits | `0..60000` | `apps/head_eng/canon_protocol.py::pack_type_b_value`, `build_type_b`; `apps/head_eng/canon_lens.py::CanonLens.baud/bits/parity/stop` | Canon spec Section 7.8: zoom position `0 (WIDE) .. 60000 (TELE)`; Section 6.2.1: Type-B data encoding in three 7-bit bytes |
| Lens UART Canon | `CMD_FOCUS_POS` Type-B (`0x88`,`C0`) | same as above | `0..60000` | same | Canon spec Section 7.9: focus position `0 (FAR) .. 60000 (NEAR)`; Section 6.2.1 encoding |
| Lens UART Canon | `CMD_IRIS_POS` Type-B (`0x96`,`C0`) | same as above | Canon absolute iris window in spec (`0x8000..0xD000` for F16..F2.8), code currently permits `0..60000` | same | Canon spec Section 7.12 and 7.11 answers: iris scale `F16:8000h` to `F2.8:D000h` (1000h per F-stop) |

Notes:
- BGC UART parity/stop defaults are not explicitly set in code; exact serial framing is unknown from scoped files.
- Active runtime lens defaults to Fuji (`apps/head_eng/main.py::lens = LensController(default_lens_type=LENS_FUJI)` and `apps/head_eng/lens_controller.py`).
- BGC axis numbering/order note: SimpleBGC spec states axis-ordered arrays are `ROLL,PITCH,YAW`; current code sends `yaw,pitch,roll` positional arguments into `>3H` payload. Mapping semantics at firmware side are not proven in repo code alone.

## 2) Work Backwards From UART: Current Upstream Range Feeding Each Axis

This table shows the range produced before UART output, and where quantization happens.

| Output axis | Current upstream value path (active v2 pipeline) | Upstream value envelope in code | Distinct levels before UART | Key bottleneck(s) | Evidence |
|---|---|---|---:|---|---|
| BGC yaw | UI `X` -> `build_udp_packet`: `int(x*512)` -> v2 field `yaw` -> `send_joystick_control` | nominal `-512..512` in bridge before pack | 1025 | bridge maps to ~10-bit signed space, then placed into 16-bit transport | `apps/controller/mvp_protocol.py::build_udp_packet`, `build_fast_packet_v2`; `apps/head_eng/main.py::decode_fast_packet_v2`; `apps/head_eng/bgc.py::BGC.send_joystick_control` |
| BGC pitch | UI `Y` -> same path | nominal `-512..512` | 1025 | same as yaw | same |
| BGC roll | UI `Z` -> same path | nominal `-512..512` | 1025 | same as yaw | same |
| Fuji focus | UI `Xrotate` -> `int(v*512)` -> `map_focus=(v+512)>>4` -> v2 `focus` -> `_normalize_input(...,0xFFFF)` | mapped to `0..64` before lens normalize | 65 | `>>4` quantization in bridge path | `apps/controller/mvp_protocol.py::map_focus`, `build_fast_packet_v2`; `apps/head_eng/fuji_lens_from_calibration.py::_normalize_input`, `set_focus_input` |
| Fuji iris | UI `Yrotate` -> `int(v*512)` -> `map_iris=(v+512)>>4` -> v2 `iris` -> `_normalize_input(...,0xFFFF)` | mapped to `0..64` before lens normalize | 65 | `>>4` quantization in bridge path | `apps/controller/mvp_protocol.py::map_iris`; `apps/head_eng/fuji_lens_from_calibration.py::_normalize_input`, `set_iris_input` |
| Fuji zoom | UI `Zrotate` -> `zoom_i=int(v*zoom_gain)` (`zoom_gain` default `60`) -> v2 `zoom` -> Fuji `move_zoom(delta)` | approx `-zoom_gain..+zoom_gain` (default `-60..60`) | up to 121 input deltas | delta/deadband/expo shaping path (not absolute-position command from host) | `apps/controller/mvp_protocol.py::build_udp_packet`; `apps/head_eng/fuji_lens_from_calibration.py::move_zoom`, `_shape_zoom_input_expo` |
| Canon focus | same fast `focus` field as Fuji path -> Canon `_normalize_input(...,60000)` -> `build_type_b` | mapped to `0..64` before normalize | 65 | same bridge `>>4` quantization | `apps/controller/mvp_protocol.py::map_focus`; `apps/head_eng/canon_lens.py::set_focus_input`, `_normalize_input`; `apps/head_eng/canon_protocol.py::build_type_b` |
| Canon iris | same fast `iris` field as Fuji path -> Canon normalize -> `build_type_b` | mapped to `0..64` before normalize | 65 | same bridge `>>4` quantization | `apps/controller/mvp_protocol.py::map_iris`; `apps/head_eng/canon_lens.py::set_iris_input` |
| Canon zoom | same fast `zoom` delta as Fuji path -> Canon `move_zoom(delta)` | approx `-zoom_gain..+zoom_gain` (default `-60..60`) | up to 121 input deltas | delta/deadband path; not direct full-range absolute command from host | `apps/controller/mvp_protocol.py::build_udp_packet`; `apps/head_eng/canon_lens.py::move_zoom` |

## 3) Resolution Utilization Snapshot (Current)

The table below compares current practical command levels (from code path) vs available UART envelope.

| Axis group | UART envelope | Current practical input levels | Utilization statement |
|---|---:|---:|---|
| BGC yaw/pitch/roll | 65536 levels each | 1025 each from bridge mapping | not full envelope (about 1.56% of 16-bit code space) |
| Fuji focus/iris | 65536 levels each | 65 levels entering lens normalize | severe upstream quantization before UART |
| Fuji zoom | 65536 absolute domain in lens state | delta-driven path from about 121 input deltas | host path is incremental; full absolute envelope is not directly commanded from fast packet |
| Canon focus/iris | 60001 levels each (`0..60000`) | 65 levels entering normalize | severe upstream quantization before UART |
| Canon zoom | 60001 absolute domain in lens state | delta-driven path from about 121 input deltas | host path is incremental; full absolute envelope is not directly commanded from fast packet |

## 4) Unknowns / Evidence Limits

| Item | Status |
|---|---|
| BGC command semantic center/scale for `yaw`,`pitch`,`roll` | unknown from scoped files; only field width (`>3H`) is proven |
| Exact number of distinct zoom command deltas after expo shaping | unknown without enumerating `_shape_zoom_input_expo` output values over input domain |
| Gamepad hardware raw precision before browser normalization | unknown from scoped files |

## 5) “Highest Possible Control Resolution” Definition (for this repo)

Use this as acceptance intent for migration planning:

1. For every axis with absolute-position UART command (`BGC yaw/pitch/roll`, Fuji focus/iris, Canon focus/iris), upstream fast API values should be able to express the full target wire envelope without avoidable pre-quantization.
2. Any intentional nonlinearity/deadband should be explicit and measurable, not inherited from compatibility transforms.
3. Delta-driven axes (current zoom paths) should document whether they remain delta control by design or move to absolute-position control semantics.

This document is endpoint-first; implementation changes are tracked in the cleanup plan in `apps/head_eng/API_SOURCE_OF_TRUTH.md`.

