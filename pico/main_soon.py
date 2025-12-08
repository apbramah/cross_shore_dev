import time
time.sleep(1) # This delay seems to make REPL connection more reliable if needed

try:
    import ota_update
    ota_update.run_active_app()
except Exception as e:
    print("OTA update failed:", e)

