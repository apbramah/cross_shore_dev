# HydraVision Appliance Freeze Checklist

Baseline checklist for reproducing the validated Bookworm Lite appliance setup on additional Pi units.

## Baseline Revision

- **Branch:** `mvp-lite`
- **Commit:** `90f0623` (minimum browser-selector baseline)
- Includes: appliance profile, Chromium/Firefox browser selector, rollback helper.

## Fresh Pi Prep

1. Flash Raspberry Pi OS Bookworm Lite.
2. Install git:
   ```bash
   sudo apt update && sudo apt install -y git
   ```
3. Clone repo to home:
   ```bash
   cd "$HOME"
   git clone https://github.com/apbramah/cross_shore_dev.git
   ```

## Force Clean Repo State

```bash
cd "$HOME/cross_shore_dev"
git fetch origin
git checkout mvp-lite
git reset --hard origin/mvp-lite
```

## Install Appliance Profile

```bash
sudo bash "Pi5 Setup/bookworm-lite-appliance/install.sh"
sudo reboot
```

## Set Chromium Default (if required)

```bash
sudo /usr/local/bin/hydravision-kiosk-browser-select chromium
```

## Verify Services

```bash
systemctl status controller.service wsbridge.service kiosk.service --no-pager -l
systemd-analyze critical-chain kiosk.service
```

## Verify Persistent Appliance Config

```bash
cat /etc/default/hydravision-appliance
```

Expected values include:
- `HYDRAVISION_KIOSK_BROWSER=chromium`
- `HYDRAVISION_ROTATION_OUTPUT=DSI-2`
- `HYDRAVISION_ROTATION_TRANSFORM=90`
- `HYDRAVISION_ETH_ENABLE=1`
- `HYDRAVISION_ETH_SUBNET_BASE=192.168.60`

## Verify Static LAN Assignment

For `HydraVision-0003`, expected ethernet is `192.168.60.103/24`:

```bash
ip -4 addr show eth0
ip route
nmcli device status
```

Expected route behavior:
- eth0 default route preferred (lower metric)
- Wi-Fi remains connected as fallback SSH path

## Visual Acceptance (minimum)

Perform 3 hard reboot cycles and confirm:
- no early boot text
- black hold is within acceptable range
- brief browser flash is known/acceptable
- UI loads reliably
- controller/encoder/button mapping is correct

## Browser Rollback Commands

Switch to Firefox:
```bash
sudo /usr/local/bin/hydravision-kiosk-browser-select firefox
```

Switch back to Chromium:
```bash
sudo /usr/local/bin/hydravision-kiosk-browser-select chromium
```

## Known Avoidance

Do **not** apply cage `-b 000000` on this unit/build; this flag was observed to break startup in this environment.
