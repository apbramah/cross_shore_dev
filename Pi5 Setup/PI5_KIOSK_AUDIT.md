# Pi5 Kiosk Assets Audit

Maps current Pi5 setup scripts and services and identifies deltas for ADC + slow dual-service kiosk mode per the Pi5 kiosk and lockdown plan.

## Current repo assets (mapping)

| Asset | Repo path | Installed / used as |
|-------|-----------|----------------------|
| Installer | `Pi5 Setup/install_pi5_setup.sh` | Run once on Pi from repo root |
| Boot patch | `Pi5 Setup/scripts/pi5_boot_patch.sh` | Called by installer; patches cmdline.txt + config.txt |
| ADC bridge unit | `Pi5 Setup/systemd/mvp_bridge_adc.service` | `/etc/systemd/system/`, enabled |
| Slow bridge unit | `Pi5 Setup/systemd/mvp_slow_bridge.service` | `/etc/systemd/system/`, enabled |
| Legacy bridge unit | `Pi5 Setup/systemd/mvp_bridge.service` | `/etc/systemd/system/`, disabled |
| Cage service | `Pi5 Setup/systemd/hydravision-cage.service` | `/etc/systemd/system/`, enabled when KIOSK_MODE=cage |
| Kiosk launcher (desktop) | `Pi5 Setup/scripts/hydravision-kiosk-launch.sh` | `/usr/local/bin/`, invoked by labwc autostart |
| Cage launcher | `Pi5 Setup/scripts/hydravision-cage-launch.sh` | `/usr/local/bin/`, ExecStart of hydravision-cage.service |
| labwc autostart | `Pi5 Setup/labwc/autostart` | `~/.config/labwc/autostart` |
| Kiosk desktop entry | `Pi5 Setup/autostart/hydravision-kiosk.desktop` | `~/.config/autostart/hydravision-kiosk.desktop` (desktop mode only) |
| Labwc keybinds | `Pi5 Setup/scripts/labwc_configure_keybinds.py` | Patches `~/.config/labwc/rc.xml` (unlock + blocked keys) |
| Admin unlock | `Pi5 Setup/scripts/hydravision-admin-unlock.sh` | `/usr/local/bin/` |
| SSH hardening | `Pi5 Setup/ssh/99-hydravision-kiosk.conf` | `/etc/ssh/sshd_config.d/` |
| Logind lockdown | `Pi5 Setup/logind/99-hydravision-kiosk.conf` | `/etc/systemd/logind.conf.d/` |
| Firefox policy | `Pi5 Setup/firefox/policies.json` | `/etc/firefox/policies/` |
| Kiosk env template | `Pi5 Setup/config/hydravision-kiosk.env` | `/etc/default/hydravision-kiosk` (if missing) |
| Validate script | `Pi5 Setup/scripts/hydravision-validate.sh` | `/usr/local/bin/` |
| Remove lockdown | `Pi5 Setup/scripts/hydravision-remove-lockdown.sh` | `/usr/local/bin/` |
| Disable cage | `Pi5 Setup/scripts/hydravision-disable-cage.sh` | `/usr/local/bin/` |
| Plymouth theme | `Pi5 Setup/plymouth/*` | `/usr/share/plymouth/themes/hydravision/` |

## Dual-service (ADC + slow) status

- **mvp_bridge_adc.service**: WS :8765, `WorkingDirectory=.../apps/controller`, `ExecStart=.../mvp_bridge_adc.py -p /dev/ttyACM0`, `After=network-online.target`, `Restart=on-failure`. **Already correct.**
- **mvp_slow_bridge.service**: WS :8766, same WorkingDirectory, `ExecStart=.../mvp_slow_bridge.py`, same After/Restart. **Already correct.**
- **Installer**: Copies both units, `systemctl enable --now` both, `systemctl disable --now mvp_bridge.service`. **No delta.**

## Deltas identified (to address in implementation)

1. **Cage launcher**  
   - Only waits for slow port (8766).  
   - **Delta:** Wait for both fast (8765) and slow (8766) before starting browser; align default UI URL with plan (`mvp_ui.html`).

2. **Validation script**  
   - Checks port 8765 only when legacy `mvp_bridge.service` is active.  
   - **Delta:** Check port 8765 when `mvp_bridge_adc.service` is active.

3. **Boot/recovery**  
   - **Delta:** Document single-user/TTY recovery fallback for locked-down systems.

4. **Lockdown**  
   - Keybinds already block run dialog and common escapes.  
   - **Delta:** Document “no terminal/file-manager” behavior and any VT-switch blocking; add udev rule for controller/serial if needed for stability.

5. **Validation runbook**  
   - **Delta:** Add formal acceptance checklist and rollback procedure (see prepare-validation-runbook).

All other plan items (SSH key-only, hidden unlock, Plymouth, Firefox policy, getty mask, logind) are already implemented; implementation steps will only refine or document them.
