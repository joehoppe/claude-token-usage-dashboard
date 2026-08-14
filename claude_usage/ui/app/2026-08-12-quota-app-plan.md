# Quota App v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the always-on-top wxPython quota window described in
[`2026-08-10-quota-app-design.md`](2026-08-10-quota-app-design.md), extending
the existing `domain`/`application`/`infrastructure` core to support four
distinguishable no-data states and a config file, and bringing the existing
CLI driver up to capability parity per that spec's §7.

**Architecture:** Onion — `domain/quota.py` gains a `QuotaUnavailable` result
type; `application/ports.py` and `application/usage.py` route it with
last-good-reading memory; `infrastructure/claude_json.py` and the new
`infrastructure/config.py` produce it. A new `ui/shared/format.py` holds
formatting helpers used by both drivers. `ui/app/presenter.py` is a pure
`QuotaSnapshot -> QuotaView` function; `ui/app/panels.py`, `frame.py`, and
`poller.py` are thin wx wiring around it. `ui/cli/` gains matching messages
for the same four states.

**Tech Stack:** Python (stdlib `tomllib`), wxPython (new dependency, approved
in `AGENTS.md`), pytest.

## Global Constraints

- Onion architecture: imports point inward only. `domain/` — stdlib only, no
  `wx`. `application/` — no `infrastructure`, no `ui`, no `wx`.
  `infrastructure/` — no `ui`, no `wx`. `ui/app` and `ui/cli` are siblings and
  must not import each other. `wx` is confined to `ui/app/`.
  (`AGENTS.md`, spec §2)
- Only MIT-licensed runtime dependencies, except the pre-approved wxPython
  exception. (`AGENTS.md` "Open Source")
- `accountUuid` is never read into any field, displayed, or logged.
  `message_detail`/`detail` carries an exception class name only — never a
  path or file contents. (spec §8)
- The app is strictly read-only: no writes to `~/.claude.json` or the config
  file; window position/size are never persisted. (spec §5.1, §8)
- `requires-python` moves to `>=3.11` so `config.py` can use stdlib
  `tomllib` (decided during planning — the spec assumes this but the repo's
  `pyproject.toml` currently pins `>=3.10`).
- Every change to `domain/`, `application/`, or `infrastructure/` must reach
  both drivers (`ui/cli/` and `ui/app/`) in the same task/commit sequence, or
  be recorded as a deviation. (spec §7.1)
- Spec documents and plans for this feature live beside their implementation
  in `claude_usage/ui/app/`, per this project's convention — not under
  `docs/superpowers/`.
- Strict TDD: a failing test precedes each implementation step, per `CLAUDE.md`.

---

### Task 1: Domain — `QuotaUnavailable` and extended `QuotaSnapshot`

**Files:**
- Modify: `claude_usage/domain/quota.py`
- Test: `tests/test_domain_quota.py`

**Interfaces:**
- Produces: `QuotaUnavailable(Enum)` with members `NO_FILE = "no_file"`,
  `NO_QUOTA_KEY = "no_quota_key"`, `READ_ERROR = "read_error"`.
  `QuotaSnapshot(captured_at: datetime, quota: QuotaReading | None,
  is_stale: bool, unavailable: QuotaUnavailable | None = None,
  detail: str | None = None)` — frozen dataclass, backward compatible with
  existing 3-keyword construction.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_domain_quota.py` (extend the existing import line to add
`QuotaUnavailable`):

```python
from claude_usage.domain.quota import (
    STALE_AFTER,
    LimitReading,
    QuotaReading,
    QuotaSnapshot,
    QuotaUnavailable,
    time_remaining,
)


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_domain_quota.py -v`
Expected: `ImportError: cannot import name 'QuotaUnavailable'`

- [ ] **Step 3: Implement**

In `claude_usage/domain/quota.py`, add the `Enum` import, the new enum, and
extend `QuotaSnapshot`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

STALE_AFTER = timedelta(minutes=15)


class QuotaUnavailable(Enum):
    NO_FILE = "no_file"            # ~/.claude.json absent
    NO_QUOTA_KEY = "no_quota_key"  # file readable, cachedUsageUtilization absent/invalid
    READ_ERROR = "read_error"      # OSError, JSONDecodeError, unusable fetchedAtMs
```

...and change the `QuotaSnapshot` class to:

```python
@dataclass(frozen=True)
class QuotaSnapshot:
    captured_at: datetime
    quota: QuotaReading | None
    is_stale: bool
    unavailable: QuotaUnavailable | None = None
    detail: str | None = None      # e.g. "JSONDecodeError"; never a file path or payload
```

Leave `LimitReading`, `QuotaReading`, `time_remaining` unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_domain_quota.py -v`
Expected: all PASS, including the pre-existing tests (`QuotaSnapshot`'s new
fields default, so `test_entities_are_frozen`'s 3-keyword construction still
works).

- [ ] **Step 5: Commit**

```bash
git add claude_usage/domain/quota.py tests/test_domain_quota.py
git commit -m "Add QuotaUnavailable outcome type and extend QuotaSnapshot"
```

---

### Task 2: Infrastructure — four-outcome `ClaudeJsonQuotaSource` + updated `QuotaSource` port

**Files:**
- Modify: `claude_usage/application/ports.py`
- Modify: `claude_usage/infrastructure/claude_json.py`
- Modify: `tests/test_infrastructure_claude_json.py`

**Interfaces:**
- Consumes: `QuotaUnavailable` from Task 1 (`claude_usage.domain.quota`).
- Produces: `QuotaSource` protocol —
  `read_quota(self) -> QuotaReading | QuotaUnavailable` and
  `read_error_detail(self) -> str | None` (the second call returns the
  caught exception's class name immediately after a `READ_ERROR` result from
  the first; `None` otherwise). `ClaudeJsonQuotaSource` implements both.

**Design note (from planning):** the spec's `detail` field needs to travel
from the infrastructure adapter to `QuotaSnapshot`, but `read_quota()`'s
signature has no room for a string. Resolved by adding a second port method,
`read_error_detail()`, called only when `read_quota()` returned
`QuotaUnavailable.READ_ERROR`. `ClaudeJsonQuotaSource` stores the caught
exception's class name between the two calls.

- [ ] **Step 1: Write the failing tests**

Rewrite `tests/test_infrastructure_claude_json.py`'s outcome-based tests
(replacing every `assert ... .read_quota() is None` with the specific
`QuotaUnavailable` member) and add the new cases:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_usage.domain.quota import QuotaUnavailable
from claude_usage.infrastructure.claude_json import ClaudeJsonQuotaSource
from claude_usage.infrastructure.clock import SystemClock

UTC = timezone.utc
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
    session, weekly, scoped = reading.limits
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
            "cachedGrowthBookFeatures": {
                "tengu_rate_limit_promo_notices": "not-a-list"
            },
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_infrastructure_claude_json.py -v`
Expected: failures — `read_quota()` still returns `None`, `read_error_detail`
does not exist.

- [ ] **Step 3: Implement**

In `claude_usage/application/ports.py`, update `QuotaSource`:

```python
"""Ports the application ring declares; infrastructure conforms structurally."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from claude_usage.domain.quota import QuotaReading, QuotaUnavailable


class QuotaSource(Protocol):
    def read_quota(self) -> QuotaReading | QuotaUnavailable: ...
    def read_error_detail(self) -> str | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
```

In `claude_usage/infrastructure/claude_json.py`, replace the class body
(keep `_parse_limits`, `_parse_resets_at`, `_parse_scope_model`,
`_parse_promos` unchanged):

```python
"""Adapter over ~/.claude.json. Read-only; never touches accountUuid."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from claude_usage.domain.quota import LimitReading, QuotaReading, QuotaUnavailable


class ClaudeJsonQuotaSource:
    def __init__(self, path: Path | None = None) -> None:
        # ~/.claude.json is the sibling of ~/.claude/, not a file inside it.
        self._path = path if path is not None else Path.home() / ".claude.json"
        self._last_error_detail: str | None = None

    def read_quota(self) -> QuotaReading | QuotaUnavailable:
        self._last_error_detail = None
        try:
            text = self._path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return QuotaUnavailable.NO_FILE
        except OSError as exc:
            return self._fail(exc)

        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            return self._fail(exc)
        if not isinstance(raw, dict):
            return self._fail(ValueError("root is not an object"))

        cached = raw.get("cachedUsageUtilization")
        if not isinstance(cached, dict):
            return QuotaUnavailable.NO_QUOTA_KEY

        fetched_at_ms = cached.get("fetchedAtMs")
        if isinstance(fetched_at_ms, bool) or not isinstance(fetched_at_ms, (int, float)):
            return self._fail(ValueError("fetchedAtMs missing or non-numeric"))
        try:
            measured_at = datetime.fromtimestamp(fetched_at_ms / 1000, tz=timezone.utc)
        except (ValueError, OverflowError, OSError) as exc:
            return self._fail(exc)

        return QuotaReading(
            measured_at=measured_at,
            limits=_parse_limits(cached),
            promo_notices=_parse_promos(raw),
        )

    def read_error_detail(self) -> str | None:
        return self._last_error_detail

    def _fail(self, exc: Exception) -> QuotaUnavailable:
        self._last_error_detail = type(exc).__name__
        return QuotaUnavailable.READ_ERROR
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_infrastructure_claude_json.py -v`
Expected: all PASS.

Run: `pytest -q` (full suite)
Expected: `tests/test_ui_cli_render.py::test_render_requires_quota` and CLI/
render tests still pass — they don't touch `ClaudeJsonQuotaSource` directly.
`tests/test_application_usage.py::test_snapshot_missing_quota_is_stale`
will now FAIL (it passes `None` to a `FakeQuotaSource`, which no longer
matches the real port's return type) — that's expected; Task 3 fixes it.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/application/ports.py claude_usage/infrastructure/claude_json.py tests/test_infrastructure_claude_json.py
git commit -m "Distinguish NO_FILE/NO_QUOTA_KEY/READ_ERROR in ClaudeJsonQuotaSource"
```

---

### Task 3: Application — `UsageService` last-good-reading memory

**Files:**
- Modify: `claude_usage/application/usage.py`
- Modify: `tests/test_application_usage.py`

**Interfaces:**
- Consumes: `QuotaSource` protocol from Task 2
  (`read_quota() -> QuotaReading | QuotaUnavailable`,
  `read_error_detail() -> str | None`); `QuotaUnavailable`, `QuotaSnapshot`,
  `STALE_AFTER` from Task 1.
- Produces:
  `UsageService(quota_source: QuotaSource, clock: Clock, stale_after:
  timedelta = STALE_AFTER)` with `.snapshot() -> QuotaSnapshot`, unchanged
  from the caller's perspective except the new optional `stale_after` param.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_application_usage.py` in full:

```python
from datetime import datetime, timedelta, timezone

from claude_usage.application.usage import UsageService
from claude_usage.domain.quota import QuotaReading, QuotaUnavailable

UTC = timezone.utc
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


def test_no_file_never_falls_back(tmp_path=None):
    good = make_reading(NOW - timedelta(minutes=5))
    source = ScriptedQuotaSource(
        [(good, None), (QuotaUnavailable.NO_FILE, None)]
    )
    service = UsageService(source, FrozenClock(NOW))
    service.snapshot()  # primes last-good-reading
    snapshot = service.snapshot()
    assert snapshot.quota is None
    assert snapshot.unavailable is QuotaUnavailable.NO_FILE
    assert snapshot.is_stale is True


def test_no_quota_key_never_falls_back():
    good = make_reading(NOW - timedelta(minutes=5))
    source = ScriptedQuotaSource(
        [(good, None), (QuotaUnavailable.NO_QUOTA_KEY, None)]
    )
    service = UsageService(source, FrozenClock(NOW))
    service.snapshot()
    snapshot = service.snapshot()
    assert snapshot.quota is None
    assert snapshot.unavailable is QuotaUnavailable.NO_QUOTA_KEY


def test_read_error_falls_back_to_prior_reading_with_original_measured_at():
    good = make_reading(NOW - timedelta(minutes=5))
    source = ScriptedQuotaSource(
        [(good, None), (QuotaUnavailable.READ_ERROR, "JSONDecodeError")]
    )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_application_usage.py -v`
Expected: failures — `UsageService.snapshot()` still treats every non-`None`
result as a good reading and has no `stale_after` param.

- [ ] **Step 3: Implement**

Replace `claude_usage/application/usage.py`:

```python
from __future__ import annotations

from datetime import timedelta

from claude_usage.application.ports import Clock, QuotaSource
from claude_usage.domain.quota import (
    STALE_AFTER,
    QuotaReading,
    QuotaSnapshot,
    QuotaUnavailable,
)


class UsageService:
    def __init__(
        self,
        quota_source: QuotaSource,
        clock: Clock,
        stale_after: timedelta = STALE_AFTER,
    ) -> None:
        self._quota_source = quota_source
        self._clock = clock
        self._stale_after = stale_after
        self._last_good: QuotaReading | None = None

    def snapshot(self) -> QuotaSnapshot:
        now = self._clock.now()
        result = self._quota_source.read_quota()

        if isinstance(result, QuotaReading):
            self._last_good = result
            return QuotaSnapshot(
                captured_at=now,
                quota=result,
                is_stale=result.is_stale(now, self._stale_after),
            )

        if result is QuotaUnavailable.READ_ERROR and self._last_good is not None:
            return QuotaSnapshot(
                captured_at=now,
                quota=self._last_good,
                is_stale=True,
                unavailable=QuotaUnavailable.READ_ERROR,
                detail=self._quota_source.read_error_detail(),
            )

        # NO_FILE / NO_QUOTA_KEY never fall back; READ_ERROR with no prior
        # reading has nothing to fall back to. Either way, discard history —
        # a stale reading shown for a missing file would be a lie.
        self._last_good = None
        detail = (
            self._quota_source.read_error_detail()
            if result is QuotaUnavailable.READ_ERROR
            else None
        )
        return QuotaSnapshot(
            captured_at=now, quota=None, is_stale=True, unavailable=result, detail=detail
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_application_usage.py -v`
Expected: all PASS.

Run: `pytest -q`
Expected: full suite passes again (Task 2's expected failure is now fixed).

- [ ] **Step 5: Commit**

```bash
git add claude_usage/application/usage.py tests/test_application_usage.py
git commit -m "Add last-good-reading fallback and configurable staleness to UsageService"
```

---

### Task 4: Infrastructure — `Config`, `ConfigSource`, `TomlConfigSource`

**Files:**
- Modify: `claude_usage/application/ports.py`
- Create: `claude_usage/infrastructure/config.py`
- Test: `tests/test_infrastructure_config.py` (new)

**Interfaces:**
- Produces: `Config(poll_seconds: int = 10, stale_after: timedelta =
  STALE_AFTER, warnings: tuple[str, ...] = ())` frozen dataclass in
  `application/ports.py`. `ConfigSource` protocol —
  `read_config(self) -> Config`. `TomlConfigSource(path: Path | None =
  None)` in `infrastructure/config.py`, implementing it, defaulting to
  `Path.home() / ".config" / "claude-usage" / "config.toml"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_infrastructure_config.py`:

```python
from datetime import timedelta

from claude_usage.application.ports import Config
from claude_usage.infrastructure.config import TomlConfigSource


def write_toml(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_absent_file_returns_defaults_silently(tmp_path):
    config = TomlConfigSource(tmp_path / "missing.toml").read_config()
    assert config == Config()
    assert config.warnings == ()


def test_valid_file_overrides_defaults(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = 30\nstale_after_minutes = 5\n")
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 30
    assert config.stale_after == timedelta(minutes=5)
    assert config.warnings == ()


def test_malformed_toml_gives_defaults_and_one_warning(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = [unterminated")
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 10
    assert config.stale_after == timedelta(minutes=15)
    assert len(config.warnings) == 1


def test_unreadable_file_gives_defaults_and_one_warning(tmp_path):
    # A directory raises OSError on read_bytes — the "unreadable" case,
    # distinct from "absent" (FileNotFoundError).
    config = TomlConfigSource(tmp_path).read_config()
    assert config.poll_seconds == 10
    assert len(config.warnings) == 1


def test_wrong_type_defaults_that_key_and_warns_others_still_apply(tmp_path):
    path = write_toml(tmp_path, 'poll_seconds = "thirty"\nstale_after_minutes = 5\n')
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 10
    assert config.stale_after == timedelta(minutes=5)
    assert len(config.warnings) == 1
    assert "poll_seconds" in config.warnings[0]


def test_out_of_range_rejected_to_default_not_clamped(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = 9999\n")
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 10
    assert len(config.warnings) == 1


def test_unknown_keys_ignored_without_warning(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = 20\nfuture_knob = true\n")
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 20
    assert config.warnings == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_infrastructure_config.py -v`
Expected: `ModuleNotFoundError: No module named 'claude_usage.infrastructure.config'`

- [ ] **Step 3: Implement**

In `claude_usage/application/ports.py`, add `Config` and `ConfigSource`
(keep the `QuotaSource`/`Clock` protocols from Task 2 unchanged):

```python
"""Ports the application ring declares; infrastructure conforms structurally."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from claude_usage.domain.quota import STALE_AFTER, QuotaReading, QuotaUnavailable


class QuotaSource(Protocol):
    def read_quota(self) -> QuotaReading | QuotaUnavailable: ...
    def read_error_detail(self) -> str | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class Config:
    poll_seconds: int = 10
    stale_after: timedelta = STALE_AFTER
    warnings: tuple[str, ...] = ()


class ConfigSource(Protocol):
    def read_config(self) -> Config: ...
```

Create `claude_usage/infrastructure/config.py`:

```python
"""Adapter reading claude-usage's config.toml. Read-only; the app never writes it."""
from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path

from claude_usage.application.ports import Config

DEFAULT_PATH = Path.home() / ".config" / "claude-usage" / "config.toml"

_POLL_SECONDS_RANGE = range(1, 601)
_STALE_MINUTES_RANGE = range(1, 1441)


class TomlConfigSource:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else DEFAULT_PATH

    def read_config(self) -> Config:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return Config()
        except OSError:
            return Config(warnings=("could not read config.toml — using defaults",))

        try:
            data = tomllib.loads(raw.decode("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            return Config(warnings=("malformed config.toml — using defaults",))

        warnings: list[str] = []
        poll_seconds = _read_int(data, "poll_seconds", 10, _POLL_SECONDS_RANGE, warnings)
        stale_minutes = _read_int(
            data, "stale_after_minutes", 15, _STALE_MINUTES_RANGE, warnings
        )
        return Config(
            poll_seconds=poll_seconds,
            stale_after=timedelta(minutes=stale_minutes),
            warnings=tuple(warnings),
        )


def _read_int(
    data: dict, key: str, default: int, valid_range: range, warnings: list[str]
) -> int:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or value not in valid_range:
        warnings.append(f"{key} is invalid — using default")
        return default
    return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_infrastructure_config.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/application/ports.py claude_usage/infrastructure/config.py tests/test_infrastructure_config.py
git commit -m "Add Config, ConfigSource, and TomlConfigSource"
```

---

### Task 5: UI shared — extract `label_for`/`coarse` to `ui/shared/format.py`

**Files:**
- Create: `claude_usage/ui/shared/__init__.py`
- Create: `claude_usage/ui/shared/format.py`
- Modify: `claude_usage/ui/cli/render.py`
- Create: `tests/test_ui_shared_format.py`
- Modify: `tests/test_ui_cli_render.py`

**Interfaces:**
- Consumes: `LimitReading` (domain, unchanged).
- Produces: `label_for(limit: LimitReading) -> str`,
  `coarse(delta: timedelta) -> str` in `claude_usage.ui.shared.format` —
  identical behavior to the functions currently in `ui/cli/render.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui_shared_format.py`:

```python
from datetime import timedelta

from claude_usage.domain.quota import LimitReading
from claude_usage.ui.shared.format import coarse, label_for


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


def test_known_kind_labels():
    assert label_for(make_limit(kind="session")) == "Session (5hr)"
    assert label_for(make_limit(kind="weekly_all")) == "Weekly (7 day)"
    assert label_for(
        make_limit(kind="weekly_scoped", scope_model="Fable")
    ) == "Weekly Fable"


def test_unknown_kind_falls_back_without_crashing():
    assert label_for(make_limit(kind="monthly_all")) == "Monthly All"
    assert label_for(
        make_limit(kind="monthly_scoped", scope_model="Sonnet")
    ) == "Monthly Scoped Sonnet"


def test_coarse_units():
    assert coarse(timedelta(seconds=30)) == "<1m"
    assert coarse(timedelta(minutes=12)) == "12m"
    assert coarse(timedelta(hours=2)) == "2h"
    assert coarse(timedelta(days=1, hours=18)) == "1d"
```

Remove the now-duplicated `test_known_kind_labels`,
`test_unknown_kind_falls_back_without_crashing`, and `test_coarse_units`
functions from `tests/test_ui_cli_render.py`, and trim its import line from
`from claude_usage.ui.cli.render import bar, coarse, label_for, render, render_row`
to `from claude_usage.ui.cli.render import bar, render, render_row`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_shared_format.py -v`
Expected: `ModuleNotFoundError: No module named 'claude_usage.ui.shared'`

- [ ] **Step 3: Implement**

Create `claude_usage/ui/shared/__init__.py` (empty).

Create `claude_usage/ui/shared/format.py`:

```python
"""Formatting helpers shared by both drivers. Pure — no wx, no ANSI."""
from __future__ import annotations

from datetime import timedelta

from claude_usage.domain.quota import LimitReading

_KIND_LABELS = {"session": "Session (5hr)", "weekly_all": "Weekly (7 day)"}


def label_for(limit: LimitReading) -> str:
    if limit.kind == "weekly_scoped" and limit.scope_model:
        return f"Weekly {limit.scope_model}"
    if limit.kind in _KIND_LABELS:
        return _KIND_LABELS[limit.kind]
    # Fallback is load-bearing: new limit kinds must render, not crash.
    label = limit.kind.replace("_", " ").title()
    if limit.scope_model:
        label = f"{label} {limit.scope_model}"
    return label


def coarse(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 60:
        return "<1m"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    return f"{total // 86400}d"
```

In `claude_usage/ui/cli/render.py`, remove the local `_KIND_LABELS`,
`label_for`, and `coarse` definitions, and add:

```python
from claude_usage.ui.shared.format import coarse, label_for
```

placed with the other imports at the top of the file. Leave `BAR_WIDTH`,
`_SEVERITY_COLORS`, `_FALLBACK_COLOR`, `_ANSI_RESET`, `bar()`,
`render_row()`, and `render()` unchanged — they still call `label_for(...)`
and `coarse(...)` by name, now resolved from the import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_shared_format.py tests/test_ui_cli_render.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/ui/shared claude_usage/ui/cli/render.py tests/test_ui_shared_format.py tests/test_ui_cli_render.py
git commit -m "Move label_for/coarse into ui/shared/format.py, shared by both drivers"
```

---

### Task 6: CLI parity — handle the three CLI-reachable no-data states

**Files:**
- Modify: `claude_usage/ui/cli/render.py`
- Modify: `claude_usage/ui/cli/main.py`
- Modify: `tests/test_ui_cli_render.py`
- Modify: `tests/test_ui_cli_main.py`

**Interfaces:**
- Consumes: `QuotaSnapshot.unavailable`/`.detail` from Task 1;
  `UsageService` from Task 3 (default `stale_after` unchanged, so CLI's
  existing `UsageService(ClaudeJsonQuotaSource(args.path), SystemClock())`
  call needs no change).
- Produces: `render()` unchanged in signature, now also appends a "showing
  last known values" note when `snapshot.unavailable is
  QuotaUnavailable.READ_ERROR` and `snapshot.detail` is set. `main()`
  unchanged in signature, now prints one of three distinct messages
  (`NO_FILE`, `NO_QUOTA_KEY`, `READ_ERROR`) instead of one generic message.

**Design note:** the CLI is one-shot — each `main()` call builds a fresh
`UsageService` and calls `.snapshot()` exactly once, so `_last_good` is
always `None` and the `READ_ERROR`-with-fallback branch (Task 3) can never
be reached through `main()`. It's still reachable by calling `render()`
directly with a hand-built `QuotaSnapshot`, which is how it's tested below.

- [ ] **Step 1: Write the failing tests**

In `tests/test_ui_cli_render.py`, extend the existing
`from claude_usage.domain.quota import LimitReading, QuotaReading, QuotaSnapshot`
import line to add `QuotaUnavailable`, then add (near the other render
tests):

```python
def test_render_read_error_with_fallback_appends_note():
    reading = QuotaReading(
        measured_at=NOW - timedelta(hours=1), limits=(make_limit(),), promo_notices=()
    )
    snapshot = QuotaSnapshot(
        captured_at=NOW,
        quota=reading,
        is_stale=True,
        unavailable=QuotaUnavailable.READ_ERROR,
        detail="JSONDecodeError",
    )
    output = render(snapshot)
    assert "showing last known values (JSONDecodeError)" in output
```

In `tests/test_ui_cli_main.py`, replace
`test_missing_cache_exits_one_with_stderr` and
`test_json_output_is_whitelisted_snapshot`, and add two new tests:

```python
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
    out, err = capsys.readouterr()
    assert code == 1
    assert err.strip() == "No quota data cached yet — run Claude Code once"


def test_read_error_exits_one_with_detail_in_stderr(tmp_path, capsys):
    path = tmp_path / "claude.json"
    path.write_text("{not json", encoding="utf-8")
    code = main(["--path", str(path)])
    out, err = capsys.readouterr()
    assert code == 1
    assert "Couldn't read quota data" in err
    assert "JSONDecodeError" in err


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
```

Delete the old `test_missing_cache_exits_one_with_stderr` function (replaced
by `test_no_file_exits_one_with_stderr`, which covers the same absent-file
case with the new message).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_cli_render.py tests/test_ui_cli_main.py -v`
Expected: failures — old generic message/`ValueError` behavior still in
place; `unavailable`/`detail` absent from JSON output.

- [ ] **Step 3: Implement**

In `claude_usage/ui/cli/render.py`, extend the existing
`from claude_usage.domain.quota import LimitReading, QuotaSnapshot, time_remaining`
import line to add `QuotaUnavailable`, then add the note branch. The full
`render()` becomes:

```python
def render(
    snapshot: QuotaSnapshot, *, color: bool = False, ascii_glyphs: bool = False
) -> str:
    quota = snapshot.quota
    if quota is None:
        raise ValueError("render() requires a snapshot with quota data")
    status = "STALE" if snapshot.is_stale else "fresh"
    age = coarse(quota.age(snapshot.captured_at))
    lines = [f"USAGE{' ' * 32}as of {age} ago · {status}", ""]
    if quota.limits:
        for limit in quota.limits:
            lines.append(
                render_row(
                    limit, snapshot.captured_at, color=color, ascii_glyphs=ascii_glyphs
                )
            )
    else:
        lines.append("  no limits reported")
    if snapshot.unavailable is QuotaUnavailable.READ_ERROR and snapshot.detail:
        lines.append("")
        lines.append(f"  note: showing last known values ({snapshot.detail})")
    if quota.promo_notices:
        lines.append("")
        lines.extend(f"  {notice}" for notice in quota.promo_notices)
    return "\n".join(lines)
```

In `claude_usage/ui/cli/main.py`, extend the existing
`from claude_usage.domain.quota import QuotaSnapshot` import line to add
`QuotaUnavailable`, then update `main()` and `snapshot_to_dict()`:

```python
_NO_DATA_MESSAGES = {
    QuotaUnavailable.NO_FILE: "Claude Code data not found",
    QuotaUnavailable.NO_QUOTA_KEY: "No quota data cached yet — run Claude Code once",
}


def snapshot_to_dict(snapshot: QuotaSnapshot) -> dict:
    """Field whitelist — a raw file passthrough could leak accountUuid."""
    quota = None
    if snapshot.quota is not None:
        quota = {
            "measured_at": snapshot.quota.measured_at.isoformat(),
            "limits": [
                {
                    "kind": limit.kind,
                    "group": limit.group,
                    "percent": limit.percent,
                    "severity": limit.severity,
                    "is_active": limit.is_active,
                    "resets_at": (
                        limit.resets_at.isoformat() if limit.resets_at else None
                    ),
                    "scope_model": limit.scope_model,
                }
                for limit in snapshot.quota.limits
            ],
            "promo_notices": list(snapshot.quota.promo_notices),
        }
    return {
        "captured_at": snapshot.captured_at.isoformat(),
        "is_stale": snapshot.is_stale,
        "quota": quota,
        "unavailable": snapshot.unavailable.value if snapshot.unavailable else None,
        "detail": snapshot.detail,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = UsageService(ClaudeJsonQuotaSource(args.path), SystemClock())
    snapshot = service.snapshot()
    if snapshot.quota is None:
        if snapshot.unavailable in _NO_DATA_MESSAGES:
            message = _NO_DATA_MESSAGES[snapshot.unavailable]
        else:
            message = "Couldn't read quota data"
            if snapshot.detail:
                message += f" ({snapshot.detail})"
        print(message, file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(snapshot_to_dict(snapshot), indent=2))
        return 0
    color = (
        not args.no_color
        and "NO_COLOR" not in os.environ
        and sys.stdout.isatty()
    )
    print(render(snapshot, color=color, ascii_glyphs=args.ascii_glyphs))
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_cli_render.py tests/test_ui_cli_main.py -v`
Expected: all PASS.

Run: `pytest -q`
Expected: full suite passes.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/ui/cli/render.py claude_usage/ui/cli/main.py tests/test_ui_cli_render.py tests/test_ui_cli_main.py
git commit -m "Bring CLI to parity with the three CLI-reachable no-data states"
```

---

### Task 7: Presenter — `ui/app/presenter.py`

**Files:**
- Create: `claude_usage/ui/app/__init__.py`
- Create: `claude_usage/ui/app/presenter.py`
- Test: `tests/test_ui_presenter.py` (new)

**Interfaces:**
- Consumes: `QuotaSnapshot`, `QuotaUnavailable`, `time_remaining` (domain);
  `Config` (application, Task 4); `label_for`, `coarse` (`ui/shared/format`,
  Task 5).
- Produces:
  `BarView(label: str, percent: int, remaining: int, severity: str,
  active: bool, resets_text: str | None)`,
  `QuotaView(headline: str, age_text: str, stale: bool,
  bars: tuple[BarView, ...], notices: tuple[str, ...],
  message: str | None, message_detail: str | None)`,
  `present(snapshot: QuotaSnapshot, config: Config) -> QuotaView`,
  `present_error(exc: Exception) -> QuotaView` — used by `poller.py`
  (Task 11) when the poll loop itself raises.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui_presenter.py`:

```python
from datetime import datetime, timedelta, timezone

from claude_usage.application.ports import Config
from claude_usage.domain.quota import LimitReading, QuotaReading, QuotaSnapshot, QuotaUnavailable
from claude_usage.ui.app.presenter import present, present_error

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 18, 10, tzinfo=UTC)


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


def make_snapshot(limits=(), promos=(), measured_at=None, is_stale=False,
                   unavailable=None, detail=None):
    reading = QuotaReading(
        measured_at=measured_at or NOW - timedelta(minutes=5),
        limits=tuple(limits),
        promo_notices=tuple(promos),
    )
    return QuotaSnapshot(
        captured_at=NOW, quota=reading, is_stale=is_stale,
        unavailable=unavailable, detail=detail,
    )


def test_headline_picks_worst_bar_not_aggregate():
    weekly_all = make_limit(kind="weekly_all", percent=39)
    weekly_fable = make_limit(kind="weekly_scoped", percent=66, scope_model="Fable")
    view = present(make_snapshot([weekly_all, weekly_fable]), Config())
    assert view.headline == "34% remaining"


def test_headline_no_limits_reported():
    view = present(make_snapshot([]), Config())
    assert view.headline == "No limits reported"


def test_remaining_is_100_minus_percent_clamped():
    view = present(make_snapshot([make_limit(percent=140)]), Config())
    assert view.bars[0].remaining == 0
    view = present(make_snapshot([make_limit(percent=-5)]), Config())
    assert view.bars[0].remaining == 100


def test_bars_sorted_by_percent_descending():
    low = make_limit(kind="session", percent=25)
    high = make_limit(kind="weekly_all", percent=75)
    view = present(make_snapshot([low, high]), Config())
    assert [bar.percent for bar in view.bars] == [75, 25]


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
        captured_at=NOW, quota=None, is_stale=True, unavailable=QuotaUnavailable.NO_QUOTA_KEY
    )
    view = present(snapshot, Config())
    assert view.message == "No quota data cached yet — run Claude Code once"


def test_read_error_no_history_message_carries_detail():
    snapshot = QuotaSnapshot(
        captured_at=NOW, quota=None, is_stale=True,
        unavailable=QuotaUnavailable.READ_ERROR, detail="OSError",
    )
    view = present(snapshot, Config())
    assert view.message == "Couldn't read quota data"
    assert view.message_detail == "OSError"


def test_read_error_with_history_has_no_message_but_shows_bars():
    view = present(
        make_snapshot(
            [make_limit(percent=50)], is_stale=True,
            unavailable=QuotaUnavailable.READ_ERROR, detail="OSError",
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
    view = present(
        make_snapshot([make_limit()], promos=["+50% weekly limits promo"]), config
    )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_presenter.py -v`
Expected: `ModuleNotFoundError: No module named 'claude_usage.ui.app'`

- [ ] **Step 3: Implement**

Create `claude_usage/ui/app/__init__.py` (empty).

Create `claude_usage/ui/app/presenter.py`:

```python
"""Pure QuotaSnapshot + Config -> QuotaView. panels.py places strings and
draws rectangles; it computes nothing — every display decision is made here.
"""
from __future__ import annotations

from dataclasses import dataclass

from claude_usage.application.ports import Config
from claude_usage.domain.quota import LimitReading, QuotaSnapshot, QuotaUnavailable, time_remaining
from claude_usage.ui.shared.format import coarse, label_for

_SEVERITY = {"normal": "normal", "warning": "warning"}

_NO_DATA_MESSAGES = {
    QuotaUnavailable.NO_FILE: "Claude Code data not found",
    QuotaUnavailable.NO_QUOTA_KEY: "No quota data cached yet — run Claude Code once",
}

_READ_ERROR_MESSAGE = "Couldn't read quota data"


@dataclass(frozen=True)
class BarView:
    label: str             # "Weekly Fable"
    percent: int
    remaining: int         # 100 - percent, the number shown (SPEC §7.2)
    severity: str           # "normal" | "warning" | "critical"
    active: bool
    resets_text: str | None  # "resets in 3h"


@dataclass(frozen=True)
class QuotaView:
    headline: str              # "34% remaining"
    age_text: str               # "as of 7m ago"
    stale: bool
    bars: tuple[BarView, ...]  # sorted by percent descending
    notices: tuple[str, ...]
    message: str | None        # set only when there are no bars to show
    message_detail: str | None


def present(snapshot: QuotaSnapshot, config: Config) -> QuotaView:
    notices = list(config.warnings)
    quota = snapshot.quota

    if quota is None:
        message = _NO_DATA_MESSAGES.get(snapshot.unavailable, _READ_ERROR_MESSAGE)
        message_detail = (
            snapshot.detail if snapshot.unavailable is QuotaUnavailable.READ_ERROR else None
        )
        return QuotaView(
            headline="No data",
            age_text="no reading yet",
            stale=True,
            bars=(),
            notices=tuple(notices),
            message=message,
            message_detail=message_detail,
        )

    if snapshot.unavailable is QuotaUnavailable.READ_ERROR and snapshot.detail:
        notices.append(snapshot.detail)
    notices.extend(quota.promo_notices)

    binding = quota.binding()
    headline = f"{_remaining(binding.percent)}% remaining" if binding else "No limits reported"

    bars = tuple(
        sorted(
            (_bar_view(limit, snapshot.captured_at) for limit in quota.limits),
            key=lambda bar: bar.percent,
            reverse=True,
        )
    )

    age_text = f"as of {coarse(quota.age(snapshot.captured_at))} ago"
    if snapshot.is_stale:
        age_text += " · STALE"

    return QuotaView(
        headline=headline,
        age_text=age_text,
        stale=snapshot.is_stale,
        bars=bars,
        notices=tuple(notices),
        message=None,
        message_detail=None,
    )


def present_error(exc: Exception) -> QuotaView:
    """Fallback view when the poller loop itself raises — it must never die
    silently, which would freeze the display on a stale reading."""
    return QuotaView(
        headline="No data",
        age_text="no reading yet",
        stale=True,
        bars=(),
        notices=(),
        message=_READ_ERROR_MESSAGE,
        message_detail=type(exc).__name__,
    )


def _remaining(percent: int) -> int:
    return max(0, min(100, 100 - percent))


def _bar_view(limit: LimitReading, now) -> BarView:
    resets_in = time_remaining(limit.resets_at, now)
    return BarView(
        label=label_for(limit),
        percent=limit.percent,
        remaining=_remaining(limit.percent),
        severity=_SEVERITY.get(limit.severity, "critical"),
        active=limit.is_active,
        resets_text=f"resets in {coarse(resets_in)}" if resets_in is not None else None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_presenter.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/ui/app/__init__.py claude_usage/ui/app/presenter.py tests/test_ui_presenter.py
git commit -m "Add pure QuotaSnapshot -> QuotaView presenter for the wx app"
```

---

### Task 8: Packaging — `pyproject.toml`, wxPython install/verify

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `wxPython` importable as `import wx` in this environment;
  `claude-usage-app` console-script entry point (function body created in
  Task 12).

- [ ] **Step 1: Update `pyproject.toml`**

```toml
[project]
name = "claude-usage"
version = "0.1.0"
description = "CLI and desktop-widget views of Claude Code subscription quota"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = ["wxPython"]

[project.scripts]
claude-usage = "claude_usage.ui.cli.main:main"
claude-usage-app = "claude_usage.ui.app.main:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["claude_usage*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

(`claude-usage-app` points at `claude_usage.ui.app.main:main`, created in
Task 12 — the entry point is declared now so packaging and the composition
root land together conceptually, but the module doesn't need to exist yet
for this step; `pip install -e .` re-resolves entry points on each install.)

- [ ] **Step 2: Install and verify wxPython imports**

Run: `pip install -e .`
Expected: wxPython installs successfully (this is a GUI toolkit with a
compiled wheel — on Windows this should be a plain binary wheel install, no
compiler required).

Run: `python -c "import wx; print(wx.version())"`
Expected: prints a wx version string with no import error. If this fails,
stop and resolve it before continuing to Task 9 — no GUI task can proceed
without a working wx import.

- [ ] **Step 3: Run the full test suite to confirm nothing regressed**

Run: `pytest -q`
Expected: all PASS (the `requires-python` bump doesn't change any runtime
behavior already covered by tests).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "Bump requires-python to 3.11, add wxPython dependency and app entry point"
```

---

### Task 9: GUI — `ui/app/panels.py`

**Files:**
- Create: `claude_usage/ui/app/panels.py`

**Interfaces:**
- Consumes: `BarView`, `QuotaView` from Task 7.
- Produces: `QuotaPanel(wx.Panel)` with `.render(view: QuotaView) -> None`,
  called by `frame.py` (Task 10) and `poller.py`'s `on_view` callback
  (Task 11).

**No automated test** — per spec §6, "no test instantiates `wx`... `panels.py`
... verified by running the app; everything that can be logically wrong
lives in the presenter, which is pure" (already covered by Task 7's tests).
This task is verified manually in Task 12, once `frame.py`, `poller.py`, and
`main.py` exist to actually run it.

- [ ] **Step 1: Implement**

Create `claude_usage/ui/app/panels.py`:

```python
"""Draws a QuotaView with wx.PaintDC rectangles (wx.Gauge can't be coloured
per-severity portably). Places strings and rectangles; computes nothing —
all display decisions were already made by presenter.present().
"""
from __future__ import annotations

import wx

from claude_usage.ui.app.presenter import BarView, QuotaView

_SEVERITY_COLORS = {
    "normal": wx.Colour(60, 179, 60),
    "warning": wx.Colour(224, 168, 0),
    "critical": wx.Colour(200, 50, 50),
}
_STALE_COLOR = wx.Colour(150, 150, 150)
_TRACK_COLOR = wx.Colour(230, 230, 230)
_BAR_HEIGHT = 18
_ROW_HEIGHT = 40
_MARGIN = 8


class QuotaPanel(wx.Panel):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self._view: QuotaView | None = None
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def render(self, view: QuotaView) -> None:
        self._view = view
        self.Refresh()

    def _on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.PaintDC(self)
        view = self._view
        if view is None:
            return
        dc.Clear()
        y = self._draw_header(dc, view)
        if view.message is not None:
            self._draw_message(dc, view, y)
            return
        for bar in view.bars:
            y = self._draw_bar(dc, bar, y, greyed=view.stale)
        self._draw_footer(dc, view, y)

    def _draw_header(self, dc: wx.DC, view: QuotaView) -> int:
        dc.SetTextForeground(wx.BLACK)
        dc.DrawText(view.headline, _MARGIN, _MARGIN)
        dc.DrawText(view.age_text, _MARGIN, _MARGIN + 18)
        return _MARGIN + 44

    def _draw_message(self, dc: wx.DC, view: QuotaView, y: int) -> None:
        dc.DrawText(view.message, _MARGIN, y)
        if view.message_detail:
            dc.DrawText(view.message_detail, _MARGIN, y + 18)

    def _draw_bar(self, dc: wx.DC, bar: BarView, y: int, *, greyed: bool) -> int:
        width = max(0, self.GetClientSize().width - 2 * _MARGIN)
        filled = int(width * max(0, min(100, bar.percent)) / 100)
        color = _STALE_COLOR if greyed else _SEVERITY_COLORS.get(
            bar.severity, _SEVERITY_COLORS["critical"]
        )
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(_TRACK_COLOR))
        dc.DrawRectangle(_MARGIN, y, width, _BAR_HEIGHT)
        dc.SetBrush(wx.Brush(color))
        dc.DrawRectangle(_MARGIN, y, filled, _BAR_HEIGHT)

        label = f"{bar.label}  {bar.remaining}%"
        if bar.active:
            label += "  ●"
        if bar.resets_text:
            label += f"  {bar.resets_text}"
        dc.SetTextForeground(wx.BLACK)
        dc.DrawText(label, _MARGIN, y + _BAR_HEIGHT + 2)
        return y + _ROW_HEIGHT

    def _draw_footer(self, dc: wx.DC, view: QuotaView, y: int) -> None:
        dc.SetTextForeground(wx.Colour(90, 90, 90))
        for notice in view.notices:
            dc.DrawText(notice, _MARGIN, y)
            y += 16
```

- [ ] **Step 2: Sanity-check the import**

Run: `python -c "from claude_usage.ui.app.panels import QuotaPanel; print(QuotaPanel)"`
Expected: prints the class, no import error. This does not instantiate any
wx object (no `wx.App()`), so it's safe to run headlessly.

- [ ] **Step 3: Commit**

```bash
git add claude_usage/ui/app/panels.py
git commit -m "Add QuotaPanel: draws a QuotaView with wx.PaintDC"
```

---

### Task 10: GUI — `ui/app/frame.py`

**Files:**
- Create: `claude_usage/ui/app/frame.py`

**Interfaces:**
- Consumes: `QuotaPanel` from Task 9; `QuotaView` from Task 7.
- Produces: `QuotaFrame(wx.Frame)` — constructor `QuotaFrame(on_close:
  Callable[[], None])`; method `.show_view(view: QuotaView) -> None`,
  called by `poller.py`'s `on_view` callback (Task 11) and once
  synchronously by `main.py` (Task 12) before `.Show()`.

**No automated test** — same rationale as Task 9. Verified manually in
Task 12.

- [ ] **Step 1: Implement**

Create `claude_usage/ui/app/frame.py`:

```python
"""wx.Frame composition root for the window: header, bar rows, footer via
QuotaPanel. STAY_ON_TOP, resizable, never steals focus on refresh (refresh
only repaints — it never calls Raise()/SetFocus()).
"""
from __future__ import annotations

from typing import Callable

import wx

from claude_usage.ui.app.panels import QuotaPanel
from claude_usage.ui.app.presenter import QuotaView


class QuotaFrame(wx.Frame):
    def __init__(self, on_close: Callable[[], None]) -> None:
        super().__init__(
            None,
            title="Claude Usage",
            size=(320, 180),
            style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP,
        )
        self._on_close = on_close
        self.panel = QuotaPanel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.panel, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, self._handle_close)

    def show_view(self, view: QuotaView) -> None:
        self.panel.render(view)

    def _handle_close(self, event: wx.CloseEvent) -> None:
        self._on_close()
        event.Skip()
```

- [ ] **Step 2: Sanity-check the import**

Run: `python -c "from claude_usage.ui.app.frame import QuotaFrame; print(QuotaFrame)"`
Expected: prints the class, no import error.

- [ ] **Step 3: Commit**

```bash
git add claude_usage/ui/app/frame.py
git commit -m "Add QuotaFrame: STAY_ON_TOP window hosting QuotaPanel"
```

---

### Task 11: GUI — `ui/app/poller.py`

**Files:**
- Create: `claude_usage/ui/app/poller.py`

**Interfaces:**
- Consumes: `UsageService` (Task 3), `Config` (Task 4), `present`/
  `present_error` (Task 7).
- Produces: `PollerThread(service: UsageService, config: Config,
  on_view: Callable[[QuotaView], None])`, subclass of
  `threading.Thread(daemon=True)`. Methods: `.refresh_once() -> QuotaView`
  (synchronous, no thread involved — used by `main.py` for the pre-`Show()`
  refresh), `.run()` (the poll loop), `.stop()` (sets the stop event; the
  frame's close handler calls this and then joins with a timeout).

**No automated test** — per spec §6, `poller.py` is verified by running the
app. Its only non-trivial logic (snapshot → present, with an exception
fallback) is exercised through `present`/`present_error`, already tested in
Task 7.

- [ ] **Step 1: Implement**

Create `claude_usage/ui/app/poller.py`:

```python
"""Background poller. All file I/O and presenter logic run off the GUI
thread; only the frozen QuotaView crosses, via wx.CallAfter.
"""
from __future__ import annotations

import threading
from typing import Callable

import wx

from claude_usage.application.ports import Config
from claude_usage.application.usage import UsageService
from claude_usage.ui.app.presenter import QuotaView, present, present_error


class PollerThread(threading.Thread):
    def __init__(
        self,
        service: UsageService,
        config: Config,
        on_view: Callable[[QuotaView], None],
    ) -> None:
        super().__init__(daemon=True)
        self._service = service
        self._config = config
        self._on_view = on_view
        self._stop_event = threading.Event()

    def refresh_once(self) -> QuotaView:
        try:
            snapshot = self._service.snapshot()
            return present(snapshot, self._config)
        except Exception as exc:
            # A poller that dies silently would freeze the display on a
            # stale reading — precisely the failure this app prevents.
            return present_error(exc)

    def run(self) -> None:
        while not self._stop_event.is_set():
            view = self.refresh_once()
            wx.CallAfter(self._on_view, view)
            self._stop_event.wait(self._config.poll_seconds)

    def stop(self) -> None:
        self._stop_event.set()
```

- [ ] **Step 2: Sanity-check the import**

Run: `python -c "from claude_usage.ui.app.poller import PollerThread; print(PollerThread)"`
Expected: prints the class, no import error. Constructing a `PollerThread`
does not create any wx object — only `.run()` (never called directly here)
touches `wx.CallAfter`.

- [ ] **Step 3: Commit**

```bash
git add claude_usage/ui/app/poller.py
git commit -m "Add PollerThread: background refresh crossing to the GUI via wx.CallAfter"
```

---

### Task 12: GUI — `ui/app/main.py` composition root, full manual verification

**Files:**
- Create: `claude_usage/ui/app/main.py`

**Interfaces:**
- Consumes: `UsageService` (Task 3), `ClaudeJsonQuotaSource` (Task 2),
  `SystemClock` (unchanged), `TomlConfigSource` (Task 4), `QuotaFrame`
  (Task 10), `PollerThread` (Task 11).
- Produces: `main(argv: list[str] | None = None) -> int`, the
  `claude-usage-app` entry point declared in Task 8's `pyproject.toml`.

**No automated test** — this is the composition root; it's exercised
entirely by the manual checklist below, which is where Tasks 9–12 (panels,
frame, poller, main) all get verified together as a running app.

- [ ] **Step 1: Implement**

Create `claude_usage/ui/app/main.py`:

```python
"""Composition root for the wx quota app."""
from __future__ import annotations

import wx

from claude_usage.application.usage import UsageService
from claude_usage.infrastructure.claude_json import ClaudeJsonQuotaSource
from claude_usage.infrastructure.clock import SystemClock
from claude_usage.infrastructure.config import TomlConfigSource
from claude_usage.ui.app.frame import QuotaFrame
from claude_usage.ui.app.poller import PollerThread


def main(argv: list[str] | None = None) -> int:
    config = TomlConfigSource().read_config()
    service = UsageService(
        ClaudeJsonQuotaSource(), SystemClock(), stale_after=config.stale_after
    )

    app = wx.App()
    # `on_close` closes over `poller`, assigned on the next line — safe
    # because the callback only runs after the user closes the window, by
    # which point `poller` is bound.
    frame = QuotaFrame(on_close=lambda: poller.stop())
    poller = PollerThread(service, config, on_view=frame.show_view)

    frame.show_view(poller.refresh_once())  # one synchronous pass first —
    poller.start()                           # the window never flashes empty
    frame.Show()
    app.MainLoop()

    poller.stop()
    poller.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Manual verification checklist**

Run: `python -m claude_usage.ui.app.main` (or, after `pip install -e .`,
`claude-usage-app`), against a real or fixture-backed `~/.claude.json`
(temporarily point `ClaudeJsonQuotaSource()`'s default path — or copy
`tests/fixtures/live_snapshot.json` to `~/.claude.json` in a scratch
account/VM — whichever is safe on this machine; do not overwrite a real
`~/.claude.json` without backing it up first).

Confirm each of the following on this Windows machine:

1. **Startup:** the window appears immediately with real data already
   drawn — no visible empty flash before the first paint.
2. **Stay-on-top:** click another window; the quota window stays above it
   without being clicked.
3. **No focus stealing:** while another app has focus, wait for a poll
   tick (or lower `poll_seconds` in a temp config file to `2` for this
   test); confirm the quota window repaints but focus does not jump to it.
4. **NO_FILE:** rename `~/.claude.json` away; within one poll interval,
   confirm the body shows "Claude Code data not found" and the header
   still shows a headline/age line.
5. **NO_QUOTA_KEY:** restore a `~/.claude.json` that has no
   `cachedUsageUtilization` key at all; confirm "No quota data cached yet —
   run Claude Code once".
6. **READ_ERROR, no history:** replace the file with `{not json`; confirm
   "Couldn't read quota data" plus a detail line (e.g. `JSONDecodeError`).
7. **READ_ERROR, with history:** restore valid data, wait for one good
   poll, then replace the file with invalid JSON again; confirm the bars
   from the last good reading are still shown, greyed, with "· STALE" in
   the age line and the error detail present in the footer notices — not
   replaced by the no-data message.
8. **Recovery:** restore valid JSON; confirm the next poll returns to
   normal (ungreyed) bars.
9. **Resize:** drag the window edge; confirm bars redraw at the new width
   without artifacts.
10. **Severity color:** if reachable, confirm a `warning`/other severity
    limit renders in a different color than `normal`; otherwise confirm the
    color mapping visually matches `_SEVERITY_COLORS` by inspection.
11. **Config:** write `~/.config/claude-usage/config.toml` with
    `poll_seconds = 3`; confirm the window visibly refreshes roughly every
    3 seconds. Then set `poll_seconds = "bad"`; confirm the app still runs
    (falls back to the default) and a warning notice appears in the footer.
12. **Shutdown:** close the window; confirm the process exits promptly
    (within ~1 second), not after waiting out a full poll interval.

Note the outcome of each item (pass/fail + any fix made) before moving on.
If any item fails, fix the relevant Task 9–12 file and re-run the checklist
from that item onward.

- [ ] **Step 3: Commit**

```bash
git add claude_usage/ui/app/main.py
git commit -m "Add wx app composition root (claude-usage-app entry point)"
```

---

### Task 13: Architecture tests — extend `test_architecture.py`

**Files:**
- Modify: `tests/test_architecture.py`

**Interfaces:**
- Consumes: nothing new — reads the `claude_usage/` tree directly.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_architecture.py` (after the existing two test
functions):

```python
def test_wx_import_confined_to_app_driver():
    excluded = PKG / "ui" / "app"
    for path in PKG.rglob("*.py"):
        if excluded in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        assert "import wx" not in text, f"{path} references wx outside ui/app"


def test_cli_and_app_drivers_do_not_import_each_other():
    for path in (PKG / "ui" / "cli").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "claude_usage.ui.app" not in text, f"{path} references ui.app"
    for path in (PKG / "ui" / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "claude_usage.ui.cli" not in text, f"{path} references ui.cli"
```

These should already pass against the code written in Tasks 1–12 — this
task locks the invariant in so a future change can't silently violate it.

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_architecture.py -v`
Expected: all PASS (including the two new functions) — if either fails, an
earlier task introduced a layering violation; fix that task's file, not
this test.

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: all PASS, full suite.

- [ ] **Step 4: Commit**

```bash
git add tests/test_architecture.py
git commit -m "Lock wx-confinement and driver-independence into architecture tests"
```

---

### Task 14: Docs — `SPEC.md` status note, `README.md` both entry points

**Files:**
- Modify: `SPEC.md`
- Modify: `README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `SPEC.md`**

Add a new section right after the header block (after the existing "Two
maintained surfaces" note, before "## 1. Goals"):

```markdown
> **Status, 2026-08-12:** v1 of the wx app
> ([`claude_usage/ui/app/2026-08-10-quota-app-design.md`](claude_usage/ui/app/2026-08-10-quota-app-design.md))
> has shipped, quota-only — the token/cost panel below (§7.4) is deferred to
> v2 for both drivers. §10's open questions are resolved: §10.1 remaining
> quota % is the headline (tokens/cost are v2); §10.2 is not applicable in
> v1 (quota is account-wide); §10.3 dollar cost is deferred with the rest of
> the token panel; §10.4 no severity alerts — the always-on-top window is
> the notification. The CLI remains a permanently maintained sibling driver,
> not a stepping-stone.
```

- [ ] **Step 2: Update `README.md`**

Replace the file's opening and add an app section. New content (full file):

```markdown
# claude-usage

Two views of Claude Code subscription quota, from the local
`~/.claude.json` cache: a one-shot CLI and an always-on-top desktop window.

## Install

```bash
pip install -e .
```

This puts `claude-usage` (CLI) and `claude-usage-app` (window) on your
`PATH`.

## CLI

```bash
python -m claude_usage.ui.cli.main
```

```console
> python -m claude_usage.ui.cli.main
USAGE                                as of 18m ago · STALE

  Session (5hr)                   3%  ░░░░░░░░░░░░░░░  resets in 3h
  Weekly (7 day)      ● active    9%  █░░░░░░░░░░░░░░  resets in 6h

  +50% weekly limits promo through Aug 19 · clau.de/cc-50-promo
```

### Flags

| Flag         | Effect                                                     |
|--------------|------------------------------------------------------------|
| `--json`     | emit the snapshot as JSON instead of the bar view          |
| `--no-color` | suppress ANSI colour                                       |
| `--ascii`    | ASCII bar glyphs (`#`/`-`) instead of unicode block glyphs |
| `--path`     | read an alternate `.claude.json` (fixtures, testing)       |

### Windows: UnicodeEncodeError

The default view prints Unicode glyphs (`█ ░ ● ○ ·`). If your console's
active codepage can't encode them (commonly cp1252), you'll see
`UnicodeEncodeError: 'charmap' codec can't encode character ...`. Force
UTF-8 for the run:

```bash
python -X utf8 -m claude_usage.ui.cli.main
```

or set it for the session in PowerShell:

```powershell
$env:PYTHONUTF8 = "1"
```

`--json` is unaffected by this either way.

## Desktop window

```bash
python -m claude_usage.ui.app.main
```

An always-on-top window showing the same quota bars, refreshed in the
background (default every 10s). Read-only — it never writes to
`~/.claude.json`.

### Config

Optional, at `~/.config/claude-usage/config.toml` (both platforms):

```toml
poll_seconds = 10         # default 10, clamped to 1..600
stale_after_minutes = 15  # default 15, clamped to 1..1440
```

Absent or malformed config falls back to defaults; a malformed or
out-of-range value shows a warning in the window's footer rather than
failing silently.

## Development

```bash
pip install -e .
pip install pytest
pytest
```
```

- [ ] **Step 3: Commit**

```bash
git add SPEC.md README.md
git commit -m "Document the wx app's status, entry point, and config in SPEC.md and README.md"
```

---

## Self-Review Notes (from planning)

- **Spec coverage:** every section of `2026-08-10-quota-app-design.md` maps
  to a task — §1/§1.1 (scope, decisions) is realized structurally across
  Tasks 1–12; §2 (architecture/domain/application/infra changes) → Tasks
  1–4; §3 (config) → Task 4; §4/§4.1 (presenter, four states) → Task 7; §5
  (frame, poller) → Tasks 9–12; §6 (testing) → the test steps embedded in
  each task plus Task 13; §7 (CLI parity, shared formatting, packaging,
  docs) → Tasks 5, 6, 8, 14; §8 (privacy) → enforced by never adding
  `accountUuid` to any parsed/serialized field (unchanged from the existing
  code) and by `detail` always being `type(exc).__name__`, never a path or
  payload (Tasks 2, 3, 7).
- **Deviation recorded (per spec §7.1's own mechanism):** the CLI does not
  read `config.toml`. `poll_seconds` has no meaning for a one-shot process,
  and `stale_after` configurability wasn't judged essential parity for a
  tool that prints one snapshot and exits — the CLI keeps the domain's
  `STALE_AFTER` default. If this changes, add a CLI config-reading task
  before shipping it.
- **Design decision not fully specified by the design doc:** the `detail`
  string's plumbing from infrastructure to `QuotaSnapshot` (Task 2) — the
  spec's `QuotaSource.read_quota()` signature has no slot for it. Resolved
  during planning by adding `read_error_detail()` to the port.
- **Placeholder scan:** no task step describes an action without showing
  the code; no "TBD"/"add error handling" language remains.
- **Type consistency check:** `QuotaSource.read_quota()` returns
  `QuotaReading | QuotaUnavailable` consistently from Task 2 onward;
  `UsageService(quota_source, clock, stale_after=STALE_AFTER)` matches its
  Task 3 definition everywhere it's called (Task 6's CLI, Task 12's app);
  `present(snapshot, config)` / `present_error(exc)` signatures from Task 7
  match their Task 11 (`poller.py`) call sites; `QuotaFrame(on_close)` /
  `.show_view(view)` from Task 10 match Task 12's usage.
