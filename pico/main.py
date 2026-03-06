import time
time.sleep(1) # This delay seems to make REPL connection more reliable if needed

import ota_update

try:
    ota_update.run_active_app()
except Exception as e:
    print(f"App execution error: {e}")
finally:
    ota_update.reboot()
