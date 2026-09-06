import json
from datetime import UTC, datetime
from pathlib import Path

from claude_usage.domain.quota import QuotaUnavailable
from claude_usage.infrastructure.claude_json import ClaudeJsonQuotaSource
from claude_usage.infrastructure.clock import SystemClock

FIXTURE = Path(__file__).parent / "fixtures" / "live_snapshot.json"


def write_json(tmp_path, payload):
    path = tmp_path / "claude.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_system_clock_returns_aware_utc():
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0


def test_absent_file_returns_no_file(tmp_path):
    source = ClaudeJsonQuotaSource(tmp_path / "missing.json")
    assert source.read_quota() is QuotaUnavailable.NO_FILE
    assert source.read_error_detail() is None


def test_unreadable_directory_returns_read_error(tmp_path):
    # A directory raises OSError (not FileNotFoundError) on read_text.
    source = ClaudeJsonQuotaSource(tmp_path)
    assert source.read_quota() is QuotaUnavailable.READ_ERROR
    assert source.read_error_detail() is not None


def test_permission_error_returns_read_error(tmp_path, monkeypatch):
    path = tmp_path / "claude.json"
    path.write_text("{}", encoding="utf-8")

    def raise_permission_error(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", raise_permission_error)
    source = ClaudeJsonQuotaSource(path)
    assert source.read_quota() is QuotaUnavailable.READ_ERROR
    assert source.read_error_detail() == "PermissionError"


def test_invalid_json_returns_read_error(tmp_path):
    path = tmp_path / "claude.json"
    path.write_text("{not json", encoding="utf-8")
    source = ClaudeJsonQuotaSource(path)
    assert source.read_quota() is QuotaUnavailable.READ_ERROR
    assert source.read_error_detail() == "JSONDecodeError"


def test_missing_cached_usage_utilization_returns_no_quota_key(tmp_path):
    path = write_json(tmp_path, {"oauthAccount": {}})
    source = ClaudeJsonQuotaSource(path)
    assert source.read_quota() is QuotaUnavailable.NO_QUOTA_KEY


def test_missing_fetched_at_ms_returns_read_error(tmp_path):
    path = write_json(tmp_path, {"cachedUsageUtilization": {"utilization": {}}})
    source = ClaudeJsonQuotaSource(path)
    assert source.read_quota() is QuotaUnavailable.READ_ERROR


def test_fixture_parses_measured_at_and_limits():
    reading = ClaudeJsonQuotaSource(FIXTURE).read_quota()
    assert reading.measured_at == datetime(2026, 8, 5, 18, 5, tzinfo=UTC)
    assert [limit.kind for limit in reading.limits] == [
        "session",
        "weekly_all",
        "weekly_scoped",
    ]
    assert [limit.percent for limit in reading.limits] == [25, 50, 75]


def test_scope_null_vs_populated():
    reading = ClaudeJsonQuotaSource(FIXTURE).read_quota()
    session, _weekly, scoped = reading.limits
    assert session.scope_model is None
    assert scoped.scope_model == "Fable"
    assert scoped.is_active is True
    assert scoped.resets_at == datetime(2026, 8, 7, 0, 0, tzinfo=UTC)


def test_promo_notices_parsed_from_fixture():
    reading = ClaudeJsonQuotaSource(FIXTURE).read_quota()
    assert reading.promo_notices == (
        "+50% weekly limits promo through Aug 19 · clau.de/cc-50-promo",
    )


def test_null_percent_entries_are_skipped(tmp_path):
    path = write_json(
        tmp_path,
        {
            "cachedUsageUtilization": {
                "fetchedAtMs": 1785953100000,
                "utilization": {
                    "limits": [
                        {"kind": "session", "group": "session", "percent": None},
                        {
                            "kind": "weekly_all",
                            "group": "weekly",
                            "percent": 50,
                            "severity": "normal",
                            "resets_at": "2026-08-07T00:00:00Z",
                            "scope": None,
                            "is_active": False,
                        },
                    ]
                },
            }
        },
    )
    reading = ClaudeJsonQuotaSource(path).read_quota()
    assert [limit.kind for limit in reading.limits] == ["weekly_all"]


def test_unparseable_resets_at_becomes_none(tmp_path):
    path = write_json(
        tmp_path,
        {
            "cachedUsageUtilization": {
                "fetchedAtMs": 1785953100000,
                "utilization": {
                    "limits": [
                        {
                            "kind": "session",
                            "group": "session",
                            "percent": 25,
                            "severity": "normal",
                            "resets_at": "not-a-date",
                            "scope": None,
                            "is_active": False,
                        }
                    ]
                },
            }
        },
    )
    reading = ClaudeJsonQuotaSource(path).read_quota()
    assert reading.limits[0].resets_at is None
    assert reading.limits[0].percent == 25


def test_missing_utilization_gives_empty_limits(tmp_path):
    path = write_json(tmp_path, {"cachedUsageUtilization": {"fetchedAtMs": 1785953100000}})
    reading = ClaudeJsonQuotaSource(path).read_quota()
    assert reading.limits == ()


def test_malformed_promos_give_empty_tuple(tmp_path):
    path = write_json(
        tmp_path,
        {
            "cachedUsageUtilization": {"fetchedAtMs": 1785953100000, "utilization": {}},
            "cachedGrowthBookFeatures": {"tengu_rate_limit_promo_notices": "not-a-list"},
        },
    )
    assert ClaudeJsonQuotaSource(path).read_quota().promo_notices == ()


def test_absent_promos_give_empty_tuple(tmp_path):
    path = write_json(
        tmp_path,
        {"cachedUsageUtilization": {"fetchedAtMs": 1785953100000, "utilization": {}}},
    )
    assert ClaudeJsonQuotaSource(path).read_quota().promo_notices == ()


def test_malformed_fetched_at_ms_nan_returns_read_error(tmp_path):
    path = write_json(
        tmp_path,
        {"cachedUsageUtilization": {"fetchedAtMs": float("nan"), "utilization": {}}},
    )
    assert ClaudeJsonQuotaSource(path).read_quota() is QuotaUnavailable.READ_ERROR


def test_malformed_fetched_at_ms_inf_returns_read_error(tmp_path):
    path = write_json(
        tmp_path,
        {"cachedUsageUtilization": {"fetchedAtMs": float("inf"), "utilization": {}}},
    )
    assert ClaudeJsonQuotaSource(path).read_quota() is QuotaUnavailable.READ_ERROR


def test_malformed_fetched_at_ms_out_of_range_returns_read_error(tmp_path):
    path = write_json(
        tmp_path,
        {
            "cachedUsageUtilization": {
                "fetchedAtMs": 99999999999999999999,
                "utilization": {},
            }
        },
    )
    assert ClaudeJsonQuotaSource(path).read_quota() is QuotaUnavailable.READ_ERROR


def test_read_error_detail_resets_on_next_successful_read():
    source = ClaudeJsonQuotaSource(FIXTURE)
    source.read_quota()
    assert source.read_error_detail() is None
