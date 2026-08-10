"""Pure QuotaSnapshot -> str. No I/O; the caller prints."""
from __future__ import annotations

from datetime import datetime, timedelta

from claude_usage.domain.quota import LimitReading, QuotaSnapshot, time_remaining

BAR_WIDTH = 15

_KIND_LABELS = {"session": "Session (5hr)", "weekly_all": "Weekly (7 day)"}

# Colour maps from the severity field only — never from percentage thresholds.
_SEVERITY_COLORS = {"normal": "\x1b[32m", "warning": "\x1b[33m"}
_FALLBACK_COLOR = "\x1b[31m"
_ANSI_RESET = "\x1b[0m"


def label_for(limit: LimitReading) -> str:
    if limit.kind == "weekly_scoped" and limit.scope_model:
        return f"Weekly {limit.scope_model}"
    if limit.kind in _KIND_LABELS:
        return _KIND_LABELS[limit.kind]
    # Fallback is load-bearing: new limit kinds must render, not crash.
    label = limit.kind.replace("_", " ").title()
    if limit.scope_model:
        label = f"{label} {limit.scope_model}"
    return label


def bar(percent: int, ascii_glyphs: bool = False) -> str:
    clamped = max(0, min(100, percent))
    filled = (clamped * BAR_WIDTH + 50) // 100
    full, empty = ("#", "-") if ascii_glyphs else ("█", "░")
    return full * filled + empty * (BAR_WIDTH - filled)


def coarse(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 60:
        return "<1m"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    return f"{total // 86400}d"


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


def render(
    snapshot: QuotaSnapshot, *, color: bool = False, ascii_glyphs: bool = False
) -> str:
    quota = snapshot.quota
    if quota is None:
        raise ValueError("render() requires a snapshot with quota data")
    status = "STALE" if snapshot.is_stale else "fresh"
    age = coarse(quota.age(snapshot.captured_at))
    lines = [f"USAGE{' ' * 32}as of {age} ago · {status}", ""]
    if quota.limits:
        for limit in quota.limits:
            lines.append(
                render_row(
                    limit, snapshot.captured_at, color=color, ascii_glyphs=ascii_glyphs
                )
            )
    else:
        lines.append("  no limits reported")
    if quota.promo_notices:
        lines.append("")
        lines.extend(f"  {notice}" for notice in quota.promo_notices)
    return "\n".join(lines)
