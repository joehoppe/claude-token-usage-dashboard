"""App icon wiring: frame icon everywhere, Dock tile on macOS. The Dock
requires a wx.adv.TaskBarIcon(TBI_DOCK) — frame.SetIcon alone never reaches
it — and the caller must hold the returned handle or GC removes the tile.
"""
from __future__ import annotations

import sys
from pathlib import Path

import wx
import wx.adv

ICON_PATH = Path(__file__).parent / "assets" / "icon.png"


def uses_dock(platform: str = sys.platform) -> bool:
    return platform == "darwin"


def attach_app_icon(frame: wx.Frame) -> wx.adv.TaskBarIcon | None:
    icon = wx.Icon(str(ICON_PATH), wx.BITMAP_TYPE_PNG)
    if not icon.IsOk():
        return None
    frame.SetIcon(icon)
    if not uses_dock():
        return None
    dock = wx.adv.TaskBarIcon(iconType=wx.adv.TBI_DOCK)
    dock.SetIcon(icon)
    return dock
