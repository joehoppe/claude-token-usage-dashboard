"""RefreshWorker tests — fakes only: no wx.App, no subprocess, no sleeping.
Coordination uses events with timeouts, never sleep(). Importing refresh.py
imports the wx module (for the call_after default); no widget is created.
"""
import threading

from claude_usage.infrastructure.claude_cli import RefreshOutcome
from claude_usage.ui.app.refresh import RefreshWorker, outcome_tooltip

VIEW = object()  # the worker never inspects the view; identity is enough


class ScriptedRefresher:
    def __init__(self, outcome, gate=None):
        self.calls = 0
        self._outcome = outcome
        self._gate = gate

    def refresh(self):
        self.calls += 1
        if self._gate is not None:
            assert self._gate.wait(timeout=5), "test gate never opened"
        return self._outcome


class RecordingDeliver:
    def __init__(self):
        self.received = []
        self.done = threading.Event()

    def __call__(self, view, outcome):
        self.received.append((view, outcome))
        self.done.set()


class RecordingCallAfter:
    """Synchronous stand-in for wx.CallAfter that proves it was the path."""

    def __init__(self):
        self.calls = 0

    def __call__(self, fn, *args):
        self.calls += 1
        fn(*args)


def make_worker(refresher, deliver):
    call_after = RecordingCallAfter()
    worker = RefreshWorker(
        refresher=refresher,
        read_view=lambda: VIEW,
        deliver=deliver,
        call_after=call_after,
    )
    return worker, call_after


def test_refreshes_reads_and_delivers_through_call_after():
    refresher = ScriptedRefresher(RefreshOutcome.REFRESHED)
    deliver = RecordingDeliver()
    worker, call_after = make_worker(refresher, deliver)
    assert worker.start() is True
    assert deliver.done.wait(timeout=5)
    assert refresher.calls == 1
    assert deliver.received == [(VIEW, RefreshOutcome.REFRESHED)]
    assert call_after.calls == 1  # delivered via call_after, never directly


def test_non_refreshed_outcome_delivered_verbatim():
    refresher = ScriptedRefresher(RefreshOutcome.NOT_FOUND)
    deliver = RecordingDeliver()
    worker, _ = make_worker(refresher, deliver)
    worker.start()
    assert deliver.done.wait(timeout=5)
    assert deliver.received == [(VIEW, RefreshOutcome.NOT_FOUND)]


def test_start_refuses_reentry_while_in_flight():
    gate = threading.Event()
    refresher = ScriptedRefresher(RefreshOutcome.REFRESHED, gate=gate)
    deliver = RecordingDeliver()
    worker, _ = make_worker(refresher, deliver)
    assert worker.start() is True
    assert worker.start() is False       # programmatic double-fire: refused
    gate.set()
    assert deliver.done.wait(timeout=5)
    assert refresher.calls == 1          # the refusal spawned nothing


def test_start_works_again_after_completion():
    refresher = ScriptedRefresher(RefreshOutcome.REFRESHED)
    deliver = RecordingDeliver()
    worker, _ = make_worker(refresher, deliver)
    assert worker.start() is True
    assert deliver.done.wait(timeout=5)
    deliver.done.clear()
    assert worker.start() is True
    assert deliver.done.wait(timeout=5)
    assert refresher.calls == 2


def test_outcome_tooltip_maps_failures_and_clears_success():
    assert outcome_tooltip(RefreshOutcome.REFRESHED) is None
    assert outcome_tooltip(RefreshOutcome.NOT_FOUND) == "Last refresh: not_found"
    assert outcome_tooltip(RefreshOutcome.TIMED_OUT) == "Last refresh: timed_out"
    assert outcome_tooltip(RefreshOutcome.FAILED) == "Last refresh: failed"
