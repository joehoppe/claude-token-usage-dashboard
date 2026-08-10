# CLI Quota POC — Design Spec

**Status:** Approved for planning
**Date:** 2026-08-05
**Author:** Joseph Hoppe (drafted with Claude Code)
**Parent:** [`SPEC.md`](../../../SPEC.md) — the wxPython dashboard. This POC seeds
that project's inner rings; the wx frame later becomes a second driver over the
same core.

A one-shot command-line tool that reproduces the three usage bars Claude Code
displays — session, weekly, and model-scoped weekly — with percentages, reset
countdowns, and an unmissable cache-age line.

> Every field name and path below was verified against a live machine on
> 2026-08-05. Concrete values — percentages, timestamps, token counts, corpus
> sizes — are representative placeholders; the raw capture is not published.
> See [Appendix A](#appendix-a--verified-observations).

---

## 1. Goal

Print, in one invocation, the data behind Claude Code's usage display:

```text
USAGE                                as of 5m ago · fresh

  Session (5hr)                  25%  ████░░░░░░░░░░░  resets in 5h
  Weekly (7 day)                 50%  ████████░░░░░░░  resets in 1d
  Weekly Fable        ● active   75%  ███████████░░░░  resets in 1d

  +50% weekly limits promo through Aug 19 · clau.de/cc-50-promo
```

The tool answers exactly one question: **can I keep working right now?**

Secondary goal: establish the `domain/` `application/` `infrastructure/` `ui/`
layout mandated by `CLAUDE.md`, so the wxPython work starts from a tested core
rather than from scratch.

## 2. Non-goals

- **Token counts, cost, and per-project attribution.** Deliberately excluded —
  see [§3](#3-source-decision). The pricing table and deduplication logic in
  `sample/core.py` stay unused until a JSONL panel is a real requirement.
- **Live refresh.** One-shot print only. No poll loop, no ANSI cursor control,
  no TTY state machine. Re-run the command.
- **Deriving percentages from transcripts.** Structurally impossible; see
  [§3.2](#32-why-jsonl-cannot-produce-the-percentages).
- **Network access, authentication, or credential storage.** The tool reads two
  local files at most and never writes.

## 3. Source decision

**Decision: read `~/.claude.json` only. Do not read the JSONL transcripts.**

The percentages and reset times live in `~/.claude.json` under
`cachedUsageUtilization`. They are **not** in the JSONL transcripts under
`~/.claude/projects/`. Verified: across the full local
corpus (hundreds of transcript files, on the order of 100 MB), zero records
carry a quota field. The only `resets_at` / `weekly_scoped` string matches in
the entire corpus are conversation text from the sessions where this JSON was
discussed, not structured data.

### 3.1 Trade-offs considered

| | `~/.claude.json` | JSONL transcripts |
|---|---|---|
| Reproduces the displayed percentages | Yes — it *is* the source | No — structurally cannot |
| Reset countdowns | `resets_at` per limit, precise | Absent |
| Read cost | 1 file, ~1 ms | hundreds of files, ~100 MB, <1 s |
| Coverage | Account-wide, every surface | Local Claude Code only |
| History | None — one snapshot | Every turn, timestamped |
| Attribution (project / model / cost) | None | Full (`cwd`, `model`, token fields) |
| Schema stability | Private, churning | Stable — 0 unparseable lines in the full corpus |

### 3.2 Why JSONL cannot produce the percentages

Four independent reasons, in descending order of severity.

**1. The numerator is systematically incomplete.** Quota is scoped to the
*account*. claude.ai web, Claude Desktop, the Slack tag, and any other machine
on the same login all draw down the same weekly pool and write no local
transcript. `SPEC.md` §2 already excludes non-Claude-Code usage as a non-goal —
but that exclusion is what makes JSONL unable to *reach* the true percentage,
not merely imprecise about it.

**2. No denominator exists locally, and back-solved ones cannot be validated.**
`limit_dollars`, `used_dollars`, and `remaining_dollars` are all `null` on the
captured account's tier. Back-solving from the observed snapshot yields three
unrelated pools (values illustrative):

| Window | JSONL tokens | Cache % | Implied pool @ 100% |
|---|---:|---:|---:|
| 5-hour | 20,000,000 | 25% | 80,000,000 |
| 7-day | 150,000,000 | 50% | 300,000,000 |
| 7-day Fable | 90,000,000 | 75% | 120,000,000 |

A single observation fits *any* denominator perfectly. Only one observation is
available, so a calibration looks flawless the moment it is made and there is
no local means of falsifying it.

**3. The denominator moves without warning.** A `+50% weekly limits promo
through Aug 19` is live on the `seven_day` bar. On Aug 19 the real weekly pool
contracts by a third, every calibrated estimate silently inflates, and nothing
in the JSONL signals the change.

**4. Deduplication is load-bearing and easy to get wrong.** The corpus holds
roughly three duplicate `message.id` values for every two unique usage
records — resumes, forks, and compaction re-emit turns. Omitting the dedup
step inflates totals by roughly 2.5×.

### 3.3 The cost of the chosen source

One risk, and the entire correctness burden of this design: **`~/.claude.json`
is a cache Claude Code refreshes only while making requests.** Observed
behaviour confirms both halves of that. While Claude Code was active the cache
age held steady at a few minutes and the `five_hour` percentage ticked up a
point mid-session; with Claude Code idle overnight the same file will read
hours old while looking perfectly current.

Consequence: **the cache age is rendered on every invocation, unconditionally.**
It is not a verbose-mode detail.

Accepted lesser costs: percent-only (cannot answer "how many tokens remain"),
no history, and a private schema — 14 non-structural keys sit beside `limits[]`,
11 of them null placeholders keyed by internal codenames (redacted here).

## 4. Package layout

```text
claude_usage/
  __init__.py
  domain/
    __init__.py
    quota.py                  LimitReading, QuotaReading, QuotaSnapshot, STALE_AFTER
  application/
    __init__.py
    ports.py                  QuotaSource, Clock  (Protocols)
    usage.py                  UsageService
  infrastructure/
    __init__.py
    claude_json.py            ClaudeJsonQuotaSource
    clock.py                  SystemClock
  ui/
    __init__.py
    cli/
      __init__.py
      render.py               pure QuotaSnapshot -> str
      main.py                 argparse + composition root
tests/
  test_domain_quota.py
  test_application_usage.py
  test_infrastructure_claude_json.py
  test_ui_cli_render.py
  test_ui_cli_main.py
  fixtures/
    live_snapshot.json        redacted capture of a real ~/.claude.json
```

Runtime dependencies: **standard library only.** Test dependency: `pytest`
(MIT). No new licence question arises.

Ports are declared in `application/ports.py`, beside their consumer rather than
beside their implementations. That placement is what inverts the dependency:
`ClaudeJsonQuotaSource` conforms structurally to a shape the application ring
declared, so no inner module ever names it.

The import discipline is greppable, and should stay that way:

```bash
grep -rnE '^(from|import) (json|pathlib|argparse|os|sys)' claude_usage/domain/    # prints nothing
grep -rn  'claude_usage.infrastructure' claude_usage/domain/ claude_usage/application/  # prints nothing
```

## 5. Domain — `domain/quota.py`

Standard library only. No I/O, no `argparse`, no ANSI.

```python
STALE_AFTER = timedelta(minutes=15)
```

Staleness is a domain rule, not a rendering flourish, because a stale reading
presented as live is the one way this tool can be actively wrong.

**`LimitReading`** (frozen dataclass) — one entry from `limits[]`:

| Field | Type | Source |
|---|---|---|
| `kind` | `str` | `entry["kind"]`, default `"unknown"` |
| `group` | `str` | `entry["group"]`, default `""` |
| `percent` | `int` | `entry["percent"]` |
| `severity` | `str` | `entry["severity"]`, default `"normal"` |
| `is_active` | `bool` | `entry["is_active"]` |
| `resets_at` | `datetime \| None` | `entry["resets_at"]`, aware UTC |
| `scope_model` | `str \| None` | `entry["scope"]["model"]["display_name"]` |

**`QuotaReading`** (frozen) — `measured_at: datetime`,
`limits: tuple[LimitReading, ...]`, `promo_notices: tuple[str, ...]`, with:

- `age(now) -> timedelta`
- `is_stale(now, threshold=STALE_AFTER) -> bool` — `age >= threshold`
- `binding() -> LimitReading | None` — highest `percent`, or `None` when
  `limits` is empty. The binding constraint is the worst bar, not the average
  and not the aggregate (`SPEC.md` §7.2): the observed snapshot read
  weekly-all 50% while weekly-Fable read 75% (illustrative values), and the
  latter is what would actually stop work.

**`QuotaSnapshot`** (frozen) — `captured_at: datetime`,
`quota: QuotaReading | None`, `is_stale: bool`.

The only type that crosses outward. Frozen because the wxPython driver will
later hand it across a thread boundary, and immutability makes that crossing
safe by construction rather than by convention.

**`time_remaining(resets_at, now) -> timedelta | None`** — pure helper;
`None` when `resets_at` is `None`, clamped at zero when already past.

## 6. Application — `application/usage.py`

```python
class QuotaSource(Protocol):
    def read_quota(self) -> QuotaReading | None: ...

class Clock(Protocol):
    def now(self) -> datetime: ...
```

`UsageService(quota_source, clock)` exposes one method:

```python
def snapshot(self) -> QuotaSnapshot
```

It reads the clock once, asks the source for a reading, and derives
`is_stale` (`True` when `quota is None` — absent data must never render as
fresh). Pure orchestration: no I/O, no widgets, no threads, and unit-testable
with two hand-written fakes and zero fixtures.

## 7. Infrastructure — `infrastructure/claude_json.py`

`ClaudeJsonQuotaSource(path=Path.home() / ".claude.json")`.

Note the path: `~/.claude.json` is the **sibling** of the `~/.claude/`
directory, not a file inside it.

Reads the file whole, then:

1. `cachedUsageUtilization.fetchedAtMs` → `measured_at`
   (milliseconds since epoch → timezone-aware UTC).
2. `cachedUsageUtilization.utilization.limits[]` → one `LimitReading` per
   entry, **skipping any entry whose `percent` is `None`**.
3. `cachedGrowthBookFeatures.tengu_rate_limit_promo_notices[].text` →
   `promo_notices`. Absent or malformed → empty tuple, never an error.

**Read `limits[]`, never the named siblings.** `five_hour` and `seven_day`
carry the same numbers today, but they sit among 11 null-valued feature-flag
keys that will churn. `limits[]` exposes every active limit uniformly, so a new
limit kind arrives as a new array entry rather than as parser breakage.

Returns `None` — never raises — on absent file, unreadable file, invalid JSON,
missing `cachedUsageUtilization`, or missing `fetchedAtMs`.

`accountUuid` is never read into any field, so it cannot reach output by
accident. `SystemClock` lives in `infrastructure/clock.py` and is injected so
tests freeze time without patching.

## 8. CLI render — `ui/cli/render.py`

Pure functions from `QuotaSnapshot` to `str`. No I/O; the caller prints.

**Row order: source order, not sorted by percent.** This is a deliberate
departure from `SPEC.md` §7.2. Claude Code displays session → weekly →
model-scoped, which is `limits[]` order; sorting descending would reorder the
display this POC exists to reproduce.

**Labels**, derived from `kind` and `scope_model`:

| `kind` | Label |
|---|---|
| `session` | `Session (5hr)` |
| `weekly_all` | `Weekly (7 day)` |
| `weekly_scoped` | `Weekly {scope_model}` |
| anything else | `kind.replace("_", " ").title()`, plus `scope_model` when present |

The fallback is load-bearing: new limit kinds must render, not crash.

**Bars** — 15 cells, `█` filled / `░` empty; `--ascii` substitutes `#` / `-`.

**Countdowns** — coarse single unit, matching the displayed form: `2h`, `1d`,
`12m`, `<1m`. Omitted for a row whose `resets_at` is `None`.

**Colour** — mapped from the `severity` field, never from local percentage
thresholds. Deriving red/amber from hardcoded cutoffs would disagree with what
Claude Code itself shows. Emitted only when stdout is a TTY and `NO_COLOR` is
unset; `--no-color` forces plain.

**Active marker** — `● active` on rows with `is_active: true` (`○` under
`--ascii`).

**Age line** — always present: `as of 5m ago · fresh`, or
`as of 3h ago · STALE` past `STALE_AFTER`.

**Promo footnote** — one line per entry in `promo_notices`, when non-empty.
Promos inflate a limit's denominator, which makes percentages non-comparable
across time; the footnote is the only local signal of that.

### 8.1 Flags — `ui/cli/main.py`

| Flag | Effect |
|---|---|
| `--json` | Emit the serialised `QuotaSnapshot` |
| `--no-color` | Suppress ANSI colour |
| `--ascii` | ASCII bar and marker glyphs |
| `--path PATH` | Read an alternate `.claude.json` (fixtures, testing) |

**`--json` serialises the `QuotaSnapshot`, not the source file.** A raw
passthrough would leak `accountUuid`; a field whitelist cannot.

## 9. Data flow and error handling

One synchronous pass, no threads:

```text
main()
  → SystemClock()  +  ClaudeJsonQuotaSource(path)
  → UsageService.snapshot()  →  QuotaSnapshot
  → render(snapshot, options)  →  str
  → print
```

| Condition | Behaviour | Exit |
|---|---|---|
| Rendered successfully | Print to stdout | 0 |
| Stale reading | Renders normally, marked `STALE` | 0 |
| `limits[]` present but empty | Header, age line, `no limits reported` | 0 |
| No usable cache | `No quota cache found — run Claude Code once to populate it.` to **stderr** | 1 |
| Unknown `kind` | Fallback label, row renders | 0 |
| Unparseable `resets_at` | Drop that row's countdown, keep its bar | 0 |
| `percent` outside 0–100 | Clamp the bar, print the raw number | 0 |

Stale data still exits 0 — it is data, and the age line already says so.
Reserving a non-zero exit for stale readings would break the composability that
motivated the one-shot design.

## 10. Privacy and security

- Read-only. Never writes to `~/.claude/` or `~/.claude.json`.
- `accountUuid` is never read, rendered, logged, or serialised. Enforced by a
  test asserting its absence from both rendered text and `--json` output.
- No transcript access at all in this POC, so conversation text, file contents,
  and any secrets they contain are out of reach by construction.
- No network calls, no credentials, nothing to leak.
- This spec lives beside its implementation (`claude_usage/ui/cli/`) and is
  tracked in git, per the project convention that spec documents are saved in
  the folder where the feature is implemented.

## 11. Testing

Strict TDD per `CLAUDE.md`: failing test first, then implementation, then
`pytest` run, changes left unstaged.

Domain and application need no filesystem — a fake `QuotaSource` and a frozen
clock cover them. Infrastructure uses `tmp_path` JSON fixtures. The renderer is
pure, so it tests as string equality.

Required cases:

| Layer | Case |
|---|---|
| Infrastructure | Absent file → `None` |
| Infrastructure | Unreadable file → `None` |
| Infrastructure | Invalid JSON → `None` |
| Infrastructure | Missing `cachedUsageUtilization` → `None` |
| Infrastructure | Missing `fetchedAtMs` → `None` |
| Infrastructure | Entries with `percent: null` skipped |
| Infrastructure | `scope: null` vs populated `scope.model.display_name` |
| Infrastructure | Absent / malformed promo notices → empty tuple |
| Domain | `is_stale` boundary at exactly 15 minutes |
| Domain | `binding()` picks highest percent; `None` on empty `limits` |
| Domain | `time_remaining` clamps a past `resets_at` to zero |
| Application | `quota is None` → `is_stale is True` |
| Render | Unknown `kind` → fallback label, no crash |
| Render | Non-`normal` severity selects a different colour |
| Render | Unparseable `resets_at` → bar retained, countdown dropped |
| Render | `percent` of 140 → bar clamped, `140%` printed |
| Render | Source order preserved, not percent-sorted |
| Render | `NO_COLOR` and non-TTY both suppress ANSI |
| Privacy | `accountUuid` absent from rendered text **and** `--json` |
| Golden | Fixture reproduces `25% / 50% / 75%` with countdowns and promo line |

The golden fixture mirrors the real `~/.claude.json` schema with anonymized
placeholder values — the schema shape, not the numbers, is the source of the
edge cases that matter.

## 12. Deviations from `SPEC.md`

| `SPEC.md` | This POC | Reason |
|---|---|---|
| §7.2 sort bars by percent descending | Source order | Reproduces the actual display order |
| §6.2 per-file cursors for incremental tailing | Not implemented | No transcript reads; also see below |
| §5.1 threading, §5.2 poll cadence | Single synchronous pass | One-shot CLI |
| §6.1 dedup, §6.4 pricing | Not implemented | Cache-only scope |
| §7.2 show remaining (`100 - percent`) | Show `percent` | Matches the display being reproduced |

`SPEC.md` corrections found while verifying, relevant when the JSONL panel is
eventually built:

1. **§6.2's incremental-tailing machinery is optional for a one-shot reader.**
   A full brute-force scan of the corpus (hundreds of files, ~100 MB) completed
   in under a second. Per-file cursors are a daemon concern.
2. **Appendix A's usage-record count is a pre-deduplication count.** Dedup on
   `message.id` shrinks the raw record count by roughly 2.5× — a structural
   difference, not a rounding one.
3. **§4.1's list of non-usage record types is incomplete.** Also observed:
   `mode`, `file-history-delta`, `custom-title`, `system`, `pr-link`,
   `permission-mode`. A reader that allow-lists types rather than selecting
   `type == "assistant"` would silently drop or mis-handle these.

---

## Appendix A — verified observations

Collected 2026-08-05 on macOS for a paid Claude account (rate-limit tier and
seat tier redacted). Schema facts — field names, entry counts, null-ness — are
as observed; numeric values and timestamps below are representative
placeholders, kept consistent with the test fixture.

### Quota cache — `~/.claude.json`

| Fact | Value |
|---|---|
| Cache age when read | a few minutes |
| Refresh behaviour | `five_hour` observed ticking up one point mid-session while Claude Code was active |
| `limits[]` entries | 3 |
| `session` | 25%, `severity: normal`, `is_active: false`, resets `2026-08-06T00:00:00Z` |
| `weekly_all` | 50%, `severity: normal`, `is_active: false`, resets `2026-08-07T00:00:00Z` |
| `weekly_scoped` | 75%, `severity: normal`, **`is_active: true`**, `scope.model.display_name: "Fable"`, resets `2026-08-07T00:00:00Z` |
| `limit_dollars` / `used_dollars` / `remaining_dollars` | `null` on this tier |
| Non-structural sibling keys | 14, of which 11 are `null` feature-flag placeholders keyed by internal codenames (redacted) |
| Active promo | `+50% weekly limits promo through Aug 19 · clau.de/cc-50-promo`, on the `seven_day` bar |

### Transcript corpus — `~/.claude/projects/`

| Fact | Value |
|---|---|
| Project directories | dozens |
| Transcript files | hundreds |
| Corpus size | on the order of 100 MB |
| Full brute-force scan | under a second |
| Unparseable lines | 0 |
| Records mentioning any quota field | 0 structured; a handful of files contain the strings as conversation text only |
| Dedup ratio | raw `assistant` records ≈ 2.5× the unique `message.id` count |
| Record types observed | `assistant` · `user` · `attachment` · `last-prompt` · `queue-operation` · `ai-title` · `file-history-snapshot` · `mode` · `file-history-delta` · `custom-title` · `system` · `pr-link` · `permission-mode` (counts redacted) |

### Window token sums, aligned to the cache's `resets_at` (illustrative)

| Window | Tokens | Cache % |
|---|---:|---:|
| 5-hour (`19:00` → `00:00`) | 20,000,000 | 25% |
| 7-day (`07-31 00:00` → `08-07 00:00`) | 150,000,000 | 50% |
| 7-day, Fable only | 90,000,000 | 75% |

Per-model 7-day splits are derivable from the JSONL (`model` is present on
every usage record); the capture's actual volumes are redacted.
