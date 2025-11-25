import os

try:
    import ota
    ota.update()
except Exception as e:
    print("OTA update failed:", e)

from time import sleep
while True:
    print("App A is running...", os.getcwd())
    sleep(0.5)
    ota.trust()
