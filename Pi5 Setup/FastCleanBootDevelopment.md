# Fast Clean Boot Development Report

## Executive Summary

- Final approach shifted to a dedicated **Bookworm Lite appliance profile** with `cage` and local UI, not desktop/Plymouth-script dependencies.
- Boot pipeline is now deterministic and reproducible via installer + canonical systemd units in `Pi5 Setup/bookworm-lite-appliance/`.
- Major blockers resolved: service-order delays, tty/cage conflicts, false validation checks, and browser startup artifacts.
- **Chromium** was selected as practical default for best observed controller mapping and kiosk visual behavior on tested hardware.
- Result is a fast, stable, appliance-style boot with significantly reduced artifacts and a documented rollback/testing process.

## Objective

Deliver a reproducible Raspberry Pi 5 appliance boot that reaches fullscreen kiosk UI quickly, with minimal visual artifacts, deterministic startup ordering, and reliable controller input behavior.

---

## Requirements (Target State)

- Appliance behavior (not desktop):
  - no desktop shell exposure
  - no interactive login prompt for operator flow
  - single-app compositor path (`cage`)
- Fast startup:
  - deterministic systemd service flow
  - no network-online blocking of UI startup
- Visual quality:
  - suppress early boot text/cursor as much as practical
  - minimize black/purple/white transition artifacts
- Functional reliability:
  - controller + bridge services auto-start
  - kiosk UI auto-launches
  - orientation persistent at 90 deg
- Reproducibility:
  - repo-first installer
  - repeatable install path for new Pi units

---

## Experimentation Timeline (What Was Tried)

## 1) Original Pi5 setup path with Plymouth/script themes

- Attempted script-based Hydra Plymouth branding.
- Hit OS/package incompatibility (`plymouth-plugin-script` unavailable on target image).
- Result: fallback/default boot visuals and inconsistent handoff behavior.

Outcome:
- Inconsistent visual sequence; not acceptable for appliance UX.

## 2) Stabilization of existing stack

- Fixed multiple blockers:
  - cage/getty contention
  - validation false check on port `8765` (ADC path is UDP, not TCP listener)
  - namespace handling in `labwc` keybind patching
  - unnecessary waits causing black boot gap
- Improved service reliability and reduced boot delay.

Outcome:
- System became functional and reproducible, but still had visual artifacts and transitional flashes.

## 3) Architectural pivot to Bookworm Lite appliance profile

- Introduced dedicated profile under:
  - `Pi5 Setup/bookworm-lite-appliance/`
- New installer + canonical systemd units:
  - `controller.service`
  - `wsbridge.service`
  - `kiosk.service`
  - `boot-splash-lock.service`
- Removed Plymouth dependency in this profile.
- Moved to `multi-user.target`, no display-manager dependency.

Outcome:
- Markedly better startup consistency and faster time to UI.

## 4) Boot polish tuning phase

- Added stronger cmdline suppression for early console noise.
- Moved visible console path off `tty1`.
- Tightened first-paint behavior with controlled browser startup settings.
- Decoupled kiosk from hard bridge requirement to reduce startup serialization.
- Added black `boot.html` trampoline before main UI load.
- Added browser selection and rollback helper.

Outcome:
- Fast boot with acceptable quality, major regressions removed, controller compatibility validated.

---

## Final Successful Path (Current Baseline)

Profile:
- `Pi5 Setup/bookworm-lite-appliance/install.sh`

Service model:
- `multi-user.target`
- `controller.service` + `wsbridge.service` + `kiosk.service`
- `kiosk.service` runs `cage -- /usr/local/bin/kiosk-browser`
- `kiosk.service` uses soft dependency model (`Wants=wsbridge.service`) to avoid unnecessary blocking

UI launch:
- browser opens `file:///opt/ui/boot.html` (black trampoline)
- then redirects to `file:///opt/ui/mvp_ui_3.html`

Orientation:
- persistent rotation via wrapper configuration (`DSI-2 -> transform 90`)

Browser handling:
- selector utility supports A/B and rollback:
  - `/usr/local/bin/hydravision-kiosk-browser-select firefox`
  - `/usr/local/bin/hydravision-kiosk-browser-select chromium`

Observed operational result:
- fast and stable boot to UI
- substantially reduced early boot text/artifacts
- controller behavior validated (Chromium path preferred on tested unit)

---

## Warnings (Major Gotchas)

- **Plymouth script plugin availability is not guaranteed** on target OS images; avoid architecture that depends on it unless you own package/toolchain.
- **Do not gate kiosk startup on network-online** for local file UI + localhost bridge architecture; it adds latency and visual dead time.
- **ADC bridge fast path is UDP, not TCP/WebSocket**; TCP port checks for `8765` create false failures and bad decisions.
- **TTY/getty/cage interactions can hang startup** if misconfigured; `tty1` ownership must be explicit and consistent.
- **Cage CLI flags may vary by build**; options like `-b` can break on some versions—test before adopting as default.
- **Root-run installers can alter file ownership** and later block pull/merge flow; normalize ownership when debugging update issues.
- **Local systemd override damage can block kiosk startup**; zero-byte unit files or masked unit symlinks in `/etc/systemd/system/` override canonical installed units.
- **Corrupted local git objects can break deployment**; always run `git fsck --full` on target Pi before `fetch/reset/install`, and reclone if corruption is detected.

---

## Browser Decision Matrix

| Criteria | Firefox ESR | Chromium |
|---|---|---|
| First-frame visual cleanliness | Medium (can still flash transient frame) | Better on tested Pi |
| Kiosk chrome suppression consistency | Medium | High |
| Controller/encoder/button behavior on this project | Working but less ideal | Best observed |
| Wayland kiosk behavior on tested unit | Good | Better |
| Policy management options | Strong enterprise policy support | Strong flags-driven control |
| Recommended default for this project baseline | Fallback/secondary | **Primary** |

### Decision

- Selected operational default: **Chromium** (for tested hardware profile).
- Keep Firefox available as rollback path for compatibility testing.

### Action Rules

- If controller mapping regresses on Firefox -> switch to Chromium immediately.
- If Chromium exhibits new instability -> rollback to Firefox via selector, capture logs, and retest.
- Preserve both paths in installer to avoid field dead-ends.

---

## Reproducibility / Freeze Notes

- Use repo baseline documented in:
  - `Pi5 Setup/APPLIANCE_FREEZE_CHECKLIST.md`
- For new devices:
  - clean clone
  - hard reset to target commit
  - run appliance installer
  - validate service state and visual sequence

This process is now repeatable and tuned for fast appliance-style boot with minimal transition artifacts.
