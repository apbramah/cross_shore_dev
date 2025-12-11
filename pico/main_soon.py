import time
time.sleep(1) # This delay seems to make REPL connection more reliable if needed

import ota_update

while True:
    try:
        ota_update.run_active_app()
    except Exception as e:
        print(f"App execution error: {e}")
    print("Restarting app in 1 seconds...")
    import time
    time.sleep(1)

