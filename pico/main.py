import sys, os, json
from ota_update import rollback, get_active_dir, check_for_version_update, trust, reboot

# Create a simple API module for the app
class OTA_API:
    trust = staticmethod(trust)

sys.modules["ota"] = OTA_API()

def run_active_app():
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

        check_for_version_update()
        import main
        main.main()
    except Exception as e:
        print("App crashed:", e)
        reboot()

run_active_app()
