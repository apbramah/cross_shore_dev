# Deploy to Pi – step-by-step runbook (run these on the Pi)

Use this after you've pushed from your PC. Run each block on the Pi in order.

**Important:** The kiosk does **not** serve the UI from the git repo. It serves from **`/opt/ui/`**. So after `git pull` you **must** copy files into `/opt/ui/` (and restart). Otherwise you will keep seeing the old UI no matter how many times you restart. Use the steps below or the one-command script.

---

## Full refresh: get the Pi running with latest (kiosk, UI, bridges)

Do this once after a push (or anytime you want the Pi to match the repo). Assumes the Pi already has the repo, `/opt/ui/`, `/opt/wsbridge/`, and systemd units installed (see “First-time Pi setup” below if not).

**On the Pi (SSH or console):**

```bash
# 1. Go to repo and pull latest
cd ~/Dev/cross_shore_dev
git fetch origin
git checkout mvp-lite-devzone
git pull --ff-only origin mvp-lite-devzone

# 2. Deploy UI and bridge into runtime, restart services
bash apps/controller/deploy-to-pi.sh
```

**What the script does:** Copies `mvp_ui_3.html`, `mvp_ui_3_layout.js`, and `position_map_standalone.html` to `/opt/ui/`, copies `mvp_slow_bridge.py` to `/opt/wsbridge/`, then restarts `wsbridge.service`, `kiosk.service`, and (if present) `controller.service` or `mvp_bridge_adc.service`. After that, the kiosk shows the latest UI and Position Display map assets, and the WebSocket bridge (and ADC bridge, if run from repo) use the latest code.

**3. Ensure services start on boot (if not already):**

```bash
sudo systemctl enable wsbridge.service
sudo systemctl enable kiosk.service
# If you use a controller/ADC bridge service:
sudo systemctl enable controller.service
# or: sudo systemctl enable mvp_bridge_adc.service
```

**4. Verify:**

```bash
systemctl is-active wsbridge.service kiosk.service
sha256sum ~/Dev/cross_shore_dev/apps/controller/mvp_ui_3.html /opt/ui/mvp_ui_3.html
```

Both hashes should match; both services should print `active`.

---

## First-time Pi setup (if the Pi is not yet configured)

- **Repo:** Clone into `~/Dev/cross_shore_dev` (e.g. `git clone <url> ~/Dev/cross_shore_dev`).
- **Runtime dirs:** Create and own `/opt/ui` and `/opt/wsbridge` (e.g. `sudo mkdir -p /opt/ui /opt/wsbridge`, `sudo chown admin:admin /opt/ui /opt/wsbridge` or keep root-owned and install with `sudo install`).
- **Kiosk entry point:** Put `boot.html` in `/opt/ui/` that redirects to `mvp_ui_3.html` (see Step 3b below). Never delete `boot.html` (e.g. avoid `rsync --delete` into `/opt/ui/`).
- **Systemd units:** Install the service files for kiosk, wsbridge, and (if used) controller/ADC bridge from `Pi5 Setup/` (e.g. into `/etc/systemd/system/`), then `sudo systemctl daemon-reload`, `enable` and `start` the services.
- **Daemon wrappers (if used):** `/usr/local/bin/wsbridge_daemon` and `/usr/local/bin/controller_daemon` (and `/usr/local/bin/kiosk-browser`) must point at the correct Python/script paths and profile dirs (e.g. controller runs `mvp_bridge_adc.py` from repo with `--profile-dir /opt/wsbridge`).

After that, use the “Full refresh” steps above for every update.

---

## One-command deploy (after pull)

From the repo root on the Pi:

```bash
cd ~/Dev/cross_shore_dev
bash apps/controller/deploy-to-pi.sh
```

This copies UI and bridge from repo → `/opt/ui/` and `/opt/wsbridge/`, then restarts wsbridge and kiosk.

---

## Step 3a – Go to repo and pull latest

**What this does:** Puts you in the Pi’s clone of the repo and updates it from the remote so the Pi has the same commits as your PC.

```bash
cd ~/Dev/cross_shore_dev
git fetch origin
git checkout mvp-lite-devzone
git pull --ff-only origin mvp-lite-devzone
```

- `cd ~/Dev/cross_shore_dev` – repo on Pi is here (not `/opt/...`).
- `git fetch origin` – gets latest refs from GitHub/origin.
- `git checkout mvp-lite-devzone` – use the same branch you pushed.
- `git pull --ff-only` – fast-forward only; fails if history diverged (safe).

---

## Step 3b – Deploy UI to runtime

**What this does:** Copies the UI file from the repo into `/opt/ui/` where the kiosk serves it. We use `install` (not rsync --delete) so we never remove `boot.html`.

```bash
sudo install -m 644 apps/controller/mvp_ui_3.html /opt/ui/
sudo install -m 644 apps/controller/position_map_standalone.html /opt/ui/ 2>/dev/null || true
```

- `install -m 644` – copy file and set permissions (readable by kiosk).
- Target `/opt/ui/` – kiosk loads `boot.html` from here, which redirects to `mvp_ui_3.html`.

**If you ever see "file could not be accessed":** Recreate the trampoline:

```bash
echo '5:requestAnimationFrame(()=>requestAnimationFrame(()=>location.replace("file:///opt/ui/mvp_ui_3.html")));' | sudo tee /opt/ui/boot.html >/dev/null
```

---

## Step 3c – Deploy bridge (if you changed Python)

**What this does:** Copies the slow-bridge script to `/opt/wsbridge/` so the wsbridge service runs the new code. Only needed when `mvp_slow_bridge.py` (or other bridge files) change.

This run: we only changed UI and docs, so **you can skip this** unless you also changed bridge code. When you do change the bridge:

```bash
sudo install -m 644 apps/controller/mvp_slow_bridge.py /opt/wsbridge/
```

---

## Step 3d – Restart services

**What this does:** Makes the running services use the new files. Restart only what you deployed.

```bash
# UI changed → restart wsbridge so it serves state to the new UI; reload browser or restart kiosk if UI still stale
sudo systemctl restart wsbridge.service
```

If the on-screen UI doesn’t update after a refresh, restart the kiosk:

```bash
sudo systemctl restart kiosk.service
```

---

## Step 4 – Verify

**What this does:** Confirms the file on disk is the one from the repo and that services are up.

**4a – Hash check (repo vs runtime)**

Repo and runtime file should be identical:

```bash
sha256sum ~/Dev/cross_shore_dev/apps/controller/mvp_ui_3.html /opt/ui/mvp_ui_3.html
sha256sum ~/Dev/cross_shore_dev/apps/controller/position_map_standalone.html /opt/ui/position_map_standalone.html
```

You should see matching pairs (repo vs runtime) for each file. If they differ, re-run deploy step 3b.

If Position Display opens but the map area is blank: verify `position_map_standalone.html` hash first; if it matches runtime, treat it as likely tile-network/CDN reachability on Pi and use the on-screen tile status diagnostics.

**4b – Services running**

```bash
systemctl is-active wsbridge.service
systemctl is-active kiosk.service
```

Both should print `active`.

**4d – Ensure services start after reboot**

The service runs from **/opt/wsbridge/** (not the repo). After you deploy with `install`, that file is what runs. To make sure the same service (and thus the deployed file) starts on boot:

```bash
sudo systemctl enable wsbridge.service
sudo systemctl enable kiosk.service
```

Then after a reboot, `wsbridge.service` will start and load `/opt/wsbridge/mvp_slow_bridge.py`. If you don’t run `enable`, a reboot may leave the service stopped until you start it manually.

**4c – Optional: prove new code is there**

```bash
grep -n "profileEditorOpen" /opt/ui/mvp_ui_3.html
```

You should see a line number and `profileEditorOpen`. If not, the wrong file is in `/opt/ui/`.

---

## Summary

| Step | Where   | Action |
|------|---------|--------|
| 1–2  | PC      | Commit, push (done) |
| 3a   | Pi      | `cd` repo, fetch, checkout, pull |
| 3b   | Pi      | `sudo install` UI to `/opt/ui/` |
| 3c   | Pi      | (Optional) `sudo install` bridge to `/opt/wsbridge/` |
| 3d   | Pi      | `sudo systemctl restart wsbridge.service` (and kiosk if needed) |
| 4    | Pi      | `sha256sum`, `systemctl is-active`, optional `grep` |

Only then consider the deploy done.

---

## Current working status (2026-03-15)

- Head IP programming flow is working with transaction-mode push and runtime verification.
- Position map runtime is working with `position_map_standalone.html` deployed to `/opt/ui/`.

### Additional verify probes (head IP programming)

```bash
python - <<'PY'
from pathlib import Path
checks = {
  "/opt/wsbridge/mvp_protocol.py": ["SLOW_KEY_NETCFG_ENTER", "SLOW_KEY_NETCFG_EXIT"],
  "/opt/wsbridge/mvp_slow_bridge.py": ["PUSH_HEAD_NETWORK_CONFIG", "head_ack_inferred", "Ignore duplicate/late APPLY ACKs"],
  "/opt/ui/mvp_ui_3.html": ["Push To Head", "Match Console LAN Subnet"],
}
for p, toks in checks.items():
    txt = Path(p).read_text(encoding="utf-8", errors="ignore")
    miss = [t for t in toks if t not in txt]
    print(p, "OK" if not miss else f"MISSING {miss}")
PY
```
