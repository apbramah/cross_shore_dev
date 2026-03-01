import time

from lens_serial import LensSerial
from canon_lens import CanonLens
from fuji_lens import FujiLens

LENS_CANON = "canon"
LENS_FUJI = "fuji"
AXES = ("zoom", "focus", "iris")


class LensController:
    def __init__(self, default_lens_type=LENS_FUJI):
        self.transport = LensSerial(38400, bits=8, parity=None, stop=1)
        self.canon = CanonLens(self.transport)
        self.fuji = FujiLens(self.transport)
        self.active_lens = None
        self.active_lens_type = None
        self.set_lens_type(default_lens_type)

    def get_lens_type(self):
        return self.active_lens_type

    def get_axis_sources(self):
        if self.active_lens is None:
            return {"zoom": "pc", "focus": "pc", "iris": "pc"}
        return self.active_lens.get_axis_sources()

    def set_lens_type(self, lens_type):
        if lens_type not in (LENS_CANON, LENS_FUJI):
            return False

        if lens_type == LENS_CANON:
            self.transport.configure(
                self.canon.baud,
                bits=self.canon.bits,
                parity=self.canon.parity,
                stop=self.canon.stop,
            )
            self.active_lens = self.canon
        else:
            self.transport.configure(
                self.fuji.baud,
                bits=self.fuji.bits,
                parity=self.fuji.parity,
                stop=self.fuji.stop,
            )
            self.active_lens = self.fuji

        self.active_lens_type = lens_type
        self.active_lens.on_activate()
        return True

    def set_axis_source(self, axis, source):
        if axis not in AXES:
            return False
        if self.active_lens is None:
            return False
        return self.active_lens.set_axis_source(axis, source)

    def move_zoom(self, delta):
        if self.active_lens is None:
            return
        self.active_lens.move_zoom(delta)

    def set_focus_input(self, value):
        if self.active_lens is None:
            return
        self.active_lens.set_focus_input(value)

    def set_iris_input(self, value):
        if self.active_lens is None:
            return
        self.active_lens.set_iris_input(value)

    def write_raw(self, data):
        if self.active_lens is None:
            return
        self.active_lens.write_raw(data)

    def read_raw(self):
        if self.active_lens is None:
            return None
        return self.active_lens.read_raw()

    def periodic(self):
        if self.active_lens is None:
            return
        self.active_lens.periodic(time.ticks_ms())
