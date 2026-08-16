# Quota Manual Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a **Refresh** button to the wx app that spawns `claude -p "/usage"`
on click (repairing a missing `cachedUsageUtilization` cache), and correct the
misleading `NO_QUOTA_KEY` remedy text in both drivers.

**Architecture:** Onion per `AGENTS.md`. The feature lives entirely in
`infrastructure/` (a `ClaudeCliRefresher` adapter plus its `QuotaRefresher`
protocol and `RefreshOutcome` enum, all in one new file) and `ui/app/` (a
button on `QuotaFrame`, a one-shot `RefreshWorker` thread, composition-root
wiring). `domain/` and `application/` are behaviorally untouched — the only
inner-ring edit is two passive data fields on the frozen `Config` dataclass.
The UI ring imports `infrastructure/` directly (outer ring importing inward);
no port is added to `application/ports.py`.

**Tech Stack:** Python stdlib (`subprocess`, `shutil`, `threading`,
`tomllib`), wxPython (pre-approved), pytest.

**Spec:** [`2026-08-16-manual-refresh-design.md`](2026-08-16-manual-refresh-design.md)
— the plan argues from that spec; read both.

## Global Constraints

- **Spec §3 prerequisite: PASSED 2026-08-16.** With `cachedUsageUtilization`
  absent, `claude -p "/usage"` repopulated the key. Measured duration: under
  ~15 seconds; session cost not separately recorded. The specced
  `refresh_timeout_seconds` default of 60 stands (ample headroom).
- Imports point inward only. `wx` is confined to `ui/app/`. `subprocess` and
  `shutil` are banned from `domain/` and `application/` (Task 3 encodes this
  in `tests/test_architecture.py`).
- **No automatic refresh anywhere.** The subprocess spawns on button click and
  only on button click. The CLI spawns nothing; its only change is message
  text.
- **Tests never invoke the real `claude`.** Every process test runs a stub
  written to `tmp_path`.
- **Tests never read or write the real `~/.claude.json`.** Fixtures and temp
  paths only, via the existing `--path` seam.
- This project never writes `~/.claude.json`; only the spawned Claude Code
  child does.
- The child's captured stdout/stderr is discarded, never logged — it may
  contain account details.
- Runtime dependencies stay MIT/Apache-2.0 (wxPython exception pre-approved).
  This plan adds no dependency.
- All work happens on branch `feat/quota-manual-refresh` (created in Task 1).
- Commit messages: imperative one-line summary matching repo history (no
  `feat:` prefixes), ending with the executor's `Co-Authored-By` trailer.
- Run the full suite (`pytest`) before every commit, not just the new tests.

## File Map

| File | Change |
|---|---|
| `claude_usage/application/2026-08-13-auto-refresh-design.md` | Delete (already deleted in worktree — Task 1 commits it) |
| `claude_usage/ui/app/2026-08-16-manual-refresh-design.md` | New spec (untracked — Task 1 commits it) |
| `claude_usage/application/ports.py` | `Config` gains `refresh_timeout_seconds`, `claude_executable` |
| `claude_usage/infrastructure/config.py` | Read both keys; add `_read_str` |
| `claude_usage/infrastructure/claude_cli.py` | **New:** `RefreshOutcome`, `QuotaRefresher`, `ClaudeCliRefresher` |
| `claude_usage/ui/app/refresh.py` | **New:** `RefreshWorker`, `outcome_tooltip` |
| `claude_usage/ui/app/frame.py` | Refresh button, `begin_refresh`/`end_refresh`, button-aware `_fit_to_content` |
| `claude_usage/ui/app/main.py` | Compose refresher + worker, wire `on_refresh` |
| `claude_usage/ui/app/presenter.py` | New `NO_QUOTA_KEY` message |
| `claude_usage/ui/cli/main.py` | New `NO_QUOTA_KEY` message |
| `tests/test_infrastructure_config.py` | Config-key tests |
| `tests/test_infrastructure_claude_cli.py` | **New:** adapter tests against stubs |
| `tests/test_ui_app_refresh.py` | **New:** worker tests with fakes |
| `tests/test_architecture.py` | Ban `subprocess`/`shutil` from inner rings |
| `tests/test_ui_presenter.py`, `tests/test_ui_cli_main.py` | Message assertions |
| `claude_usage/ui/app/2026-08-10-quota-app-design.md:239` | Update quoted message (spec §9) |
| `claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md:350` | Update quoted message (spec §9) |

---

### Task 1: Branch and spec bookkeeping

**Files:**
- Commit deletion: `claude_usage/application/2026-08-13-auto-refresh-design.md` (already deleted in the worktree)
- Commit new: `claude_usage/ui/app/2026-08-16-manual-refresh-design.md`, `claude_usage/ui/app/2026-08-16-manual-refresh-plan.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the branch every later task commits to.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/quota-manual-refresh
```

- [ ] **Step 2: Stage the spec swap and this plan**

```bash
git add claude_usage/application/2026-08-13-auto-refresh-design.md \
        claude_usage/ui/app/2026-08-16-manual-refresh-design.md \
        claude_usage/ui/app/2026-08-16-manual-refresh-plan.md
git status   # expect: one deletion, two new files, nothing else staged
```

- [ ] **Step 3: Commit**

```bash
git commit -m "Replace the auto-refresh spec with the manual refresh design and plan"
```

---

### Task 2: `Config` gains `refresh_timeout_seconds` and `claude_executable`

**Files:**
- Modify: `claude_usage/application/ports.py:20-24`
- Modify: `claude_usage/infrastructure/config.py`
- Test: `tests/test_infrastructure_config.py`

**Interfaces:**
- Consumes: existing `Config`, `TomlConfigSource`, `_read_int`.
- Produces: `Config.refresh_timeout_seconds: int = 60` (valid 5–600) and
  `Config.claude_executable: str | None = None` (valid: non-empty string);
  same key names in `config.toml`. Task 8 reads both fields.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_infrastructure_config.py`)

```python
def test_refresh_timeout_valid_override(tmp_path):
    path = write_toml(tmp_path, "refresh_timeout_seconds = 120\n")
    config = TomlConfigSource(path).read_config()
    assert config.refresh_timeout_seconds == 120
    assert config.warnings == ()


def test_refresh_timeout_out_of_range_defaults_and_warns(tmp_path):
    path = write_toml(tmp_path, "refresh_timeout_seconds = 4\n")
    config = TomlConfigSource(path).read_config()
    assert config.refresh_timeout_seconds == 60
    assert len(config.warnings) == 1
    assert "refresh_timeout_seconds" in config.warnings[0]


def test_claude_executable_absent_is_none(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = 20\n")
    config = TomlConfigSource(path).read_config()
    assert config.claude_executable is None
    assert config.warnings == ()


def test_claude_executable_valid_string(tmp_path):
    path = write_toml(tmp_path, 'claude_executable = "/opt/claude/bin/claude"\n')
    config = TomlConfigSource(path).read_config()
    assert config.claude_executable == "/opt/claude/bin/claude"
    assert config.warnings == ()


def test_claude_executable_wrong_type_defaults_and_warns(tmp_path):
    path = write_toml(tmp_path, "claude_executable = 7\n")
    config = TomlConfigSource(path).read_config()
    assert config.claude_executable is None
    assert len(config.warnings) == 1
    assert "claude_executable" in config.warnings[0]


def test_claude_executable_empty_string_defaults_and_warns(tmp_path):
    path = write_toml(tmp_path, 'claude_executable = ""\n')
    config = TomlConfigSource(path).read_config()
    assert config.claude_executable is None
    assert len(config.warnings) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_infrastructure_config.py -v`
Expected: the six new tests FAIL with `AttributeError: 'Config' object has no attribute 'refresh_timeout_seconds'` (and `claude_executable`); the seven existing tests still pass.

- [ ] **Step 3: Add the fields to `Config`** (`claude_usage/application/ports.py`)

```python
@dataclass(frozen=True)
class Config:
    poll_seconds: int = 10
    stale_after: timedelta = STALE_AFTER
    refresh_timeout_seconds: int = 60
    claude_executable: str | None = None
    warnings: tuple[str, ...] = ()
```

(All construction sites use keyword arguments, so inserting before `warnings`
breaks nothing.)

- [ ] **Step 4: Read both keys in `TomlConfigSource`** (`claude_usage/infrastructure/config.py`)

Add beside the existing range constants:

```python
_REFRESH_TIMEOUT_RANGE = range(5, 601)
```

In `read_config`, after the `stale_minutes` read, replace the `return` with:

```python
        refresh_timeout = _read_int(
            data, "refresh_timeout_seconds", 60, _REFRESH_TIMEOUT_RANGE, warnings
        )
        claude_executable = _read_str(data, "claude_executable", warnings)
        return Config(
            poll_seconds=poll_seconds,
            stale_after=timedelta(minutes=stale_minutes),
            refresh_timeout_seconds=refresh_timeout,
            claude_executable=claude_executable,
            warnings=tuple(warnings),
        )
```

Add below `_read_int`, following its contract (invalid → warning + default,
never raises):

```python
def _read_str(data: dict, key: str, warnings: list[str]) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str) or not value:
        warnings.append(f"{key} is invalid — using default")
        return None
    return value
```

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: all pass (existing `test_absent_file_returns_defaults_silently`
compares against `Config()`, which now carries the new defaults — still equal).

- [ ] **Step 6: Commit**

```bash
git add claude_usage/application/ports.py claude_usage/infrastructure/config.py \
        tests/test_infrastructure_config.py
git commit -m "Add refresh_timeout_seconds and claude_executable to Config"
```

---

### Task 3: `ClaudeCliRefresher` adapter and inner-ring process ban

**Files:**
- Create: `claude_usage/infrastructure/claude_cli.py`
- Test: `tests/test_infrastructure_claude_cli.py` (new)
- Modify: `tests/test_architecture.py:7-16`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (Tasks 4 and 8 import these from
  `claude_usage.infrastructure.claude_cli`):
  - `RefreshOutcome` enum: `REFRESHED | NOT_FOUND | TIMED_OUT | FAILED`,
    values `"refreshed" | "not_found" | "timed_out" | "failed"`
  - `QuotaRefresher` protocol: `refresh() -> RefreshOutcome`
  - `ClaudeCliRefresher(executable: str | None = None, timeout_seconds: int = 60)`

- [ ] **Step 1: Write the failing tests** (`tests/test_infrastructure_claude_cli.py`)

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_infrastructure_claude_cli.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'claude_usage.infrastructure.claude_cli'`.

- [ ] **Step 3: Implement the adapter** (`claude_usage/infrastructure/claude_cli.py`)

```python
"""Adapter spawning `claude -p "/usage"`, which makes Claude Code refresh its
own quota cache. This project never writes ~/.claude.json — only the child
does. Captured child output is discarded, never logged: it may contain
account details.
"""
from __future__ import annotations

import shutil
import subprocess
from enum import Enum
from typing import Protocol


class RefreshOutcome(Enum):
    REFRESHED = "refreshed"    # process exited 0
    NOT_FOUND = "not_found"    # no claude executable resolved
    TIMED_OUT = "timed_out"    # exceeded refresh_timeout_seconds
    FAILED = "failed"          # non-zero exit, or the spawn itself failed


class QuotaRefresher(Protocol):
    def refresh(self) -> RefreshOutcome: ...


class ClaudeCliRefresher:
    def __init__(
        self,
        executable: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def refresh(self) -> RefreshOutcome:
        """Never raises: this runs on the refresh worker thread, where an
        escaping exception would die silently and wedge the button on
        "Refreshing…" — every failure mode is a return value.
        """
        exe = self._executable or shutil.which("claude")
        if exe is None:
            return RefreshOutcome.NOT_FOUND
        try:
            completed = subprocess.run(
                [exe, "-p", "/usage"],
                shell=False,
                stdin=subprocess.DEVNULL,  # a child that prompts must hit EOF
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RefreshOutcome.TIMED_OUT
        except OSError:
            return RefreshOutcome.FAILED
        if completed.returncode == 0:
            return RefreshOutcome.REFRESHED
        return RefreshOutcome.FAILED
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_infrastructure_claude_cli.py -v`
Expected: all 7 PASS (the timeout test takes ~1s — `subprocess.run` kills the
sleeping stub when the timeout expires).

- [ ] **Step 5: Ban `subprocess`/`shutil` from the inner rings** (`tests/test_architecture.py`)

Replace `FORBIDDEN_REFS` with:

```python
FORBIDDEN_REFS = {
    "domain": [
        "claude_usage.application",
        "claude_usage.infrastructure",
        "claude_usage.ui",
        "import wx",
        "import subprocess",
        "from subprocess",
        "import shutil",
        "from shutil",
    ],
    "application": [
        "claude_usage.infrastructure",
        "claude_usage.ui",
        "import wx",
        "import subprocess",
        "from subprocess",
        "import shutil",
        "from shutil",
    ],
    "infrastructure": ["claude_usage.ui", "import wx"],
}
```

(Both needle forms, because `from subprocess import run` does not contain the
substring `import subprocess`. This guard test passes immediately — it exists
to fail when a future edit reaches for a process from an inner ring.)

- [ ] **Step 6: Run the full suite**

Run: `pytest`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add claude_usage/infrastructure/claude_cli.py \
        tests/test_infrastructure_claude_cli.py tests/test_architecture.py
git commit -m "Add ClaudeCliRefresher adapter spawning claude -p /usage"
```

---

### Task 4: `RefreshWorker` and `outcome_tooltip`

**Files:**
- Create: `claude_usage/ui/app/refresh.py`
- Test: `tests/test_ui_app_refresh.py` (new)

**Interfaces:**
- Consumes: `QuotaRefresher`, `RefreshOutcome` from Task 3.
- Produces (Task 8 imports these from `claude_usage.ui.app.refresh`):
  - `RefreshWorker(refresher, read_view, deliver, call_after=wx.CallAfter)`
    with `start() -> bool`
  - `outcome_tooltip(outcome: RefreshOutcome) -> str | None` — `None` for
    `REFRESHED`, else `"Last refresh: <value>"`

- [ ] **Step 1: Write the failing tests** (`tests/test_ui_app_refresh.py`)

```python
"""RefreshWorker tests — fakes only: no wx.App, no subprocess, no sleeping.
Coordination uses events with timeouts, never sleep(). Importing refresh.py
imports the wx module (for the call_after default); no widget is created.
"""
import threading

from claude_usage.infrastructure.claude_cli import RefreshOutcome
from claude_usage.ui.app.refresh import RefreshWorker, outcome_tooltip

VIEW = object()  # the worker never inspects the view; identity is enough


class ScriptedRefresher:
    def __init__(self, outcome, gate=None):
        self.calls = 0
        self._outcome = outcome
        self._gate = gate

    def refresh(self):
        self.calls += 1
        if self._gate is not None:
            assert self._gate.wait(timeout=5), "test gate never opened"
        return self._outcome


class RecordingDeliver:
    def __init__(self):
        self.received = []
        self.done = threading.Event()

    def __call__(self, view, outcome):
        self.received.append((view, outcome))
        self.done.set()


class RecordingCallAfter:
    """Synchronous stand-in for wx.CallAfter that proves it was the path."""

    def __init__(self):
        self.calls = 0

    def __call__(self, fn, *args):
        self.calls += 1
        fn(*args)


def make_worker(refresher, deliver):
    call_after = RecordingCallAfter()
    worker = RefreshWorker(
        refresher=refresher,
        read_view=lambda: VIEW,
        deliver=deliver,
        call_after=call_after,
    )
    return worker, call_after


def test_refreshes_reads_and_delivers_through_call_after():
    refresher = ScriptedRefresher(RefreshOutcome.REFRESHED)
    deliver = RecordingDeliver()
    worker, call_after = make_worker(refresher, deliver)
    assert worker.start() is True
    assert deliver.done.wait(timeout=5)
    assert refresher.calls == 1
    assert deliver.received == [(VIEW, RefreshOutcome.REFRESHED)]
    assert call_after.calls == 1  # delivered via call_after, never directly


def test_non_refreshed_outcome_delivered_verbatim():
    refresher = ScriptedRefresher(RefreshOutcome.NOT_FOUND)
    deliver = RecordingDeliver()
    worker, _ = make_worker(refresher, deliver)
    worker.start()
    assert deliver.done.wait(timeout=5)
    assert deliver.received == [(VIEW, RefreshOutcome.NOT_FOUND)]


def test_start_refuses_reentry_while_in_flight():
    gate = threading.Event()
    refresher = ScriptedRefresher(RefreshOutcome.REFRESHED, gate=gate)
    deliver = RecordingDeliver()
    worker, _ = make_worker(refresher, deliver)
    assert worker.start() is True
    assert worker.start() is False       # programmatic double-fire: refused
    gate.set()
    assert deliver.done.wait(timeout=5)
    assert refresher.calls == 1          # the refusal spawned nothing


def test_start_works_again_after_completion():
    refresher = ScriptedRefresher(RefreshOutcome.REFRESHED)
    deliver = RecordingDeliver()
    worker, _ = make_worker(refresher, deliver)
    assert worker.start() is True
    assert deliver.done.wait(timeout=5)
    deliver.done.clear()
    assert worker.start() is True
    assert deliver.done.wait(timeout=5)
    assert refresher.calls == 2


def test_outcome_tooltip_maps_failures_and_clears_success():
    assert outcome_tooltip(RefreshOutcome.REFRESHED) is None
    assert outcome_tooltip(RefreshOutcome.NOT_FOUND) == "Last refresh: not_found"
    assert outcome_tooltip(RefreshOutcome.TIMED_OUT) == "Last refresh: timed_out"
    assert outcome_tooltip(RefreshOutcome.FAILED) == "Last refresh: failed"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_ui_app_refresh.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'claude_usage.ui.app.refresh'`.

- [ ] **Step 3: Implement the worker** (`claude_usage/ui/app/refresh.py`)

```python
"""One-shot refresh worker. Mirrors poller.py's threading rules: the spawn
and re-read run off the GUI thread, and only frozen data crosses back, via
call_after (wx.CallAfter in production, injectable for tests).
"""
from __future__ import annotations

import threading
from typing import Any, Callable

import wx

from claude_usage.infrastructure.claude_cli import QuotaRefresher, RefreshOutcome
from claude_usage.ui.app.presenter import QuotaView


def outcome_tooltip(outcome: RefreshOutcome) -> str | None:
    """The button's whole outcome display: failures become a tooltip so a
    machine without `claude` on PATH does not fail silently; success clears
    it — the refreshed data speaks for itself.
    """
    if outcome is RefreshOutcome.REFRESHED:
        return None
    return f"Last refresh: {outcome.value}"


class RefreshWorker:
    def __init__(
        self,
        refresher: QuotaRefresher,
        read_view: Callable[[], QuotaView],
        deliver: Callable[[QuotaView, RefreshOutcome], None],
        call_after: Callable[..., Any] = wx.CallAfter,
    ) -> None:
        self._refresher = refresher
        self._read_view = read_view
        self._deliver = deliver
        self._call_after = call_after
        self._in_flight = threading.Lock()

    def start(self) -> bool:
        """Spawn one refresh thread; False and no-op if one is in flight.
        The disabled button is the primary guard — this refusal only keeps a
        programmatic double-fire from producing two child processes.
        """
        if not self._in_flight.acquire(blocking=False):
            return False
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self) -> None:
        # refresh() and read_view never raise (their contracts); the finally
        # keeps a broken contract from wedging start() shut forever. Released
        # before delivery: the run is over once the child exited and the
        # re-read finished.
        try:
            outcome = self._refresher.refresh()
            view = self._read_view()
        finally:
            self._in_flight.release()
        self._call_after(self._deliver, view, outcome)
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_ui_app_refresh.py -v`
Expected: all 5 PASS, in well under a second (no sleeps — events only).

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add claude_usage/ui/app/refresh.py tests/test_ui_app_refresh.py
git commit -m "Add RefreshWorker running the CLI refresh off the GUI thread"
```

---

### Task 5: App message — "click Refresh"

**Files:**
- Modify: `claude_usage/ui/app/presenter.py:22`
- Modify: `claude_usage/ui/app/2026-08-10-quota-app-design.md:239` (spec §9: quoted text must not contradict code)
- Test: `tests/test_ui_presenter.py:98`

**Interfaces:**
- Consumes: nothing from other tasks (independent of the button).
- Produces: the exact app string `No quota data cached yet — click Refresh`.

- [ ] **Step 1: Update the assertion to the new text** (`tests/test_ui_presenter.py:98`)

```python
    assert view.message == "No quota data cached yet — click Refresh"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ui_presenter.py::test_no_quota_key_message -v`
Expected: FAIL — actual is still `"No quota data cached yet — run Claude Code once"`.

- [ ] **Step 3: Change the message** (`claude_usage/ui/app/presenter.py:22`, in `_NO_DATA_MESSAGES`)

```python
    QuotaUnavailable.NO_QUOTA_KEY: "No quota data cached yet — click Refresh",
```

- [ ] **Step 4: Update the sibling spec's quote** (`claude_usage/ui/app/2026-08-10-quota-app-design.md:239`)

```markdown
| `NO_QUOTA_KEY` | "No quota data cached yet — click Refresh" | empty |
```

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add claude_usage/ui/app/presenter.py tests/test_ui_presenter.py \
        claude_usage/ui/app/2026-08-10-quota-app-design.md
git commit -m "Point the app's NO_QUOTA_KEY message at the Refresh button"
```

---

### Task 6: CLI message — "open /usage in Claude Code"

**Files:**
- Modify: `claude_usage/ui/cli/main.py:42`
- Modify: `claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md:350` (spec §9)
- Test: `tests/test_ui_cli_main.py:34`

**Interfaces:**
- Consumes: nothing from other tasks. This is the CLI's **only** change — no
  refresher import, no flag, no spawn.
- Produces: the exact CLI string `No quota data cached yet — open /usage in Claude Code`.

- [ ] **Step 1: Update the assertion** (`tests/test_ui_cli_main.py:34`)

```python
    assert err.strip() == "No quota data cached yet — open /usage in Claude Code"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ui_cli_main.py::test_no_quota_key_exits_one_with_stderr -v`
Expected: FAIL on the old text.

- [ ] **Step 3: Change the message** (`claude_usage/ui/cli/main.py:42`, in `_NO_DATA_MESSAGES`)

```python
    QuotaUnavailable.NO_QUOTA_KEY: "No quota data cached yet — open /usage in Claude Code",
```

- [ ] **Step 4: Update the sibling spec's quote** (`claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md:350`)

```markdown
| No usable cache | `No quota data cached yet — open /usage in Claude Code` to **stderr** | 1 |
```

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add claude_usage/ui/cli/main.py tests/test_ui_cli_main.py \
        claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md
git commit -m "Correct the CLI's NO_QUOTA_KEY remedy to opening /usage"
```

---

### Task 7: The Refresh button on `QuotaFrame`

**Files:**
- Modify: `claude_usage/ui/app/frame.py`

Per design §10 the frame is thin wx glue over the parts tested in Tasks 3–4;
it gets a manual smoke check here (headless-safe: no behavior change until
Task 8 wires `on_refresh`) and a full one in Task 8.

**Interfaces:**
- Consumes: nothing new (the callback is an opaque `Callable`).
- Produces (Task 8 calls these):
  - `QuotaFrame(on_close, on_refresh: Callable[[], None] | None = None)` —
    `None` (the default) creates no button, so existing callers and any
    refresher-less composition run unchanged
  - `begin_refresh() -> None` — disables the button, label "Refreshing…"
  - `end_refresh(tooltip: str | None) -> None` — label "Refresh", re-enabled;
    sets the tooltip, or clears it when `None`

- [ ] **Step 1: Add the button and its state methods** (`claude_usage/ui/app/frame.py`)

Add a module constant beside `_MIN_WIDTH`:

```python
_BUTTON_MARGIN = 8
```

Replace `__init__` and add the two methods (`_handle_close` is unchanged):

```python
    def __init__(
        self,
        on_close: Callable[[], None],
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            None,
            title="Claude Usage",
            size=(356, 220),
            style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP,
        )
        self.SetBackgroundColour(wx.Colour(*theme.BACKGROUND))
        self._on_close = on_close
        self.panel = QuotaPanel(self)
        self._refresh_button: wx.Button | None = None
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.panel, 1, wx.EXPAND)
        if on_refresh is not None:
            self._refresh_button = wx.Button(self, label="Refresh")
            self._refresh_button.Bind(wx.EVT_BUTTON, lambda event: on_refresh())
            sizer.Add(self._refresh_button, 0, wx.ALL, _BUTTON_MARGIN)
        self.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, self._handle_close)

    def begin_refresh(self) -> None:
        """The disabled button is the entire in-progress UI (design §6)."""
        if self._refresh_button is None:
            return
        self._refresh_button.Disable()
        self._refresh_button.SetLabel("Refreshing…")

    def end_refresh(self, tooltip: str | None) -> None:
        if self._refresh_button is None:
            return
        self._refresh_button.SetLabel("Refresh")
        self._refresh_button.Enable()
        if tooltip is None:
            self._refresh_button.UnsetToolTip()
        else:
            self._refresh_button.SetToolTip(tooltip)
```

- [ ] **Step 2: Include the button row in the fit computation**

In `_fit_to_content`, replace the `needed` line:

```python
        needed = self.panel.content_height(view) + self._button_row_height()
```

and add:

```python
    def _button_row_height(self) -> int:
        # Without this the button clips: content_height() covers only
        # QuotaPanel's drawing (design §6).
        if self._refresh_button is None:
            return 0
        return self._refresh_button.GetBestSize().height + 2 * _BUTTON_MARGIN
```

- [ ] **Step 3: Run the full suite**

Run: `pytest`
Expected: all pass (no test constructs `QuotaFrame`; the new parameter
defaults to `None`).

- [ ] **Step 4: Smoke-check the no-button path is unchanged**

Run: `python -m claude_usage.ui.app.main --path tests/fixtures/live_snapshot.json`
Expected: the window looks exactly as before — no button, nothing clipped
(the composition root does not pass `on_refresh` until Task 8). Close it.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/ui/app/frame.py
git commit -m "Add a Refresh button and in-progress state to QuotaFrame"
```

---

### Task 8: Composition root wiring and end-to-end smoke

**Files:**
- Modify: `claude_usage/ui/app/main.py`

The composition root has no unit tests (established convention — it is wiring
over tested parts); its verification is the smoke script below. The CLI root
is **not** touched.

**Interfaces:**
- Consumes: `Config.refresh_timeout_seconds` / `Config.claude_executable`
  (Task 2), `ClaudeCliRefresher` (Task 3), `RefreshWorker` /
  `outcome_tooltip` (Task 4), `QuotaFrame.begin_refresh` / `end_refresh` /
  `on_refresh` (Task 7), existing `PollerThread.refresh_once`.
- Produces: the running app. The button is always wired — no config switch.

- [ ] **Step 1: Wire the refresher, worker, and callback** (`claude_usage/ui/app/main.py`)

Add imports:

```python
from claude_usage.infrastructure.claude_cli import ClaudeCliRefresher
from claude_usage.ui.app.refresh import RefreshWorker, outcome_tooltip
```

In `main`, replace the frame/poller block with:

```python
    def on_refresh() -> None:
        # Closes over `worker`, assigned below — safe because the callback
        # only fires on a button click, after wiring completes. If start()
        # is refused (a run is in flight), the in-flight run's delivery
        # re-enables the button.
        frame.begin_refresh()
        worker.start()

    frame = QuotaFrame(on_close=lambda: poller.stop(), on_refresh=on_refresh)
    poller = PollerThread(service, config, on_view=frame.show_view)

    def deliver(view, outcome) -> None:
        frame.show_view(view)
        frame.end_refresh(outcome_tooltip(outcome))

    worker = RefreshWorker(
        ClaudeCliRefresher(
            executable=config.claude_executable,
            timeout_seconds=config.refresh_timeout_seconds,
        ),
        read_view=poller.refresh_once,
        deliver=deliver,
    )
```

(Everything from `frame.show_view(poller.refresh_once())` down is unchanged.
The existing comment about `on_close` closing over `poller` stays.)

- [ ] **Step 2: Run the full suite**

Run: `pytest`
Expected: all pass.

- [ ] **Step 3: End-to-end smoke against a stub — never the real `claude`**

```bash
STUB_DIR=$(mktemp -d)
printf '#!/bin/sh\nsleep 2\nexit 0\n' > "$STUB_DIR/claude"
chmod +x "$STUB_DIR/claude"
cat > "$STUB_DIR/config.toml" <<EOF
claude_executable = "$STUB_DIR/claude"
refresh_timeout_seconds = 10
EOF
python -m claude_usage.ui.app.main \
    --path tests/fixtures/live_snapshot.json --config "$STUB_DIR/config.toml"
```

Expected, in order:
1. The window shows the fixture's bars with a **Refresh** button below them,
   fully visible (nothing clipped — the fit computation grew for it).
2. Click Refresh → the button disables and reads **Refreshing…**; the window
   stays responsive (drag it) for the ~2s the stub sleeps.
3. The button returns to **Refresh**, enabled, with no tooltip.

Then the failure tooltip:

```bash
printf '#!/bin/sh\nexit 1\n' > "$STUB_DIR/claude"
python -m claude_usage.ui.app.main \
    --path tests/fixtures/live_snapshot.json --config "$STUB_DIR/config.toml"
```

Expected: click Refresh → button cycles quickly; hovering it shows the
tooltip **Last refresh: failed**. Close the app and `rm -rf "$STUB_DIR"`.

- [ ] **Step 4: Commit**

```bash
git add claude_usage/ui/app/main.py
git commit -m "Wire the Refresh button through the app composition root"
```

---

## Completion Checklist

- [ ] Full suite green: `pytest`
- [ ] `git log --oneline main..` shows the eight commits above, on
  `feat/quota-manual-refresh`
- [ ] Grep proves the absolutes: `grep -rn "subprocess" claude_usage/domain
  claude_usage/application claude_usage/ui/cli` returns nothing;
  `grep -rn "claude_cli" claude_usage/ui/cli` returns nothing (the CLI has no
  refresher)
- [ ] No test touches the real `~/.claude.json` or invokes a real `claude`
  (all spawn tests go through `write_stub`)
