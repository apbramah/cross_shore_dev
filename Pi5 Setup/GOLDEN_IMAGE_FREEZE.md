# Golden Image Freeze Checklist

One-page freeze checklist for cloning validated HydraVision Pi5 appliance builds.

## Freeze baseline (on validated unit)

Run:

```bash
cd /home/admin/Dev/cross_shore_dev
git rev-parse --short HEAD
hostnamectl --static
grep '^HYDRAVISION_KIOSK_BROWSER=' /etc/default/hydravision-appliance
systemctl is-active controller.service wsbridge.service kiosk.service
```

Record:

- branch: `mvp-lite`
- commit: expected `ce174fd` (or approved successor)
- hostname: validated unit ID
- browser default: `chromium`

## Health snapshot before imaging

Run:

```bash
git fsck --full
systemctl status controller.service wsbridge.service kiosk.service --no-pager -l
ip -4 addr show eth0
ip -4 addr show wlan0
```

Pass criteria:

- `git fsck --full` reports no corruption
- all 3 services are active
- ethernet is on expected static subnet (`192.168.60.x`)
- wifi remains available for SSH fallback

## Reboot acceptance (3 cycles minimum)

Perform three cold boots. On each cycle confirm:

- no unexpected boot-text regression
- kiosk reaches UI reliably
- controller and bridge behavior are functional

## Create golden image

After passing all checks:

- create full SD/SSD image backup of this unit
- label image with:
  - date
  - branch + commit
  - hostname used during validation
  - tester initials

## Provisioning additional units (`0004`, `0005`, ...)

For each new unit:

1. flash from golden image (or run fresh-bookworm checklist)
2. set hostname to target unit ID
3. boot and verify:
   - `systemctl status controller.service wsbridge.service kiosk.service --no-pager -l`
   - `ip -4 addr show eth0`
   - `ip route`
4. confirm hostname-derived static ethernet matches policy (`192.168.60.1xx`)
5. confirm wifi fallback remains connected for remote SSH

## Troubleshooting quick checks

- masked units:
  - `systemctl is-enabled controller.service wsbridge.service kiosk.service`
- stale overrides:
  - `ls -l /etc/systemd/system/{controller,wsbridge,kiosk}.service`
- repo corruption:
  - `git fsck --full` (reclone if corrupt objects are reported)

