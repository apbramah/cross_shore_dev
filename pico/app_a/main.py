import os

ota_present = False
try:
    import ota
    ota_present = True
    ota.update()
except Exception as e:
    print("OTA update failed:", e)

def ota_trust():
    if ota_present:
        ota.trust()

from time import sleep
while True:
    print("App running in directory:", os.getcwd())
    sleep(0.5)
    ota_trust()
