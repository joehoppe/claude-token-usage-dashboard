"""wx.Frame composition root for the window: header, bar rows, footer via
QuotaPanel. STAY_ON_TOP, resizable, never steals focus on refresh (refresh
only repaints — it never calls Raise()/SetFocus()).
"""
from __future__ import annotations

from typing import Callable

import wx

from claude_usage.ui.app import theme
from claude_usage.ui.app.panels import QuotaPanel
from claude_usage.ui.app.presenter import QuotaView
from claude_usage.ui.app.refresh import (
    HELP_DIALOG_MESSAGE,
    HELP_DIALOG_TITLE,
    HELP_TOOLTIP,
)

_MIN_WIDTH = 240
_BUTTON_MARGIN = 8


class QuotaFrame(wx.Frame):
    def __init__(
        self,
        on_close: Callable[[], None],
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            None,
            title="Claude Usage",
            size=(356, 220),
            style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP,
        )
        self.SetBackgroundColour(wx.Colour(*theme.BACKGROUND))
        self._on_close = on_close
        self.panel = QuotaPanel(self)
        self._refresh_button: wx.Button | None = None
        self._help_button: wx.Button | None = None
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.panel, 1, wx.EXPAND)
        if on_refresh is not None:
            self._refresh_button = wx.Button(self, label="Refresh")
            self._refresh_button.Bind(wx.EVT_BUTTON, lambda event: on_refresh())
            # Pre-compute button size for both labels to prevent clipping on label change
            refresh_size = self._refresh_button.GetBestSize()
            self._refresh_button.SetLabel("Refreshing…")
            refreshing_size = self._refresh_button.GetBestSize()
            self._refresh_button.SetLabel("Refresh")
            # Set min size to the max of both dimensions
            max_width = max(refresh_size.width, refreshing_size.width)
            max_height = max(refresh_size.height, refreshing_size.height)
            self._refresh_button.SetMinSize(wx.Size(max_width, max_height))
            # The "?" warns that refreshing spends quota (tooltip for hover,
            # dialog for click) — it must be visible before the first click,
            # so it cannot live on the Refresh button's own tooltip, which
            # end_refresh() overwrites with failure outcomes.
            self._help_button = wx.Button(
                self, label="?", style=wx.BU_EXACTFIT
            )
            self._help_button.SetToolTip(HELP_TOOLTIP)
            self._help_button.Bind(wx.EVT_BUTTON, self._show_refresh_help)
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(self._refresh_button, 0)
            row.Add(
                self._help_button,
                0,
                wx.LEFT | wx.ALIGN_CENTER_VERTICAL,
                _BUTTON_MARGIN,
            )
            sizer.Add(row, 0, wx.ALL, _BUTTON_MARGIN)
        self.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, self._handle_close)

    def begin_refresh(self) -> None:
        """The disabled button is the entire in-progress UI (design §6)."""
        if self._refresh_button is None:
            return
        self._refresh_button.Disable()
        self._refresh_button.SetLabel("Refreshing…")

    def end_refresh(self, tooltip: str | None) -> None:
        if self._refresh_button is None:
            return
        self._refresh_button.SetLabel("Refresh")
        self._refresh_button.Enable()
        if tooltip is None:
            self._refresh_button.UnsetToolTip()
        else:
            self._refresh_button.SetToolTip(tooltip)

    def show_view(self, view: QuotaView) -> None:
        self._fit_to_content(view)
        self.panel.render(view)

    def _fit_to_content(self, view: QuotaView) -> None:
        """Grow the window when a view needs more room than it has, and hold
        that as the minimum. The constructor's height is only a starting
        guess — bar count varies per view, and the window chrome eats height
        the frame size does not account for, so a fixed height clips.

        Never shrinks: a size the user chose deliberately must stick.
        """
        needed = self.panel.content_height(view) + self._button_row_height()
        width, height = self.GetClientSize()
        self.SetMinClientSize((_MIN_WIDTH, needed))
        if height < needed:
            self.SetClientSize((width, needed))

    def _show_refresh_help(self, event: wx.CommandEvent) -> None:
        with wx.MessageDialog(
            self,
            HELP_DIALOG_MESSAGE,
            HELP_DIALOG_TITLE,
            style=wx.OK | wx.ICON_INFORMATION,
        ) as dialog:
            dialog.ShowModal()

    def _button_row_height(self) -> int:
        # Without this the button clips: content_height() covers only
        # QuotaPanel's drawing (design §6).
        if self._refresh_button is None:
            return 0
        heights = [self._refresh_button.GetMinSize().height]
        if self._help_button is not None:
            heights.append(self._help_button.GetMinSize().height)
        return max(heights) + 2 * _BUTTON_MARGIN

    def _handle_close(self, event: wx.CloseEvent) -> None:
        self._on_close()
        event.Skip()
