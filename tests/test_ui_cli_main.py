import json
import sys
from pathlib import Path

import pytest

from claude_usage.infrastructure.claude_cli import RefreshOutcome
from claude_usage.ui.cli.main import build_parser, main

FIXTURE = Path(__file__).parent / "fixtures" / "live_snapshot.json"


class FakeRefresher:
    def __init__(self, outcome: RefreshOutcome) -> None:
        self._outcome = outcome
        self.calls = 0

    def refresh(self) -> RefreshOutcome:
        self.calls += 1
        return self._outcome


def test_renders_fixture_and_exits_zero(capsys):
    code = main(["--path", str(FIXTURE)])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert "Session (5hr)" in out
    assert "Weekly Fable" in out
    assert "run " in out
    assert " data " in out
    assert "ago" in out


def test_no_file_exits_one_with_stderr(tmp_path, capsys):
    code = main(["--path", str(tmp_path / "missing.json")])
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert err.strip() == "Claude Code data not found"


def test_no_quota_key_exits_one_with_stderr(tmp_path, capsys):
    path = tmp_path / "claude.json"
    path.write_text(json.dumps({"oauthAccount": {}}), encoding="utf-8")
    code = main(["--path", str(path)])
    _, err = capsys.readouterr()
    assert code == 1
    assert err.strip() == "No quota data cached yet — open /usage in Claude Code"


def test_read_error_exits_one_with_detail_in_stderr(tmp_path, capsys):
    path = tmp_path / "claude.json"
    path.write_text("{not json", encoding="utf-8")
    code = main(["--path", str(path)])
    _, err = capsys.readouterr()
    assert code == 1
    assert "Couldn't read quota data" in err
    assert "JSONDecodeError" in err


def test_stale_reading_still_exits_zero(tmp_path, capsys):
    # Deterministic: rewrite the fixture with an ancient fetchedAtMs rather
    # than depending on the wall clock (which would flake near the fixture's
    # own timestamp).
    stale = json.loads(FIXTURE.read_text(encoding="utf-8"))
    stale["cachedUsageUtilization"]["fetchedAtMs"] = 1609459200000  # 2021-01-01
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(stale), encoding="utf-8")
    code = main(["--path", str(path)])
    out, _ = capsys.readouterr()
    assert code == 0
    assert "STALE" in out


def test_json_output_is_whitelisted_snapshot(capsys):
    code = main(["--path", str(FIXTURE), "--json"])
    out, _ = capsys.readouterr()
    assert code == 0
    payload = json.loads(out)
    assert set(payload) == {"captured_at", "is_stale", "quota", "unavailable", "detail"}
    assert payload["unavailable"] is None
    assert payload["detail"] is None
    kinds = [limit["kind"] for limit in payload["quota"]["limits"]]
    assert kinds == ["session", "weekly_all", "weekly_scoped"]
    assert "accountUuid" not in out
    assert "REDACTED" not in out


def test_ascii_flag(capsys):
    main(["--path", str(FIXTURE), "--ascii"])
    out, _ = capsys.readouterr()
    assert "#" in out
    assert "█" not in out


def test_non_tty_suppresses_ansi(capsys):
    # capsys' replacement stdout is not a TTY.
    main(["--path", str(FIXTURE)])
    out, _ = capsys.readouterr()
    assert "\x1b[" not in out


def test_no_color_env_suppresses_ansi_even_on_tty(capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    main(["--path", str(FIXTURE)])
    out, _ = capsys.readouterr()
    assert "\x1b[" not in out


def test_tty_without_no_color_emits_ansi(capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    main(["--path", str(FIXTURE)])
    out, _ = capsys.readouterr()
    assert "\x1b[" in out


def test_no_color_flag_suppresses_ansi_even_on_tty(capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    main(["--path", str(FIXTURE), "--no-color"])
    out, _ = capsys.readouterr()
    assert "\x1b[" not in out


def test_refresh_flag_runs_refresher_before_render(capsys):
    refresher = FakeRefresher(RefreshOutcome.REFRESHED)
    code = main(
        ["--path", str(FIXTURE), "--refresh"],
        refresher_factory=lambda: refresher,
    )
    out, err = capsys.readouterr()
    assert code == 0
    assert refresher.calls == 1
    assert err == ""
    assert "Session (5hr)" in out


def test_without_refresh_flag_refresher_never_runs(capsys):
    refresher = FakeRefresher(RefreshOutcome.REFRESHED)
    code = main(["--path", str(FIXTURE)], refresher_factory=lambda: refresher)
    assert code == 0
    assert refresher.calls == 0


@pytest.mark.parametrize(
    "outcome",
    [
        RefreshOutcome.NOT_FOUND,
        RefreshOutcome.TIMED_OUT,
        RefreshOutcome.FAILED,
    ],
)
def test_refresh_failure_warns_and_still_renders(outcome, capsys):
    code = main(
        ["--path", str(FIXTURE), "--refresh"],
        refresher_factory=lambda: FakeRefresher(outcome),
    )
    out, err = capsys.readouterr()
    assert code == 0
    assert f"Refresh failed: {outcome.value} — showing cached data" in err
    assert "Session (5hr)" in out


def test_refresh_failure_keeps_json_stdout_clean(capsys):
    code = main(
        ["--path", str(FIXTURE), "--refresh", "--json"],
        refresher_factory=lambda: FakeRefresher(RefreshOutcome.NOT_FOUND),
    )
    out, err = capsys.readouterr()
    assert code == 0
    assert "Refresh failed" in err
    payload = json.loads(out)
    assert payload["quota"] is not None


def test_refresh_help_text_names_the_quota_cost():
    help_text = build_parser().format_help()
    assert "--refresh" in help_text
    assert "quota" in help_text


def test_account_uuid_never_reaches_any_output(capsys):
    # The fixture contains accountUuid "REDACTED-0000-...". It must appear in
    # neither the rendered text nor the --json output.
    main(["--path", str(FIXTURE)])
    rendered, _ = capsys.readouterr()
    main(["--path", str(FIXTURE), "--json"])
    as_json, _ = capsys.readouterr()
    for output in (rendered, as_json):
        assert "REDACTED-0000-0000-0000-000000000000" not in output
        assert "accountUuid" not in output
