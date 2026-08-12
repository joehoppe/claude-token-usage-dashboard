"""Draws a QuotaView with wx.PaintDC rectangles (wx.Gauge can't be coloured
per-severity portably). Places strings and rectangles; computes nothing —
all display decisions were already made by presenter.present().
"""
from __future__ import annotations

import wx

from claude_usage.ui.app.presenter import BarView, QuotaView

_SEVERITY_COLORS = {
    "normal": wx.Colour(60, 179, 60),
    "warning": wx.Colour(224, 168, 0),
    "critical": wx.Colour(200, 50, 50),
}
_STALE_COLOR = wx.Colour(150, 150, 150)
_TRACK_COLOR = wx.Colour(230, 230, 230)
_BAR_HEIGHT = 18
_ROW_HEIGHT = 40
_MARGIN = 8


class QuotaPanel(wx.Panel):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self._view: QuotaView | None = None
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def render(self, view: QuotaView) -> None:
        self._view = view
        self.Refresh()

    def _on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.PaintDC(self)
        view = self._view
        if view is None:
            return
        dc.Clear()
        y = self._draw_header(dc, view)
        if view.message is not None:
            self._draw_message(dc, view, y)
            return
        for bar in view.bars:
            y = self._draw_bar(dc, bar, y, greyed=view.stale)
        self._draw_footer(dc, view, y)

    def _draw_header(self, dc: wx.DC, view: QuotaView) -> int:
        dc.SetTextForeground(wx.BLACK)
        dc.DrawText(view.headline, _MARGIN, _MARGIN)
        dc.DrawText(view.age_text, _MARGIN, _MARGIN + 18)
        return _MARGIN + 44

    def _draw_message(self, dc: wx.DC, view: QuotaView, y: int) -> None:
        dc.DrawText(view.message, _MARGIN, y)
        if view.message_detail:
            dc.DrawText(view.message_detail, _MARGIN, y + 18)

    def _draw_bar(self, dc: wx.DC, bar: BarView, y: int, *, greyed: bool) -> int:
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
        dc.SetTextForeground(wx.BLACK)
        dc.DrawText(label, _MARGIN, y + _BAR_HEIGHT + 2)
        return y + _ROW_HEIGHT

    def _draw_footer(self, dc: wx.DC, view: QuotaView, y: int) -> None:
        dc.SetTextForeground(wx.Colour(90, 90, 90))
        for notice in view.notices:
            dc.DrawText(notice, _MARGIN, y)
            y += 16
