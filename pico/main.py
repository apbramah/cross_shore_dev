import machine, time, json, os, sys

BOOT_STATUS_FILE = "boot_status.json"
ROLLBACK_TIMEOUT = 30  # seconds allowed for new firmware to confirm boot

def get_active_slot():
    try:
        with open("active_slot.txt") as f:
            slot = f.read().strip().lower()
            if slot not in ("a", "b"):
                raise ValueError
            return slot
    except:
        with open("active_slot.txt", "w") as f:
            f.write("a")
        return "a"

def set_active_slot(slot):
    tmp = "active_slot.tmp"
    with open(tmp, "w") as f:
        f.write(slot.lower())
    os.rename(tmp, "active_slot.txt")

def load_boot_status():
    try:
        with open(BOOT_STATUS_FILE) as f:
            return json.load(f)
    except:
        return None

def save_boot_status(status):
    tmp = BOOT_STATUS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(status, f)
    os.rename(tmp, BOOT_STATUS_FILE)

def rollback_if_needed():
    status = load_boot_status()
    if not status:
        return
    if status.get("status") == "pending":
        elapsed = time.time() - status.get("timestamp", 0)
        if elapsed > ROLLBACK_TIMEOUT:
            print("⚠️ Boot confirmation timeout — rolling back!")
            prev = "A" if status["slot"] == "B" else "B"
            set_active_slot(prev)
            save_boot_status({"slot": prev, "status": "stable"})
            machine.reset()

def run_active_app():
    slot = get_active_slot()
    rollback_if_needed()
    app_dir = f"/app_{slot}"
    print("Launching app from:", app_dir)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    try:
        exec(open(f"{app_dir}/main.py").read(), globals())
    except Exception as e:
        print("App crashed:", e)
        rollback_if_needed()  # handle immediate crash
        machine.reset()

run_active_app()
