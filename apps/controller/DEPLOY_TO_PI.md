# Deploy to Pi for test – best process

Use this every time you push changes for testing on the Pi. It avoids drift, wrong paths, and broken runtime.

---

## 1. On your dev PC (before pushing)

- Commit and push from the repo that has your changes:
  ```bash
  git add -A
  git status
  git commit -m "Your message"
  git push origin <branch>
  ```
- Note which files you changed (especially under `apps/controller/` and any Python under `apps/` or repo root that runs on Pi).

---

## 2. On the Pi – pull and deploy

**Paths (do not guess):**

- Repo on Pi: `~/Dev/cross_shore_dev` (or `$HOME/Dev/cross_shore_dev`).
- UI runtime: `/opt/ui/` (kiosk loads `boot.html` → `mvp_ui_3.html`).
- Bridge runtime: `/opt/wsbridge/` (wsbridge + slow bridge scripts).

**Commands (run from Pi, adjust branch if needed):**

```bash
cd ~/Dev/cross_shore_dev
git fetch origin
git checkout <branch>   # e.g. mvp-lite-devzone
git pull --ff-only origin <branch>
```

**Deploy only what changed – do not use `rsync --delete`** (it can remove `boot.html` and break the kiosk):

```bash
# UI: copy controller UI/assets into runtime (keeps boot.html intact)
sudo install -m 644 apps/controller/mvp_ui_3.html /opt/ui/
sudo install -m 644 apps/controller/mvp_ui_3_layout.js /opt/ui/ 2>/dev/null || true

# If boot.html is missing, restore it (kiosk entry point)
echo '5:requestAnimationFrame(()=>requestAnimationFrame(()=>location.replace("file:///opt/ui/mvp_ui_3.html")));' | sudo tee /opt/ui/boot.html >/dev/null

# Bridge (slow bridge + any scripts used by wsbridge)
sudo install -m 644 apps/controller/mvp_slow_bridge.py /opt/wsbridge/
# Add other files if you changed them, e.g.:
# sudo install -m 644 path/to/file /opt/wsbridge/
```

**Restart only the services that use those files:**

```bash
sudo systemctl restart wsbridge.service
# If kiosk serves static files from /opt/ui and you only changed HTML/JS, a browser refresh is often enough; if not:
# sudo systemctl restart kiosk.service
```

---

## 3. Verify (required)

Run these on the Pi so we don’t claim “done” without proof:

```bash
# Hashes: repo file and runtime file must match for changed files
sha256sum ~/Dev/cross_shore_dev/apps/controller/mvp_ui_3.html /opt/ui/mvp_ui_3.html

# Services that must be running
systemctl is-active wsbridge.service
systemctl is-active kiosk.service

# Optional: confirm a known string from your change is in the runtime file
grep -n "profileEditorOpen" /opt/ui/mvp_ui_3.html
```

If hashes differ or a service is inactive, fix before saying “deployed and tested”.

---

## 4. If something is wrong

- **“File could not be accessed” in browser**  
  Kiosk loads `file:///opt/ui/boot.html`. If `boot.html` is missing, recreate it (see step 2 above). Never use `rsync --delete` into `/opt/ui/`.

- **UI on Pi doesn’t match repo**  
  Don’t overwrite the repo from runtime unless you intend to keep Pi’s version. To make Pi match repo: pull on Pi, then re-run the `sudo install` deploy steps and restart services.

- **Wrong path / wrong service**  
  Repo path on Pi is `~/Dev/cross_shore_dev`. Services are `wsbridge.service` and `kiosk.service` (not `mvp-bridge.service`). Check with:
  ```bash
  systemctl list-units --type=service --state=running | grep -E 'kiosk|wsbridge|controller'
  ```

---

## Summary

1. **PC:** Commit and push; note changed files.  
2. **Pi:** Pull in `~/Dev/cross_shore_dev`; deploy with `sudo install -m 644` (no `rsync --delete`); ensure `boot.html` exists; restart `wsbridge` (and kiosk if needed).  
3. **Verify:** Hash match, `systemctl is-active`, optional grep.  
4. Only then consider the deploy “done”.

This aligns with `.cursor/rules/pi-runtime-deploy-safety.mdc`.
