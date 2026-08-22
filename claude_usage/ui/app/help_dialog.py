"""Dark-themed replacement for the native About-Refresh alert. The native
macOS alert (NSAlert) always stamps the app bundle icon onto the dialog and
ignores wx.ICON_NONE, so an icon-free dialog has to own its whole surface:
same forced palette as the main window, wrapped message text, one OK button.
"""
from __future__ import annotations

import wx

from claude_usage.ui.app import theme
from claude_usage.ui.app.refresh import HELP_DIALOG_MESSAGE, HELP_DIALOG_TITLE

_PADDING = 16
_WRAP_WIDTH = 360


class HelpDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        # The parent frame is STAY_ON_TOP; without matching that level the
        # modal dialog opens *behind* the frame and the app looks frozen.
        super().__init__(
            parent,
            title=HELP_DIALOG_TITLE,
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )
        self.SetBackgroundColour(wx.Colour(*theme.BACKGROUND))
        message = wx.StaticText(self, label=HELP_DIALOG_MESSAGE)
        message.SetForegroundColour(wx.Colour(*theme.TEXT_PRIMARY))
        message.Wrap(_WRAP_WIDTH)
        ok_button = wx.Button(self, wx.ID_OK)
        ok_button.SetDefault()
        # There is no Cancel button for Esc to fall back on, so map Esc to
        # OK explicitly; Enter already triggers the default button.
        self.SetEscapeId(wx.ID_OK)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(message, 0, wx.ALL, _PADDING)
        sizer.Add(
            ok_button, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, _PADDING
        )
        self.SetSizerAndFit(sizer)
        self.CentreOnParent()
