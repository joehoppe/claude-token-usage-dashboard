from datetime import UTC, datetime, timedelta

from claude_usage.application.usage import UsageService
from claude_usage.domain.quota import QuotaReading, QuotaUnavailable

NOW = datetime(2026, 8, 5, 18, 10, tzinfo=UTC)


class FakeQuotaSource:
    def __init__(self, result, detail=None):
        self._result = result
        self._detail = detail

    def read_quota(self):
        return self._result

    def read_error_detail(self):
        return self._detail


class ScriptedQuotaSource:
    """Returns a different result on each call, for fallback-sequence tests."""

    def __init__(self, results):
        self._results = list(results)
        self._detail = None

    def read_quota(self):
        result, detail = self._results.pop(0)
        self._detail = detail
        return result

    def read_error_detail(self):
        return self._detail


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
    assert snapshot.unavailable is None


def test_snapshot_stale_reading():
    reading = make_reading(NOW - timedelta(hours=3))
    service = UsageService(FakeQuotaSource(reading), FrozenClock(NOW))
    assert service.snapshot().is_stale is True


def test_configured_stale_threshold_is_honoured():
    reading = make_reading(NOW - timedelta(minutes=2))
    service = UsageService(
        FakeQuotaSource(reading), FrozenClock(NOW), stale_after=timedelta(minutes=1)
    )
    assert service.snapshot().is_stale is True


def test_no_file_never_falls_back():
    good = make_reading(NOW - timedelta(minutes=5))
    source = ScriptedQuotaSource([(good, None), (QuotaUnavailable.NO_FILE, None)])
    service = UsageService(source, FrozenClock(NOW))
    service.snapshot()  # primes last-good-reading
    snapshot = service.snapshot()
    assert snapshot.quota is None
    assert snapshot.unavailable is QuotaUnavailable.NO_FILE
    assert snapshot.is_stale is True


def test_no_quota_key_never_falls_back():
    good = make_reading(NOW - timedelta(minutes=5))
    source = ScriptedQuotaSource([(good, None), (QuotaUnavailable.NO_QUOTA_KEY, None)])
    service = UsageService(source, FrozenClock(NOW))
    service.snapshot()
    snapshot = service.snapshot()
    assert snapshot.quota is None
    assert snapshot.unavailable is QuotaUnavailable.NO_QUOTA_KEY


def test_read_error_falls_back_to_prior_reading_with_original_measured_at():
    good = make_reading(NOW - timedelta(minutes=5))
    source = ScriptedQuotaSource([(good, None), (QuotaUnavailable.READ_ERROR, "JSONDecodeError")])
    service = UsageService(source, FrozenClock(NOW))
    service.snapshot()
    snapshot = service.snapshot()
    assert snapshot.quota is good
    assert snapshot.quota.measured_at == good.measured_at
    assert snapshot.is_stale is True
    assert snapshot.unavailable is QuotaUnavailable.READ_ERROR
    assert snapshot.detail == "JSONDecodeError"


def test_read_error_with_no_history_returns_error_state():
    source = FakeQuotaSource(QuotaUnavailable.READ_ERROR, detail="OSError")
    service = UsageService(source, FrozenClock(NOW))
    snapshot = service.snapshot()
    assert snapshot.quota is None
    assert snapshot.is_stale is True
    assert snapshot.unavailable is QuotaUnavailable.READ_ERROR
    assert snapshot.detail == "OSError"


def test_no_file_discards_history_so_later_read_error_has_no_fallback():
    good = make_reading(NOW - timedelta(minutes=5))
    source = ScriptedQuotaSource(
        [
            (good, None),
            (QuotaUnavailable.NO_FILE, None),
            (QuotaUnavailable.READ_ERROR, "OSError"),
        ]
    )
    service = UsageService(source, FrozenClock(NOW))
    service.snapshot()  # good reading stored
    service.snapshot()  # NO_FILE discards it
    snapshot = service.snapshot()  # READ_ERROR has nothing to fall back to
    assert snapshot.quota is None
    assert snapshot.unavailable is QuotaUnavailable.READ_ERROR
