"""Composition root: config + adapters -> UsageService -> PollerThread ->
QuotaFrame -> wx.MainLoop. Config is read once at startup, not per poll.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import wx

from claude_usage.application.usage import UsageService
from claude_usage.infrastructure.claude_json import ClaudeJsonQuotaSource
from claude_usage.infrastructure.clock import SystemClock
from claude_usage.infrastructure.config import TomlConfigSource
from claude_usage.ui.app.frame import QuotaFrame
from claude_usage.ui.app.poller import PollerThread

_JOIN_TIMEOUT_SECONDS = 2.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-usage-app",
        description="Always-on-top window showing Claude Code quota usage.",
    )
    parser.add_argument(
        "--path", type=Path, default=None,
        help="read an alternate .claude.json (fixtures, testing)",
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="read an alternate config.toml (fixtures, testing)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = TomlConfigSource(args.config).read_config()
    service = UsageService(
        ClaudeJsonQuotaSource(args.path), SystemClock(), stale_after=config.stale_after
    )

    app = wx.App()
    # `on_close` closes over `poller`, assigned on the next line — safe
    # because the callback only runs after the user closes the window, by
    # which point `poller` is bound.
    frame = QuotaFrame(on_close=lambda: poller.stop())
    poller = PollerThread(service, config, on_view=frame.show_view)

    frame.show_view(poller.refresh_once())  # one synchronous pass first —
    poller.start()                          # the window never flashes empty
    frame.Show()
    app.MainLoop()

    # Joined after MainLoop rather than inside on_close: the close handler
    # runs on the GUI thread, and blocking it there stalls teardown.
    poller.stop()
    poller.join(timeout=_JOIN_TIMEOUT_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
