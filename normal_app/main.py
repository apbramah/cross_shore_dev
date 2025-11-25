import os
from ota_update import check_for_version_update
check_for_version_update()

from time import sleep
while True:
    print("App A is running...", os.getcwd())
    sleep(0.5)
