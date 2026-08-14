"""Draws a QuotaView with wx.PaintDC rectangles (wx.Gauge can't be coloured
per-severity portably). Places strings and rectangles; computes nothing —
all display decisions were already made by presenter.present().

Colors come from theme.py and are painted explicitly so the window looks the
same on every platform instead of inheriting OS widget colors.
"""
from __future__ import annotations

import wx

from claude_usage.ui.app import theme
from claude_usage.ui.app.presenter import BarView, QuotaView

_BACKGROUND = wx.Colour(*theme.BACKGROUND)
_TEXT_PRIMARY = wx.Colour(*theme.TEXT_PRIMARY)
_TEXT_SECONDARY = wx.Colour(*theme.TEXT_SECONDARY)
_TRACK_COLOR = wx.Colour(*theme.TRACK)
_STALE_COLOR = wx.Colour(*theme.STALE_FILL)
_SEVERITY_COLORS = {
    severity: wx.Colour(*rgb) for severity, rgb in theme.SEVERITY_FILLS.items()
}
_BAR_HEIGHT = 18
_ROW_HEIGHT = 40
_MARGIN = 8
_LINE_HEIGHT = 18     # header lines and message lines
_NOTICE_HEIGHT = 16   # footer notice lines
_HEADER_HEIGHT = _MARGIN + 44


class QuotaPanel(wx.Panel):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(_BACKGROUND)
        self._view: QuotaView | None = None
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def render(self, view: QuotaView) -> None:
        self._view = view
        self.Refresh()

    def content_height(self, view: QuotaView) -> int:
        """Pixels this view needs to draw without clipping. The frame asks
        before rendering — bar count varies per view, so a fixed window
        height would clip whenever a limit is added.
        """
        height = _HEADER_HEIGHT
        if view.message is not None:
            height += _LINE_HEIGHT * (2 if view.message_detail else 1)
        else:
            height += _ROW_HEIGHT * len(view.bars)
            height += _NOTICE_HEIGHT * len(view.notices)
        return height + _MARGIN

    def _on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.PaintDC(self)
        dc.SetBackground(wx.Brush(_BACKGROUND))
        dc.Clear()
        view = self._view
        if view is None:
            return
        y = self._draw_header(dc, view)
        if view.message is not None:
            self._draw_message(dc, view, y)
            return
        for bar in view.bars:
            y = self._draw_bar(dc, bar, y, greyed=view.stale)
        self._draw_footer(dc, view, y)

    def _draw_header(self, dc: wx.DC, view: QuotaView) -> int:
        base_font = self.GetFont()
        dc.SetFont(base_font.Bold())
        dc.SetTextForeground(_TEXT_PRIMARY)
        dc.DrawText(view.headline, _MARGIN, _MARGIN)
        dc.SetFont(base_font)
        dc.SetTextForeground(_TEXT_SECONDARY)
        dc.DrawText(view.age_text, _MARGIN, _MARGIN + _LINE_HEIGHT)
        return _HEADER_HEIGHT

    def _draw_message(self, dc: wx.DC, view: QuotaView, y: int) -> None:
        dc.SetTextForeground(_TEXT_PRIMARY)
        dc.DrawText(view.message, _MARGIN, y)
        if view.message_detail:
            dc.SetTextForeground(_TEXT_SECONDARY)
            dc.DrawText(view.message_detail, _MARGIN, y + 18)

    def _draw_bar(
        self, dc: wx.DC, bar: BarView, y: int, *, greyed: bool
    ) -> int:
        width = max(0, self.GetClientSize().width - 2 * _MARGIN)
        filled = int(width * max(0, min(100, bar.percent)) / 100)
        color = _STALE_COLOR if greyed else _SEVERITY_COLORS.get(
            bar.severity, _SEVERITY_COLORS["critical"]
        )
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(_TRACK_COLOR))
        dc.DrawRectangle(_MARGIN, y, width, _BAR_HEIGHT)
        dc.SetBrush(wx.Brush(color))
        dc.DrawRectangle(_MARGIN, y, filled, _BAR_HEIGHT)

        label = f"{bar.label}  {bar.remaining}%"
        if bar.active:
            label += "  ●"
        if bar.resets_text:
            label += f"  {bar.resets_text}"
        dc.SetTextForeground(_TEXT_PRIMARY)
        dc.DrawText(label, _MARGIN, y + _BAR_HEIGHT + 2)
        return y + _ROW_HEIGHT

    def _draw_footer(self, dc: wx.DC, view: QuotaView, y: int) -> None:
        dc.SetTextForeground(_TEXT_SECONDARY)
        for notice in view.notices:
            dc.DrawText(notice, _MARGIN, y)
            y += 16
