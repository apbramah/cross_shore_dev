Executive summary (Feb 2026)

This project has moved from a single-file Canon prototype to a modular dual-protocol engineering tool:

- Canon behavior from the original tester has been preserved in a package-based architecture.
- Fuji L10 support has been added as a second tab with its own COM port, protocol/parser, control UI, logging, and BIT runner.
- The app now supports active-tab gamepad routing (Canon or Fuji) and per-axis source control UI on both tabs.
- The app title is now "HydraVision Lens Tester".

Current operational state:

- Canon: stable (BIT, keepalive, gamepad, axis control).
- Fuji: functional with protocol-level control, startup sequencing, polling keepalive, SW4 control visibility, and manual/gamepad/slider control paths.
- Fuji behavior required iterative tuning against real hardware and vendor-app sniff traces; key lessons are documented below.

What has been implemented so far (high level)

1) Architecture refactor completed

- CanonLensTester.py is now a thin entrypoint.
- Core logic split into modules:
  - canon_protocol.py
  - frame_parser.py
  - serial_worker.py
  - keepalive.py
  - bit_runner.py
  - gamepad.py
  - ui_app.py
  - main.py
- Fuji modules added:
  - fuji_protocol.py
  - fuji_frame_parser.py
  - fuji_bit_runner.py

2) Canon path retained and stabilized

- Canon BIT flow remains callback-driven and deterministic.
- Canon gamepad remains gated by Canon BIT pass.
- Canon axis source/position controls remain as the known-good baseline.

3) Fuji tab and protocol support added

- Independent Fuji COM connection and serial settings (38400 8N1).
- Fuji frame build/parse/checksum implemented.
- Fuji lens name auto-read and display on connect.
- Fuji SW4 ownership readout and controls.
- Fuji BIT implemented in dedicated FujiBitRunner module (callback pattern like Canon).
- Fuji status panel mirrors Canon status semantics (idle/running/pass/fail + detail).

4) Fuji startup/keepalive aligned with observed vendor behavior

- Connect sequence includes repeated connect and discovery burst.
- SW4 host assertion updated to use F8 semantics for host-all.
- Continuous Fuji polling loop added (switch states + axis positions + extra status functions seen in captures) to prevent ownership timeout and maintain fresh UI state.

5) UI parity improvements and gamepad routing

- Fuji axis control cards now mirror Canon style:
  - mode selector (PC/Camera/Off)
  - Apply Source
  - slider/target/position/send
- Active-tab gamepad routing implemented:
  - Canon tab drives Canon worker/protocol
  - Fuji tab drives Fuji worker/protocol
- Fuji connect path now starts gamepad flow correctly when enabled and Fuji is active/ready.

Key lessons learned from integration/debugging

1) Spec compliance alone was not enough; observed device behavior mattered

- Fuji integration required matching not just frame format but also startup order, SW4 semantics, and polling cadence used by the vendor tool.

2) SW4 ownership semantics are critical and timing-sensitive

- Incorrect SW4 assumptions or sparse host traffic caused "accepted command but no movement" behavior.
- Ownership can drift if host does not keep the session active.

3) Request/response traffic pattern affects real control outcomes

- Continuous low-latency polling acted as practical keepalive and state synchronization.
- Intermittent control-only traffic produced unstable authority behavior.

4) UI intent and hardware readback must be separated

- Forcing UI source selections from every SW4 readback caused control-mode "snap back" behavior.
- Better model: user selection defines desired state; readback is displayed as telemetry.

5) Logging + sniff traces accelerated convergence

- Side-by-side TX/RX evidence from this app and vendor captures was the fastest way to identify protocol/sequence mismatches.

Purpose

CanonLensTester.py is an engineer-facing diagnostic and control tool for Canon BCTV ENG lenses over a serial link (typically via USB-to-RS422/RS232 adapter).

It provides a known-good reference implementation of Canon’s serial protocol for:

Initial handshake / initialization sequence

Keeping the session alive

Taking control of zoom, focus, and iris axes

Issuing absolute position commands and monitoring “follow” feedback

It is intended as part of an internal “engineers debug kit” and as a stepping stone for porting the final control logic to embedded MicroPython (Pico / control system).

How it evolved

Started as a simple GUI to:

Pick a COM port

Send a few known frames (CTRL_CMD / FINISH_INIT / LENS_NAME_REQ)

Display RX data

Evolved into a hardened tool with:

Automatic BIT (built-in test) on connect:

wait settle time

init handshake

query lens ID

start keepalive

request PC control for each axis

sweep axes to min/max/center while verifying follow responses

Continuous keepalive sending

Manual frame send (hex entry)

Frame reassembly/parser (Type-A / Type-B / Type-C)

Axis control widgets (source select + slider + send)

Gamepad control section:

zoom via joystick axis with accumulator and deadband

focus/iris via buttons with repeat rate

UI deadband adjustment

starts only after BIT passes

Protocol framing implemented (current)

Type-A: 3-byte frames ending in BF (e.g., CTRL_CMD 80 C6 BF)

Type-B: 6-byte frames ending in BF (axis positions, finish init)

Type-C: variable length starting with BE and ending with BF (lens name, control source switching)

Parser (CanonFrameParser) reassembles frames from arbitrary serial chunks, uses a basic resync strategy to avoid desync.

Significant problems solved (and why they matter)

Unreliable “CTRL_CMD echo”

Some Canon lenses echo 80 C6 BF; some do not.

Early BIT treated missing echo as a failure; newer lenses caused false failures.

Fix: treat CTRL_CMD echo as a non-fatal capability/behavior indicator.

Lesson: never assume one lens family’s echo/handshake behavior is universal.

Correct lens-name decoding across models

Lens name response payload appears as UTF-16LE-ish pairs, but byte order can vary by lens/firmware.

We initially decoded “printable bytes” which produced garbage or leading characters.

Then we implemented the paired decode and fixed indentation issues that prevented it running.

Final: decode <ASCII> 00 pairs (UTF-16LE) and optionally strip leading “&”.

Lesson: decoding must be robust to slight protocol variations; unit tests for parsing are worthwhile.

RX frame reassembly / resync

Serial reads arrive in arbitrary chunks; frames can be split or combined.

Implemented a buffer-based parser that:

recognizes Type-C by BE…BF

recognizes Type-A/Type-B by fixed size and BF terminator

drops bytes to resync if unknown patterns appear

Lesson: frame parsing must be stateful; assume arbitrary chunk boundaries.

Deterministic init/BIT logic

Added synchronous waits for specific RX prefixes during BIT so initialization is deterministic.

The tool drains stale RX frames before each “send and wait” step to avoid matching old frames.

Lesson: deterministic initialization needs explicit “send -> wait for response” primitives.

Keepalive flood/noise

Keepalive at 0.5s can spam logs.

Implemented throttled logging (e.g., log every N keepalive sends).

Lesson: logs must remain readable during long runs.

Gamepad integration + ownership gating

Gamepad starts only after BIT passes (so control source is known to be correct).

Zoom uses accumulator and deadband; focus/iris use repeated step events.

Lesson: input devices need filtering, throttling, and separation from protocol plumbing.

Main components (high-level)

SerialWorker

opens/closes pyserial connection

manages a background RX thread

pushes raw bytes into a queue

CanonFrameParser

reassembles frames from raw RX chunks

App (CustomTkinter UI)

Connection controls, modem line toggles

Manual send + logs

BIT orchestration thread

Axis panels (zoom/focus/iris source + position control)

Keepalive thread

Gamepad thread (pygame) + UI controls

Known limitations / caveats

Gamepad zoom is jittery (expected from noisy analog axis + high update rate).

Not urgent; can be improved with smoothing/slew limiting and “send only on delta threshold”.

Lens name decoding currently assumes UTF-16LE pairs; may need fallback logic if other models return different packing.

Parser resync is simple; sufficient so far but could be hardened if new lens behaviors appear.

Two serial devices (Canon + future Fuji) will require separate workers/parsers and UI separation (tabs/modules).

To-do list (practical next steps)

Code quality / structure

Split CanonLensTester.py into modules (UI, protocol, serial, BIT, gamepad, utilities).

Add basic unit tests for frame parsing and lens-name decoding.

Centralize constants and command builders in a protocol module.

Usability

Add “Verbose logging” checkbox (gate gamepad debug + frequent TX logs).

Add “Save log to file” button (timestamped).

Display capability summary in BIT pass status (CTRL echo YES/NO, lens ID, etc).

Gamepad (later)

Low-pass filter + slew limiter on zoom axis.

Only transmit zoom when change exceeds threshold.

Respect axis ownership (don’t drive if axis source is Camera/Off).

Fuji lens support

Add second tab or sibling app with separate COM port and Fuji protocol implementation.

Implement Fuji handshake based on captured known-good frames from vendor app.

Mirror BIT pattern (init -> take control -> sweep axes -> keepalive if required).

Lessons learned (engineering takeaways)

Protocol “spec” is not always complete; real devices vary by firmware generation.

Build tools that tolerate variation:

treat some steps as best-effort

anchor success on the most reliable responses (lens name, finish init, follow feedback)

Always implement frame reassembly and resync; never assume read boundaries align to frames.

Keep initialization deterministic with send/wait primitives and RX queue management.

Logs must be readable; throttle periodic chatter.


Proposed module boundaries + exact interfaces
1) serial_worker.py

What it owns

SerialWorker, SerialConfig

RX background thread -> rx_queue of raw bytes

send() with lock

modem line setters

Public API

SerialConfig(port: str, baud: int, dtr: bool, rts: bool)

class SerialWorker:

open(cfg: SerialConfig) -> None

close() -> None

is_open() -> bool

send(data: bytes) -> None

set_dtr(state: bool) -> None

set_rts(state: bool) -> None

rx_queue: queue.Queue[bytes] (raw byte chunks)

No UI, no protocol constants.

2) frame_parser.py

What it owns

CanonFrameParser (buffer-based, reassembly/resync)

Public API

class CanonFrameParser:

feed(data: bytes) -> list[bytes]

No protocol decode beyond framing.

3) canon_protocol.py

What it owns

All protocol constants + frame builders + packing/unpacking

Lens name decoding helper (pure function)

Public API

Constants:

BAUD, PARITY, BITS, STOP

CTRL_CMD, FINISH_INIT, LENS_NAME_REQ

SRC_OFF, SRC_CAMERA, SRC_PC

SCMD_*, CMD_*, SUBCMD_C0

Helpers:

hexdump(b: bytes) -> str

pack_type_b_value(v: int) -> tuple[int,int,int]

unpack_type_b_value(d1: int, d2: int, d3: int) -> int

build_type_b(cmd: int, subcmd: int, v: int) -> bytes

build_type_c_switch(scmd: int, src_bits: int) -> bytes

decode_lens_name_type_c(frame: bytes) -> str | None

returns decoded string or None

Implementation note:

decode_lens_name_type_c() should encapsulate the UTF-16LE-ish logic you fixed.

4) utils.py

What it owns

COM port enumeration + parsing

regex for hex input validation (or keep it in protocol)

Public API

list_com_ports() -> list[str]

extract_port_name(display: str) -> str

HEX_RE (optional)

5) bit_runner.py

What it owns

The BIT state machine and all timing/waits

Uses send/wait prefix logic

Does NOT touch UI widgets directly

Key design

BIT should talk to the app via callbacks so it stays testable and avoids circular imports.

Public API

<>Python
from dataclasses import dataclass
from typing import Callable, Optional

@dataclass
class BitCallbacks:
    log: Callable[[str, str], None]                 # (tag, msg)
    set_status: Callable[[str, str], None]          # (state, detail)  state in {"idle","running","pass","fail"}
    on_lens_id: Callable[[str], None]               # lens name string
    on_targets: Callable[[int, int, int], None]     # zoom, focus, iris targets for gamepad/GUI sync
    on_passed: Callable[[], None]                   # mark bit_passed True, start gamepad if enabled
    on_failed: Callable[[str], None]                # mark bit_passed False

class BitRunner:
    def __init__(self, worker: SerialWorker, rx_frame_q: "queue.Queue[bytes]", callbacks: BitCallbacks):
        ...

    def start(self) -> None
    def stop(self) -> None
    def is_running(self) -> bool

<>End Python

Important

BIT needs access to rx_frame_q (frames, not raw bytes). The App will keep _handle_frame() pushing frames into rx_frame_q, same as today.

6) keepalive.py

What it owns

Keepalive thread loop (sends CTRL_CMD periodically)

Throttled logging

Public API

<>Python
Important

BIT needs access to rx_frame_q (frames, not raw bytes). The App will keep _handle_frame() pushing frames into rx_frame_q, same as today.

<>End Python

7) gamepad.py

What it owns

GamepadConfig

pygame loop thread

deadband + accumulator logic

button repeat logic

sends axis commands via worker

Key design

Gamepad shouldn’t assume UI objects exist.

Gamepad gets:

a can_drive() callback (e.g., lambda: worker.is_open() and bit_passed)

an axis_enabled(axis: str) -> bool callback (optional later)

a set_ui_targets(z,f,i) callback (so App updates sliders)

a log() callback

Public API

<> Python

from dataclasses import dataclass
from typing import Callable

@dataclass
class GamepadConfig:
    enabled: bool = True
    zoom_axis_index: int = 3
    focus_dec_button: int = 4
    focus_inc_button: int = 5
    iris_dec_button: int = 1
    iris_inc_button: int = 2
    zoom_deadband: float = 0.12
    zoom_max_counts_per_s: float = 18000.0
    focus_step: int = 250
    iris_step: int = 250
    button_repeat_hz: float = 10.0
    loop_hz: float = 40.0
    zoom_send_hz: float = 20.0
    debug_log_buttons: bool = False
    debug_log_zoom: bool = False

class GamepadRunner:
    def __init__(
        self,
        worker: SerialWorker,
        cfg: GamepadConfig,
        can_drive: Callable[[], bool],
        get_follow: Callable[[], tuple[int|None, int|None, int|None]],
        set_targets: Callable[[int,int,int], None],
        log: Callable[[str,str], None],
    ):
        ...

    def start(self) -> None
    def stop(self) -> None
    def is_running(self) -> bool
    def set_deadband(self, deadband: float) -> None

    <>End Python
8) ui_app.py

What it owns

The App(ctk.CTk) class and all UI widgets

It wires everything:

creates SerialWorker, CanonFrameParser

starts RX polling

owns _handle_frame() and pushes frames into rx_frame_q

instantiates BitRunner / KeepaliveRunner / GamepadRunner

It implements the callbacks (log/status/slider updates)

App responsibilities

Provide these callback functions:

self._log(tag,msg)

self._ui_set_bit_status(state,detail)

self._set_lens_label(name)

self._set_sliders(z,f,i) and store targets

self._mark_bit_passed() / _mark_bit_failed(reason)

9) main.py

What it owns

Windows DPI awareness setup

app = App(); app.mainloop()

A minimal “wiring sketch” 

Inside App.__init__ after creating worker/parser:

self.keepalive = KeepaliveRunner(worker, interval_s, CTRL_CMD, log=self._ui_log)

self.gamepad_runner = GamepadRunner(worker, cfg, can_drive=..., get_follow=..., set_targets=..., log=self._ui_log)

self.bit_runner = BitRunner(worker, self.rx_frame_q, callbacks=BitCallbacks(...))

When BIT passes:

Start keepalive (BIT already does or triggers App to start)

Start gamepad if enabled