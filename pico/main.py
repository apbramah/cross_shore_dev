import machine, sys

def get_active_slot():
    try:
        with open("/active_slot.txt") as f:
            slot = f.read().strip().lower()
            if slot not in ("a", "b"):
                raise ValueError
            return slot
    except:
        with open("/active_slot.txt", "w") as f:
            f.write("a")
        return "a"

def run_active_app():
    slot = get_active_slot()
    app_dir = f"/app_{slot}"
    print("Launching app from:", app_dir)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    try:
        exec(open(f"{app_dir}/main.py").read(), globals())
    except Exception as e:
        print("App crashed:", e)
        machine.reset()

run_active_app()
