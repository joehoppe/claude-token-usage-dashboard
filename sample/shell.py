"""Outer rings of the onion: infrastructure, presentation, wiring.

This is the only file that knows wxPython exists, the only file that
touches the filesystem, and the only file that starts a thread. All three
are *details* — swapping JSONL for SQLite, or wx for Qt, changes this file
and nothing in ``core.py``.

Run it::

    pip install wxPython
    python sample/shell.py

Requires Python 3.10+ (PEP 604 ``X | None`` annotations).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import wx

from core import (
    DashboardService,
    LimitReading,
    ModelRate,
    PricingTable,
    QuotaReading,
    Snapshot,
    UsageRecord,
)

# ---------------------------------------------------------------------------
# Configuration — rates go stale, so they live at the edge, stamped with a
# date the UI displays (SPEC.md §6.4).
# ---------------------------------------------------------------------------

PRICING_AS_OF = "2026-06-24"
PRICING_RATES = {
    "claude-fable-5": ModelRate(10.00, 50.00),
    "claude-mythos-5": ModelRate(10.00, 50.00),
    "claude-opus-5": ModelRate(5.00, 25.00),
    "claude-opus-4-8": ModelRate(5.00, 25.00),
    "claude-sonnet-5": ModelRate(3.00, 15.00),
    "claude-sonnet-4-6": ModelRate(3.00, 15.00),
    "claude-haiku-4-5": ModelRate(1.00, 5.00),
}

TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
QUOTA_FILE = Path.home() / ".claude.json"  # sibling of .claude/, not inside
POLL_SECONDS = 5.0

# ---------------------------------------------------------------------------
# Infrastructure — adapters that satisfy core.py's ports.
# ---------------------------------------------------------------------------


class SystemClock:
    """Injected so tests can freeze time without patching anything."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def _parse_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


class JsonlUsageSource:
    """Reads token usage out of Claude Code's transcript files.

    Satisfies ``core.UsageSource`` structurally — no base class and no
    registration, so ``core.py`` never learns this type's name.
    """

    def __init__(self, root: Path = TRANSCRIPT_ROOT) -> None:
        self._root = root

    def read_usage(self) -> Iterator[UsageRecord]:
        if not self._root.is_dir():
            return
        for transcript in self._root.rglob("*.jsonl"):
            yield from self._read_file(transcript)

    def _read_file(self, path: Path) -> Iterator[UsageRecord]:
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError:
            return
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    # Transcripts are append-only and actively written, so
                    # a trailing line may be a partial write (SPEC.md §3).
                    continue
                record = self._to_record(raw)
                if record is not None:
                    yield record

    @staticmethod
    def _to_record(raw: dict) -> UsageRecord | None:
        if raw.get("type") != "assistant":
            return None
        message = raw.get("message") or {}
        usage = message.get("usage") or {}
        message_id = message.get("id")
        if not message_id or not usage:
            return None

        try:
            timestamp = _parse_timestamp(raw["timestamp"])
        except (KeyError, ValueError):
            return None

        # Branch on the cache_creation sub-fields rather than the flat
        # total: 2.00x vs 1.25x is a material spread (SPEC.md §6.4).
        created = usage.get("cache_creation") or {}
        return UsageRecord(
            message_id=message_id,
            model=message.get("model", "<unknown>"),
            timestamp=timestamp,
            input_tokens=usage.get("input_tokens") or 0,
            output_tokens=usage.get("output_tokens") or 0,
            cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
            cache_creation_5m_tokens=(
                created.get("ephemeral_5m_input_tokens") or 0
            ),
            cache_creation_1h_tokens=(
                created.get("ephemeral_1h_input_tokens") or 0
            ),
        )


class ClaudeJsonQuotaSource:
    """Reads the quota cache Claude Code maintains. Never authenticates."""

    def __init__(self, path: Path = QUOTA_FILE) -> None:
        self._path = path

    def read_quota(self) -> QuotaReading | None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        cached = raw.get("cachedUsageUtilization") or {}
        fetched_at_ms = cached.get("fetchedAtMs")
        if not fetched_at_ms:
            return None

        # Read limits[], not the named keys: the sibling keys are a
        # churning feature-flag surface, while limits[] grows uniformly
        # as new limit kinds arrive (SPEC.md §4.2).
        entries = (cached.get("utilization") or {}).get("limits") or []
        limits = tuple(
            limit
            for limit in (self._to_limit(entry) for entry in entries)
            if limit is not None
        )
        return QuotaReading(
            measured_at=datetime.fromtimestamp(
                fetched_at_ms / 1000, tz=timezone.utc
            ),
            limits=limits,
        )

    @staticmethod
    def _to_limit(entry: dict) -> LimitReading | None:
        percent = entry.get("percent")
        if percent is None:
            return None
        scope = entry.get("scope") or {}
        model = scope.get("model") or {}
        return LimitReading(
            kind=entry.get("kind", "unknown"),
            percent=int(percent),
            severity=entry.get("severity", "normal"),
            is_active=bool(entry.get("is_active")),
            scope_label=model.get("display_name"),
        )


# ---------------------------------------------------------------------------
# Presentation — the outer ring owns concurrency so the core stays sync.
# ---------------------------------------------------------------------------


class SnapshotPoller(threading.Thread):
    """Runs ``DashboardService.snapshot()`` off the GUI thread.

    All file I/O and JSON parsing happens here; results reach the GUI
    *only* as an immutable ``Snapshot`` handed over by ``wx.CallAfter``.
    Parsing on the GUI thread visibly stalls the window (SPEC.md §5.1).
    """

    def __init__(
        self, service: DashboardService, frame: "DashboardFrame"
    ) -> None:
        super().__init__(daemon=True, name="snapshot-poller")
        self._service = service
        self._frame = frame
        self._stopped = threading.Event()

    def run(self) -> None:
        while not self._stopped.is_set():
            try:
                snapshot = self._service.snapshot()
            except Exception as exc:  # a crashed poller must not kill the app
                wx.CallAfter(self._frame.show_error, str(exc))
            else:
                wx.CallAfter(self._frame.show_snapshot, snapshot)
            self._stopped.wait(POLL_SECONDS)

    def stop(self) -> None:
        self._stopped.set()


class DashboardFrame(wx.Frame):
    """Renders a ``Snapshot``. Knows nothing of files, JSON, or pricing.

    Its only inward dependency is ``DashboardService`` — handed in, not
    constructed here, so the frame cannot reach past it to the filesystem.
    """

    def __init__(self, service: DashboardService) -> None:
        super().__init__(
            None,
            title="Usage Dashboard for Claude",
            style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP,
        )
        panel = wx.Panel(self)

        self._quota_text = wx.StaticText(panel, label="Reading quota…")
        self._quota_text.SetFont(self._quota_text.GetFont().Bold())
        self._token_text = wx.StaticText(panel, label="Scanning…")

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(
            wx.StaticText(panel, label="Remaining quota"), 0, wx.ALL, 8
        )
        sizer.Add(
            self._quota_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8
        )
        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 4)
        sizer.Add(
            wx.StaticText(panel, label="Tokens by model"), 0, wx.ALL, 8
        )
        sizer.Add(
            self._token_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8
        )
        panel.SetSizer(sizer)

        self.CreateStatusBar()
        self.SetStatusText("Starting…")
        self.SetMinSize((380, 320))
        self.SetSize((380, 400))

        self._poller = SnapshotPoller(service, self)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._poller.start()

    # -- called on the GUI thread via wx.CallAfter -------------------------

    def show_snapshot(self, snapshot: Snapshot) -> None:
        self._quota_text.SetLabel(self._format_quota(snapshot))
        self._token_text.SetLabel(self._format_tokens(snapshot))
        self.SetStatusText(self._format_status(snapshot))
        self.Layout()

    def show_error(self, message: str) -> None:
        self.SetStatusText(f"Error: {message}")

    # -- formatting: presentation's concern, kept out of the core ----------

    @staticmethod
    def _format_quota(snapshot: Snapshot) -> str:
        quota = snapshot.quota
        if quota is None or not quota.limits:
            return "No quota cache found"
        ranked = sorted(
            quota.limits, key=lambda item: item.percent, reverse=True
        )
        return "\n".join(
            f"{limit.percent:>3}%  {limit.label}"
            + ("  ←active" if limit.is_active else "")
            for limit in ranked
        )

    @staticmethod
    def _format_tokens(snapshot: Snapshot) -> str:
        if not snapshot.model_totals:
            return "No usage records found"
        lines = [
            f"{total.tokens:>12,}  {total.model}"
            + ("" if total.is_priced else "  (unpriced)")
            for total in snapshot.model_totals
        ]
        cost = format(snapshot.total_cost_usd, ",.2f")
        lines.append("")
        lines.append(f"{snapshot.total_tokens:>12,}  total")
        lines.append(f"{'$' + cost:>13}  at {PRICING_AS_OF} rates")
        return "\n".join(lines)

    @staticmethod
    def _format_status(snapshot: Snapshot) -> str:
        # Staleness is always shown: a stale reading rendered as live is
        # the primary correctness risk (SPEC.md §3, §7.3).
        if snapshot.quota is None:
            return "quota unavailable"
        age = snapshot.quota.age(snapshot.captured_at)
        minutes = int(age.total_seconds() // 60)
        freshness = "STALE" if snapshot.quota_is_stale else "fresh"
        return (
            f"{freshness} — quota read {minutes}m ago · "
            f"{snapshot.records_counted:,} records "
            f"({snapshot.duplicates_skipped:,} duplicates skipped)"
        )

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._poller.stop()
        event.Skip()


# ---------------------------------------------------------------------------
# Composition root — the one place allowed to know every concrete type.
#
# Wiring lives here and only here. Every class above receives its
# collaborators; none reach out for one. That is what makes the inner
# rings testable without a filesystem, a clock, or a display.
# ---------------------------------------------------------------------------


def main() -> None:
    service = DashboardService(
        usage_source=JsonlUsageSource(),
        quota_source=ClaudeJsonQuotaSource(),
        pricing=PricingTable(rates=PRICING_RATES, as_of=PRICING_AS_OF),
        clock=SystemClock(),
    )
    app = wx.App(False)
    DashboardFrame(service).Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
