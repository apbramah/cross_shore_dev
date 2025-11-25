import machine, sys, os, json
from ota_update import rollback, get_active_dir, check_for_version_update

# Create a simple API module for the app
class OTA_API:
    update = staticmethod(check_for_version_update)

sys.modules["ota"] = OTA_API()

def run_active_app():
    app_dir = get_active_dir()
    print("Booting app from:", app_dir)

    sys.path.insert(0, "/")
    try:
        os.chdir(app_dir)
        try:
            with open('manifest.json') as f:
                manifest = json.load(f)
                if not manifest["trusted"]:
                    manifest["num_boot_attempts"] += 1

                    if manifest["num_boot_attempts"] > 3:
                        rollback()

                    with open('manifest.json', 'w') as f:
                        json.dump(manifest, f)                    
        except:
            pass
        exec(open('main.py').read(), globals())
    except Exception as e:
        print("App crashed:", e)
        machine.reset()

run_active_app()
