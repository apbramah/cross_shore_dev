import time
time.sleep(1) # This delay seems to make REPL connection more reliable if needed

import ota_update
ota_update.run_active_app(['http://192.168.1.52:8000', 'http://192.168.1.52:80'])
