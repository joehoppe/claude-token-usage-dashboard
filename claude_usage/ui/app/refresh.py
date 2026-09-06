"""One-shot refresh worker. Mirrors poller.py's threading rules: the spawn
and re-read run off the GUI thread, and only frozen data crosses back, via
call_after (wx.CallAfter in production, injectable for tests).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import wx

from claude_usage.infrastructure.claude_cli import QuotaRefresher, RefreshOutcome
from claude_usage.ui.app.presenter import QuotaView

# Copy for the "?" help button beside Refresh. The warning must name the
# exact command and the fact that it spends quota — refreshing is not free.
HELP_TOOLTIP = (
    'Refresh runs the Claude CLI (claude -p "/usage"), '
    "which itself uses a small amount of your usage quota."
)
HELP_DIALOG_TITLE = "About Refresh"
HELP_DIALOG_MESSAGE = (
    'Refresh launches the Claude CLI in the background (claude -p "/usage") '
    "so Claude Code updates its own quota cache. That call is a real, tiny "
    "Claude session, so each refresh consumes a small amount of your usage "
    "quota."
)


def outcome_tooltip(outcome: RefreshOutcome) -> str | None:
    """The button's whole outcome display: failures become a tooltip so a
    machine without `claude` on PATH does not fail silently; success clears
    it — the refreshed data speaks for itself.
    """
    if outcome is RefreshOutcome.REFRESHED:
        return None
    return f"Last refresh: {outcome.value}"


class RefreshWorker:
    def __init__(
        self,
        refresher: QuotaRefresher,
        read_view: Callable[[], QuotaView],
        deliver: Callable[[QuotaView, RefreshOutcome], None],
        call_after: Callable[..., Any] = wx.CallAfter,
    ) -> None:
        self._refresher = refresher
        self._read_view = read_view
        self._deliver = deliver
        self._call_after = call_after
        self._in_flight = threading.Lock()

    def start(self) -> bool:
        """Spawn one refresh thread; False and no-op if one is in flight.
        The disabled button is the primary guard — this refusal only keeps a
        programmatic double-fire from producing two child processes.
        """
        if not self._in_flight.acquire(blocking=False):
            return False
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self) -> None:
        # refresh() and read_view never raise (their contracts); the finally
        # keeps a broken contract from wedging start() shut forever. Released
        # before delivery: the run is over once the child exited and the
        # re-read finished.
        try:
            outcome = self._refresher.refresh()
            view = self._read_view()
        finally:
            self._in_flight.release()
        self._call_after(self._deliver, view, outcome)
