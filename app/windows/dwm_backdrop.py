"""Windows 10/11 DWM: dark title bar and Mica/acrylic backdrop where supported."""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_MAINWINDOW = 2
DWMSBT_TRANSIENTWINDOW = 3


def _hwnd(window) -> int:
    try:
        return int(window.winId())
    except (AttributeError, TypeError, ValueError):
        return 0


def apply_premium_window_chrome(window, *, dialog: bool = False) -> None:
    """Best-effort dark caption + Mica (main) or acrylic (dialogs) on Windows 11."""
    if os.name != "nt":
        return
    hwnd = _hwnd(window)
    if not hwnd:
        return
    try:
        dwm = ctypes.windll.dwmapi
    except OSError:
        return

    dark = wintypes.INT(1)
    dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark), ctypes.sizeof(dark))

    if sys.getwindowsversion().build >= 22000:
        backdrop = wintypes.INT(DWMSBT_TRANSIENTWINDOW if dialog else DWMSBT_MAINWINDOW)
        dwm.DwmSetWindowAttribute(
            hwnd, DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(backdrop), ctypes.sizeof(backdrop)
        )
