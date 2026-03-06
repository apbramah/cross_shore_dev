#!/usr/bin/env python3
from __future__ import annotations

import os
import xml.etree.ElementTree as ET


RC_XML = "/home/admin/.config/labwc/rc.xml"
UNLOCK_KEY = "C-A-S-u"
UNLOCK_CMD = "/usr/local/bin/hydravision-admin-unlock.sh"
BLOCKED_KEYS = (
    "A-Tab",
    "A-F4",
    "W-r",
    "C-A-t",
    "C-A-Delete",
    "A-space",
    "C-A-F1",
    "C-A-F2",
    "C-A-F3",
    "C-A-F4",
    "C-A-F5",
    "C-A-F6",
)
BLOCK_CMD = "/usr/bin/true"


def ensure_tree() -> ET.ElementTree:
    if os.path.isfile(RC_XML):
        tree = ET.parse(RC_XML)
        root = tree.getroot()
        if root.tag != "labwc_config":
            raise RuntimeError(f"Unexpected root tag in {RC_XML}: {root.tag}")
        return tree
    root = ET.Element("labwc_config")
    return ET.ElementTree(root)


def get_or_create(parent: ET.Element, tag: str) -> ET.Element:
    node = parent.find(tag)
    if node is None:
        node = ET.SubElement(parent, tag)
    return node


def ensure_execute_keybind(keyboard: ET.Element, key: str, command_value: str) -> None:
    for keybind in keyboard.findall("keybind"):
        if keybind.get("key") != key:
            continue
        action = keybind.find("action")
        if action is None:
            action = ET.SubElement(keybind, "action", {"name": "Execute"})
        if action.get("name") != "Execute":
            action.set("name", "Execute")
        command = action.find("command")
        if command is None:
            command = ET.SubElement(action, "command")
        command.text = command_value
        return

    keybind = ET.SubElement(keyboard, "keybind", {"key": key})
    action = ET.SubElement(keybind, "action", {"name": "Execute"})
    command = ET.SubElement(action, "command")
    command.text = command_value


def main() -> None:
    tree = ensure_tree()
    root = tree.getroot()
    keyboard = get_or_create(root, "keyboard")
    ensure_execute_keybind(keyboard, UNLOCK_KEY, UNLOCK_CMD)
    for blocked_key in BLOCKED_KEYS:
        ensure_execute_keybind(keyboard, blocked_key, BLOCK_CMD)
    os.makedirs(os.path.dirname(RC_XML), exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(RC_XML, encoding="utf-8", xml_declaration=True)
    print(f"Configured labwc keybind {UNLOCK_KEY} -> {UNLOCK_CMD}")
    print(f"Configured blocked keybinds: {', '.join(BLOCKED_KEYS)}")


if __name__ == "__main__":
    main()
