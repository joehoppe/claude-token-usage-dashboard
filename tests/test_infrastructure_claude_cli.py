"""ClaudeCliRefresher spawn tests — always against a stub, never the real claude."""
import json
import os
import stat
import sys
from pathlib import Path

from claude_usage.infrastructure.claude_cli import ClaudeCliRefresher, RefreshOutcome


def write_stub(tmp_path: Path, body: str) -> str:
    """An executable claude stand-in; `body` is the Python the stub runs.

    A wrapper script rather than a bare binary — mirroring how `claude`
    resolves in the wild (npm .cmd shim on Windows, shell shim elsewhere),
    which is exactly the case the design's §5 Windows note flags.
    """
    script = tmp_path / "stub_body.py"
    script.write_text(body, encoding="utf-8")
    if os.name == "nt":
        exe = tmp_path / "claude.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        exe = tmp_path / "claude"
        exe.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
        )
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


def test_exit_zero_is_refreshed(tmp_path):
    exe = write_stub(tmp_path, "raise SystemExit(0)")
    assert ClaudeCliRefresher(executable=exe).refresh() is RefreshOutcome.REFRESHED


def test_nonzero_exit_is_failed(tmp_path):
    exe = write_stub(tmp_path, "raise SystemExit(3)")
    assert ClaudeCliRefresher(executable=exe).refresh() is RefreshOutcome.FAILED


def test_timeout_is_timed_out(tmp_path):
    exe = write_stub(tmp_path, "import time; time.sleep(30)")
    refresher = ClaudeCliRefresher(executable=exe, timeout_seconds=1)
    assert refresher.refresh() is RefreshOutcome.TIMED_OUT


def test_no_executable_resolved_is_not_found(monkeypatch):
    monkeypatch.setattr(
        "claude_usage.infrastructure.claude_cli.shutil.which", lambda name: None
    )
    assert ClaudeCliRefresher().refresh() is RefreshOutcome.NOT_FOUND


def test_explicit_executable_that_cannot_spawn_is_failed(tmp_path):
    # An explicit path is "resolved" even if broken: NOT_FOUND means only
    # that which() found nothing; a bad spawn is FAILED (OSError branch).
    missing = str(tmp_path / "nope")
    assert ClaudeCliRefresher(executable=missing).refresh() is RefreshOutcome.FAILED


def test_argv_is_exactly_dash_p_usage(tmp_path):
    log = tmp_path / "argv.json"
    exe = write_stub(
        tmp_path,
        "import json, sys, pathlib\n"
        f"pathlib.Path({str(log)!r}).write_text(json.dumps(sys.argv[1:]))\n",
    )
    ClaudeCliRefresher(executable=exe).refresh()
    assert json.loads(log.read_text(encoding="utf-8")) == ["-p", "/usage"]


def test_stdin_sees_eof_instead_of_blocking(tmp_path):
    exe = write_stub(tmp_path, "import sys\nsys.stdin.read()\nraise SystemExit(0)")
    refresher = ClaudeCliRefresher(executable=exe, timeout_seconds=10)
    assert refresher.refresh() is RefreshOutcome.REFRESHED
