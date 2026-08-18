from datetime import datetime, timedelta, timezone

import pytest

from claude_usage.domain.quota import (
    LimitReading,
    QuotaReading,
    QuotaSnapshot,
    QuotaUnavailable,
)
from claude_usage.ui.cli.render import bar, render, render_row

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 18, 10, tzinfo=UTC)


def make_limit(**overrides):
    defaults = dict(
        kind="session",
        group="session",
        percent=25,
        severity="normal",
        is_active=False,
        resets_at=None,
        scope_model=None,
    )
    defaults.update(overrides)
    return LimitReading(**defaults)


def make_snapshot(limits, promos=(), measured_at=NOW - timedelta(minutes=5),
                  is_stale=False):
    reading = QuotaReading(
        measured_at=measured_at,
        limits=tuple(limits),
        promo_notices=tuple(promos),
    )
    return QuotaSnapshot(captured_at=NOW, quota=reading, is_stale=is_stale)


# --- bar ------------------------------------------------------------------

def test_bar_fill_rounding():
    assert bar(25) == "████" + "░" * 11
    assert bar(50) == "████████" + "░" * 7
    assert bar(75) == "███████████" + "░" * 4
    assert bar(0) == "░" * 15
    assert bar(100) == "█" * 15


def test_bar_clamps_out_of_range():
    assert bar(140) == "█" * 15
    assert bar(-5) == "░" * 15


def test_bar_ascii_glyphs():
    assert bar(50, ascii_glyphs=True) == "########" + "-" * 7


# --- rows -----------------------------------------------------------------

def test_row_without_resets_at_omits_countdown():
    row = render_row(make_limit(resets_at=None), NOW)
    assert "resets in" not in row
    assert "25%" in row


def test_row_with_countdown():
    limit = make_limit(resets_at=NOW + timedelta(hours=5))
    assert render_row(limit, NOW).endswith("resets in 5h")


def test_row_active_marker():
    row = render_row(make_limit(is_active=True), NOW)
    assert "● active" in row
    ascii_row = render_row(make_limit(is_active=True), NOW, ascii_glyphs=True)
    assert "○ active" in ascii_row


def test_row_overrange_percent_prints_raw_number_and_clamps_bar():
    row = render_row(make_limit(percent=140), NOW)
    assert "140%" in row
    assert "█" * 15 in row


def test_row_severity_selects_color():
    normal = render_row(make_limit(severity="normal"), NOW, color=True)
    warning = render_row(make_limit(severity="warning"), NOW, color=True)
    exceeded = render_row(make_limit(severity="exceeded"), NOW, color=True)
    assert "\x1b[32m" in normal
    assert "\x1b[33m" in warning
    assert "\x1b[31m" in exceeded


def test_row_no_ansi_when_color_off():
    assert "\x1b[" not in render_row(make_limit(severity="warning"), NOW)


# --- full render ----------------------------------------------------------

def test_render_preserves_source_order_not_percent_order():
    snapshot = make_snapshot(
        [
            make_limit(kind="weekly_all", percent=50),
            make_limit(kind="weekly_scoped", percent=75, scope_model="Fable"),
            make_limit(kind="session", percent=25),
        ]
    )
    lines = render(snapshot).splitlines()
    rows = [line for line in lines if "%" in line]
    assert "Weekly (7 day)" in rows[0]
    assert "Weekly Fable" in rows[1]
    assert "Session (5hr)" in rows[2]


def test_render_age_line_fresh():
    output = render(make_snapshot([make_limit()]), tz=UTC)
    assert output.splitlines()[0] == (
        "USAGE" + " " * 12 + "run 6:10 PM · data 5m ago · fresh"
    )


def test_render_age_line_stale():
    snapshot = make_snapshot(
        [make_limit()], measured_at=NOW - timedelta(hours=3), is_stale=True
    )
    header = render(snapshot, tz=UTC).splitlines()[0]
    assert "run 6:10 PM · data 3h ago · STALE" in header


def test_render_run_time_converts_to_given_timezone():
    snapshot = make_snapshot([make_limit()])
    header = render(snapshot, tz=timezone(timedelta(hours=-4))).splitlines()[0]
    assert "run 2:10 PM · data 5m ago" in header


def test_render_clock_wraps_past_midnight_to_twelve():
    # 18:10 UTC at UTC+6 is 00:10 the next day — must read 12:10 AM, not 0:10.
    snapshot = make_snapshot([make_limit()])
    header = render(snapshot, tz=timezone(timedelta(hours=6))).splitlines()[0]
    assert "run 12:10 AM" in header


def test_render_empty_limits():
    output = render(make_snapshot([]), tz=UTC)
    assert "no limits reported" in output
    assert "data 5m ago" in output


def test_render_promo_footnote():
    promo = "+50% weekly limits promo through Aug 19 · clau.de/cc-50-promo"
    output = render(make_snapshot([make_limit()], promos=[promo]))
    assert output.splitlines()[-1] == "  " + promo


def test_render_requires_quota():
    snapshot = QuotaSnapshot(captured_at=NOW, quota=None, is_stale=True)
    with pytest.raises(ValueError):
        render(snapshot)


def test_render_read_error_with_fallback_appends_note():
    reading = QuotaReading(
        measured_at=NOW - timedelta(hours=1), limits=(make_limit(),), promo_notices=()
    )
    snapshot = QuotaSnapshot(
        captured_at=NOW,
        quota=reading,
        is_stale=True,
        unavailable=QuotaUnavailable.READ_ERROR,
        detail="JSONDecodeError",
    )
    output = render(snapshot)
    assert "showing last known values (JSONDecodeError)" in output


# --- golden ---------------------------------------------------------------
# End-to-end through infrastructure + application + render with frozen time.
# Expected string built with explicit " " * n so column widths are unambiguous:
# rows are "  " + label.ljust(20) + marker.ljust(10) + pct.rjust(4)
#          + "  " + bar + "  resets in X".

from pathlib import Path

from claude_usage.application.usage import UsageService
from claude_usage.infrastructure.claude_json import ClaudeJsonQuotaSource

FIXTURE = Path(__file__).parent / "fixtures" / "live_snapshot.json"

GOLDEN = "\n".join(
    [
        "USAGE" + " " * 12 + "run 6:10 PM · data 5m ago · fresh",
        "",
        "  Session (5hr)" + " " * 18 + "25%  " + "█" * 4 + "░" * 11
        + "  resets in 5h",
        "  Weekly (7 day)" + " " * 17 + "50%  " + "█" * 8 + "░" * 7
        + "  resets in 1d",
        "  Weekly Fable" + " " * 8 + "● active" + " " * 3 + "75%  "
        + "█" * 11 + "░" * 4 + "  resets in 1d",
        "",
        "  +50% weekly limits promo through Aug 19 · clau.de/cc-50-promo",
    ]
)


class FrozenClock:
    def __init__(self, now):
        self._now = now

    def now(self):
        return self._now


def test_golden_reproduces_fixture_display():
    # Fixture fetchedAtMs = 2026-08-05T18:05:00Z; freeze "now" 5 minutes later.
    frozen = FrozenClock(datetime(2026, 8, 5, 18, 10, tzinfo=UTC))
    service = UsageService(ClaudeJsonQuotaSource(FIXTURE), frozen)
    assert render(service.snapshot(), tz=UTC) == GOLDEN
