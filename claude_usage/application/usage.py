from __future__ import annotations

from datetime import timedelta

from claude_usage.application.ports import Clock, QuotaSource
from claude_usage.domain.quota import (
    STALE_AFTER,
    QuotaReading,
    QuotaSnapshot,
    QuotaUnavailable,
)


class UsageService:
    def __init__(
        self,
        quota_source: QuotaSource,
        clock: Clock,
        stale_after: timedelta = STALE_AFTER,
    ) -> None:
        self._quota_source = quota_source
        self._clock = clock
        self._stale_after = stale_after
        self._last_good: QuotaReading | None = None

    def snapshot(self) -> QuotaSnapshot:
        now = self._clock.now()
        result = self._quota_source.read_quota()

        if isinstance(result, QuotaReading):
            self._last_good = result
            return QuotaSnapshot(
                captured_at=now,
                quota=result,
                is_stale=result.is_stale(now, self._stale_after),
            )

        if result is QuotaUnavailable.READ_ERROR and self._last_good is not None:
            return QuotaSnapshot(
                captured_at=now,
                quota=self._last_good,
                is_stale=True,
                unavailable=QuotaUnavailable.READ_ERROR,
                detail=self._quota_source.read_error_detail(),
            )

        # NO_FILE / NO_QUOTA_KEY never fall back; READ_ERROR with no prior
        # reading has nothing to fall back to. Either way, discard history —
        # a stale reading shown for a missing file would be a lie.
        self._last_good = None
        detail = (
            self._quota_source.read_error_detail()
            if result is QuotaUnavailable.READ_ERROR
            else None
        )
        return QuotaSnapshot(
            captured_at=now, quota=None, is_stale=True, unavailable=result, detail=detail
        )
