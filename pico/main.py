import sys
from ota_update import run_active_app, trust

# Create a simple API module for the app
class OTA_API:
    trust = staticmethod(trust)

sys.modules["ota"] = OTA_API()

run_active_app()
