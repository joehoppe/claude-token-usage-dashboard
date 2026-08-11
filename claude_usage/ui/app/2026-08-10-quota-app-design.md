# Quota App v1 — Design Spec

**Status:** Approved
**Date:** 2026-08-10
**Author:** Joseph Hoppe (drafted with Claude Code)
**Supersedes:** `claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md`
**Parent:** [`SPEC.md`](../../../SPEC.md)

Replaces the one-shot CLI with an always-on-top wxPython window showing Claude
Code subscription quota. Quota only — the token/cost panel from `SPEC.md` §7.4
is deferred to v2.

---

## 1. Scope

**In:** a `wx.Frame` with `wx.STAY_ON_TOP` rendering the bars from
`~/.claude.json`'s `cachedUsageUtilization.utilization.limits[]`, a staleness
indicator, four distinct no-data/error states, a read-only config file, and a
background poller.

**Out of v1:** transcript reading, deduplication, incremental tailing, model
normalization, pricing, cost, rolling windows, per-project breakdown. All of
that is `SPEC.md` §4.1/§6/§7.4 and lands in v2.

**Out of scope entirely:** frozen app bundles (py2app/PyInstaller), tray/menu-bar
mode, launch-at-login, OS notifications, persisted window geometry.

### 1.1 Decisions carried from `SPEC.md` §10

| Open question | Resolution |
|---|---|
| §10.1 Headline metric | Remaining quota %. Tokens/cost are v2. |
| §10.2 Scope | All projects. Not applicable in v1 (quota is account-wide). |
| §10.3 Dollar cost | Deferred with the rest of the token panel. |
| §10.4 Severity alerts | No. The always-on-top window is the notification. |

`SPEC.md` §8's line "this spec file is not to be committed to git" is stale —
`SPEC.md` is already tracked on `main` and stays tracked.

---

## 2. Architecture

Onion, per `AGENTS.md`. Existing layers are extended, not restructured.

```
ui/app/    main.py (composition root) · frame.py · panels.py · poller.py · presenter.py
             ↓
application/  usage.py (UsageService) · ports.py (QuotaSource, Clock, ConfigSource)
             ↓
domain/       quota.py (LimitReading, QuotaReading, QuotaSnapshot, QuotaUnavailable)
             ↑
infrastructure/  claude_json.py · config.py · clock.py   (implement the ports)
```

The composition root builds `ClaudeJsonQuotaSource`, `SystemClock`,
`TomlConfigSource`, injects them into `UsageService`, and hands the service to
`PollerThread`. No inner layer imports `wx`.

### 2.1 Domain changes

`ClaudeJsonQuotaSource.read_quota()` currently collapses every failure into a
single `None`. §5 requires four distinguishable outcomes, so the contract
changes.

```python
class QuotaUnavailable(Enum):
    NO_FILE = "no_file"            # ~/.claude.json absent
    NO_QUOTA_KEY = "no_quota_key"  # file readable, cachedUsageUtilization absent/invalid
    READ_ERROR = "read_error"      # OSError, JSONDecodeError, unusable fetchedAtMs
```

`QuotaSnapshot` becomes a result type:

```python
@dataclass(frozen=True)
class QuotaSnapshot:
    captured_at: datetime
    quota: QuotaReading | None
    is_stale: bool
    unavailable: QuotaUnavailable | None = None
    detail: str | None = None      # e.g. "JSONDecodeError"; never a file path or payload
```

Invariant: exactly one of `quota` / `unavailable` is set, **except** in the
stale-fallback case (§5, `READ_ERROR` with history), where both are set —
`quota` is the last good reading and `unavailable` is `READ_ERROR`.

`LimitReading`, `QuotaReading`, `binding()`, `is_stale()`, `time_remaining()`
are unchanged. `STALE_AFTER` remains the default, now overridable by config.

### 2.2 Application changes

```python
class QuotaSource(Protocol):
    def read_quota(self) -> QuotaReading | QuotaUnavailable: ...

class ConfigSource(Protocol):
    def read_config(self) -> Config: ...
```

`UsageService` gains last-good-reading memory:

- Good read → store it, return a fresh snapshot (`is_stale` from the reading's
  own age against the configured threshold).
- `READ_ERROR` **with** a stored reading → return that reading with its original
  `measured_at`, `is_stale=True`, `unavailable=READ_ERROR`, `detail` set.
- `READ_ERROR` **without** a stored reading → `quota=None`, `unavailable=READ_ERROR`.
- `NO_FILE` / `NO_QUOTA_KEY` → **never** fall back. These are not transient; a
  stale reading shown for a missing file would be a lie. Any stored reading is
  discarded.
- Absent data must never render as fresh: `is_stale` is `True` whenever
  `quota is None`.

The stored reading lives in the service instance, mutated only on the poller
thread. It never crosses to the GUI thread.

### 2.3 Infrastructure changes

`claude_json.py` distinguishes causes:

| Condition | Result |
|---|---|
| `FileNotFoundError` (or `NotADirectoryError`) | `NO_FILE` |
| Other `OSError` (e.g. `PermissionError`) | `READ_ERROR` |
| `json.JSONDecodeError` / non-dict root | `READ_ERROR` |
| `cachedUsageUtilization` missing or not a dict | `NO_QUOTA_KEY` |
| `fetchedAtMs` missing/non-numeric/unconvertible | `READ_ERROR` |
| otherwise | `QuotaReading` |

An empty `limits[]` is **not** an error — it yields a `QuotaReading` with no
bars, rendered as "no limits reported". Per-entry parse failures continue to be
skipped individually, as today. The `accountUuid` field is never read.

New `infrastructure/config.py` — `TomlConfigSource`, stdlib `tomllib`,
`Path.home() / ".config" / "claude-usage" / "config.toml"` on both platforms.

`clock.py` is unchanged.

---

## 3. Config

```toml
poll_seconds = 10         # default 10, clamped to 1..600
stale_after_minutes = 15  # default 15, clamped to 1..1440
```

```python
@dataclass(frozen=True)
class Config:
    poll_seconds: int = 10
    stale_after: timedelta = timedelta(minutes=15)
    warnings: tuple[str, ...] = ()
```

- Absent file → defaults, silently, no warning.
- Unreadable or malformed TOML → all defaults + one warning.
- A key with the wrong type, or out of range → that key defaults, others still
  apply, one warning naming the key. Out-of-range values are rejected to the
  default rather than clamped silently, so the UI never disagrees with the file.
- Unknown keys are ignored without warning — forward compatibility.

`warnings` surface as `QuotaView.notices` entries. Config is read **once** at
startup by the composition root, not per poll. The app never writes it.

---

## 4. Presenter

`ui/app/presenter.py` exports one pure function:

```python
def present(snapshot: QuotaSnapshot, config: Config) -> QuotaView
```

Every display decision is made here. `panels.py` places strings and draws
rectangles; it computes nothing.

```python
@dataclass(frozen=True)
class BarView:
    label: str             # "Weekly Fable"
    percent: int           # used
    remaining: int         # 100 - percent, the number shown (SPEC §7.2)
    severity: str          # "normal" | "warning" | "critical"
    active: bool
    resets_text: str | None  # "resets in 3h"

@dataclass(frozen=True)
class QuotaView:
    headline: str              # "34% remaining"
    age_text: str              # "as of 7m ago"
    stale: bool
    bars: tuple[BarView, ...]  # sorted by percent descending
    notices: tuple[str, ...]
    message: str | None        # set only when there are no bars to show
    message_detail: str | None
```

Rules:

- `headline` comes from `QuotaReading.binding()` — the **worst** bar, the
  constraint that would actually stop work. Not an average, not the aggregate.
  With no limits, `headline` is "No limits reported".
- `remaining = 100 - percent`, clamped to `0..100`.
- `severity` maps `normal`/`warning` through unchanged; **any other value,
  including unknown future ones, maps to `critical`.** Failing loud beats
  rendering an unrecognized severity as safe.
- Severity is never derived from `percent` — `SPEC.md` §7.2. The presenter emits
  a semantic name; `panels.py` owns the `wx.Colour` values.
- `label` reuses the CLI's `label_for` logic: `weekly_scoped` + scope model →
  "Weekly <Model>"; known kinds → friendly names; **unknown kinds fall back to
  title-cased text rather than raising** — new limit kinds must render.
- `age_text` uses the CLI's `coarse()` formatting, always shown.
- `stale=True` greys the bars and appends "· STALE" to `age_text`.

`label_for` and `coarse` move from `ui/cli/render.py` into the presenter before
the CLI is deleted. The ANSI colour codes and bar glyphs do not move — they die
with the CLI.

### 4.1 The four no-data states

| State | `message` | `bars` |
|---|---|---|
| `NO_FILE` | "Claude Code data not found" | empty |
| `NO_QUOTA_KEY` | "No quota data cached yet — run Claude Code once" | empty |
| `READ_ERROR`, no prior reading | "Couldn't read quota data" (`detail` → `message_detail`) | empty |
| `READ_ERROR`, prior reading | `None` | from the prior reading, `stale=True`, `detail` appended to `notices` |

`message_detail` carries the exception class name only — never a path, never
file contents.

---

## 5. Runtime

### 5.1 Frame

- `wx.Frame`, `wx.STAY_ON_TOP` in the style, default ~320×180, resizable, never
  steals focus on refresh.
- Header: `headline` · `age_text` (with stale marker).
- Body: one bar row per `BarView`, drawn with `wx.PaintDC` rectangles —
  `wx.Gauge` cannot be coloured per-severity portably. Each row shows label,
  remaining %, the bar, an active marker, and `resets_text`.
- Footer: `notices`, one per line, omitted when empty.
- When `message` is set the body is replaced by `message` + `message_detail`.
- Position and size are **not** persisted. The app is strictly read-only
  (`SPEC.md` §8); this knowingly departs from `SPEC.md` §7.1.

### 5.2 Poller

`PollerThread(threading.Thread, daemon=True)`:

1. Perform one synchronous refresh before `frame.Show()` so the window never
   flashes empty.
2. Loop on `threading.Event.wait(config.poll_seconds)` — shutdown is immediate,
   not up to one interval late.
3. Call `service.snapshot()` then `present()` **off** the GUI thread.
4. Cross to the GUI thread only via `wx.CallAfter` with the frozen `QuotaView`.
   Nothing else crosses; the thread never touches wx state.
5. Catch every exception in the loop, convert it to a `READ_ERROR`-shaped view,
   and continue. A poller that dies silently would freeze the display on a stale
   reading — precisely the `SPEC.md` §7.3 failure this app exists to prevent.

The frame sets the stop event in its close handler and joins with a short
timeout.

---

## 6. Testing

Strict TDD: a failing test precedes each implementation step.

| File | Coverage |
|---|---|
| `test_domain_quota.py` (extend) | `QuotaUnavailable`; `QuotaSnapshot` invariants; `binding()`; `is_stale` at the threshold boundary; `time_remaining` past reset → 0 |
| `test_application_usage.py` (extend) | `READ_ERROR` after a good read returns the prior reading with its **original** `measured_at` and `is_stale=True`; `READ_ERROR` with no history returns the error state; `NO_FILE`/`NO_QUOTA_KEY` never fall back and discard history; configured stale threshold is honoured |
| `test_infrastructure_claude_json.py` (extend) | Each of the four outcomes from a real fixture: absent path, `{}`, invalid JSON, valid data. `PermissionError` via monkeypatched `read_text`. Empty `limits[]` → reading, not error. Bad `fetchedAtMs`. Malformed individual limit entries skipped |
| `test_infrastructure_config.py` (new) | Absent, valid, malformed TOML, wrong types, out-of-range, unknown keys |
| `test_ui_presenter.py` (new) | Headline picks the worst bar, not the aggregate (the 39%-vs-66% case, `SPEC.md` §7.2); remaining vs percent; sort order; unknown severity → `critical`; unknown `kind` renders; all four messages; stale greying; promo + config notices |
| `test_architecture.py` (extend) | `ui/app/` unimported by any inner layer; `domain/` imports stdlib only; no `wx` import outside `ui/app/` |

No test instantiates `wx`. `frame.py`, `panels.py`, and `poller.py` are verified
by running the app — everything that can be logically wrong lives in the
presenter, which is pure.

Fixtures under `tests/fixtures/` are kept and reused.

---

## 7. CLI removal

The CLI is deprecated on approval of this spec and **removed in the same commit
that ships the app** — v1 reaches full parity with it on day one, since the CLI
also only reads quota. Headless verification lives in the test suite, not in a
shipped entrypoint.

Deleted: `claude_usage/ui/cli/` (including
`2026-08-05-cli-quota-poc-design.md`, per `AGENTS.md` — the spec goes when the
feature goes) and `tests/test_ui_cli_main.py`, `tests/test_ui_cli_render.py`.

`pyproject.toml`: the `claude-usage` script repoints to
`claude_usage.ui.app.main:main`; `description` changes from "One-shot CLI
showing Claude Code quota usage from the local cache" to reflect the window.
`wxPython` is added to `dependencies` (approved in `AGENTS.md`; no attribution
obligation triggers while distribution is source/pip only).

`SPEC.md` gains a short status note recording that v1 is quota-only and that
§10.1–§10.4 are resolved as in §1.1 above.

---

## 8. Privacy

Unchanged from `SPEC.md` §8 and still binding: read-only, no network, no
credentials. `accountUuid` is never read, displayed, or logged. `message_detail`
carries an exception class name only — never a path or file contents. v1 does
not read transcripts at all, so no conversation text is touched.
