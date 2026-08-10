"""Adapter over ~/.claude.json. Read-only; never touches accountUuid."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from claude_usage.domain.quota import LimitReading, QuotaReading


class ClaudeJsonQuotaSource:
    def __init__(self, path: Path | None = None) -> None:
        # ~/.claude.json is the sibling of ~/.claude/, not a file inside it.
        self._path = path if path is not None else Path.home() / ".claude.json"

    def read_quota(self) -> QuotaReading | None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        cached = raw.get("cachedUsageUtilization")
        if not isinstance(cached, dict):
            return None
        fetched_at_ms = cached.get("fetchedAtMs")
        if isinstance(fetched_at_ms, bool) or not isinstance(fetched_at_ms, (int, float)):
            return None
        try:
            measured_at = datetime.fromtimestamp(fetched_at_ms / 1000, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
        return QuotaReading(
            measured_at=measured_at,
            limits=_parse_limits(cached),
            promo_notices=_parse_promos(raw),
        )


def _parse_limits(cached: dict) -> tuple[LimitReading, ...]:
    utilization = cached.get("utilization")
    if not isinstance(utilization, dict):
        return ()
    entries = utilization.get("limits")
    if not isinstance(entries, list):
        return ()
    readings = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        percent = entry.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, int):
            continue
        readings.append(
            LimitReading(
                kind=str(entry.get("kind") or "unknown"),
                group=str(entry.get("group") or ""),
                percent=percent,
                severity=str(entry.get("severity") or "normal"),
                is_active=bool(entry.get("is_active", False)),
                resets_at=_parse_resets_at(entry.get("resets_at")),
                scope_model=_parse_scope_model(entry.get("scope")),
            )
        )
    return tuple(readings)


def _parse_resets_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_scope_model(scope: object) -> str | None:
    if not isinstance(scope, dict):
        return None
    model = scope.get("model")
    if not isinstance(model, dict):
        return None
    name = model.get("display_name")
    return name if isinstance(name, str) else None


def _parse_promos(raw: dict) -> tuple[str, ...]:
    features = raw.get("cachedGrowthBookFeatures")
    if not isinstance(features, dict):
        return ()
    notices = features.get("tengu_rate_limit_promo_notices")
    if not isinstance(notices, list):
        return ()
    return tuple(
        entry["text"]
        for entry in notices
        if isinstance(entry, dict) and isinstance(entry.get("text"), str)
    )
