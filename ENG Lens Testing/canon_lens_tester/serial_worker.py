from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional, Union

import serial

from .canon_protocol import BAUD, BITS, PARITY, STOP


@dataclass
class SerialConfig:
    port: str
    baud: int = BAUD
    dtr: bool = True
    rts: bool = False
    bytesize: int = BITS
    parity: Union[int, str] = PARITY
    stopbits: Union[int, float] = STOP


class SerialWorker:
    def __init__(self):
        self.ser: Optional[serial.Serial] = None
        self.rx_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.rx_queue: "queue.Queue[bytes]" = queue.Queue()
        self.lock = threading.Lock()

    def is_open(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def open(self, cfg: SerialConfig) -> None:
        if self.is_open():
            raise RuntimeError("Serial already open")

        ser = serial.Serial(
            port=cfg.port,
            baudrate=cfg.baud,
            bytesize=cfg.bytesize,
            parity=cfg.parity,
            stopbits=cfg.stopbits,
            timeout=0.05,
            write_timeout=0.2,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        ser.dtr = bool(cfg.dtr)
        ser.rts = bool(cfg.rts)

        self.ser = ser
        self.stop_event.clear()

        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self.rx_thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.rx_thread and self.rx_thread.is_alive():
            self.rx_thread.join(timeout=0.3)
        self.rx_thread = None

        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def set_dtr(self, state: bool) -> None:
        if self.ser:
            self.ser.dtr = bool(state)

    def set_rts(self, state: bool) -> None:
        if self.ser:
            self.ser.rts = bool(state)

    def send(self, data: bytes) -> None:
        if not self.is_open():
            raise RuntimeError("Serial not open")
        with self.lock:
            self.ser.write(data)

    def get_modem_status(self) -> dict[str, bool]:
        """
        Returns input modem-line states as seen by the adapter.
        Keys: dsr, cts, ri, cd
        """
        if not self.is_open() or not self.ser:
            return {"dsr": False, "cts": False, "ri": False, "cd": False}
        try:
            return {
                "dsr": bool(self.ser.dsr),
                "cts": bool(self.ser.cts),
                "ri": bool(self.ser.ri),
                "cd": bool(self.ser.cd),
            }
        except Exception:
            return {"dsr": False, "cts": False, "ri": False, "cd": False}

    def _rx_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                if not self.ser or not self.ser.is_open:
                    break
                n = self.ser.in_waiting
                if n:
                    b = self.ser.read(n)
                    if b:
                        self.rx_queue.put(b)
                time.sleep(0.005)
            except Exception:
                break
