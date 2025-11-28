import network, sys, os, time, machine, json, urequests

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

STATIC_IP = ('192.168.1.51', '255.255.255.0', '192.168.1.1', '8.8.8.8')

def connect_network():
    nic = network.WIZNET5K()
    nic.active(True)
    try:
        print("Attempting to connect to Ethernet using DHCP...")
        nic.ifconfig('dhcp')
    except:
        print("...failed. Falling back to static IP")
        nic.ifconfig(STATIC_IP)

    while not nic.isconnected():
        pass

    print("Ethernet connected:", nic.ifconfig())

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

def load_manifest(home_url):
    print("Fetching manifest...")
    resp = urequests.get(f"{home_url}/manifest.json")
    manifest = json.loads(resp.text)
    resp.close()
    return manifest

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

def check_for_version_update(home_urls):
    try:
        connect_network()
    except Exception as e:
        print("Network connection failed:", e)
        return

    for home_url in home_urls:
        try:
            check_for_updates(home_url)
            break
        except Exception as e:
            print("OTA failed:", e)

wdt = None

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

        global wdt
        # wdt = machine.WDT(timeout=8000)   # timeout in milliseconds

        import main
        main.main()
    except Exception as e:
        print("App crashed:", e)
        reboot()

trusted = False

def trust():
    global wdt, trusted
    if wdt:
        wdt.feed()

    # We use the trusted flag to avoid flash operations on every call
    if not trusted:
        with open('manifest.json') as f:
            manifest = json.load(f)
            if not manifest["trusted"]:
                manifest["trusted"] = True
                with open('manifest.json', 'w') as f:
                    json.dump(manifest, f)
        trusted = True

# Create a simple API module for the app
class OTA_API:
    trust = staticmethod(trust)

sys.modules["ota"] = OTA_API()

