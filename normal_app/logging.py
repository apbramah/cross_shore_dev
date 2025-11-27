# minimal logging shim for MicroPython

DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40
CRITICAL = 50

def getLogger(name=None):
    return Logger()

class Logger:
    def debug(self, msg, *args): print("[DEBUG]", msg % args if args else msg)
    def info(self, msg, *args): print("[INFO]", msg % args if args else msg)
    def warning(self, msg, *args): print("[WARN]", msg % args if args else msg)
    def error(self, msg, *args): print("[ERROR]", msg % args if args else msg)
    def critical(self, msg, *args): print("[CRIT]", msg % args if args else msg)
    def exception(self, msg, *args): print("[EXC]", msg % args if args else msg)
