import os, time
from machine import Pin

led = Pin(25, Pin.OUT)

ota_present = False
try:
    import ota
    ota_present = True
except Exception as e:
    print("Couldn't import ota:", e)

def ota_trust():
    if ota_present:
        ota.trust()

def main():
    while True:
        print("App running in directory:", os.getcwd())
        time.sleep(0.5)
        led.toggle()

        ota_trust()

if __name__ == "__main__":
    main()
