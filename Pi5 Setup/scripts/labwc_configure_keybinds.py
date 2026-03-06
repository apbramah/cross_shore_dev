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


def local_name(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def namespace_uri(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return ""


def namespaced(parent: ET.Element, tag: str) -> str:
    ns = namespace_uri(parent.tag)
    if ns:
        return f"{{{ns}}}{tag}"
    return tag


def ensure_tree() -> ET.ElementTree:
    if os.path.isfile(RC_XML):
        tree = ET.parse(RC_XML)
        root = tree.getroot()
        if local_name(root.tag) not in {"labwc_config", "openbox_config"}:
            raise RuntimeError(f"Unexpected root tag in {RC_XML}: {root.tag}")
        return tree
    root = ET.Element("labwc_config")
    return ET.ElementTree(root)


def get_or_create(parent: ET.Element, tag: str) -> ET.Element:
    ns_tag = namespaced(parent, tag)
    node = parent.find(ns_tag)
    if node is None:
        node = ET.SubElement(parent, ns_tag)
    return node


def ensure_execute_keybind(keyboard: ET.Element, key: str, command_value: str) -> None:
    keybind_tag = namespaced(keyboard, "keybind")
    action_tag = namespaced(keyboard, "action")
    command_tag = namespaced(keyboard, "command")

    for keybind in keyboard.findall(keybind_tag):
        if keybind.get("key") != key:
            continue
        action = keybind.find(action_tag)
        if action is None:
            action = ET.SubElement(keybind, action_tag, {"name": "Execute"})
        if action.get("name") != "Execute":
            action.set("name", "Execute")
        command = action.find(command_tag)
        if command is None:
            command = ET.SubElement(action, command_tag)
        command.text = command_value
        return

    keybind = ET.SubElement(keyboard, keybind_tag, {"key": key})
    action = ET.SubElement(keybind, action_tag, {"name": "Execute"})
    command = ET.SubElement(action, command_tag)
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
