import sys, os, time, json

try:
    import network
    import machine
    import urequests as requests
    os_path_sep = '/'

    def normalize_path(path):
        # Convert Windows backslashes → forward slashes
        path = path.replace("\\", "/")

        # Remove trailing slash unless root
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")

        return path

    def makedirs(path):
        path = normalize_path(path)

        # Split into components
        parts = path.split("/")
        
        # If absolute path, preserve leading slash
        if path.startswith("/"):
            current = "/"
        else:
            current = ""

        for part in parts:
            if not part:
                continue  # skip empty segments (can happen if path starts with '/')
            
            if current == "/" or current == "":
                current = current + part
            else:
                current = current + "/" + part

            # Try to create directory
            try:
                os.mkdir(current)
            except OSError:
                # Directory probably already exists
                pass

    os_makedirs = makedirs

    def reset():
        machine.reset()

    local_ips = []

    def connect_network(nic_setup):
        print('Trying to connect using:', nic_setup)
        nic = network.WIZNET5K()
        nic.active(True)
        nic.ifconfig(nic_setup)

        while not nic.isconnected():
            pass

        ifconfig = nic.ifconfig()

        global local_ips
        local_ips.append(ifconfig[0])

except:
    import requests
    os_path_sep = os.path.sep
    os_makedirs = os.makedirs

    def reset():
        os.chdir(root_dir)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    local_ips = []

    def connect_network(nic_setup):
        # On a PC, the network is already connected, so nothing to
        # do in that regard. But we still need to populate local_ips
        import socket

        hostname = socket.gethostname()
        global local_ips
        local_ips = socket.gethostbyname_ex(hostname)[2]

def path_exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False

root_dir = os.getcwd()

def get_active_dir():
    filename = root_dir + os_path_sep + 'active_slot.txt'
    try:
        with open(filename) as f:
            active_dir = f.read().strip().lower()
            if active_dir not in ("app_a", "app_b"):
                raise ValueError
            return root_dir + os_path_sep + active_dir
    except:
        with open(filename, "w") as f:
            f.write('app_a')
        return root_dir + os_path_sep + 'app_a'

def get_target_dir():
    active_dir = get_active_dir().split(os_path_sep)[-1]
    target_dir = "app_b" if active_dir == "app_a" else "app_a"
    return root_dir + os_path_sep + target_dir

def set_active_dir(active_dir):
    filename = root_dir + os_path_sep + 'active_slot.txt'
    with open(filename, "w") as f:
        f.write(active_dir.split(os_path_sep)[-1])

def reboot():
    print("Rebooting...")
    time.sleep(1)
    reset()

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
    resp = requests.get(url)
    dirs = dest_path.rsplit("/", 1)
    if len(dirs) > 1:
        dirpath = dirs[0]
        if not path_exists(dirpath):
            os_makedirs(dirpath)
    with open(dest_path, "wb") as f:
        f.write(resp.text.encode('utf-8'))

    resp.close()

def load_manifest(home_url):
    home_url = '/'.join([home_url, registry_get('app_path', 'apps/base'), 'manifest.json'])
    print("Fetching manifest:", home_url)
    resp = requests.get(home_url)
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
        url = '/'.join([home_url, registry_get('app_path', 'apps/base'), path])
        dest = f"{target_dir}/{path}"
        download_file(url, dest)

    manifest["num_boot_attempts"] = 0
    manifest["trusted"] = False
    with open(f"{target_dir}/manifest.json", "w") as f:
        json.dump(manifest, f)
    print(manifest)

    print("Switching active slot to:", target_dir)
    set_active_dir(target_dir)

def check_for_updates(home_url):
    app_dir = get_active_dir()

    remote_manifest = load_manifest(home_url)
    new_version = remote_manifest.get("version")

    try:
        with open(app_dir + '/manifest.json') as f:
            local_manifest = json.load(f)
        local_version = local_manifest.get("version")
        needs_update = (new_version != local_version)
    except FileNotFoundError:
        local_version = 'unknown'
        needs_update = True    

    if needs_update:
        print(f"Updating from {local_version} to {new_version}")
        apply_update(home_url, remote_manifest)
    else:
        print("No update required. Current version:", local_version)

def check_for_version_update():
    network_configs = registry_get('network_configs', [('dhcp', 'http://192.168.60.91:80')])

    checked = False
    successful_server_url = None
    while not checked:
        for nic_setup, server_url in network_configs:
            connect_network(nic_setup)
            print('Connected. Local ips:', local_ips)

            try:
                check_for_updates(server_url)
                checked = True
                successful_server_url = server_url
                break
            except Exception as e:
                print("OTA failed:", e)
        time.sleep(1)
    
    return successful_server_url

def run_active_app():
    server_url = check_for_version_update()

    app_dir = get_active_dir()
    print("Booting app from:", app_dir)

    os.chdir(app_dir)
    sys.path.insert(0, app_dir)
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

    import main
    main.main(server_url)

trusted = False

def trust():
    global trusted

    # We use the trusted flag to avoid flash operations on every call
    if not trusted:
        with open('manifest.json') as f:
            manifest = json.load(f)
            if not manifest["trusted"]:
                manifest["trusted"] = True
                with open('manifest.json', 'w') as f:
                    json.dump(manifest, f)
        trusted = True

REGISTRY_PATH = root_dir + os_path_sep + 'registry.json'

def _load_registry():
    try:
        with open(REGISTRY_PATH) as f:
            registry = json.load(f)
    except:
        registry = {}

    return registry

def _save_registry(registry):
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f)

def registry_get(key, default):
    registry = _load_registry()
    return registry.get(key, default)

def registry_set(key, value):
    registry = _load_registry()
    registry[key] = value
    _save_registry(registry)

def get_local_ips():
    return local_ips

# Create a simple API module for the app
class OTA_API:
    trust = staticmethod(trust)
    registry_get = staticmethod(registry_get)
    registry_set = staticmethod(registry_set)
    reboot = staticmethod(reboot)
    get_local_ips = staticmethod(get_local_ips)

sys.modules["ota"] = OTA_API()
