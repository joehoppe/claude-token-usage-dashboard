"""Composition root: config + adapters -> UsageService -> PollerThread ->
QuotaFrame -> wx.MainLoop. Config is read once at startup, not per poll.
"""
from __future__ import annotations

import wx

from claude_usage.application.usage import UsageService
from claude_usage.infrastructure.claude_json import ClaudeJsonQuotaSource
from claude_usage.infrastructure.clock import SystemClock
from claude_usage.infrastructure.config import TomlConfigSource
from claude_usage.ui.app.frame import QuotaFrame
from claude_usage.ui.app.poller import PollerThread

_JOIN_TIMEOUT_SECONDS = 2.0


def main() -> int:
    config = TomlConfigSource().read_config()
    service = UsageService(
        ClaudeJsonQuotaSource(), SystemClock(), stale_after=config.stale_after
    )

    app = wx.App()

    def handle_close() -> None:
        poller.stop()
        poller.join(timeout=_JOIN_TIMEOUT_SECONDS)

    frame = QuotaFrame(on_close=handle_close)
    poller = PollerThread(service, config, on_view=frame.show_view)

    # One synchronous refresh before Show() so the window never flashes empty.
    frame.show_view(poller.refresh_once())
    frame.Show()
    poller.start()
    app.MainLoop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
