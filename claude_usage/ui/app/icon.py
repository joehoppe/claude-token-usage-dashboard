"""App icon wiring: window icons everywhere, Dock tile on macOS, taskbar
identity on Windows. The Dock requires a wx.adv.TaskBarIcon(TBI_DOCK) —
frame.SetIcons alone never reaches it — and the caller must hold the
returned handle or GC removes the tile.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

import wx
import wx.adv

ICON_PATH = Path(__file__).parent / "assets" / "icon.png"

# One icon per slot the shell asks for: 16px title bar and Alt-Tab, 32px
# taskbar button, the rest for higher DPI and the large shell views.
# Downscaling each ourselves beats handing Windows a single 1254px icon and
# letting it squeeze that into 32px.
ICON_SIZES = (16, 24, 32, 48, 256)

# Unique, space-free, and deliberately not Anthropic-branded — this app is
# unaffiliated. A bare "ClaudeUsage" would risk colliding with another vendor.
APP_USER_MODEL_ID = "JosephHoppe.ClaudeUsage.Dashboard"


def uses_dock(platform: str = sys.platform) -> bool:
    return platform == "darwin"


def uses_app_user_model_id(platform: str = sys.platform) -> bool:
    return platform == "win32"


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Claim a taskbar identity of our own.

    A process with no explicit AppUserModelID resolves back to its launcher —
    python.exe — so the shell paints that shortcut's icon on the taskbar
    button and ignores the window icon entirely. Must run before the first
    window exists; afterwards the button has already been created.
    """
    if not uses_app_user_model_id():
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def build_icon_bundle() -> wx.IconBundle | None:
    """The source PNG downscaled once per entry in ICON_SIZES."""
    image = wx.Image(str(ICON_PATH), wx.BITMAP_TYPE_PNG)
    if not image.IsOk():
        return None
    bundle = wx.IconBundle()
    for size in ICON_SIZES:
        scaled = image.Scale(size, size, wx.IMAGE_QUALITY_HIGH)
        bundle.AddIcon(wx.Icon(wx.Bitmap(scaled)))
    return bundle


def attach_app_icon(frame: wx.Frame) -> wx.adv.TaskBarIcon | None:
    bundle = build_icon_bundle()
    if bundle is None:
        return None
    frame.SetIcons(bundle)
    if not uses_dock():
        return None
    dock = wx.adv.TaskBarIcon(iconType=wx.adv.TBI_DOCK)
    # Full-resolution source rather than a bundle entry: the Dock tile is
    # drawn far larger than any window icon slot.
    dock.SetIcon(wx.Icon(str(ICON_PATH), wx.BITMAP_TYPE_PNG))
    return dock
