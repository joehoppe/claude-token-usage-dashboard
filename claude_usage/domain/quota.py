"""Quota domain entities. Standard library only — no I/O, no wx, no ANSI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

STALE_AFTER = timedelta(minutes=15)


class QuotaUnavailable(Enum):
    # The trailing comments are a column: each member against what it means.
    # fmt: off
    NO_FILE = "no_file"            # ~/.claude.json absent
    NO_QUOTA_KEY = "no_quota_key"  # file readable, cachedUsageUtilization absent/invalid
    READ_ERROR = "read_error"      # OSError, JSONDecodeError, unusable fetchedAtMs
    # fmt: on


@dataclass(frozen=True)
class LimitReading:
    """One entry from cachedUsageUtilization.utilization.limits[]."""

    kind: str
    group: str
    percent: int
    severity: str
    is_active: bool
    resets_at: datetime | None
    scope_model: str | None


@dataclass(frozen=True)
class QuotaReading:
    measured_at: datetime
    limits: tuple[LimitReading, ...]
    promo_notices: tuple[str, ...]

    def age(self, now: datetime) -> timedelta:
        return now - self.measured_at

    def is_stale(self, now: datetime, threshold: timedelta = STALE_AFTER) -> bool:
        return self.age(now) >= threshold

    def binding(self) -> LimitReading | None:
        """The worst bar — the constraint that would actually stop work."""
        if not self.limits:
            return None
        return max(self.limits, key=lambda limit: limit.percent)


@dataclass(frozen=True)
class QuotaSnapshot:
    captured_at: datetime
    quota: QuotaReading | None
    is_stale: bool
    unavailable: QuotaUnavailable | None = None
    detail: str | None = None  # e.g. "JSONDecodeError"; never a file path or payload


def time_remaining(resets_at: datetime | None, now: datetime) -> timedelta | None:
    if resets_at is None:
        return None
    return max(resets_at - now, timedelta(0))
