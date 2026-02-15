#!/usr/bin/env bash
set -euo pipefail

CMDLINE="/boot/firmware/cmdline.txt"
CONFIG="/boot/firmware/config.txt"
BACKUP_DIR="/boot/firmware/backup_hydravision_$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"
cp -a "$CMDLINE" "$BACKUP_DIR/cmdline.txt"
cp -a "$CONFIG" "$BACKUP_DIR/config.txt"

python3 - <<'PY'
from pathlib import Path

cmdline_path = Path("/boot/firmware/cmdline.txt")
line = cmdline_path.read_text().strip().splitlines()[0]
parts = [p for p in line.split(" ") if p]

def remove_prefix(items, prefix):
    return [p for p in items if not p.startswith(prefix)]

# Remove existing flags we will re-add.
parts = [p for p in parts if p not in {
    "quiet",
    "splash",
    "plymouth.ignore-serial-consoles",
    "vt.global_cursor_default=0",
    "systemd.show_status=1",
    "systemd.show_status=true",
}]
parts = remove_prefix(parts, "loglevel=")

# Add quiet splash flags.
parts += [
    "quiet",
    "splash",
    "loglevel=3",
    "vt.global_cursor_default=0",
    "plymouth.ignore-serial-consoles",
]

cmdline_path.write_text(" ".join(parts) + "\n")
PY

python3 - <<'PY'
from pathlib import Path

cfg_path = Path("/boot/firmware/config.txt")
lines = cfg_path.read_text().splitlines()

def set_kv(lines, key, value):
    found = False
    out = []
    for line in lines:
        if line.strip().startswith(key + "="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    return out

lines = set_kv(lines, "disable_splash", "1")
cfg_path.write_text("\n".join(lines) + "\n")
PY

echo "Boot flags updated. Backup saved to: $BACKUP_DIR"

