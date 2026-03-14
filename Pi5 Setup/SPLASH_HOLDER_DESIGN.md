# HydraVision Pi5 Rebuild Plan (Authoritative Restart)

## 1) Mission

Deliver a customer-safe Pi5 kiosk that boots fast and clean, auto-starts required services, and shows only the operator UI.

### Non-negotiable requirement
- System-level HydraVision splash from boot/handoff sequence.
- No blank desktop exposure to customer.
- No browser "fake splash page" as final solution.
- Fast and slow bridges auto-run.
- Fullscreen UI with touch + game controller ready.
- Locked down operator environment.
- Hidden admin backdoor path remains available.

---

## 2) Explicit lessons learned (do not repeat)

1. **OS mismatch was the major risk**
   - On Debian 13 / trixie, `plymouth-plugin-script` is unavailable and script-based Plymouth behavior differs.
   - This created unpredictable splash behavior and extra boot artifacts (dots/cursor/black gaps).

2. **Do not do ad-hoc Pi-only fixes first**
   - All changes must be repo-first, then deployed atomically.
   - CRLF line endings in deployed shell scripts caused runtime failures (`bash\r` style issues).

3. **Do not rely on fixed-time splash to hide all transitions**
   - Fixed sleep causes splash -> black gap -> browser -> UI.
   - Must move to readiness/handoff logic where possible.

4. **TTY/cage conflict must be controlled**
   - `getty@tty1` can fight with `hydravision-cage.service`, causing restart loops.
   - Service setup must prevent tty contention.

5. **Rotation on DSI panel is compositor-level in this stack**
   - `display_rotate` and `video=...rotate=` may be ignored on DSI/rp1 DRM path.
   - `wlr-randr --output DSI-2 --transform 90` is the proven working transform on this hardware.

6. **Never deviate from requirement without explicit sign-off**
   - Any fallback or compromise must be stated and approved first.

---

## 3) OS recommendation (must decide up front)

### Recommended production baseline
- **Raspberry Pi OS (64-bit) Bookworm Desktop** via Raspberry Pi Imager.

Why:
- Current kiosk scripts and expected package behavior align better with Bookworm.
- Lower risk for Plymouth + kiosk integration than trixie.

### If staying on trixie
- Treat as compatibility mode with known limitations:
  - script-based Plymouth theme support gap,
  - possible unavoidable early boot artifacts.
- Must document that full visual polish may be constrained until Bookworm.

---

## 4) Raspberry Pi Imager instructions (authoritative)

1. Open Raspberry Pi Imager.
2. Device: **Raspberry Pi 5**.
3. OS: **Raspberry Pi OS (64-bit)** (Bookworm Desktop).
4. Storage: target SSD/microSD.
5. Edit settings:
   - Hostname: per device (e.g. `HydraVision-0001`)
   - Username: `admin`
   - Strong password
   - Locale/timezone/keyboard correct
   - Enable SSH + **public key auth only**
6. Write + verify.
7. First boot:
   - login once as `admin`
   - run:
     ```bash
     sudo apt update && sudo apt full-upgrade -y
     sudo reboot
     ```
8. Confirm baseline:
   - Wayland desktop starts normally
   - Touch + controller enumerate under `/dev/input/*`
9. Create baseline backup image (recommended) before kiosk automation.

---

## 5) Required architecture (agreed)

Boot/runtime sequence target:

1. Firmware/bootloader
2. Kernel cmdline quiet/splash flags
3. Plymouth HydraVision (as supported by OS)
4. systemd starts:
   - `mvp_bridge_adc.service`
   - `mvp_slow_bridge.service`
5. Single-app kiosk compositor path (`hydravision-cage.service`)
6. Splash-holder process
7. Handoff to fullscreen Firefox UI
8. No operator-visible desktop shell

### Important
- Final state must avoid browser-window-first visual.
- Splash-holder should remain visible until controlled handoff to UI render path.

---

## 6) Security/lockdown requirements

- Operator cannot access repo/files/terminal.
- Escape shortcuts blocked in kiosk session.
- SSH hardened: key-only auth.
- Hidden local unlock remains:
  - hotkey trigger
  - password prompt
  - audit logging to journald.

---

## 7) Rotation policy (agreed)

- Do **not** force rotation in boot firmware config by default.
- Use compositor/output transform where required.
- Proven live command on this panel:
  ```bash
  wlr-randr --output DSI-2 --transform 90
  ```
- Persist transform through kiosk startup script/service logic.
- Any further rotation automation changes require explicit sign-off.

---

## 8) Engineering process rules for the new agent

1. Repo-first only: change in repo, then deploy.
2. Single-step execution with output verification gates.
3. Every recommendation must be labeled:
   - Verified fact
   - Assumption
4. No "final fix" language unless acceptance tests pass.
5. Before each risky change:
   - provide rollback command.
6. Do not request broad testing loops; ask one precise check at a time.
7. No requirement drift without user approval.

---

## 9) Acceptance criteria (must all pass)

1. **Visual boot path**
   - Operator sees only acceptable boot visuals and HydraVision splash path.
   - No desktop flash.
   - No prolonged black/cursor gap before UI.

2. **Function**
   - Bridges active and stable.
   - UI responsive.
   - Touch + controller operational.

3. **Security**
   - No operator repo/file access.
   - SSH key-only works.
   - Hidden unlock works and is logged.

4. **Stability**
   - 10 cold boots in a row pass all above checks.

---

## 10) Known technical debt from prior attempt

- Mixed desktop/cage/autostart artifacts caused instability.
- CRLF shell scripts deployed to Pi caused runtime failures.
- TTY conflicts (`getty@tty1`) caused cage restart loops.
- Current trixie behavior may still show early firmware dots/cursor artifacts.
- If strict visual requirement cannot be met on trixie, rebase to Bookworm.

---

## 11) First tasks for new agent (ordered)

1. Audit current Pi state and classify: clean baseline vs contaminated.
2. Enforce clean baseline (desktop stable + SSH reachable).
3. Align local repo + branch + deployed files exactly.
4. Reapply kiosk stack from installer in controlled mode.
5. Verify cage + bridges + splash-holder path with log gates.
6. Implement/persist DSI transform (`DSI-2 -> transform 90`) in kiosk path.
7. Run full acceptance checklist and report pass/fail with evidence.

---

## 12) Command discipline format (mandatory)

For each interaction, new agent must use:

1. Verified facts
2. Unknowns
3. One command only
4. Expected result
5. Next command contingent on result

No multi-branch command dumps unless explicitly requested.
