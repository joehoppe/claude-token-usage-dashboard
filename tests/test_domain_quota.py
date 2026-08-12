import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from claude_usage.domain.quota import (
    STALE_AFTER,
    LimitReading,
    QuotaReading,
    QuotaSnapshot,
    QuotaUnavailable,
    time_remaining,
)

UTC = timezone.utc
MEASURED = datetime(2026, 8, 5, 18, 5, tzinfo=UTC)


def make_limit(**overrides):
    defaults = dict(
        kind="session",
        group="session",
        percent=25,
        severity="normal",
        is_active=False,
        resets_at=None,
        scope_model=None,
    )
    defaults.update(overrides)
    return LimitReading(**defaults)


def make_reading(limits=(), measured_at=MEASURED):
    return QuotaReading(
        measured_at=measured_at, limits=tuple(limits), promo_notices=()
    )


def test_stale_after_is_15_minutes():
    assert STALE_AFTER == timedelta(minutes=15)


def test_age_is_now_minus_measured_at():
    reading = make_reading()
    now = MEASURED + timedelta(minutes=5)
    assert reading.age(now) == timedelta(minutes=5)


def test_is_stale_false_just_under_threshold():
    reading = make_reading()
    now = MEASURED + timedelta(minutes=14, seconds=59)
    assert reading.is_stale(now) is False


def test_is_stale_true_at_exactly_threshold():
    reading = make_reading()
    now = MEASURED + timedelta(minutes=15)
    assert reading.is_stale(now) is True


def test_binding_picks_highest_percent():
    weekly = make_limit(kind="weekly_all", percent=50)
    scoped = make_limit(kind="weekly_scoped", percent=75, scope_model="Fable")
    session = make_limit(kind="session", percent=25)
    reading = make_reading([session, weekly, scoped])
    assert reading.binding() is scoped


def test_binding_none_when_no_limits():
    assert make_reading([]).binding() is None


def test_time_remaining_none_when_resets_at_none():
    assert time_remaining(None, MEASURED) is None


def test_time_remaining_future():
    resets = MEASURED + timedelta(hours=5)
    assert time_remaining(resets, MEASURED) == timedelta(hours=5)


def test_time_remaining_clamps_past_to_zero():
    resets = MEASURED - timedelta(hours=1)
    assert time_remaining(resets, MEASURED) == timedelta(0)


def test_entities_are_frozen():
    limit = make_limit()
    with pytest.raises(dataclasses.FrozenInstanceError):
        limit.percent = 99
    snapshot = QuotaSnapshot(captured_at=MEASURED, quota=None, is_stale=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.is_stale = False


def test_quota_unavailable_members():
    assert QuotaUnavailable.NO_FILE.value == "no_file"
    assert QuotaUnavailable.NO_QUOTA_KEY.value == "no_quota_key"
    assert QuotaUnavailable.READ_ERROR.value == "read_error"


def test_snapshot_unavailable_and_detail_default_to_none():
    snapshot = QuotaSnapshot(captured_at=MEASURED, quota=None, is_stale=True)
    assert snapshot.unavailable is None
    assert snapshot.detail is None


def test_snapshot_accepts_unavailable_and_detail():
    snapshot = QuotaSnapshot(
        captured_at=MEASURED,
        quota=None,
        is_stale=True,
        unavailable=QuotaUnavailable.READ_ERROR,
        detail="JSONDecodeError",
    )
    assert snapshot.unavailable is QuotaUnavailable.READ_ERROR
    assert snapshot.detail == "JSONDecodeError"
