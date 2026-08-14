"""Forced dark palette for the quota window, identical on every platform —
never inherit the OS widget colors (dark on macOS dark-mode, light on
Windows). Plain RGB tuples, no wx, so contrast rules are testable headless;
panels.py converts to wx.Colour at the edge.
"""
from __future__ import annotations

BACKGROUND = (30, 30, 30)
TEXT_PRIMARY = (235, 235, 235)
TEXT_SECONDARY = (176, 176, 176)
TRACK = (60, 60, 60)
STALE_FILL = (128, 128, 128)

SEVERITY_FILLS = {
    "normal": (60, 179, 60),
    "warning": (224, 168, 0),
    "critical": (222, 70, 70),
}
