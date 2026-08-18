# Usage Dashboard for Claude — Design Spec

**Status:** Draft
**Date:** 2026-08-05
**Author:** Joseph Hoppe (drafted with Claude Code)

A small always-on-top desktop widget showing local Claude Code token
consumption and remaining subscription quota. Runs on macOS and Windows from a
single wxPython codebase.

> All schema details, field names, paths, and sample values in this document
> were verified against a live machine on 2026-08-05 (290 transcript files,
> 14,751 usage records). See [Appendix A](#appendix-a--verified-observations).
>
> **Two maintained surfaces.** This spec describes the wx desktop widget. A
> one-shot CLI
> ([`claude_usage/ui/cli/`](claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md))
> reads the same quota cache through the same core and is a permanent,
> actively maintained driver — not a stepping-stone that goes away once the
> widget ships. **Any change to the `domain/` / `application/` /
> `infrastructure/` core should be checked against both drivers for feature
> parity**, or the divergence recorded explicitly. See
> [`claude_usage/ui/app/2026-08-10-quota-app-design.md`](claude_usage/ui/app/2026-08-10-quota-app-design.md)
> §7 for the policy and its mechanics.

---

## 1. Goals

1. Show **remaining subscription quota** — the number that determines whether
   work can continue right now.
2. Show **token consumption** over a chosen period, broken down by model and
   project.
3. Stay visible over other windows without stealing focus.
4. Run identically on macOS and Windows with no per-OS code paths beyond what
   `pathlib` handles.
5. Require no API key, no network access, and no credential storage.

## 2. Non-goals

- **Organization or API-key billing.** The Admin API cost/usage reports
  (`/v1/organizations/cost_report`, `/v1/organizations/usage_report/messages`)
  cover Console API spend, a separate billing surface from a Claude subscription.
  Out of scope.
- **Claude.ai web/mobile usage.** Only Claude Code writes the local transcripts
  this tool reads.
- **Live quota fetching.** See [§4.2](#42-quota-source) — the tool reads a cache
  maintained by Claude Code and never authenticates.
- **Historical quota trend.** Only a current snapshot is available locally;
  quota percentages are not retained over time by any local file.

## 3. Constraints

| Constraint | Consequence |
|---|---|
| Quota is expressed **only as a percentage** — no token or dollar denominator | Token totals and quota % are independent metrics and can never be reconciled. They must be presented as separate panels. |
| Quota data is a **cache refreshed only when Claude Code runs** | Staleness must be displayed. A stale reading rendered as live is the tool's primary correctness risk. |
| Transcripts are **append-only but actively written** | Reader must tolerate partial trailing lines. |
| Cost is **not recorded** in transcripts | Must be computed from a local model→price table, which will drift from real pricing. |

---

## 4. Data sources

### 4.1 Token source — transcript JSONL

**Location:** `Path.home() / ".claude" / "projects"`
(`~/.claude/projects` on macOS, `%USERPROFILE%\.claude\projects` on Windows.)

**Layout:** one directory per project, named by replacing every `/` in the
project's absolute path with `-`. One `.jsonl` file per session, named by
session UUID. Discover with `rglob("*.jsonl")`.

> **Do not decode the directory name to recover the project path.** The
> transform is lossy — a literal hyphen in a folder name is indistinguishable
> from a path separator. Read the `cwd` field off any record instead; it is the
> true absolute path and is present on every line.

**Relevant record shape** — usage appears only on `type: "assistant"` lines:

```json
{
  "type": "assistant",
  "timestamp": "2026-08-05T14:56:50.000Z",
  "sessionId": "0445287c-…",
  "requestId": "req_…",
  "cwd": "/Users/joseph.hoppe/Documents/GitHub/claude-token-usage-dashboard",
  "gitBranch": "main",
  "isSidechain": false,
  "message": {
    "id": "msg_011Cdk7aAP2A8CJs9yyehs7f",
    "model": "claude-opus-5",
    "usage": {
      "input_tokens": 2,
      "output_tokens": 632,
      "cache_creation_input_tokens": 683,
      "cache_read_input_tokens": 387721,
      "cache_creation": {
        "ephemeral_1h_input_tokens": 683,
        "ephemeral_5m_input_tokens": 0
      },
      "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 },
      "service_tier": "standard",
      "speed": "standard",
      "iterations": [ { "type": "message", "…": "…" } ]
    }
  }
}
```

Other observed `type` values carry no usage and must be skipped:
`user`, `queue-operation`, `attachment`, `file-history-snapshot`,
`last-prompt`, `ai-title`.

### 4.2 Quota source — `cachedUsageUtilization`

**Location:** `Path.home() / ".claude.json"` — note this is the **sibling file**
to the `.claude/` directory, not inside it.

**Key:** `cachedUsageUtilization`

```json
{
  "fetchedAtMs": 1785955815544,
  "accountUuid": "…",
  "utilization": {
    "five_hour":  { "utilization": 3,  "resets_at": "…", "limit_dollars": null,
                    "used_dollars": null, "remaining_dollars": null },
    "seven_day":  { "utilization": 39, "resets_at": "…", "limit_dollars": null, "…": null },
    "limits": [
      { "kind": "session",       "group": "session", "percent": 3,
        "severity": "normal", "resets_at": "…", "scope": null, "is_active": false },
      { "kind": "weekly_all",    "group": "weekly",  "percent": 39,
        "severity": "normal", "resets_at": "…", "scope": null, "is_active": false },
      { "kind": "weekly_scoped", "group": "weekly",  "percent": 66,
        "severity": "normal", "resets_at": "…", "is_active": true,
        "scope": { "model": { "id": null, "display_name": "Fable" }, "surface": null } }
    ],
    "extra_usage": { "is_enabled": false, "…": null },
    "spend": { "used": { "amount_minor": 0, "currency": "USD", "exponent": 2 },
               "limit": null, "percent": 0, "enabled": false, "…": null }
  }
}
```

**Read `limits[]`, not the named keys.** Alongside `five_hour` and `seven_day`,
`utilization` carries a dozen null-valued siblings with internal codenames
(`tangelo`, `iguana_necktie`, `nimbus_quill`, `cinder_cove`, `amber_ladder`,
`seven_day_opus`, `seven_day_sonnet`, …). That set is a feature-flag surface and
will churn. `limits[]` exposes every active limit uniformly, so new limit kinds
arrive as new array entries rather than as parser breakage.

Supplementary read-only context from the same file:

- `oauthAccount.userRateLimitTier` — e.g. `default_claude_max_5x`
- `oauthAccount.seatTier` — e.g. `team_tier_1`
- `cachedGrowthBookFeatures.tengu_rate_limit_promo_notices` — active promos that
  temporarily inflate a limit's denominator, which makes percentages
  non-comparable across time. Display as a footnote when present.

---

## 5. Architecture

```
┌──────────────────────────────────────────────────────────┐
│ wx.Frame (STAY_ON_TOP)                                   │
│   QuotaPanel        TokenPanel        StatusBar          │
└──────────────────────────▲───────────────────────────────┘
                           │ wx.CallAfter(snapshot)
┌──────────────────────────┴───────────────────────────────┐
│ PollerThread (threading.Thread, daemon)                  │
│   every N seconds → Aggregator.refresh() → Snapshot      │
└───────────┬──────────────────────────────┬───────────────┘
            │                              │
   ┌────────▼─────────┐          ┌─────────▼──────────┐
   │ TranscriptReader │          │ QuotaReader        │
   │  incremental     │          │  whole-file read   │
   │  offset per file │          │  ~/.claude.json    │
   └────────┬─────────┘          └─────────┬──────────┘
            │                              │
     ┌──────▼───────┐              (no transform)
     │ PricingTable │
     └──────────────┘
```

This diagram is the wx driver. `claude_usage/ui/cli/` is a second, thinner
driver over the same `TranscriptReader`/`QuotaReader`/`PricingTable` stack — a
single synchronous pass instead of `PollerThread`, and quota-only today (no
token/cost panel yet in either driver). It is a permanent sibling, not scaffolding
for this one; see the note above and the CLI's own spec for its data-flow
diagram.

### 5.1 Threading

All file I/O and JSON parsing happens on `PollerThread`. Results cross to the
GUI thread **only** via `wx.CallAfter` with an immutable `Snapshot`. Parsing in
the GUI thread will visibly stall the window — the largest single transcript
observed is 1.44 MB and the full corpus is 114 MB.

### 5.2 Poll cadence

- Transcripts: default **5 s**. Cheap after the first pass (see §6.2).
- Quota: default **10 s**. The underlying cache updates far less often; polling
  faster only re-reads unchanged bytes.

Both configurable. The first full scan is the only expensive operation.

---

## 6. Core algorithms

### 6.1 Deduplication — required

The same assistant message appears in multiple `.jsonl` files when a session is
resumed, forked, or compacted. **Deduplicate on `message.id`** across the entire
corpus, not per file. Skipping this double-counts tokens; it is the single most
likely source of silently wrong totals.

`requestId` is a usable secondary key but is absent on some records;
`message.id` was present on every one of the 14,751 usage records observed.

### 6.2 Incremental tailing

Persist per-file state keyed by **absolute path**:

```python
@dataclass
class FileCursor:
    offset: int        # byte offset of the last complete line consumed
    size: int          # file size at that offset
    mtime: float
```

Each poll:

1. `stat()` the file. If `mtime` and `size` are unchanged, skip.
2. If `size < offset`, the file was truncated or replaced — reset the cursor to
   0 and re-read.
3. Open in binary, `seek(offset)`, read to EOF.
4. Split on `\n`. **Discard any trailing fragment not terminated by `\n`** and
   advance `offset` only past the last complete line. The active session's file
   is being appended to as it is read; parsing a half-written record raises
   `json.JSONDecodeError`.

Per-file cursors keyed by path are required rather than a single global
timestamp — two files were observed sharing an identical mtime to the second.

### 6.3 Model ID normalization — required

Observed strings across 290 files:

| Count | Model string |
|---:|---|
| 10,603 | `claude-fable-5` |
| 1,494 | `claude-sonnet-5` |
| 1,277 | `claude-haiku-4-5-20251001` |
| 856 | `claude-opus-5` |
| 514 | `claude-opus-4-8` |
| 7 | `<synthetic>` |

`~/.claude.json` additionally contains `claude-fable-5[1m]`.

The resolver must therefore:

1. **Skip `<synthetic>`** entirely — Claude Code's internal placeholder records
   (interruptions, injected errors). They carry no real cost and 7 of them have
   `service_tier: null`. Counting them inflates totals.
2. **Strip a `[…]` suffix** — `claude-fable-5[1m]` → `claude-fable-5`. The 1M
   context variant is priced the same on current models.
3. **Strip a trailing `-YYYYMMDD` date** — `claude-haiku-4-5-20251001` →
   `claude-haiku-4-5`.
4. **Fail loudly on an unknown model** — surface it in the UI as
   "unpriced: <id>" rather than silently pricing at zero. New models will appear.

### 6.4 Cost computation

Per USD/MTok, as of 2026-06-24. This table **will** go stale; treat it as
configuration, not code, and stamp it with a date shown in the UI.

| Model | Input | Output |
|---|---:|---:|
| `claude-fable-5`, `claude-mythos-5` | 10.00 | 50.00 |
| `claude-opus-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6` | 5.00 | 25.00 |
| `claude-sonnet-5` | 3.00 | 15.00 |
| `claude-sonnet-4-6` | 3.00 | 15.00 |
| `claude-haiku-4-5` | 1.00 | 5.00 |

Multipliers on the input rate:

| Token field | Multiplier |
|---|---:|
| `input_tokens` | 1.00 |
| `cache_read_input_tokens` | 0.10 |
| `cache_creation.ephemeral_5m_input_tokens` | 1.25 |
| `cache_creation.ephemeral_1h_input_tokens` | 2.00 |

Branch on the `cache_creation` sub-fields rather than using the flat
`cache_creation_input_tokens` total — 2.00× versus 1.25× is a material spread,
and the sessions observed were entirely 1h.

`server_tool_use.web_search_requests` is billed **per request, not per token**.
Track it as a separate line item; do not fold it into the token math.

**`iterations[]` must not be summed alongside the top-level fields.** It is a
per-attempt breakdown that re-states the same numbers (verified identical on
single-attempt turns). Use one or the other. It becomes informative only when a
turn had multiple attempts, e.g. entries with `type: "fallback_message"`.

### 6.5 Rolling windows

Bucket records by `timestamp` (ISO 8601, UTC) into: current 5-hour window,
current 7-day window, today, and all-time. Align the 5-hour and 7-day buckets to
the `resets_at` values from the quota cache so the token panel and quota panel
describe the same periods — otherwise the two panels invite a false comparison.

---

## 7. UI

### 7.1 Frame

- `wx.Frame` with `wx.STAY_ON_TOP` in the style. Verified to behave correctly on
  both platforms.
- Persist position and size across launches.
- Compact default (~320×220), resizable.
- No focus stealing on refresh.

### 7.2 Quota panel — primary

- One horizontal bar per entry in `limits[]`, in fixed kind order: `session`,
  then `weekly_all`, then `weekly_scoped` (unknown kinds after these, in input
  order).
- **The headline number is the worst bar**, which is the binding constraint —
  not the aggregate and not an average. In the observed snapshot the aggregate
  weekly read 39% while the Fable-scoped weekly read 66%; the latter is what
  would actually stop work.
- Label each bar `kind` + `scope.model.display_name` when scope is non-null.
- Show **used** (`percent`, clamped to 0–100).
- Show a countdown to `resets_at`.
- **Color from the `severity` field, not from local thresholds.** Deriving
  red/amber from hardcoded percentages will disagree with what Claude Code
  itself displays.
- Mark `is_active: true` visually.

### 7.3 Staleness indicator — required

Derive age from `fetchedAtMs` and display it always ("as of 7m ago"). Past a
threshold (default 15 min), grey the bars and label them stale. Claude Code
refreshes this cache only while making requests, so with Claude Code idle the
figures can be hours old while looking current. **This is the highest-risk
element in the UI and is not optional.**

### 7.4 Token panel — secondary

Tokens and computed cost for the selected window, broken down by model, with an
input/output/cache-read/cache-write split. Optional per-project breakdown keyed
on `cwd`. Include a toggle to fold in `isSidechain: true` records (subagent
usage — real spend, worth seeing separately).

---

## 8. Privacy and security

- Read-only. The tool never writes to `~/.claude/` or `~/.claude.json`.
- Never display or log `cachedUsageUtilization.accountUuid`.
- Transcripts contain full conversation text, file contents, and possibly
  secrets. Read only the fields this spec names; never render message content.
- No network calls, no credentials, nothing to leak.
- Per project convention, this spec file is not to be committed to git.

## 9. Testing

- Fixtures drawn from the real corpus (290 files, 14,751 usage records) — the
  only source of the edge cases that matter.
- Required cases: duplicate `message.id` across files; partial trailing line;
  file truncation mid-session; `<synthetic>` model; date-suffixed and
  `[1m]`-suffixed model IDs; unknown model; `scope: null` vs populated;
  a missing `cachedUsageUtilization` key; an absent `~/.claude.json`;
  `severity` values other than `normal`.
- Verify total-token math against an independent one-off script over the same
  corpus before trusting the aggregator.

## 10. Open questions

1. **Which metric is the headline?** This spec assumes remaining quota %
   (§7.2), with tokens/cost secondary. If the intent is cost tracking instead,
   §7 inverts — the collector layer is unaffected either way.
2. **Scope: all projects, or just the current one?** Assumed all-projects
   aggregate, with per-project as a drill-down.
3. **Is dollar cost wanted at all?** On a Max subscription it is notional — the
   real constraint is the quota windows. It may be more noise than signal.
4. Should the widget alert (notify/flash) on crossing a `severity` change?

---

## Appendix A — verified observations

Collected 2026-08-05 on macOS 25.5.0, `~/.claude` for a `default_claude_max_5x`
account, `seatTier: team_tier_1`.

| Fact | Value |
|---|---|
| Project directories | 29 |
| Transcript files | 290 |
| Corpus size | 114 MB |
| Largest single transcript | 1.44 MB |
| Usage-bearing records | 14,751 |
| `service_tier` values | `standard` (14,744), `null` (7 — all `<synthetic>`) |
| Quota snapshot | 5h 3% · weekly-all 39% · weekly-Fable 66% (`is_active`) |
| Quota cache age when read | ~7 minutes |
| `limit_dollars` / `used_dollars` / `remaining_dollars` | `null` on this tier |
| Credits / extra usage | disabled (`can_purchase_credits: false`) |
| Active promo | `+50% weekly limits promo through Aug 19` on the `seven_day` bar |

**Sampled file:** the session that produced this spec —
`~/.claude/projects/-Users-joseph-hoppe-Documents-GitHub-claude-token-usage-dashboard/0445287c-….jsonl`
— 65 lines, 25 usage-bearing (lines 13–16, 22, 23, 25, 27–29, 31, 33, 34, 37,
38, 44, 45, 47, 52, 53, 55, 56, 59, 64, 65), 8,988,111 tokens summed across all
four token fields.
