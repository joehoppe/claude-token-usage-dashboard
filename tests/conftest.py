"""Fixtures shared across the wxPython test modules.

`wx_app` lives here rather than in each test module because a same-named
session fixture declared per module is a *distinct* fixture: a full run
builds one wx.App per module instead of one per session. Three coexist
harmlessly today, but nothing about that is guaranteed, and one shared
definition is the honest expression of what the tests want — a single
live application object for the session.

No display guard: when no screen is reachable — a headless runner, or a
macOS process outside the logged-in Aqua session — wx.App() raises
SystemExit and the run fails loudly. That is the behaviour CI wants.
Skipping instead would turn a GUI toolkit that never loaded into a green
build.
"""
import pytest
import wx


@pytest.fixture(scope="session")
def wx_app():
    """The one wx.App for the whole session.

    Never Show()n: the tests construct widgets and inspect them, so the
    app exists only to satisfy wx's requirement that one be alive before
    any window or image is created.
    """
    return wx.App()
