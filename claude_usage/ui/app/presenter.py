"""Pure QuotaSnapshot + Config -> QuotaView. panels.py places strings and
draws rectangles; it computes nothing — every display decision is made here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from claude_usage.application.ports import Config
from claude_usage.domain.quota import (
    LimitReading,
    QuotaSnapshot,
    QuotaUnavailable,
    time_remaining,
)
from claude_usage.ui.shared.format import coarse, label_for

_SEVERITY = {"normal": "normal", "warning": "warning"}

# Fixed display order; unknown kinds sort after these, keeping input order.
_KIND_ORDER = {"session": 0, "weekly_all": 1, "weekly_scoped": 2}

_NO_DATA_MESSAGES = {
    QuotaUnavailable.NO_FILE: "Claude Code data not found",
    QuotaUnavailable.NO_QUOTA_KEY: "No quota data cached yet — click Refresh",
}

_READ_ERROR_MESSAGE = "Couldn't read quota data"


@dataclass(frozen=True)
class BarView:
    label: str               # "Weekly Fable"
    percent: int
    used: int                # percent clamped to 0–100, the number shown (SPEC §7.2)
    severity: str            # "normal" | "warning" | "critical"
    active: bool
    resets_text: str | None  # "resets in 3h"


@dataclass(frozen=True)
class QuotaView:
    headline: str              # "66% used"
    age_text: str              # "as of 7m ago"
    stale: bool
    bars: tuple[BarView, ...]  # fixed kind order: session, weekly, weekly fable
    notices: tuple[str, ...]
    message: str | None        # set only when there are no bars to show
    message_detail: str | None


def present(snapshot: QuotaSnapshot, config: Config) -> QuotaView:
    notices = list(config.warnings)
    quota = snapshot.quota

    if quota is None:
        message = _NO_DATA_MESSAGES.get(snapshot.unavailable, _READ_ERROR_MESSAGE)
        message_detail = (
            snapshot.detail
            if snapshot.unavailable is QuotaUnavailable.READ_ERROR
            else None
        )
        return QuotaView(
            headline="No data",
            age_text="no reading yet",
            stale=True,
            bars=(),
            notices=tuple(notices),
            message=message,
            message_detail=message_detail,
        )

    if snapshot.unavailable is QuotaUnavailable.READ_ERROR and snapshot.detail:
        notices.append(snapshot.detail)
    notices.extend(quota.promo_notices)

    binding = quota.binding()
    headline = (
        f"{_used(binding.percent)}% used" if binding else "No limits reported"
    )

    bars = tuple(
        _bar_view(limit, snapshot.captured_at)
        for limit in sorted(
            quota.limits,
            key=lambda limit: _KIND_ORDER.get(limit.kind, len(_KIND_ORDER)),
        )
    )

    age_text = f"as of {coarse(quota.age(snapshot.captured_at))} ago"
    if snapshot.is_stale:
        age_text += " · STALE"

    return QuotaView(
        headline=headline,
        age_text=age_text,
        stale=snapshot.is_stale,
        bars=bars,
        notices=tuple(notices),
        message=None,
        message_detail=None,
    )


def present_error(exc: Exception) -> QuotaView:
    """Fallback view when the poller loop itself raises — it must never die
    silently, which would freeze the display on a stale reading."""
    return QuotaView(
        headline="No data",
        age_text="no reading yet",
        stale=True,
        bars=(),
        notices=(),
        message=_READ_ERROR_MESSAGE,
        message_detail=type(exc).__name__,
    )


def _used(percent: int) -> int:
    return max(0, min(100, percent))


def _bar_view(limit: LimitReading, now: datetime) -> BarView:
    resets_in = time_remaining(limit.resets_at, now)
    return BarView(
        label=label_for(limit),
        percent=limit.percent,
        used=_used(limit.percent),
        severity=_SEVERITY.get(limit.severity, "critical"),
        active=limit.is_active,
        resets_text=f"resets in {coarse(resets_in)}" if resets_in is not None else None,
    )
