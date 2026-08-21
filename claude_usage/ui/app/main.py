"""Composition root: config + adapters -> UsageService -> PollerThread ->
QuotaFrame -> wx.MainLoop. Config is read once at startup, not per poll.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import wx

from claude_usage.application.usage import UsageService
from claude_usage.infrastructure.claude_cli import ClaudeCliRefresher
from claude_usage.infrastructure.claude_json import ClaudeJsonQuotaSource
from claude_usage.infrastructure.clock import SystemClock
from claude_usage.infrastructure.config import TomlConfigSource
from claude_usage.ui.app.frame import QuotaFrame
from claude_usage.ui.app.icon import attach_app_icon, set_app_user_model_id
from claude_usage.ui.app.poller import PollerThread
from claude_usage.ui.app.refresh import RefreshWorker, outcome_tooltip

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


def _enable_dark_titlebar(app: wx.App) -> None:
    """Paint the native title bar dark to match the forced dark content.

    Must run before any window exists. `DarkMode_Always` rather than
    `DarkMode_Auto`: theme.py forces a dark palette whatever the OS theme is,
    so the title bar must not flip to light under a light Windows theme.
    No-op off MSW, where neither name exists — hence the getattr pair rather
    than direct attribute access.
    """
    enable = getattr(app, "MSWEnableDarkMode", None)
    always = getattr(wx.App, "DarkMode_Always", None)
    if enable is not None and always is not None:
        enable(always)


def main(argv: list[str] | None = None) -> int:
    # Before anything can create a window: the taskbar button takes its icon
    # from the process AppUserModelID, and that is read once, at creation.
    set_app_user_model_id()

    args = build_parser().parse_args(argv)
    config = TomlConfigSource(args.config).read_config()
    service = UsageService(
        ClaudeJsonQuotaSource(args.path), SystemClock(), stale_after=config.stale_after
    )

    app = wx.App()
    _enable_dark_titlebar(app)

    def on_refresh() -> None:
        # Closes over `worker`, assigned below — safe because the callback
        # only fires on a button click, after wiring completes. If start()
        # is refused (a run is in flight), the in-flight run's delivery
        # re-enables the button.
        frame.begin_refresh()
        worker.start()

    # `on_close` closes over `poller`, assigned on the next line — safe
    # because the callback only runs after the user closes the window, by
    # which point `poller` is bound.
    frame = QuotaFrame(on_close=lambda: poller.stop(), on_refresh=on_refresh)
    poller = PollerThread(service, config, on_view=frame.show_view)

    def deliver(view, outcome) -> None:
        frame.show_view(view)
        frame.end_refresh(outcome_tooltip(outcome))

    worker = RefreshWorker(
        ClaudeCliRefresher(
            executable=config.claude_executable,
            timeout_seconds=config.refresh_timeout_seconds,
        ),
        read_view=poller.refresh_once,
        deliver=deliver,
    )

    # Held until MainLoop exits: dropping the TaskBarIcon reverts the Dock tile.
    dock_icon = attach_app_icon(frame)

    frame.show_view(poller.refresh_once())  # one synchronous pass first —
    poller.start()                          # the window never flashes empty
    frame.Show()
    app.MainLoop()

    if dock_icon is not None:
        dock_icon.Destroy()

    # Joined after MainLoop rather than inside on_close: the close handler
    # runs on the GUI thread, and blocking it there stalls teardown.
    poller.stop()
    poller.join(timeout=_JOIN_TIMEOUT_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
