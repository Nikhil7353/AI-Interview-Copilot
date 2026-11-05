"""Best-effort Windows display affinity for the app's own top-level windows."""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
WINDOWS_10_2004_BUILD = 19041


def set_capture_exclusion(hwnd: int, enabled: bool = True, *, api=None, build: int | None = None) -> tuple[bool, str]:
    """Request capture exclusion and confirm the affinity value via Win32.

    A successful query confirms the OS affinity state only. It does not prove a
    conferencing app or a particular capture path will omit the window.
    """
    if os.name != "nt":
        return False, "Windows capture exclusion is unavailable; the window remains visible."
    if enabled:
        if build is None:
            build = sys.getwindowsversion().build
        if build < WINDOWS_10_2004_BUILD:
            return False, "Capture exclusion requires Windows 10 version 2004 or newer; the window remains visible."
    try:
        user32 = api or ctypes.WinDLL("user32", use_last_error=True)
        set_affinity = user32.SetWindowDisplayAffinity
        get_affinity = user32.GetWindowDisplayAffinity
        set_affinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        set_affinity.restype = wintypes.BOOL
        get_affinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        get_affinity.restype = wintypes.BOOL
        requested = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
        if not set_affinity(hwnd, requested):
            error = ctypes.get_last_error()
            return False, f"Windows rejected the capture setting (error {error}); the window remains normally visible."
        actual = wintypes.DWORD()
        if not get_affinity(hwnd, ctypes.byref(actual)) or actual.value != requested:
            return False, "Windows did not confirm the requested capture setting; the window remains normally visible."
        if enabled:
            return True, "Windows confirmed the display-affinity request. Capture behavior is still unverified; assume the window may be visible."
        return True, "Normal window capture restored."
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        return False, f"Capture setting is unsupported here ({exc}); the window remains normally visible."
