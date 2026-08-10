from __future__ import annotations

from claude_usage.application.ports import Clock, QuotaSource
from claude_usage.domain.quota import QuotaSnapshot


class UsageService:
    def __init__(self, quota_source: QuotaSource, clock: Clock) -> None:
        self._quota_source = quota_source
        self._clock = clock

    def snapshot(self) -> QuotaSnapshot:
        now = self._clock.now()
        quota = self._quota_source.read_quota()
        # Absent data must never render as fresh.
        is_stale = True if quota is None else quota.is_stale(now)
        return QuotaSnapshot(captured_at=now, quota=quota, is_stale=is_stale)
