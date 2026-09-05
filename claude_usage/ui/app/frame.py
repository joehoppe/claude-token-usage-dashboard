"""wx.Frame composition root for the window: a top row (headline, age text,
Refresh/help buttons), then bar rows and footer via QuotaPanel. STAY_ON_TOP,
resizable, never steals focus on refresh (refresh only repaints — it never
calls Raise()/SetFocus()).
"""
from __future__ import annotations

from typing import Callable

import wx

from claude_usage.ui.app import theme
from claude_usage.ui.app.help_dialog import HelpDialog
from claude_usage.ui.app.panels import QuotaPanel
from claude_usage.ui.app.presenter import QuotaView
from claude_usage.ui.app.refresh import HELP_TOOLTIP

_MIN_WIDTH = 240
# Opening size of the window. Narrow on purpose: this is a glanceable side
# panel meant to park beside real work, not a document window. The height is
# only a starting guess — _fit_to_content() grows it to whatever the current
# view needs (see below).
_DEFAULT_SIZE = (377, 216)
_BUTTON_MARGIN = 8
# Extra horizontal breathing room for the exact-fit "?" button.
_HELP_BUTTON_PADDING = 6


class QuotaFrame(wx.Frame):
    def __init__(
        self,
        on_close: Callable[[], None],
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            None,
            title="Usage Dashboard for Claude",
            size=_DEFAULT_SIZE,
            style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP,
        )
        self.SetBackgroundColour(wx.Colour(*theme.BACKGROUND))
        self._on_close = on_close
        self.panel = QuotaPanel(self)
        self._refresh_button: wx.Button | None = None
        self._help_button: wx.Button | None = None
        self._headline_text = wx.StaticText(self, label="")
        self._headline_text.SetFont(self._headline_text.GetFont().Bold())
        self._headline_text.SetForegroundColour(wx.Colour(*theme.TEXT_PRIMARY))
        self._age_text = wx.StaticText(self, label="")
        self._age_text.SetForegroundColour(wx.Colour(*theme.TEXT_SECONDARY))
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self._headline_text, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(
            self._age_text,
            0,
            wx.LEFT | wx.ALIGN_CENTER_VERTICAL,
            _BUTTON_MARGIN,
        )
        row.AddStretchSpacer(1)
        sizer = wx.BoxSizer(wx.VERTICAL)
        if on_refresh is not None:
            self._refresh_button = wx.Button(self, label="Refresh")
            self._refresh_button.Bind(wx.EVT_BUTTON, lambda event: on_refresh())
            # Pre-compute the size of both labels so a label change never
            # clips: min size is the max of both dimensions.
            refresh_size = self._refresh_button.GetBestSize()
            self._refresh_button.SetLabel("Refreshing…")
            refreshing_size = self._refresh_button.GetBestSize()
            self._refresh_button.SetLabel("Refresh")
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
            # BU_EXACTFIT hugs the "?" glyph too tightly to read as a button,
            # so widen it a little without touching the exact-fit height.
            help_size = self._help_button.GetBestSize()
            self._help_button.SetMinSize(
                wx.Size(help_size.width + _HELP_BUTTON_PADDING, help_size.height)
            )
            self._help_button.SetToolTip(HELP_TOOLTIP)
            self._help_button.Bind(wx.EVT_BUTTON, self._show_refresh_help)
            row.Add(self._refresh_button, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(
                self._help_button,
                0,
                wx.LEFT | wx.ALIGN_CENTER_VERTICAL,
                _BUTTON_MARGIN,
            )
        sizer.Add(row, 0, wx.EXPAND | wx.ALL, _BUTTON_MARGIN)
        sizer.Add(self.panel, 1, wx.EXPAND)
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
        self._headline_text.SetLabel(view.headline)
        self._age_text.SetLabel(view.age_text)
        self.Layout()  # label widths changed; re-place the top row
        self._fit_to_content(view)
        self.panel.render(view)

    def _fit_to_content(self, view: QuotaView) -> None:
        """Grow the window when a view needs more room than it has, and hold
        that as the minimum. The constructor's height is only a starting
        guess — bar count varies per view, and the window chrome eats height
        the frame size does not account for, so a fixed height clips.

        Never shrinks: a size the user chose deliberately must stick.
        """
        needed = self.panel.content_height(view) + self._top_row_height()
        width, height = self.GetClientSize()
        self.SetMinClientSize((_MIN_WIDTH, needed))
        if height < needed:
            self.SetClientSize((width, needed))

    def _show_refresh_help(self, event: wx.CommandEvent) -> None:
        with HelpDialog(self) as dialog:
            dialog.ShowModal()

    def _top_row_height(self) -> int:
        # Without this the top row clips: content_height() covers only
        # QuotaPanel's drawing (design §6).
        heights = [
            self._headline_text.GetBestSize().height,
            self._age_text.GetBestSize().height,
        ]
        if self._refresh_button is not None:
            heights.append(self._refresh_button.GetMinSize().height)
        if self._help_button is not None:
            heights.append(self._help_button.GetMinSize().height)
        return max(heights) + 2 * _BUTTON_MARGIN

    def _handle_close(self, event: wx.CloseEvent) -> None:
        self._on_close()
        event.Skip()
