"""Register configurable global shortcuts on Windows, with Qt-local fallback."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from PySide6.QtGui import QKeySequence

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

_VK = {
    "SPACE": 0x20, "TAB": 0x09, "RETURN": 0x0D, "ENTER": 0x0D,
    "ESC": 0x1B, "ESCAPE": 0x1B, "INSERT": 0x2D, "DELETE": 0x2E,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
}


def parse_shortcut(sequence: str) -> tuple[int, int]:
    """Return Win32 modifier and virtual-key values for a single key chord."""
    parsed = QKeySequence(sequence)
    if parsed.isEmpty() or parsed.count() != 1:
        raise ValueError("Use one shortcut chord, such as Ctrl+Shift+Space.")
    portable = parsed.toString(QKeySequence.PortableText).upper()
    parts = [part.strip() for part in portable.split("+") if part.strip()]
    modifiers = 0
    for part in parts[:-1]:
        if part in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif part == "ALT":
            modifiers |= MOD_ALT
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
        else:
            raise ValueError("Only Ctrl, Alt, and Shift modifiers are supported for global shortcuts.")
    if not modifiers:
        raise ValueError("A global shortcut must include Ctrl, Alt, or Shift.")
    key = parts[-1]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        virtual_key = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        virtual_key = 0x70 + int(key[1:]) - 1
    else:
        virtual_key = _VK.get(key)
    if virtual_key is None:
        raise ValueError(f"Unsupported global shortcut key: {key}")
    return modifiers | MOD_NOREPEAT, virtual_key


def register_global_hotkeys(hwnd: int, shortcuts: dict[int, str], *, api=None) -> tuple[list[int], list[str]]:
    """Register shortcut ids on this window and return registered ids/errors."""
    if os.name != "nt":
        return [], ["Global shortcuts are Windows-only; app-local shortcuts remain available."]
    user32 = api or ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, wintypes.INT, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    registered, errors = [], []
    for identifier, sequence in shortcuts.items():
        try:
            modifiers, key = parse_shortcut(sequence)
        except ValueError as exc:
            errors.append(f"{sequence}: {exc}")
            continue
        if user32.RegisterHotKey(hwnd, identifier, modifiers, key):
            registered.append(identifier)
        else:
            errors.append(f"{sequence} is already in use; its app-local shortcut is still available.")
    return registered, errors


def unregister_global_hotkeys(hwnd: int, identifiers: list[int], *, api=None) -> None:
    if os.name != "nt" or not identifiers:
        return
    user32 = api or ctypes.WinDLL("user32", use_last_error=True)
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, wintypes.INT]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    for identifier in identifiers:
        user32.UnregisterHotKey(hwnd, identifier)
