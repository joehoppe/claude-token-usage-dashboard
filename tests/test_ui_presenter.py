from datetime import UTC, datetime, timedelta

from claude_usage.application.ports import Config
from claude_usage.domain.quota import (
    LimitReading,
    QuotaReading,
    QuotaSnapshot,
    QuotaUnavailable,
)
from claude_usage.ui.app.presenter import present, present_error

NOW = datetime(2026, 8, 5, 18, 10, tzinfo=UTC)


def make_limit(**overrides):
    defaults = {
        "kind": "session",
        "group": "session",
        "percent": 25,
        "severity": "normal",
        "is_active": False,
        "resets_at": None,
        "scope_model": None,
    }
    defaults.update(overrides)
    return LimitReading(**defaults)


def make_snapshot(
    limits=(), promos=(), measured_at=None, is_stale=False, unavailable=None, detail=None
):
    reading = QuotaReading(
        measured_at=measured_at or NOW - timedelta(minutes=5),
        limits=tuple(limits),
        promo_notices=tuple(promos),
    )
    return QuotaSnapshot(
        captured_at=NOW,
        quota=reading,
        is_stale=is_stale,
        unavailable=unavailable,
        detail=detail,
    )


def test_headline_picks_worst_bar_not_aggregate():
    weekly_all = make_limit(kind="weekly_all", percent=39)
    weekly_fable = make_limit(kind="weekly_scoped", percent=66, scope_model="Fable")
    view = present(make_snapshot([weekly_all, weekly_fable]), Config())
    assert view.headline == "66% used"


def test_headline_no_limits_reported():
    view = present(make_snapshot([]), Config())
    assert view.headline == "No limits reported"


def test_used_is_percent_clamped():
    view = present(make_snapshot([make_limit(percent=140)]), Config())
    assert view.bars[0].used == 100
    view = present(make_snapshot([make_limit(percent=-5)]), Config())
    assert view.bars[0].used == 0


def test_bars_display_session_then_weekly_then_weekly_fable():
    weekly_fable = make_limit(kind="weekly_scoped", percent=90, scope_model="Fable")
    session = make_limit(kind="session", percent=10)
    weekly_all = make_limit(kind="weekly_all", percent=50)
    view = present(make_snapshot([weekly_fable, session, weekly_all]), Config())
    assert [bar.label for bar in view.bars] == ["Session (5hr)", "Weekly (7 day)", "Weekly Fable"]


def test_unknown_kind_bars_display_after_known_kinds():
    unknown = make_limit(kind="monthly_all", percent=99)
    session = make_limit(kind="session", percent=10)
    view = present(make_snapshot([unknown, session]), Config())
    assert [bar.label for bar in view.bars] == ["Session (5hr)", "Monthly All"]


def test_unknown_severity_maps_to_critical():
    view = present(make_snapshot([make_limit(severity="exceeded")]), Config())
    assert view.bars[0].severity == "critical"
    view = present(make_snapshot([make_limit(severity="normal")]), Config())
    assert view.bars[0].severity == "normal"
    view = present(make_snapshot([make_limit(severity="warning")]), Config())
    assert view.bars[0].severity == "warning"


def test_unknown_kind_renders_via_shared_label_for():
    view = present(make_snapshot([make_limit(kind="monthly_all")]), Config())
    assert view.bars[0].label == "Monthly All"


def test_no_file_message():
    snapshot = QuotaSnapshot(
        captured_at=NOW, quota=None, is_stale=True, unavailable=QuotaUnavailable.NO_FILE
    )
    view = present(snapshot, Config())
    assert view.message == "Claude Code data not found"
    assert view.bars == ()


def test_no_quota_key_message():
    snapshot = QuotaSnapshot(
        captured_at=NOW,
        quota=None,
        is_stale=True,
        unavailable=QuotaUnavailable.NO_QUOTA_KEY,
    )
    view = present(snapshot, Config())
    assert view.message == "No quota data cached yet — click Refresh"


def test_read_error_no_history_message_carries_detail():
    snapshot = QuotaSnapshot(
        captured_at=NOW,
        quota=None,
        is_stale=True,
        unavailable=QuotaUnavailable.READ_ERROR,
        detail="OSError",
    )
    view = present(snapshot, Config())
    assert view.message == "Couldn't read quota data"
    assert view.message_detail == "OSError"


def test_read_error_with_history_has_no_message_but_shows_bars():
    view = present(
        make_snapshot(
            [make_limit(percent=50)],
            is_stale=True,
            unavailable=QuotaUnavailable.READ_ERROR,
            detail="OSError",
        ),
        Config(),
    )
    assert view.message is None
    assert len(view.bars) == 1
    assert view.stale is True
    assert "OSError" in view.notices


def test_stale_appends_marker_to_age_text():
    view = present(make_snapshot([make_limit()], is_stale=True), Config())
    assert view.age_text.endswith("· STALE")
    assert view.stale is True


def test_promo_and_config_notices_both_present():
    config = Config(warnings=("stale_after_minutes is invalid — using default",))
    view = present(make_snapshot([make_limit()], promos=["+50% weekly limits promo"]), config)
    assert "stale_after_minutes is invalid — using default" in view.notices
    assert "+50% weekly limits promo" in view.notices


def test_resets_text_present_and_absent():
    with_reset = make_limit(resets_at=NOW + timedelta(hours=3))
    without_reset = make_limit(resets_at=None)
    view = present(make_snapshot([with_reset, without_reset]), Config())
    assert any(bar.resets_text == "resets in 3h" for bar in view.bars)
    assert any(bar.resets_text is None for bar in view.bars)


def test_present_error_returns_read_error_shaped_view():
    view = present_error(RuntimeError("boom"))
    assert view.message == "Couldn't read quota data"
    assert view.message_detail == "RuntimeError"
    assert view.bars == ()
