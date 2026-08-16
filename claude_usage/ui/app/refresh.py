"""One-shot refresh worker. Mirrors poller.py's threading rules: the spawn
and re-read run off the GUI thread, and only frozen data crosses back, via
call_after (wx.CallAfter in production, injectable for tests).
"""
from __future__ import annotations

import threading
from typing import Any, Callable

import wx

from claude_usage.infrastructure.claude_cli import QuotaRefresher, RefreshOutcome
from claude_usage.ui.app.presenter import QuotaView


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
