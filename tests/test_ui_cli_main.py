import json
import sys
from pathlib import Path

from claude_usage.ui.cli.main import main

FIXTURE = Path(__file__).parent / "fixtures" / "live_snapshot.json"


def test_renders_fixture_and_exits_zero(capsys):
    code = main(["--path", str(FIXTURE)])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert "Session (5hr)" in out
    assert "Weekly Fable" in out
    assert "as of" in out


def test_missing_cache_exits_one_with_stderr(tmp_path, capsys):
    code = main(["--path", str(tmp_path / "missing.json")])
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert "No quota cache found — run Claude Code once to populate it." in err


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
    assert set(payload) == {"captured_at", "is_stale", "quota"}
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
