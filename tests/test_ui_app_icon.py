"""Icon asset, sizing, and platform-guard tests.

The bundle tests need a wx.App — wx.Image refuses to decode a PNG without
one — but no window is ever created or shown. Everything else runs with no
wx object at all.
"""

import ctypes
import struct
import sys

import pytest

from claude_usage.ui.app.icon import (
    APP_USER_MODEL_ID,
    ICON_PATH,
    ICON_SIZES,
    build_icon_bundle,
    set_app_user_model_id,
    uses_app_user_model_id,
    uses_dock,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Windows asks a window for exactly two icon sizes: 16px for the title bar
# and Alt-Tab, 32px for the taskbar button at 100% DPI.
WINDOWS_ICON_SLOTS = (16, 32)

# SetCurrentProcessExplicitAppUserModelID rejects longer ids and ids with
# spaces: https://learn.microsoft.com/windows/win32/shell/appids
MAX_APP_USER_MODEL_ID_LENGTH = 128


def source_png_edge() -> int:
    """Shortest edge, read straight out of the IHDR chunk — no decoder."""
    width, height = struct.unpack(">II", ICON_PATH.read_bytes()[16:24])
    return min(width, height)


def test_icon_asset_exists():
    assert ICON_PATH.is_file()


def test_icon_asset_is_png():
    assert ICON_PATH.read_bytes()[:8] == PNG_MAGIC


def test_dock_only_on_macos():
    assert uses_dock("darwin")
    assert not uses_dock("win32")
    assert not uses_dock("linux")


def test_icon_sizes_cover_the_windows_icon_slots():
    for slot in WINDOWS_ICON_SLOTS:
        assert slot in ICON_SIZES


def test_icon_sizes_never_upscale_the_source():
    assert max(ICON_SIZES) <= source_png_edge()


def test_bundle_holds_an_exact_icon_for_every_size(wx_app):
    bundle = build_icon_bundle()
    for size in ICON_SIZES:
        icon = bundle.GetIcon((size, size))
        assert (icon.GetWidth(), icon.GetHeight()) == (size, size)


def test_app_user_model_id_only_on_windows():
    assert uses_app_user_model_id("win32")
    assert not uses_app_user_model_id("darwin")
    assert not uses_app_user_model_id("linux")


def test_app_user_model_id_meets_shell_constraints():
    assert APP_USER_MODEL_ID
    assert " " not in APP_USER_MODEL_ID
    assert len(APP_USER_MODEL_ID) <= MAX_APP_USER_MODEL_ID_LENGTH


@pytest.mark.skipif(sys.platform != "win32", reason="shell32 is Windows-only")
def test_set_app_user_model_id_registers_the_id_with_the_shell():
    set_app_user_model_id()

    registered = ctypes.c_wchar_p()
    result = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(registered))

    assert result == 0
    assert registered.value == APP_USER_MODEL_ID
