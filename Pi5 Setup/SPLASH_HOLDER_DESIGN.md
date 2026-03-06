# HydraVision Rebuild Plan (Clean Restart)

This plan replaces all ad-hoc steps with a controlled rebuild path:

1. return Pi to a known clean baseline,
2. deploy from repo only,
3. enforce the agreed requirement:
   - system-level HydraVision splash (not browser),
   - no customer file access,
   - fast + clean boot to UI.

## Non-negotiable requirement

- Splash must be system-level and persist from boot until UI handoff.
- Browser splash pages are not acceptable as the final solution.
- No rotation changes will be made by boot automation unless explicitly approved.

## Recommended OS baseline

### Primary recommendation
- **Raspberry Pi OS (64-bit) Bookworm Desktop** via Raspberry Pi Imager.
- Rationale: current kiosk scripts and package assumptions were written against Bookworm behavior.

### If staying on Debian 13 / trixie
- Supported only with explicit compatibility checks.
- Must validate every package and service assumption before deployment.

## Phase 0 - Freeze changes

- Stop applying direct one-off shell edits on Pi.
- All changes must originate in repo (`Pi5 Setup/*`) and be deployed as a set.

## Phase 1 - Clean Pi baseline (no rollback image required)

Target state after cleanup:
- predictable desktop boot,
- no custom autostart fragments from previous trials,
- no stale cage wrappers.

Baseline checks:
- default target is `graphical.target`,
- `hydravision-cage.service` disabled/inactive,
- desktop manager active,
- bridges can still be started manually for testing.

Artifacts to remove/neutralize:
- custom labwc autostarts not in repo,
- custom user scripts under `~/.local/bin` used in experiments,
- stale desktop autostart entries,
- stale logs used for prior debugging.

## Phase 2 - Repo-first implementation set

All files below are maintained in repo and installed by installer:

- `Pi5 Setup/scripts/hydravision-cage-launch.sh` (outer launcher)
- `Pi5 Setup/scripts/hydravision-splash-then-browser.sh` (inner splash->browser handoff)
- `Pi5 Setup/systemd/hydravision-cage.service`
- `Pi5 Setup/install_pi5_setup.sh`
- `Pi5 Setup/config/hydravision-kiosk.env`
- splash assets from `Pi5 Setup/plymouth/hydravision_boot.svg`

### Required behavior

1. outer launcher waits for bridge readiness (`8765`, `8766`),
2. starts cage with inner launcher,
3. inner launcher starts splash-holder process (Wayland image app),
4. holds splash for configured minimum (`HYDRAVISION_SPLASH_HOLD_SECONDS`),
5. hands off to Firefox kiosk UI.

## Phase 3 - Splash-holder strategy

### Interim (acceptable for first test pass)
- use `imv` fullscreen as splash-holder process under cage.
- kill splash-holder after hold, then exec Firefox.

### Final (production)
- dedicated minimal Wayland splash-holder binary:
  - shows image fullscreen,
  - exits on explicit ready signal (file/socket),
  - cleaner transition than killing an image viewer.

## Phase 4 - Rotation policy (agreed)

- Boot scripts do **not** enforce rotation by default.
- Rotation source of truth is the display/session setting unless explicitly approved.
- If rotation needs automation later, add a single explicit variable and apply only with sign-off.

## Phase 5 - Security and access

- Keep dual bridge services enabled (`mvp_bridge_adc`, `mvp_slow_bridge`).
- Keep kiosk lockdown + key-only SSH path.
- Keep hidden unlock flow (`Ctrl+Alt+Shift+U`) with journald audit.

## Phase 6 - Acceptance gates (must all pass)

1. **Visual sequence gate**  
   power on -> HydraVision splash -> UI  
   no desktop flash, no blank browser window before UI.

2. **Function gate**  
   both bridges active, UI control path works, touch + gamepad live.

3. **Security gate**  
   no terminal/file manager path for operator user, unlock + SSH admin path works.

4. **Stability gate**  
   10 consecutive cold boots with no regressions.

## Execution model from this point

- One command block at a time.
- Each step has expected output and pass/fail decision.
- No next change until current gate passes.
