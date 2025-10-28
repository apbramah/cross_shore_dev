import network, os, time, machine, json, hashlib
import uwebsockets.client

# ====== CONFIG ======
BASE_URL = "pico/app_a"
MANIFEST_URL = BASE_URL + "/manifest.json"
REBOOT_AFTER_UPDATE = True
ws = None
WS_URL = "ws://192.168.1.52:80/"
# ====================

_original_print = print

def print(*args, **kwargs):
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    
    # Build the full message string (same as print would output)
    message = sep.join(str(arg) for arg in args) + end
    
    # Call the handler with the plain message
    if ws:
        ws.send('log:' + message.strip())
    _original_print(*args, **kwargs)

def path_exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False

def is_dir(path):
    try:
        return os.stat(path)[0] & 0x4000  # directory bit in st_mode
    except OSError:
        return False

def makedirs(path):
    """Recursively create directories (like os.makedirs)."""
    parts = path.split("/")
    current = ""
    for p in parts:
        if not p:
            continue
        current = current + "/" + p
        if not path_exists(current):
            try:
                os.mkdir(current)
            except OSError:
                pass  # already exists or race condition

# ------------------------------
# Wi-Fi
# ------------------------------
def connect_wifi():
    global ws
    # Setup Ethernet
    nic = network.WIZNET5K()
    nic.active(True)
    nic.ifconfig(('192.168.1.51', '255.255.255.0', '192.168.1.1', '8.8.8.8'))
    print("Waiting for Ethernet link...")
    while not nic.isconnected():
        pass
    print("Ethernet connected:", nic.ifconfig())

    print("Connecting to WebSocket server...")
    ws = uwebsockets.client.connect(WS_URL)
    ws.send("DEVICE")  # announce as device

# ------------------------------
# Utility functions
# ------------------------------
def get_active_slot():
    try:
        with open("active_slot.txt") as f:
            return f.read().strip().lower()
    except:
        with open("active_slot.txt", "w") as f:
            f.write("a")
        return "a"

def set_active_slot(slot):
    tmp = "active_slot.tmp"
    with open(tmp, "w") as f:
        f.write(slot)
    os.rename(tmp, "active_slot.txt")  # atomic-ish

def cleanup_dir(path):
    # if not os.path.exists(path):
    #     return
    for item in os.listdir(path):
        full = path + "/" + item
        if os.stat(full)[0] & 0x4000:
            cleanup_dir(full)
        else:
            os.remove(full)
    os.rmdir(path)

# ------------------------------
# Download + verify
# ------------------------------
def download_file(url, dest_path):
    print("Downloading:", url)
    ws.send('get:' + url)
    resp = ws.recv()
    dirs = dest_path.rsplit("/", 1)
    if len(dirs) > 1:
        dirpath = dirs[0]
        if not path_exists(dirpath):
            makedirs(dirpath)
    with open(dest_path, "wb") as f:
        f.write(resp)

def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(512)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

# ------------------------------
# OTA logic
# ------------------------------
def load_manifest():
    print("Fetching manifest...")
    ws.send('get:' + MANIFEST_URL)
    resp = ws.recv()
    manifest = json.loads(resp)
    return manifest

def verify_files(manifest, base_dir):
    print("Verifying files...")
    for path, expected in manifest["files"].items():
        local = f"{base_dir}/{path}"
        actual = file_hash(local)
        if actual != expected:
            print("Hash mismatch:", path)
            return False
    return True

def apply_update(manifest):
    current = get_active_slot()
    target = "b" if current == "a" else "a"
    target_dir = f"/app_{target}"
    print("Updating inactive slot:", target_dir)

    if path_exists(target_dir):
        cleanup_dir(target_dir)
    else:
        os.mkdir(target_dir)

    for path in manifest["files"]:
        print("Updating file:", path)
        url = f"{BASE_URL}/{path}"
        dest = f"{target_dir}/{path}"
        download_file(url, dest)

    # if not verify_files(manifest, target_dir):
    #     raise RuntimeError("File verification failed")

    set_active_slot(target)
    print("Switched active slot to:", target)
    with open(f"{target_dir}/version.txt", "w") as f:
        f.write(manifest["version"])

    if REBOOT_AFTER_UPDATE:
        print("Rebooting into new firmware...")
        time.sleep(1)
        machine.reset()

def check_for_updates():
    manifest = load_manifest()
    new_version = manifest.get("version")
    active = get_active_slot()
    active_dir = f"/app_{active}"
    local_version = None
    try:
        with open(f"{active_dir}/version.txt") as f:
            local_version = f.read().strip()
    except:
        print(f"No local version found at {active_dir}/version.txt")

    if new_version != local_version:
        print(f"Updating from {local_version} to {new_version}")
        apply_update(manifest)
    else:
        print("No update required. Current version:", local_version)
        time.sleep(1)

# ------------------------------
# Main
# ------------------------------
def main():
    try:
        connect_wifi()
        check_for_updates()
    except Exception as e:
        print("OTA failed:", e)
