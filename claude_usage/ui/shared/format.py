"""Formatting helpers shared by both drivers. Pure — no wx, no ANSI."""
from __future__ import annotations

from datetime import timedelta

from claude_usage.domain.quota import LimitReading

_KIND_LABELS = {"session": "Session (5hr)", "weekly_all": "Weekly (7 day)"}


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


def coarse(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 60:
        return "<1m"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    return f"{total // 86400}d"
