# Command Architecture: Toward a Clean, Scalable Design

## Top-level architecture: three layers

The system is best viewed as three layers, with the **head** further decomposed into three abstract subsystems:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 1: UX CONTROL                                                     │
│  (Controller UI, encoder, touch, profiles, shaping, assignment)           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ WebSocket / state, command_id + value
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 2: IP CONNECTION                                                 │
│  (Bridge, protocol, UDP fast/slow, network config)                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ UDP packets (fast axes, slow command_id + value)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 3: CAMERA HEAD                                                   │
│  ┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐ │
│  │ (a) MOTOR CONTROLLER │ │ (b) PAYLOAD 1       │ │ (c) PAYLOAD 2       │ │
│  │ Abstract: gimbal    │ │ Abstract: camera    │ │ Abstract: lens     │ │
│  │ • BGC (current)     │ │ • Sony (current)    │ │ • Fuji (current)   │ │
│  │ • ODrive (current)  │ │ • Proton (current)  │ │ • Canon (current)  │ │
│  │ • VESC (soon)       │ │                     │ │                    │ │
│  └─────────────────────┘ └─────────────────────┘ └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

- **UX control** talks only in terms of **command_id** and **normalised values** (e.g. 0–10). It does not know whether a command goes to BGC, ODrive, or VESC.
- **IP connection** carries command_id + value (and fast stream); it does not care which head subsystem will consume a slow command.
- **Head** has three **abstract roles**: motor controller, camera (payload 1), lens (payload 2). Each role has **pluggable implementations** (BGC/ODrive/VESC, Sony/Proton, Fuji/Canon). The command registry targets the **role** (e.g. `motor_controller`, `camera`, `lens`); the head selects the concrete driver (BGC vs ODrive vs VESC, etc.) by config or discovery.

Abstracting by this extra level means:
- Adding **VESC** is “new motor_controller implementation”; UX and protocol stay unchanged.
- Adding **Proton** camera or another lens brand is “new camera/lens implementation”; command_ids and value definitions stay the same.
- The **master command table** references **device_class** (motor_controller | camera | lens) and optionally **value type + normalisation** so every value has a single, shared definition.

---

## Value definition: type and normalisation

Every command value should have an explicit **value definition** in the registry:

- **Type:** e.g. `integer`, `float`, `enum`, `boolean`.
- **Normalisation:** how the value is represented in different layers, so UX, wire, and device never disagree.
  - **UI normalised:** e.g. integer 0–10 (slider steps), float 0.0–10.0, or enum (index + labels).
  - **Wire normalised:** what goes over UDP (e.g. int16, uint8, enum code).
  - **Device range:** optional min/max or enum mapping per device_class (e.g. BGC gain 0–255, gyro 0–16383).

Example for one command:

```yaml
# Single definition: type + normalisation everywhere
- id: 11
  name: gyro_heading_correction
  type: slow
  device_class: motor_controller
  value:
    type: integer
    ui:       { range: [0, 10], step: 1 }      # UI shows 0–10
    wire:     { encoding: uint16, range: [0, 16383] }
    default:  5376
  ui: { slider: true, quick: false }
```

Another:

```yaml
- id: 1
  name: motors_on
  type: slow
  device_class: motor_controller
  value:
    type: enum
    ui:   { values: [0, 1], labels: [OFF, ON] }
    wire: { encoding: uint8 }
    default: 1
  ui: { slider: true, quick: true }
```

So: **one row per command**, with **type** and **normalisation** (ui, wire, and optionally device) defined in one place. Codegen or runtime can derive UI widgets, wire encode/decode, and validation from this.

---

## Current state: not clean

Right now the system has **multiple sources of truth**:

- **Slow:** `SLOW_KEY_IDS` in `mvp_protocol.py`, `SLOW_KEY_NAMES` + switch in `main.py`, `_default_slow_state()` in bridge, `mvp_factory_defaults.json`, and UI arrays (`SLOW_SLIDER_COMMANDS`, `SLOW_QUICK_COMMANDS`) all must stay in sync.
- **Fast (shaping):** `_default_shaping_profile()` in bridge, factory defaults, UI `FAST_SLIDER_COMMANDS` / `FAST_QUICK_COMMANDS`.
- Identifiers are **string keys**; the “API” is whatever the code happens to agree on. Adding a command = editing 5+ places and hoping nothing is missed.

So in software-engineering terms: **no**, this is not a clean architecture for a system where you regularly add commands and UART-connected devices. It’s a **distributed, implicit contract** with high risk of drift and bugs.

---

## What a senior engineer would aim for

Proven approaches for “one place to add a command, everything else follows”:

1. **Single source of truth (schema-driven / data-driven API)**  
   One **master command table** (or small set of tables) defines every command: id, name, type, value encoding, default, which device(s), and UI hints. All runtimes and the UI **derive** from this; they don’t re‑declare the same list.

2. **Command ID as the contract**  
   The wire and internal contract is **command_id** (integer). Names and labels are **metadata** for logs and UI. Controller sends `(command_id, value)`; head dispatches by id. No string matching in hot paths; no typos; adding a command = one new row and one handler.

3. **Device registry / adapter pattern**  
   Each UART device (BGC, Fuji, Canon, Sony VISCA, future devices) **registers** which command_ids it handles and how to encode/decode. Adding a new device = add a module and register; the core “command table” and dispatcher don’t need to know device details.

4. **Optional codegen**  
   Master table (JSON/YAML) → generate: Python constants and encode/decode, MicroPython head constants and dispatch stubs, UI JSON/TypeScript for dropdowns and labels. One edit in the table, regenerate, all layers stay aligned. Same idea as OpenAPI/protobuf/device descriptor codegen.

---

## Target shape: master command table

A single **command registry** defines every command with **id**, **device_class** (abstract role: motor_controller | camera | lens | controller), and **value** (type + normalisation). Concrete implementations (BGC, VESC, Sony, Fuji, etc.) are chosen at the head; the registry stays implementation-agnostic.

```yaml
# One table: command_id, device_class (role), value type + normalisation

schema_version: 2

device_classes:
  motor_controller: [BGC, ODrive, VESC]
  camera:           [Sony, Proton]
  lens:             [Fuji, Canon]

commands:
  - id: 1
    name: motors_on
    type: slow
    device_class: motor_controller
    value:
      type: enum
      ui:   { values: [0, 1], labels: [OFF, ON] }
      wire: { encoding: uint8 }
      default: 1
    ui: { slider: true, quick: true }

  - id: 2
    name: control_mode
    type: slow
    device_class: motor_controller
    value:
      type: enum
      ui:   { values: [0, 1], labels: [Speed, Angle] }
      wire: { encoding: uint8 }
      default: 0
    ui: { slider: true, quick: true }

  - id: 11
    name: gyro_heading_correction
    type: slow
    device_class: motor_controller
    value:
      type: integer
      ui:   { range: [0, 10], step: 1 }
      wire: { encoding: uint16, range: [0, 16383] }
      default: 5376
    ui: { slider: true, quick: false }

  - id: 3
    name: lens_select
    type: slow
    device_class: lens
    value:
      type: enum
      ui:   { values: [0, 1], labels: [Fuji, Canon] }
      wire: { encoding: uint8 }
      default: 0
    ui: { slider: true, quick: true }

  - id: 256
    name: shape_expo
    type: fast
    device_class: controller
    value:
      type: float
      ui:   { range: [0, 10], step: 0.1 }
      default: 5.0
    ui: { slider: true, quick: false }
```

- **Controller/bridge:** Load registry; state is `dict[command_id, value]`. Encode for wire using each command's `value.wire`; derive UI from `value.ui`.
- **Head:** Dispatcher maps `command_id` to `device_class`; the active driver for that class (BGC vs ODrive vs VESC, etc.) handles the command. No UX or protocol change when swapping BGC for VESC.
- **UI:** Builds controls from `value.type` and `value.ui`; sends `{ command_id, value }` in normalised form. Assignment is slot to command_id.
- **Value:** Every value has one definition: **type** (integer, float, enum, boolean) and **normalisation** (ui range/step/labels, wire encoding/range). One place for validation and encode/decode.

That way you really do have **one internal API doc**: the master table. Everything else references **command IDs** and, for display, the metadata in that table.

---

## Device (UART) side: registry pattern

For “regularly add UART-connected devices”, a clean approach is a **device registry**:

- **Command registry** says which `command_id` is handled by which **device_class** (motor_controller | camera | lens). Implementations (BGC, ODrive, VESC, Sony, Proton, Fuji, Canon) are chosen at the head.
- **Per device_class**, one or more implementations (e.g. BGC, ODrive, VESC for motor_controller). Each implementation module:
  - Registers: “I handle command_ids [1, 2, 11, 12, 13, 14, 15, 16, 17, 18].”
  - Exposes: `encode(id, value) -> wire_bytes_or_udp_payload`, `handle(id, value)` (and optionally decode for telemetry).
- **Dispatcher** on the head: look up `command_id` to device_class, then call the **active implementation** for that class (e.g. BGC vs VESC for motor_controller). Swapping BGC for VESC = change active implementation; command set and protocol unchanged.

Same idea as a driver model: registry maps command to **class**; each class has pluggable implementations (BGC/ODrive/VESC, Sony/Proton, Fuji/Canon).

## Proven techniques (names to search)

- **Schema-driven / data-driven API:** one schema or table drives server, client, and docs (e.g. OpenAPI, GraphQL schema, protobuf).
- **Command pattern + registry:** commands are first-class (id + payload); a registry maps id → handler. Common in game engines and device control.
- **Protocol codegen:** .proto, ASN.1, or custom YAML/JSON → generate wire format and language bindings. Single source of truth for message/command layout.
- **Device/driver registry:** Linux kernel, USB, or embedded HAL: “device declares what it handles”; core dispatches by id/tag.

---

## Migration path (pragmatic)

1. **Introduce the master table** (e.g. `command_registry.json`) next to the repo. Populate it from current `SLOW_KEY_IDS` and shaping keys; treat it as the **documentation and spec** first. Keep existing code working.
2. **Add command_id to the wire** (or keep current key_id for slow and treat it as “id”). Bridge and UI start using **id** in state and in assignment payloads; keep name in the table for logs and UI labels. UI loads “list of commands” from bridge (from registry) instead of hardcoded arrays.
3. **Refactor head** to dispatch by id from a table and call device modules by device tag. Each device module owns its ids.
4. **Optional:** Add a small codegen step (e.g. “python scripts/codegen_commands.py”) that emits Python/MicroPython constants and UI JSON from the registry so new commands are “add row + implement handler” only.

That gives you a **cleaner architecture**: one master matrix/table as the internal API, UI and runtimes referencing command IDs and metadata from that table, and a clear pattern for adding commands and new UART devices without touching five different files by hand.

---

## Planning and managing the migration

How an experienced developer would plan and run this migration so it stays on track, stays safe, and stays reversible.

### Principles

- **Incremental, not big-bang.** Each phase delivers a working system; no “merge everything and hope.” Prefer small PRs and short-lived branches.
- **Backwards compatibility first.** New wire formats or IDs run alongside old behaviour until consumers are migrated; then deprecate and remove. Avoid flipping the whole system in one release.
- **Validate at boundaries.** After each phase, prove: controller still drives head, head still responds, UI still reflects state. Use the same deploy/verify steps (hash check, service status, smoke test) every time.
- **One-way door vs two-way door.** Decisions that are easy to reverse (e.g. add a new JSON file, add an optional field) can move fast. Decisions that are hard to reverse (e.g. remove a wire format, change key_id semantics) need a clear rollback plan and, if possible, a feature flag or compatibility shim.

### Phasing the work

| Phase | Goal | Deliverable | Validation gate |
|-------|------|-------------|-----------------|
| **0** | Agree contract | `command_registry.json` (or YAML) in repo; doc in COMMAND_MATRIX_REFERENCE / COMMAND_ARCHITECTURE. No code behaviour change. | Registry parses; doc reviewed. |
| **1** | Single source for “list of commands” | Bridge (and optionally codegen) reads registry; STATE / LIST commands include ids and metadata. UI still uses names where it does today; registry is additive. | Existing UI and head behaviour unchanged; new fields visible in STATE. |
| **2** | UI and bridge use command_id | UI assignment storage and SET_* payloads use command_id; bridge encodes from registry. Keep name in payloads for logs. Old head still works (key_id unchanged). | Full operator flow works; add-one-command test: add row to registry, implement handler on head, no UI/bridge string changes. |
| **3** | Head dispatches by device_class | Head loads registry (or generated constants); dispatcher maps command_id → device_class → active implementation. BGC/Fuji/Canon remain implementations. | Same behaviour; new motor_controller implementation (e.g. VESC stub) can be wired without touching protocol. |
| **4** | Return path and distribution | Fast return (50 Hz) and slow return (state snapshot) defined and emitted; bridge or gateway can re-publish. FreeD adapter consumes fast return. | Dashboard sees live state; graphics engine receives 50 Hz stream; FreeD output verifiable with existing freeD tools. |

Phases 0–1 are low risk (additive). Phases 2–3 touch wire and head behaviour; keep a compatibility window (e.g. bridge sends both key_id and command_id; head accepts both) until all heads/firmware are updated. Phase 4 is additive (new UDP streams / adapter) and can be done in parallel once the canonical return schema exists.

### Tracking and ownership

- **Backlog:** One epic or roadmap item per phase; stories or tasks for “registry file,” “bridge reads registry,” “UI uses command_id in assignment,” “head dispatcher by device_class,” “fast return packet format,” “FreeD adapter,” etc. Dependencies between tasks are explicit (e.g. “FreeD adapter” blocks on “fast return packet format”).
- **Definition of done per phase:** Code merged; deploy steps documented; validation gate run (manual or automated); COMMAND_ARCHITECTURE / COMMAND_MATRIX_REFERENCE updated if the contract changed.
- **Owner:** One person or small team responsible for “contract and migration”; they review registry changes and any PR that touches protocol or dispatch. Reduces drift and duplicate approaches.

### Risk reduction and rollback

- **Feature flags / compatibility shims:** Where possible, ship new behaviour behind a flag or version check (e.g. head sends new telemetry only if controller requested version ≥ 2). Allows turning off new path without redeploying.
- **Rollback plan per phase:** “If Phase 2 breaks production: revert bridge + UI to send only key names; head still understands key_id.” Document the revert steps and the last known-good deploy (tag, commit, or artifact).
- **Testing:** Unit tests for encode/decode and for “registry matches SLOW_KEY_IDS”; integration test or script that sends a known command and asserts response. Run these in CI so refactors don’t silently break the contract.
- **Pi runtime parity:** Per the deploy-safety rule: after any change that affects the head or bridge, verify file hashes and service status on the device; don’t mark “done” until runtime matches repo and tests pass.

### Summary

Plan the migration in **phases** with clear deliverables and **validation gates**. Keep **backwards compatibility** until consumers are migrated; use the **registry as the single source of truth** from Phase 1. **Track** work in a backlog with owners and dependencies; **define done** as “merged + deployed + verified.” **Reduce risk** with flags, rollback plans, and automated checks. That way the migration is predictable, reviewable, and reversible.

---

## Bidirectional data: commands and returns

The same three layers apply in reverse: **return data** (head → network → consumers) mirrors the command path. Define both directions in one contract.

```
COMMAND PATH (already described)          RETURN PATH (head → consumers)
UX → IP → Head                             Head → IP → Consumers
  fast command: axes (yaw, pitch, roll…)     fast return: axis position feedback @ 50 Hz
  slow command: command_id + value           slow return: current slow state (snapshot or deltas)
```

- **Fast return** = continuous axis position feedback at a fixed rate (e.g. 50 Hz): pan, tilt, roll (and optionally position X/Y/Z), zoom, focus, iris. Same logical axes as fast command; direction and semantics are feedback, not command. Define in a **fast-return registry** (or same registry with `direction: command | return`) with **type** and **normalisation** (e.g. degrees for angles, mm for position, 0–4095 or 0–1 for zoom/focus). Source is device_class (motor_controller, camera, lens) so the head knows which subsystem supplies each axis.
- **Slow return** = current slow-command state: full snapshot of (command_id, value) for all slow commands, or deltas (only changed keys). Rate can be periodic (e.g. 1–5 Hz) or on-change. Reuse the **command registry**: slow return is “current value of each slow command_id”; same value types and normalisation, no second schema.

---

## Distribution of return data

Return streams must be available to **multiple consumers** on the network (e.g. engineering dashboards, broadcast graphics engines) without the head knowing who they are.

- **Single producer:** The head (or a telemetry gateway colocated with the bridge) is the single source of truth for fast and slow return streams. It does not care how many consumers there are.
- **Consumers:** Engineering support dashboards (e.g. browser UIs over WebSocket); broadcast graphics engine (requires all axis position at 50 Hz for real-time tracking). Others can subscribe without protocol or head changes.
- **Transport:**
  - **Fast return @ 50 Hz:** Use **UDP** (multicast or unicast to a list of endpoints). One packet per tick; any number of subscribers. Low latency; standard in broadcast; no back pressure from consumers.
  - **Slow return:** Same UDP stream at a lower rate, or a separate channel (e.g. WebSocket state push from bridge). Bridge can aggregate head telemetry and re-publish to browsers.
  - **Bridge as repeater:** Bridge subscribes to head UDP telemetry and re-exposes it over WebSocket (and/or REST) so engineering dashboards do not need raw UDP. Graphics engine can consume UDP directly for 50 Hz.
- **Scaling:** Adding consumers = adding subscribers to the same stream(s). No change to head or protocol. Optionally introduce a small pub/sub or UDP repeater process if the set of consumers is large or dynamic.

---

## FreeD and other output formats

**freeD** is an industry-standard protocol for camera tracking data: 29-byte UDP packet with Pitch/Yaw/Roll (degrees), Position X/Y/Z (mm), Zoom and Focus (typically 0–4095), plus identifier and checksum. Used by Unreal Engine, disguise, stYpe, Mo-Sys, Panasonic, and others. References: [freeD (Go implementation)](https://github.com/stvmyr/freeD), [Vinten/Radamec freeD manual](https://www.manualsdir.com/manuals/641433/vinten-radamec-free-d.html) (e.g. section A.3).

- **freeD as output format, not internal transport:** Internal “fast return” remains a single canonical stream (axis feedback at 50 Hz) with your own units and schema. **FreeD is one consumer format.**
- **FreeD adapter:** A small service or library that (1) subscribes to the 50 Hz fast-return stream (UDP from head or bridge), (2) maps your axes (pan, tilt, roll, zoom, focus, and position X/Y/Z if available) into the freeD struct (degrees, mm, 0–4095), (3) emits 29-byte freeD packets at 50 Hz to the graphics engine’s IP/port. This adapter can run on the bridge host or a dedicated “tracking gateway” that receives your UDP and outputs freeD.
- **Extensibility:** Other broadcast protocols (e.g. another tracking standard) can be added as further adapters that consume the same canonical fast return; no change to head or core protocol.

---

## Implementation practices for return paths

- **Single responsibility:** Head (or gateway) produces one canonical fast stream and one canonical slow stream. Adapters (FreeD, WebSocket for dashboards) only consume and transform; they do not define the schema.
- **Schema-driven return payload:** Define return axes and slow-state shape in the same registry (or a dedicated return section). Use it for codegen: encoders, FreeD mapper, dashboard API. Same “one table, many derivations” as for commands.
- **Clock and latency:** For 50 Hz delivery, consider stamping packets with a sequence number or timestamp so consumers can detect drops and, if needed, align to a common clock (e.g. for sync with video).
- **Failure modes:** Define what consumers see when the head is offline: no packets vs. last-known-state; whether slow return includes an “online” flag or heartbeat so dashboards and graphics can show connection status.
