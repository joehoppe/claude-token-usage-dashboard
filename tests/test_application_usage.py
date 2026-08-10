from datetime import datetime, timedelta, timezone

from claude_usage.application.usage import UsageService
from claude_usage.domain.quota import QuotaReading

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 18, 10, tzinfo=UTC)


class FakeQuotaSource:
    def __init__(self, reading):
        self._reading = reading

    def read_quota(self):
        return self._reading


class FrozenClock:
    def __init__(self, now):
        self._now = now

    def now(self):
        return self._now


def make_reading(measured_at):
    return QuotaReading(measured_at=measured_at, limits=(), promo_notices=())


def test_snapshot_fresh_reading():
    reading = make_reading(NOW - timedelta(minutes=5))
    service = UsageService(FakeQuotaSource(reading), FrozenClock(NOW))
    snapshot = service.snapshot()
    assert snapshot.captured_at == NOW
    assert snapshot.quota is reading
    assert snapshot.is_stale is False


def test_snapshot_stale_reading():
    reading = make_reading(NOW - timedelta(hours=3))
    service = UsageService(FakeQuotaSource(reading), FrozenClock(NOW))
    assert service.snapshot().is_stale is True


def test_snapshot_missing_quota_is_stale():
    service = UsageService(FakeQuotaSource(None), FrozenClock(NOW))
    snapshot = service.snapshot()
    assert snapshot.quota is None
    assert snapshot.is_stale is True
