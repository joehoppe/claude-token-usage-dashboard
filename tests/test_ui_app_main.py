"""Dark-appearance startup tests.

The real-app test runs in a fresh interpreter instead of against the shared
wx_app fixture. On MSW SetAppearance only takes effect before any window
exists — see _enable_dark_titlebar's own docstring — so once any earlier
module has built a frame, the call returns CannotChange and the assertion
fails on Windows alone. A subprocess gives the call the virgin process its
contract requires and makes the result independent of collection order.

The contract tests run against plain fakes with no wx object at all.
"""

import subprocess
import sys

import wx

from claude_usage.ui.app.main import _enable_dark_titlebar

# Prefixes the verdict so it survives any chatter wx puts on stdout.
_VERDICT = "dark-appearance:"

# Deliberately the whole program: a wx.App and the appearance call, with no
# window created ahead of them.
_PROBE = f"""
import wx

from claude_usage.ui.app.main import _enable_dark_titlebar

print("{_VERDICT}", _enable_dark_titlebar(wx.App()))
"""


class RecordingApp:
    """wxPython >= 4.3: SetAppearance exists; records what was requested."""

    def __init__(self):
        self.requested = None

    def SetAppearance(self, appearance):
        self.requested = appearance
        return wx.App.AppearanceResult.Ok


class LegacyApp:
    """wxPython < 4.3: no SetAppearance at all."""


def test_dark_appearance_succeeds_on_this_platform():
    # Regression: on macOS the old MSWEnableDarkMode path raised
    # NotImplementedError — the name exists off Windows but is a stub.
    probe = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # No display is a loud failure, not a skip: a GUI toolkit that never
    # loaded must not report green (conftest makes the same call).
    assert probe.returncode == 0, f"the probe process died:\n{probe.stdout}\n{probe.stderr}"
    assert f"{_VERDICT} True" in probe.stdout, (
        f"expected a dark appearance:\n{probe.stdout}\n{probe.stderr}"
    )


def test_requests_always_dark_not_system_appearance():
    app = RecordingApp()
    _enable_dark_titlebar(app)
    assert app.requested == wx.App.Appearance.Dark


def test_wxpython_without_setappearance_is_a_quiet_no_op():
    assert _enable_dark_titlebar(LegacyApp()) is False
