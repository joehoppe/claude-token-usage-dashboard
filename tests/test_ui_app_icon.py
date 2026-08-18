"""Icon asset and platform-guard tests — no wx.App, no widgets. Importing
icon.py imports the wx module (for attach_app_icon); nothing is created.
"""
from claude_usage.ui.app.icon import ICON_PATH, uses_dock

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_icon_asset_exists():
    assert ICON_PATH.is_file()


def test_icon_asset_is_png():
    assert ICON_PATH.read_bytes()[:8] == PNG_MAGIC


def test_dock_only_on_macos():
    assert uses_dock("darwin")
    assert not uses_dock("win32")
    assert not uses_dock("linux")
