import re

from serial.tools import list_ports


HEX_RE = re.compile(r"^[0-9a-fA-F\s]+$")


def list_com_ports() -> list[str]:
    ports = []
    for p in list_ports.comports():
        desc = p.description or ""
        ports.append(f"{p.device} - {desc}".strip())
    return ports


def extract_port_name(display: str) -> str:
    return display.split(" - ")[0].strip()
