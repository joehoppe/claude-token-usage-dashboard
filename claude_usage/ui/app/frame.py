"""wx.Frame composition root for the window: header, bar rows, footer via
QuotaPanel. STAY_ON_TOP, resizable, never steals focus on refresh (refresh
only repaints — it never calls Raise()/SetFocus()).
"""
from __future__ import annotations

from typing import Callable

import wx

from claude_usage.ui.app.panels import QuotaPanel
from claude_usage.ui.app.presenter import QuotaView


class QuotaFrame(wx.Frame):
    def __init__(self, on_close: Callable[[], None]) -> None:
        super().__init__(
            None,
            title="Claude Usage",
            size=(320, 180),
            style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP,
        )
        self._on_close = on_close
        self.panel = QuotaPanel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.panel, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, self._handle_close)

    def show_view(self, view: QuotaView) -> None:
        self.panel.render(view)

    def _handle_close(self, event: wx.CloseEvent) -> None:
        self._on_close()
        event.Skip()
