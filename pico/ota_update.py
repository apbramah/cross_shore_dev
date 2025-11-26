import network, sys, os, time, machine, json, hashlib
import urequests
wdt = machine.WDT(timeout=8000)   # timeout in milliseconds

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
    # Setup Ethernet
    nic = network.WIZNET5K()
    nic.active(True)
    nic.ifconfig(('192.168.1.51', '255.255.255.0', '192.168.1.1', '8.8.8.8'))
    print("Waiting for Ethernet link...")
    while not nic.isconnected():
        pass
    print("Ethernet connected:", nic.ifconfig())

# ------------------------------
# Utility functions
# ------------------------------
def get_active_dir():
    try:
        with open("/active_slot.txt") as f:
            active_dir = f.read().strip().lower()
            if active_dir not in ("/app_a", "/app_b"):
                raise ValueError
            return active_dir
    except:
        with open("/active_slot.txt", "w") as f:
            f.write("/app_a")
        return "/app_a"

def get_target_dir():
    active_dir = get_active_dir()
    target_dir = "/app_b" if active_dir == "/app_a" else "/app_a"
    return target_dir

def set_active_dir(active_dir):
    tmp = "/active_slot.tmp"
    with open(tmp, "w") as f:
        f.write(active_dir)
    os.rename(tmp, "/active_slot.txt")  # atomic-ish

def reboot():
    print("Rebooting...")
    time.sleep(1)
    machine.reset()

def rollback():
    print("Rolling back to previous firmware...")
    target_dir = get_target_dir()
    set_active_dir(target_dir)
    print("Switched active slot to:", target_dir)
    reboot()

def trust():
    wdt.feed()
    with open('manifest.json') as f:
        manifest = json.load(f)
        if not manifest["trusted"]:
            manifest["trusted"] = True
            with open('manifest.json', 'w') as f:
                json.dump(manifest, f)

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
    resp = urequests.get(url)
    dirs = dest_path.rsplit("/", 1)
    if len(dirs) > 1:
        dirpath = dirs[0]
        if not path_exists(dirpath):
            makedirs(dirpath)
    with open(dest_path, "wb") as f:
        f.write(resp.text)

    resp.close()

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
def load_manifest(home_url):
    print("Fetching manifest...")
    resp = urequests.get(f"{home_url}/manifest.json")
    manifest = json.loads(resp.text)
    resp.close()
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

def apply_update(home_url, manifest):
    target_dir = get_target_dir()
    print("Updating inactive slot:", target_dir)

    try:
        with open(f"{target_dir}/manifest.json") as f:
            old_manifest = json.load(f)
            if old_manifest["version"] == manifest["version"]:
                print("Target slot already has this version.")
                return
    except:
        pass

    if path_exists(target_dir):
        cleanup_dir(target_dir)
    else:
        os.mkdir(target_dir)

    for path in manifest["files"]:
        print("Updating file:", path)
        url = f"{home_url}/{path}"
        dest = f"{target_dir}/{path}"
        download_file(url, dest)

    # if not verify_files(manifest, target_dir):
    #     raise RuntimeError("File verification failed")

    manifest["num_boot_attempts"] = 0
    manifest["trusted"] = False
    with open(f"{target_dir}/manifest.json", "w") as f:
        json.dump(manifest, f)
    print(manifest)

    print("Switching active slot to:", target_dir)
    set_active_dir(target_dir)

    reboot()

def check_for_updates(home_url):
    with open('manifest.json') as f:
        local_manifest = json.load(f)
    remote_manifest = load_manifest(home_url)
    new_version = remote_manifest.get("version")
    local_version = local_manifest.get("version")

    if new_version != local_version:
        print(f"Updating from {local_version} to {new_version}")
        apply_update(home_url, remote_manifest)
    else:
        print("No update required. Current version:", local_version)

# ------------------------------
# Main
# ------------------------------
def check_for_version_update(home_urls):
    for home_url in home_urls:
        try:
            connect_wifi()
            check_for_updates(home_url)
            break
        except Exception as e:
            print("OTA failed:", e)

# Create a simple API module for the app
class OTA_API:
    trust = staticmethod(trust)

sys.modules["ota"] = OTA_API()

def run_active_app(home_urls):
    app_dir = get_active_dir()
    print("Booting app from:", app_dir)

    try:
        os.chdir(app_dir)
        try:
            with open('manifest.json') as f:
                manifest = json.load(f)
                print(manifest)
                if manifest["trusted"]:
                    print("App is trusted.")
                else:
                    print("App is NOT trusted.")
                    manifest["num_boot_attempts"] += 1
                    print("Boot attempts:", manifest["num_boot_attempts"])

                    if manifest["num_boot_attempts"] > 3:
                        print("Too many failed boot attempts. Rolling back.")
                        rollback()

                    with open('manifest.json', 'w') as f:
                        json.dump(manifest, f)                    
        except:
            pass

        check_for_version_update(home_urls)
        import main
        main.main()
    except Exception as e:
        print("App crashed:", e)
        reboot()
