import machine


class I2CStatusSlave:
    """
    Read-only I2C status responder.

    The repo currently does not include a single guaranteed I2C slave API for
    RP2040 MicroPython, so this class feature-detects known slave backends and
    fails soft when unavailable.
    """

    def __init__(self, bus_id=0, sda_pin=4, scl_pin=5, address=0x3A, freq=100_000):
        self.bus_id = int(bus_id)
        self.sda_pin = int(sda_pin)
        self.scl_pin = int(scl_pin)
        self.address = int(address) & 0x7F
        self.freq = int(freq)
        self._backend_name = "none"
        self._dev = None
        self._last_frame = bytes([0] * 28)
        self._last_error = ""
        self._init_backend()

    @property
    def available(self):
        return self._dev is not None

    @property
    def backend_name(self):
        return self._backend_name

    @property
    def last_error(self):
        return self._last_error

    def _try_set_frame(self):
        if self._dev is None:
            return False
        frame = self._last_frame
        try:
            if hasattr(self._dev, "setdata"):
                self._dev.setdata(frame)
                return True
            if hasattr(self._dev, "set_buffer"):
                self._dev.set_buffer(frame)
                return True
            if hasattr(self._dev, "write"):
                self._dev.write(frame)
                return True
            if hasattr(self._dev, "put"):
                self._dev.put(frame)
                return True
        except Exception as exc:
            self._last_error = str(exc)
            return False
        return False

    def _init_backend(self):
        sda = machine.Pin(self.sda_pin)
        scl = machine.Pin(self.scl_pin)

        # Backend A: firmware exposing machine.I2CSlave
        try:
            if hasattr(machine, "I2CSlave"):
                cls = getattr(machine, "I2CSlave")
                try:
                    self._dev = cls(self.bus_id, sda=sda, scl=scl, addr=self.address, freq=self.freq)
                except TypeError:
                    self._dev = cls(self.bus_id, sda=sda, scl=scl, address=self.address, freq=self.freq)
                self._backend_name = "machine.I2CSlave"
                self._try_set_frame()
                return
        except Exception as exc:
            self._last_error = str(exc)

        # Backend B: external i2cslave module (if present on target image).
        try:
            import i2cslave  # type: ignore

            cls = getattr(i2cslave, "I2CSlave", None)
            if cls is not None:
                try:
                    self._dev = cls(self.bus_id, sda=sda, scl=scl, slaveAddress=self.address, freq=self.freq)
                except TypeError:
                    self._dev = cls(self.bus_id, sda=sda, scl=scl, address=self.address, freq=self.freq)
                self._backend_name = "i2cslave.I2CSlave"
                self._try_set_frame()
                return
        except Exception as exc:
            self._last_error = str(exc)

        self._dev = None
        self._backend_name = "none"

    def set_frame(self, frame_bytes):
        if not isinstance(frame_bytes, (bytes, bytearray)):
            return
        self._last_frame = bytes(frame_bytes)
        self._try_set_frame()

    def poll(self):
        """
        Keep backend event loops serviced if the backend exposes one.
        No heavy work should run here.
        """
        if self._dev is None:
            return
        try:
            if hasattr(self._dev, "poll"):
                self._dev.poll()
            elif hasattr(self._dev, "handle_event"):
                self._dev.handle_event()
        except Exception as exc:
            self._last_error = str(exc)
