"""Pure QuotaSnapshot -> str. No I/O; the caller prints."""

from __future__ import annotations

from datetime import datetime, tzinfo

from claude_usage.domain.quota import (
    LimitReading,
    QuotaSnapshot,
    QuotaUnavailable,
    time_remaining,
)
from claude_usage.ui.shared.format import coarse, label_for

BAR_WIDTH = 15

# Colour maps from the severity field only — never from percentage thresholds.
_SEVERITY_COLORS = {"normal": "\x1b[32m", "warning": "\x1b[33m"}
_FALLBACK_COLOR = "\x1b[31m"
_ANSI_RESET = "\x1b[0m"


def bar(percent: int, ascii_glyphs: bool = False) -> str:
    clamped = max(0, min(100, percent))
    filled = (clamped * BAR_WIDTH + 50) // 100
    full, empty = ("#", "-") if ascii_glyphs else ("█", "░")
    return full * filled + empty * (BAR_WIDTH - filled)


def render_row(
    limit: LimitReading,
    now: datetime,
    *,
    color: bool = False,
    ascii_glyphs: bool = False,
) -> str:
    marker = ""
    if limit.is_active:
        marker = "○ active" if ascii_glyphs else "● active"
    bar_str = bar(limit.percent, ascii_glyphs)
    if color:
        code = _SEVERITY_COLORS.get(limit.severity, _FALLBACK_COLOR)
        bar_str = f"{code}{bar_str}{_ANSI_RESET}"
    percent_str = f"{limit.percent}%"
    row = f"  {label_for(limit):<20}{marker:<10}{percent_str:>4}  {bar_str}"
    remaining = time_remaining(limit.resets_at, now)
    if remaining is not None:
        row += f"  resets in {coarse(remaining)}"
    return row.rstrip()


def clock_time(moment: datetime, tz: tzinfo | None = None) -> str:
    """12-hour wall-clock time; avoids platform-specific strftime flags."""
    local = moment.astimezone(tz)
    meridiem = "PM" if local.hour >= 12 else "AM"
    return f"{local.hour % 12 or 12}:{local.minute:02d} {meridiem}"


def render(
    snapshot: QuotaSnapshot,
    *,
    color: bool = False,
    ascii_glyphs: bool = False,
    tz: tzinfo | None = None,
) -> str:
    quota = snapshot.quota
    if quota is None:
        raise ValueError("render() requires a snapshot with quota data")
    status = "STALE" if snapshot.is_stale else "fresh"
    age = coarse(quota.age(snapshot.captured_at))
    run_at = clock_time(snapshot.captured_at, tz)
    header = f"USAGE{' ' * 12}run {run_at} · data {age} ago · {status}"
    lines = [header, ""]
    if quota.limits:
        for limit in quota.limits:
            lines.append(
                render_row(limit, snapshot.captured_at, color=color, ascii_glyphs=ascii_glyphs)
            )
    else:
        lines.append("  no limits reported")
    if snapshot.unavailable is QuotaUnavailable.READ_ERROR and snapshot.detail:
        lines.append("")
        lines.append(f"  note: showing last known values ({snapshot.detail})")
    if quota.promo_notices:
        lines.append("")
        lines.extend(f"  {notice}" for notice in quota.promo_notices)
    return "\n".join(lines)
