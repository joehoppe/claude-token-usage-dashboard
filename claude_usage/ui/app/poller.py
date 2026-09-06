"""Background poller. All file I/O and presenter logic run off the GUI
thread; only the frozen QuotaView crosses, via wx.CallAfter.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

import wx

from claude_usage.application.ports import Config
from claude_usage.application.usage import UsageService
from claude_usage.ui.app.presenter import QuotaView, present, present_error


class PollerThread(threading.Thread):
    def __init__(
        self,
        service: UsageService,
        config: Config,
        on_view: Callable[[QuotaView], None],
    ) -> None:
        super().__init__(daemon=True)
        self._service = service
        self._config = config
        self._on_view = on_view
        self._stop_event = threading.Event()

    def refresh_once(self) -> QuotaView:
        try:
            snapshot = self._service.snapshot()
            return present(snapshot, self._config)
        except Exception as exc:
            # A poller that dies silently would freeze the display on a
            # stale reading — precisely the failure this app prevents.
            return present_error(exc)

    def run(self) -> None:
        while not self._stop_event.is_set():
            view = self.refresh_once()
            wx.CallAfter(self._on_view, view)
            self._stop_event.wait(self._config.poll_seconds)

    def stop(self) -> None:
        self._stop_event.set()
