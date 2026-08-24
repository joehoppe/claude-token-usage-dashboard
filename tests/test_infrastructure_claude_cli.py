"""ClaudeCliRefresher spawn tests — always against a stub, never the real claude."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

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


@pytest.mark.skipif(os.name != "nt", reason="console windows are a Windows concept")
def test_child_gets_no_console_window(tmp_path):
    """A console-subsystem child spawned from a console-less parent is handed
    a brand-new console window — the terminal that flashes on Refresh. The
    npm claude.cmd shim is exactly that (cmd.exe, then node.exe), and the app
    is launched with pythonw, which has no console to inherit.

    The spawn must therefore happen from a console-less parent or the bug is
    invisible: pytest itself runs attached to a console (often a ConPTY, whose
    GetConsoleWindow is 0), which the child inherits, so no window is ever
    created. DETACHED_PROCESS reproduces the real condition faithfully.
    """
    log = tmp_path / "console.json"
    exe = write_stub(
        tmp_path,
        "import ctypes, json, pathlib\n"
        f"pathlib.Path({str(log)!r}).write_text("
        "json.dumps(ctypes.windll.kernel32.GetConsoleWindow()))\n",
    )
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import sys\n"
        "from claude_usage.infrastructure.claude_cli import ClaudeCliRefresher\n"
        "ClaudeCliRefresher(executable=sys.argv[1]).refresh()\n",
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, str(driver), exe],
        creationflags=subprocess.DETACHED_PROCESS,
        cwd=repo_root,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        timeout=120,
        check=True,
    )
    assert json.loads(log.read_text(encoding="utf-8")) == 0
