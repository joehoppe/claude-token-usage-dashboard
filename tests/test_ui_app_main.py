"""Dark-appearance startup tests.

The real-app test needs a wx.App — SetAppearance is a method on the live app
object — but no window is ever created or shown. The contract tests run
against plain fakes with no wx object at all.
"""
import wx

from claude_usage.ui.app.main import _enable_dark_titlebar


class RecordingApp:
    """wxPython >= 4.3: SetAppearance exists; records what was requested."""

    def __init__(self):
        self.requested = None

    def SetAppearance(self, appearance):
        self.requested = appearance
        return wx.App.AppearanceResult.Ok


class LegacyApp:
    """wxPython < 4.3: no SetAppearance at all."""


def test_dark_appearance_succeeds_on_this_platform(wx_app):
    # Regression: on macOS the old MSWEnableDarkMode path raised
    # NotImplementedError — the name exists off Windows but is a stub.
    assert _enable_dark_titlebar(wx_app) is True


def test_requests_always_dark_not_system_appearance():
    app = RecordingApp()
    _enable_dark_titlebar(app)
    assert app.requested == wx.App.Appearance.Dark


def test_wxpython_without_setappearance_is_a_quiet_no_op():
    assert _enable_dark_titlebar(LegacyApp()) is False
