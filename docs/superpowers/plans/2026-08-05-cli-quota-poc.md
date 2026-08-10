# CLI Quota POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-shot CLI (`python3 -m claude_usage.ui.cli.main`) that prints Claude Code's three usage bars — session, weekly, model-scoped weekly — with percentages, reset countdowns, and an unconditional cache-age line, read from `~/.claude.json`.

**Architecture:** Onion architecture per `CLAUDE.md`: pure domain entities (`claude_usage/domain/`), a use-case service depending only on ports it declares (`claude_usage/application/`), file-reading adapters (`claude_usage/infrastructure/`), and a pure-function renderer plus argparse composition root (`claude_usage/ui/cli/`). One synchronous pass, no threads, no network. Spec: `claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md`.

**Tech Stack:** Python ≥ 3.10, standard library only at runtime. `pytest` (MIT) as the sole test dependency.

## Global Constraints

- Runtime dependencies: **standard library only**. Test dependency: `pytest` (MIT). No other packages — the project is MIT-only (wxPython exception does not apply here; this POC must not import `wx`).
- Inward-only imports: `domain` imports nothing from other layers and no I/O modules (`json`, `pathlib`, `argparse`, `os`, `sys`); `application` never imports `infrastructure` or `ui`; `infrastructure` never imports `ui`. Ports live in `application/ports.py`.
- Read-only tool: never write to `~/.claude/` or `~/.claude.json`.
- `accountUuid` is never read into any field, rendered, logged, or serialised.
- Read `cachedUsageUtilization.utilization.limits[]`, never the named siblings (`five_hour`, `seven_day`, codename keys).
- Cache age is rendered on every invocation, unconditionally. `STALE_AFTER = timedelta(minutes=15)`.
- Colour comes from the `severity` field only, never from local percentage thresholds.
- Row order is `limits[]` source order (deliberate deviation from `SPEC.md` §7.2 — see POC spec §12).
- Strict TDD: failing test first, run it, implement, run again. Run the full suite at the end of every task.
- **Git: leave all changes unstaged. Do NOT create branches or commits — the user manages git and must approve any commit message first.** (Overrides the usual per-task commit steps.)
- Nothing under `docs/superpowers/` is ever committed to git (user convention).
- Exit codes: 0 for any rendered output (including stale and empty-limits); 1 only when no usable cache exists, with the error on **stderr**.

## File Structure

```text
pyproject.toml                              project metadata + pytest config (Task 1)
claude_usage/
  __init__.py                               (Task 1)
  domain/
    __init__.py                             (Task 1)
    quota.py                                LimitReading, QuotaReading, QuotaSnapshot,
                                            STALE_AFTER, time_remaining (Task 1)
  application/
    __init__.py                             (Task 2)
    ports.py                                QuotaSource, Clock protocols (Task 2)
    usage.py                                UsageService (Task 2)
  infrastructure/
    __init__.py                             (Task 3)
    clock.py                                SystemClock (Task 3)
    claude_json.py                          ClaudeJsonQuotaSource (Task 3)
  ui/
    __init__.py                             (Task 4)
    cli/
      __init__.py                           (Task 4)
      render.py                             pure QuotaSnapshot -> str (Task 4)
      main.py                               argparse + composition root (Task 5)
tests/
  test_domain_quota.py                      (Task 1)
  test_application_usage.py                 (Task 2)
  test_infrastructure_claude_json.py        (Task 3)
  test_ui_cli_render.py                     (Task 4, golden added in Task 6)
  test_ui_cli_main.py                       (Task 5)
  test_architecture.py                      (Task 6)
  fixtures/
    live_snapshot.json                      redacted capture shape (Task 3)
```

---

### Task 1: Scaffolding + domain entities (`domain/quota.py`)

**Files:**
- Create: `pyproject.toml`
- Create: `claude_usage/__init__.py`, `claude_usage/domain/__init__.py` (both empty)
- Create: `claude_usage/domain/quota.py`
- Test: `tests/test_domain_quota.py`

**Interfaces:**
- Consumes: nothing (innermost ring).
- Produces (all later tasks import these from `claude_usage.domain.quota`):
  - `STALE_AFTER: timedelta` (15 minutes)
  - `LimitReading` frozen dataclass: `kind: str`, `group: str`, `percent: int`, `severity: str`, `is_active: bool`, `resets_at: datetime | None`, `scope_model: str | None`
  - `QuotaReading` frozen dataclass: `measured_at: datetime`, `limits: tuple[LimitReading, ...]`, `promo_notices: tuple[str, ...]`; methods `age(now) -> timedelta`, `is_stale(now, threshold=STALE_AFTER) -> bool`, `binding() -> LimitReading | None`
  - `QuotaSnapshot` frozen dataclass: `captured_at: datetime`, `quota: QuotaReading | None`, `is_stale: bool`
  - `time_remaining(resets_at: datetime | None, now: datetime) -> timedelta | None`

- [ ] **Step 1: Verify pytest is available**

Run: `python3 -m pytest --version`
If missing: `python3 -m pip install pytest` (MIT; test-only dependency, allowed).

- [ ] **Step 2: Create scaffolding**

Create `pyproject.toml`:

```toml
[project]
name = "claude-usage"
version = "0.1.0"
description = "One-shot CLI showing Claude Code quota usage from the local cache"
requires-python = ">=3.10"
license = { text = "MIT" }

[project.scripts]
claude-usage = "claude_usage.ui.cli.main:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["claude_usage*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

Create empty files: `claude_usage/__init__.py`, `claude_usage/domain/__init__.py`.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_domain_quota.py`:

```python
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from claude_usage.domain.quota import (
    STALE_AFTER,
    LimitReading,
    QuotaReading,
    QuotaSnapshot,
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_domain_quota.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_usage.domain.quota'`

- [ ] **Step 5: Write the implementation**

Create `claude_usage/domain/quota.py`:

```python
"""Quota domain entities. Standard library only — no I/O, no wx, no ANSI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

STALE_AFTER = timedelta(minutes=15)


@dataclass(frozen=True)
class LimitReading:
    """One entry from cachedUsageUtilization.utilization.limits[]."""

    kind: str
    group: str
    percent: int
    severity: str
    is_active: bool
    resets_at: datetime | None
    scope_model: str | None


@dataclass(frozen=True)
class QuotaReading:
    measured_at: datetime
    limits: tuple[LimitReading, ...]
    promo_notices: tuple[str, ...]

    def age(self, now: datetime) -> timedelta:
        return now - self.measured_at

    def is_stale(self, now: datetime, threshold: timedelta = STALE_AFTER) -> bool:
        return self.age(now) >= threshold

    def binding(self) -> LimitReading | None:
        """The worst bar — the constraint that would actually stop work."""
        if not self.limits:
            return None
        return max(self.limits, key=lambda limit: limit.percent)


@dataclass(frozen=True)
class QuotaSnapshot:
    captured_at: datetime
    quota: QuotaReading | None
    is_stale: bool


def time_remaining(resets_at: datetime | None, now: datetime) -> timedelta | None:
    if resets_at is None:
        return None
    return max(resets_at - now, timedelta(0))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_domain_quota.py -v`
Expected: 10 passed

---

### Task 2: Application ring — ports + `UsageService`

**Files:**
- Create: `claude_usage/application/__init__.py` (empty)
- Create: `claude_usage/application/ports.py`
- Create: `claude_usage/application/usage.py`
- Test: `tests/test_application_usage.py`

**Interfaces:**
- Consumes: `QuotaReading`, `QuotaSnapshot` from `claude_usage.domain.quota` (Task 1).
- Produces:
  - `QuotaSource` protocol with `read_quota(self) -> QuotaReading | None`
  - `Clock` protocol with `now(self) -> datetime`
  - `UsageService(quota_source: QuotaSource, clock: Clock)` with `snapshot(self) -> QuotaSnapshot`. Rule: `is_stale` is `True` when `quota is None` — absent data must never render as fresh.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_application_usage.py`:

```python
from datetime import datetime, timedelta, timezone

from claude_usage.application.usage import UsageService
from claude_usage.domain.quota import QuotaReading

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 18, 10, tzinfo=UTC)


class FakeQuotaSource:
    def __init__(self, reading):
        self._reading = reading

    def read_quota(self):
        return self._reading


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


def test_snapshot_stale_reading():
    reading = make_reading(NOW - timedelta(hours=3))
    service = UsageService(FakeQuotaSource(reading), FrozenClock(NOW))
    assert service.snapshot().is_stale is True


def test_snapshot_missing_quota_is_stale():
    service = UsageService(FakeQuotaSource(None), FrozenClock(NOW))
    snapshot = service.snapshot()
    assert snapshot.quota is None
    assert snapshot.is_stale is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_application_usage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_usage.application'`

- [ ] **Step 3: Write the implementation**

Create empty `claude_usage/application/__init__.py`.

Create `claude_usage/application/ports.py`:

```python
"""Ports the application ring declares; infrastructure conforms structurally."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from claude_usage.domain.quota import QuotaReading


class QuotaSource(Protocol):
    def read_quota(self) -> QuotaReading | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
```

Create `claude_usage/application/usage.py`:

```python
from __future__ import annotations

from claude_usage.application.ports import Clock, QuotaSource
from claude_usage.domain.quota import QuotaSnapshot


class UsageService:
    def __init__(self, quota_source: QuotaSource, clock: Clock) -> None:
        self._quota_source = quota_source
        self._clock = clock

    def snapshot(self) -> QuotaSnapshot:
        now = self._clock.now()
        quota = self._quota_source.read_quota()
        # Absent data must never render as fresh.
        is_stale = True if quota is None else quota.is_stale(now)
        return QuotaSnapshot(captured_at=now, quota=quota, is_stale=is_stale)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_application_usage.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 13 passed

---

### Task 3: Infrastructure — `SystemClock`, `ClaudeJsonQuotaSource`, fixture

**Files:**
- Create: `claude_usage/infrastructure/__init__.py` (empty)
- Create: `claude_usage/infrastructure/clock.py`
- Create: `claude_usage/infrastructure/claude_json.py`
- Create: `tests/fixtures/live_snapshot.json`
- Test: `tests/test_infrastructure_claude_json.py`

**Interfaces:**
- Consumes: `LimitReading`, `QuotaReading` from `claude_usage.domain.quota` (Task 1).
- Produces:
  - `SystemClock` with `now(self) -> datetime` (timezone-aware UTC)
  - `ClaudeJsonQuotaSource(path: Path | None = None)` — defaults to `Path.home() / ".claude.json"` (the **sibling** of `~/.claude/`, not inside it) — with `read_quota(self) -> QuotaReading | None`. Returns `None` — never raises — on absent/unreadable file, invalid JSON, missing `cachedUsageUtilization`, or missing `fetchedAtMs`.
  - Fixture `tests/fixtures/live_snapshot.json` used again by Tasks 5 and 6. Its `fetchedAtMs` is `1785953100000` = 2026-08-05T18:05:00Z; percents 25/50/75.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/live_snapshot.json` — the real `~/.claude.json` schema with anonymized placeholder values (schema verified in the POC spec, Appendix A). The `REDACTED-…` uuid stays in the fixture so later privacy tests can assert it never leaks. Named siblings and `null_placeholder_*` keys (standing in for internal feature-flag keys, names redacted) are present deliberately: the parser must ignore them.

```json
{
  "oauthAccount": {
    "userRateLimitTier": "example_rate_limit_tier",
    "seatTier": "example_seat_tier"
  },
  "cachedUsageUtilization": {
    "fetchedAtMs": 1785953100000,
    "accountUuid": "REDACTED-0000-0000-0000-000000000000",
    "utilization": {
      "five_hour": {
        "utilization": 25,
        "resets_at": "2026-08-06T00:00:00Z",
        "limit_dollars": null,
        "used_dollars": null,
        "remaining_dollars": null
      },
      "seven_day": {
        "utilization": 50,
        "resets_at": "2026-08-07T00:00:00Z",
        "limit_dollars": null,
        "used_dollars": null,
        "remaining_dollars": null
      },
      "null_placeholder_a": null,
      "null_placeholder_b": null,
      "null_placeholder_c": null,
      "null_placeholder_d": null,
      "null_placeholder_e": null,
      "limits": [
        {
          "kind": "session",
          "group": "session",
          "percent": 25,
          "severity": "normal",
          "resets_at": "2026-08-06T00:00:00Z",
          "scope": null,
          "is_active": false
        },
        {
          "kind": "weekly_all",
          "group": "weekly",
          "percent": 50,
          "severity": "normal",
          "resets_at": "2026-08-07T00:00:00Z",
          "scope": null,
          "is_active": false
        },
        {
          "kind": "weekly_scoped",
          "group": "weekly",
          "percent": 75,
          "severity": "normal",
          "resets_at": "2026-08-07T00:00:00Z",
          "is_active": true,
          "scope": {
            "model": { "id": null, "display_name": "Fable" },
            "surface": null
          }
        }
      ],
      "extra_usage": { "is_enabled": false },
      "spend": {
        "used": { "amount_minor": 0, "currency": "USD", "exponent": 2 },
        "limit": null,
        "percent": 0,
        "enabled": false
      }
    }
  },
  "cachedGrowthBookFeatures": {
    "tengu_rate_limit_promo_notices": [
      { "text": "+50% weekly limits promo through Aug 19 · clau.de/cc-50-promo" }
    ]
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_infrastructure_claude_json.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

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


def test_absent_file_returns_none(tmp_path):
    source = ClaudeJsonQuotaSource(tmp_path / "missing.json")
    assert source.read_quota() is None


def test_unreadable_file_returns_none(tmp_path):
    # A directory raises OSError on read_text — the "unreadable" case.
    assert ClaudeJsonQuotaSource(tmp_path).read_quota() is None


def test_invalid_json_returns_none(tmp_path):
    path = tmp_path / "claude.json"
    path.write_text("{not json", encoding="utf-8")
    assert ClaudeJsonQuotaSource(path).read_quota() is None


def test_missing_cached_usage_utilization_returns_none(tmp_path):
    path = write_json(tmp_path, {"oauthAccount": {}})
    assert ClaudeJsonQuotaSource(path).read_quota() is None


def test_missing_fetched_at_ms_returns_none(tmp_path):
    path = write_json(tmp_path, {"cachedUsageUtilization": {"utilization": {}}})
    assert ClaudeJsonQuotaSource(path).read_quota() is None


def test_fixture_parses_measured_at_and_limits():
    reading = ClaudeJsonQuotaSource(FIXTURE).read_quota()
    assert reading is not None
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
    assert reading is not None
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_infrastructure_claude_json.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_usage.infrastructure'`

- [ ] **Step 4: Write the implementation**

Create empty `claude_usage/infrastructure/__init__.py`.

Create `claude_usage/infrastructure/clock.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
```

Create `claude_usage/infrastructure/claude_json.py`:

```python
"""Adapter over ~/.claude.json. Read-only; never touches accountUuid."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from claude_usage.domain.quota import LimitReading, QuotaReading


class ClaudeJsonQuotaSource:
    def __init__(self, path: Path | None = None) -> None:
        # ~/.claude.json is the sibling of ~/.claude/, not a file inside it.
        self._path = path if path is not None else Path.home() / ".claude.json"

    def read_quota(self) -> QuotaReading | None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        cached = raw.get("cachedUsageUtilization")
        if not isinstance(cached, dict):
            return None
        fetched_at_ms = cached.get("fetchedAtMs")
        if isinstance(fetched_at_ms, bool) or not isinstance(fetched_at_ms, (int, float)):
            return None
        measured_at = datetime.fromtimestamp(fetched_at_ms / 1000, tz=timezone.utc)
        return QuotaReading(
            measured_at=measured_at,
            limits=_parse_limits(cached),
            promo_notices=_parse_promos(raw),
        )


def _parse_limits(cached: dict) -> tuple[LimitReading, ...]:
    utilization = cached.get("utilization")
    if not isinstance(utilization, dict):
        return ()
    entries = utilization.get("limits")
    if not isinstance(entries, list):
        return ()
    readings = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        percent = entry.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, int):
            continue
        readings.append(
            LimitReading(
                kind=str(entry.get("kind") or "unknown"),
                group=str(entry.get("group") or ""),
                percent=percent,
                severity=str(entry.get("severity") or "normal"),
                is_active=bool(entry.get("is_active", False)),
                resets_at=_parse_resets_at(entry.get("resets_at")),
                scope_model=_parse_scope_model(entry.get("scope")),
            )
        )
    return tuple(readings)


def _parse_resets_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_scope_model(scope: object) -> str | None:
    if not isinstance(scope, dict):
        return None
    model = scope.get("model")
    if not isinstance(model, dict):
        return None
    name = model.get("display_name")
    return name if isinstance(name, str) else None


def _parse_promos(raw: dict) -> tuple[str, ...]:
    features = raw.get("cachedGrowthBookFeatures")
    if not isinstance(features, dict):
        return ()
    notices = features.get("tengu_rate_limit_promo_notices")
    if not isinstance(notices, list):
        return ()
    return tuple(
        entry["text"]
        for entry in notices
        if isinstance(entry, dict) and isinstance(entry.get("text"), str)
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_infrastructure_claude_json.py -v`
Expected: 14 passed

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 27 passed

---

### Task 4: Renderer — `ui/cli/render.py`

**Files:**
- Create: `claude_usage/ui/__init__.py`, `claude_usage/ui/cli/__init__.py` (both empty)
- Create: `claude_usage/ui/cli/render.py`
- Test: `tests/test_ui_cli_render.py`

**Interfaces:**
- Consumes: `LimitReading`, `QuotaSnapshot`, `time_remaining` from `claude_usage.domain.quota` (Task 1).
- Produces (Task 5's `main` calls `render`; Task 6's golden test calls it too):
  - `render(snapshot: QuotaSnapshot, *, color: bool = False, ascii_glyphs: bool = False) -> str` — raises `ValueError` if `snapshot.quota is None` (the caller must handle that case before rendering)
  - Helpers, unit-tested individually: `label_for(limit) -> str`, `bar(percent, ascii_glyphs=False) -> str`, `coarse(delta) -> str`, `render_row(limit, now, *, color=False, ascii_glyphs=False) -> str`
  - Row format (fixed columns): `"  " + label.ljust(20) + marker.ljust(10) + f"{percent}%".rjust(4) + "  " + bar + ["  resets in " + countdown]`, right-trimmed of trailing spaces. Marker is `"● active"` (`"○ active"` under ascii) or empty. Bar is 15 cells, `█`/`░` (`#`/`-` under ascii), filled = `(clamp(percent, 0, 100) * 15 + 50) // 100` (integer round-half-up).
  - Header: `"USAGE" + 32 spaces + "as of {coarse(age)} ago · fresh|STALE"`, then a blank line, then rows in **source order**, then (if promos) a blank line and one 2-space-indented line per promo notice.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui_cli_render.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from claude_usage.domain.quota import LimitReading, QuotaReading, QuotaSnapshot
from claude_usage.ui.cli.render import bar, coarse, label_for, render, render_row

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


def make_snapshot(limits, promos=(), measured_at=NOW - timedelta(minutes=5),
                  is_stale=False):
    reading = QuotaReading(
        measured_at=measured_at,
        limits=tuple(limits),
        promo_notices=tuple(promos),
    )
    return QuotaSnapshot(captured_at=NOW, quota=reading, is_stale=is_stale)


# --- labels ---------------------------------------------------------------

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


# --- bar ------------------------------------------------------------------

def test_bar_fill_rounding():
    assert bar(25) == "████" + "░" * 11
    assert bar(50) == "████████" + "░" * 7
    assert bar(75) == "███████████" + "░" * 4
    assert bar(0) == "░" * 15
    assert bar(100) == "█" * 15


def test_bar_clamps_out_of_range():
    assert bar(140) == "█" * 15
    assert bar(-5) == "░" * 15


def test_bar_ascii_glyphs():
    assert bar(50, ascii_glyphs=True) == "########" + "-" * 7


# --- coarse durations -----------------------------------------------------

def test_coarse_units():
    assert coarse(timedelta(seconds=30)) == "<1m"
    assert coarse(timedelta(minutes=12)) == "12m"
    assert coarse(timedelta(hours=2)) == "2h"
    assert coarse(timedelta(days=1, hours=18)) == "1d"


# --- rows -----------------------------------------------------------------

def test_row_without_resets_at_omits_countdown():
    row = render_row(make_limit(resets_at=None), NOW)
    assert "resets in" not in row
    assert "25%" in row


def test_row_with_countdown():
    limit = make_limit(resets_at=NOW + timedelta(hours=5))
    assert render_row(limit, NOW).endswith("resets in 5h")


def test_row_active_marker():
    row = render_row(make_limit(is_active=True), NOW)
    assert "● active" in row
    ascii_row = render_row(make_limit(is_active=True), NOW, ascii_glyphs=True)
    assert "○ active" in ascii_row


def test_row_overrange_percent_prints_raw_number_and_clamps_bar():
    row = render_row(make_limit(percent=140), NOW)
    assert "140%" in row
    assert "█" * 15 in row


def test_row_severity_selects_color():
    normal = render_row(make_limit(severity="normal"), NOW, color=True)
    warning = render_row(make_limit(severity="warning"), NOW, color=True)
    exceeded = render_row(make_limit(severity="exceeded"), NOW, color=True)
    assert "\x1b[32m" in normal
    assert "\x1b[33m" in warning
    assert "\x1b[31m" in exceeded


def test_row_no_ansi_when_color_off():
    assert "\x1b[" not in render_row(make_limit(severity="warning"), NOW)


# --- full render ----------------------------------------------------------

def test_render_preserves_source_order_not_percent_order():
    snapshot = make_snapshot(
        [
            make_limit(kind="weekly_all", percent=50),
            make_limit(kind="weekly_scoped", percent=75, scope_model="Fable"),
            make_limit(kind="session", percent=25),
        ]
    )
    lines = render(snapshot).splitlines()
    rows = [line for line in lines if "%" in line]
    assert "Weekly (7 day)" in rows[0]
    assert "Weekly Fable" in rows[1]
    assert "Session (5hr)" in rows[2]


def test_render_age_line_fresh():
    output = render(make_snapshot([make_limit()]))
    assert output.splitlines()[0] == "USAGE" + " " * 32 + "as of 5m ago · fresh"


def test_render_age_line_stale():
    snapshot = make_snapshot(
        [make_limit()], measured_at=NOW - timedelta(hours=3), is_stale=True
    )
    assert "as of 3h ago · STALE" in render(snapshot).splitlines()[0]


def test_render_empty_limits():
    output = render(make_snapshot([]))
    assert "no limits reported" in output
    assert "as of 5m ago" in output


def test_render_promo_footnote():
    promo = "+50% weekly limits promo through Aug 19 · clau.de/cc-50-promo"
    output = render(make_snapshot([make_limit()], promos=[promo]))
    assert output.splitlines()[-1] == "  " + promo


def test_render_requires_quota():
    snapshot = QuotaSnapshot(captured_at=NOW, quota=None, is_stale=True)
    with pytest.raises(ValueError):
        render(snapshot)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ui_cli_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_usage.ui'`

- [ ] **Step 3: Write the implementation**

Create empty `claude_usage/ui/__init__.py` and `claude_usage/ui/cli/__init__.py`.

Create `claude_usage/ui/cli/render.py`:

```python
"""Pure QuotaSnapshot -> str. No I/O; the caller prints."""
from __future__ import annotations

from datetime import datetime, timedelta

from claude_usage.domain.quota import LimitReading, QuotaSnapshot, time_remaining

BAR_WIDTH = 15

_KIND_LABELS = {"session": "Session (5hr)", "weekly_all": "Weekly (7 day)"}

# Colour maps from the severity field only — never from percentage thresholds.
_SEVERITY_COLORS = {"normal": "\x1b[32m", "warning": "\x1b[33m"}
_FALLBACK_COLOR = "\x1b[31m"
_ANSI_RESET = "\x1b[0m"


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


def bar(percent: int, ascii_glyphs: bool = False) -> str:
    clamped = max(0, min(100, percent))
    filled = (clamped * BAR_WIDTH + 50) // 100
    full, empty = ("#", "-") if ascii_glyphs else ("█", "░")
    return full * filled + empty * (BAR_WIDTH - filled)


def coarse(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 60:
        return "<1m"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    return f"{total // 86400}d"


def render_row(
    limit: LimitReading,
    now: datetime,
    *,
    color: bool = False,
    ascii_glyphs: bool = False,
) -> str:
    marker = ""
    if limit.is_active:
        marker = "○ active" if ascii_glyphs else "● active"
    bar_str = bar(limit.percent, ascii_glyphs)
    if color:
        code = _SEVERITY_COLORS.get(limit.severity, _FALLBACK_COLOR)
        bar_str = f"{code}{bar_str}{_ANSI_RESET}"
    percent_str = f"{limit.percent}%"
    row = f"  {label_for(limit):<20}{marker:<10}{percent_str:>4}  {bar_str}"
    remaining = time_remaining(limit.resets_at, now)
    if remaining is not None:
        row += f"  resets in {coarse(remaining)}"
    return row.rstrip()


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
    if quota.promo_notices:
        lines.append("")
        lines.extend(f"  {notice}" for notice in quota.promo_notices)
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ui_cli_render.py -v`
Expected: 18 passed

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 45 passed

---

### Task 5: CLI entrypoint — `ui/cli/main.py`

**Files:**
- Create: `claude_usage/ui/cli/main.py`
- Test: `tests/test_ui_cli_main.py`

**Interfaces:**
- Consumes: `UsageService` (Task 2), `ClaudeJsonQuotaSource`, `SystemClock` (Task 3), `render` (Task 4), fixture `tests/fixtures/live_snapshot.json` (Task 3).
- Produces:
  - `build_parser() -> argparse.ArgumentParser` with flags `--json`, `--no-color`, `--ascii`, `--path PATH`
  - `snapshot_to_dict(snapshot: QuotaSnapshot) -> dict` — field whitelist; `accountUuid` structurally cannot appear
  - `main(argv: list[str] | None = None) -> int` — exit 0 on rendered output (stale included), exit 1 with stderr message `No quota cache found — run Claude Code once to populate it.` when the source returns `None`
  - Module runnable via `python3 -m claude_usage.ui.cli.main`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui_cli_main.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ui_cli_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_usage.ui.cli.main'`

- [ ] **Step 3: Write the implementation**

Create `claude_usage/ui/cli/main.py`:

```python
"""Composition root: argparse -> adapters -> UsageService -> render -> print."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from claude_usage.application.usage import UsageService
from claude_usage.domain.quota import QuotaSnapshot
from claude_usage.infrastructure.claude_json import ClaudeJsonQuotaSource
from claude_usage.infrastructure.clock import SystemClock
from claude_usage.ui.cli.render import render


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-usage",
        description="Show Claude Code quota usage from the local cache.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="emit the snapshot as JSON",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="suppress ANSI colour"
    )
    parser.add_argument(
        "--ascii", action="store_true", dest="ascii_glyphs",
        help="ASCII bar and marker glyphs",
    )
    parser.add_argument(
        "--path", type=Path, default=None,
        help="read an alternate .claude.json (fixtures, testing)",
    )
    return parser


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
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = UsageService(ClaudeJsonQuotaSource(args.path), SystemClock())
    snapshot = service.snapshot()
    if snapshot.quota is None:
        print(
            "No quota cache found — run Claude Code once to populate it.",
            file=sys.stderr,
        )
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


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ui_cli_main.py -v`
Expected: 9 passed

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 54 passed

---

### Task 6: Golden fixture test, privacy test, architecture tests, live smoke run

**Files:**
- Modify: `tests/test_ui_cli_render.py` (append golden test)
- Modify: `tests/test_ui_cli_main.py` (append privacy test)
- Create: `tests/test_architecture.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5 plus fixture `tests/fixtures/live_snapshot.json`. No new production code — if any of these tests fail, fix the production code from the earlier task, not the test.

- [ ] **Step 1: Write the golden test (failing until proven otherwise)**

Append to `tests/test_ui_cli_render.py`:

```python
# --- golden ---------------------------------------------------------------
# End-to-end through infrastructure + application + render with frozen time.
# Expected string built with explicit " " * n so column widths are unambiguous:
# rows are "  " + label.ljust(20) + marker.ljust(10) + pct.rjust(4)
#          + "  " + bar + "  resets in X".

from pathlib import Path

from claude_usage.application.usage import UsageService
from claude_usage.infrastructure.claude_json import ClaudeJsonQuotaSource

FIXTURE = Path(__file__).parent / "fixtures" / "live_snapshot.json"

GOLDEN = "\n".join(
    [
        "USAGE" + " " * 32 + "as of 5m ago · fresh",
        "",
        "  Session (5hr)" + " " * 18 + "25%  " + "█" * 4 + "░" * 11
        + "  resets in 5h",
        "  Weekly (7 day)" + " " * 17 + "50%  " + "█" * 8 + "░" * 7
        + "  resets in 1d",
        "  Weekly Fable" + " " * 8 + "● active" + " " * 3 + "75%  "
        + "█" * 11 + "░" * 4 + "  resets in 1d",
        "",
        "  +50% weekly limits promo through Aug 19 · clau.de/cc-50-promo",
    ]
)


class FrozenClock:
    def __init__(self, now):
        self._now = now

    def now(self):
        return self._now


def test_golden_reproduces_fixture_display():
    # Fixture fetchedAtMs = 2026-08-05T18:05:00Z; freeze "now" 5 minutes later.
    frozen = FrozenClock(datetime(2026, 8, 5, 18, 10, tzinfo=UTC))
    service = UsageService(ClaudeJsonQuotaSource(FIXTURE), frozen)
    assert render(service.snapshot()) == GOLDEN
```

- [ ] **Step 2: Write the privacy test**

Append to `tests/test_ui_cli_main.py`:

```python
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
```

- [ ] **Step 3: Write the architecture tests**

Create `tests/test_architecture.py`:

```python
"""Encodes the spec's greppable import discipline (POC spec §4)."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "claude_usage"

FORBIDDEN_REFS = {
    "domain": [
        "claude_usage.application",
        "claude_usage.infrastructure",
        "claude_usage.ui",
        "import wx",
    ],
    "application": ["claude_usage.infrastructure", "claude_usage.ui", "import wx"],
    "infrastructure": ["claude_usage.ui", "import wx"],
}

IO_IMPORT = re.compile(r"^(from|import) (json|pathlib|argparse|os|sys)\b", re.M)


def layer_files(layer):
    files = list((PKG / layer).rglob("*.py"))
    assert files, f"no files found under claude_usage/{layer}"
    return files


def test_inward_only_imports():
    for layer, banned in FORBIDDEN_REFS.items():
        for path in layer_files(layer):
            text = path.read_text(encoding="utf-8")
            for needle in banned:
                assert needle not in text, f"{path} references {needle}"


def test_domain_has_no_io_imports():
    for path in layer_files("domain"):
        match = IO_IMPORT.search(path.read_text(encoding="utf-8"))
        assert match is None, f"{path} imports {match.group(2)}"
```

- [ ] **Step 4: Run the new tests**

Run: `python3 -m pytest tests/test_ui_cli_render.py tests/test_ui_cli_main.py tests/test_architecture.py -v`
Expected: all pass (golden 1, privacy 1, architecture 2, plus the pre-existing ones). If the golden fails, diff with `repr()` on both strings; the GOLDEN literal encodes the agreed column rule — fix `render.py`, not the golden, unless the mismatch is in the plan's own arithmetic.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 58 passed

- [ ] **Step 6: Live smoke test (read-only)**

Run each and eyeball the output:

```bash
python3 -m claude_usage.ui.cli.main
python3 -m claude_usage.ui.cli.main --ascii
python3 -m claude_usage.ui.cli.main --json
```

Expected: three bars (session / weekly / model-scoped weekly) with percentages matching what Claude Code's `/usage` shows, an age line, and — through Aug 19 — the +50% promo footnote. `--json` output must contain no `accountUuid`. If the machine has no `~/.claude.json`, expect the exit-1 stderr message instead; that is correct behaviour, not a failure.

- [ ] **Step 7: Confirm nothing is staged and nothing under `~/.claude*` changed**

Run: `git status --short`
Expected: only untracked/modified entries for this repo's new files, none staged. Do not stage or commit anything.

---

## Wrap-up (after all tasks)

Per the user's git rules, leave everything unstaged and propose — do not execute:

- **Branch name:** `feat/cli-quota-poc`
- **Commit message draft:**

  ```text
  feat: add one-shot CLI quota display over ~/.claude.json cache

  Onion-architecture core (domain/application/infrastructure/ui) with
  pure renderer, staleness handling, and full pytest coverage.
  ```

Remind the user that `docs/superpowers/` (this plan) stays out of git per their convention. The spec now lives at `claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md` and is tracked with the feature (left unstaged).
