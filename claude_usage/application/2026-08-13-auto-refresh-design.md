# Quota Auto-Refresh — Design Spec

**Status:** Approved, blocked on §3
**Date:** 2026-08-13
**Author:** Joseph Hoppe (drafted with Claude Code)
**Parent:** [`SPEC.md`](../../SPEC.md)
**Sibling specs:**
[`claude_usage/ui/app/2026-08-10-quota-app-design.md`](../ui/app/2026-08-10-quota-app-design.md) ·
[`claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md`](../ui/cli/2026-08-05-cli-quota-poc-design.md)

When no quota data is cached, both drivers currently dead-end on an error
message. This spec has them repair the condition themselves by invoking
`claude -p "/usage"`, which causes Claude Code to refresh its own cache.

---

## 1. Problem

`python -m claude_usage.ui.cli.main` prints:

```text
No quota data cached yet — run Claude Code once
```

The message is accurate about the state and wrong about the remedy.

`~/.claude.json` exists and parses; it simply has no `cachedUsageUtilization`
key, which is the `NO_QUOTA_KEY` branch of
[`claude_json.py`](../infrastructure/claude_json.py). Reading Claude Code
2.1.229's bundle establishes why:

- The key is written only by an internal `Nap()`, reached only from `FOn()`,
  which awaits a `fetchUtilization` call — `GET /api/oauth/usage`. It is not
  written passively during normal sessions.
- The sign-out path clears `cachedUsageUtilization` alongside `oauthAccount`,
  `modelAccessCache`, `orgModelDefaultCache`, `clientDataCacheSlots`, and
  `autoCompactWindowsCache`.

The observed file has every sibling from that clear-list repopulated with
timestamps from the same minute, and `cachedUsageUtilization` absent — the
signature of a sign-out followed by a fresh login. The siblings return
automatically at startup; this key does not, because nothing had called the
usage endpoint since.

So the advice "run Claude Code once" cannot work: the user runs it constantly.
Only a usage fetch repairs the state. `tests/fixtures/live_snapshot.json`,
captured 2026-08-05, contains the key, confirming it is normally present and
that this is a recoverable gap rather than a version change.

## 2. Scope

**In:** a `QuotaRefresher` port, a `ClaudeCliRefresher` adapter that runs
`claude -p "/usage"`, an arming rule in `UsageService`, two config keys, one
CLI flag, and the wiring in both composition roots.

**In, by entanglement:** the `NO_QUOTA_KEY` message text. After this change the
message appears only when auto-refresh was disabled or failed, so "run Claude
Code once" becomes actively misleading. See §10.

**Out:** any write to `~/.claude.json` by this project. The file stays
read-only to us; only Claude Code writes it. Retry loops, backoff schedules,
and refresh-on-stale are also out — this spec fires on absent data only, never
on data that merely looks old.

**Out:** a distinct "refreshing…" display state. During a refresh both drivers
keep showing the existing no-data message. Adding a transient state means a new
`QuotaView` variant and presenter changes in both drivers, which buys polish
this feature does not need. Revisit if the wait proves annoying in practice.

## 3. Blocking prerequisite — verify the mechanism

**Do not implement before this passes.** The entire design rests on one
unverified assumption.

The bundle contains two `/usage` command definitions:

| Variant | Shape |
|---|---|
| interactive | `type:"local-jsx"`, `requires:{ink:true}` |
| headless | `type:"local"`, `supportsNonInteractive:true` |

The headless variant dispatches a `get_usage` control request, which reaches
`UOn()` → `FOn()` → the fetch that writes the cache. That is why `-p` is the
chosen invocation. But it has been read, not observed.

Verification, run by hand once:

1. Confirm `cachedUsageUtilization` is absent from `~/.claude.json`.
2. Run `claude -p "/usage"`.
3. Confirm the key is now present, and note the wall-clock duration.

If the key appears, proceed. If it does not, the write happens only on the
interactive `ink` path; the architecture below is unaffected but the argv in
§7 must change, and a headless variant may not exist at all — in which case
abandon the feature rather than spawn an interactive terminal behind the user's
back.

Record the measured duration in the plan: it calibrates the default timeout in
§8, which is otherwise a guess.

**Cost note:** `claude -p` starts a session. Whether a local slash command
incurs token cost is unconfirmed. Check the duration and any session cost
during step 2, because this runs unattended.

## 4. Architecture

Onion per `AGENTS.md`; rings are extended, not restructured.

```text
ui/cli/main.py · ui/app/main.py        (composition roots — decide whether to inject)
             ↓
application/  usage.py (arming rule) · ports.py (QuotaRefresher, RefreshOutcome, Config)
             ↓
domain/       quota.py                 (unchanged by this spec)
             ↑
infrastructure/  claude_cli.py (new) · config.py · claude_json.py · clock.py
```

The refresher is a port because both drivers need identical behaviour. Two
placements were rejected:

- **Per-driver logic in each composition root** duplicates the arming state in
  two places, where it will drift.
- **Folding it into `ClaudeJsonQuotaSource`** hides a subprocess spawn inside a
  method named `read_quota`, and makes the adapter untestable without process
  mocks.

`domain/` is untouched. `RefreshOutcome` describes the result of a port call,
not a quota entity, so it belongs beside `Config` in `application/ports.py`.

## 5. Application — port contract

Added to `application/ports.py`:

```python
class RefreshOutcome(Enum):
    REFRESHED = "refreshed"    # process exited 0
    NOT_FOUND = "not_found"    # no claude executable resolved
    TIMED_OUT = "timed_out"    # exceeded refresh_timeout_seconds
    FAILED = "failed"          # non-zero exit, or the spawn itself failed


class QuotaRefresher(Protocol):
    def refresh(self) -> RefreshOutcome: ...
```

`refresh()` never raises. Every failure mode is a return value, because a
refresher that throws would take down the poller thread — the exact failure
[`poller.py`](../ui/app/poller.py) already guards against.

## 6. Application — the arming rule

`UsageService.__init__` gains `refresher: QuotaRefresher | None = None`.
`snapshot()` gains `allow_refresh: bool = True`. The service holds
`_refresh_armed: bool`, initially `True`.

A refresh fires when **all** hold:

- `read_quota()` returned `NO_FILE` or `NO_QUOTA_KEY`
- a refresher was injected
- `_refresh_armed` is `True`
- the caller passed `allow_refresh=True`

On firing: disarm, call `refresh()`, then re-read `read_quota()` **exactly
once**. If that yields a `QuotaReading`, return it as a normal snapshot.
Otherwise fall through to the existing unavailable path with
`detail` set to the `RefreshOutcome` value.

The re-read happens after **any** outcome, not only `REFRESHED`. A process that
exceeded the timeout may still have written the cache before it hung, and the
re-read costs one file read.

Re-arming happens on exactly one event: `read_quota()` returning a
`QuotaReading`. Not on a timer, not on a new snapshot call.

This single rule produces the right behaviour in both drivers:

| Driver | Consequence |
|---|---|
| CLI (short-lived process) | at most one spawn per invocation |
| app (long-lived, 10s poll) | one spawn per unavailable streak; re-armed only once real data returns |

A permanently broken state therefore costs exactly one subprocess per app run,
not one every ten seconds.

`READ_ERROR` never triggers a refresh, and its existing `_last_good` fallback
in [`usage.py`](usage.py) is unchanged. A corrupt or permission-denied file is
not something relaunching Claude Code repairs, and retrying would spawn a
process against a fault that will still be there.

### 6.1 `allow_refresh` exists for one caller

[`ui/app/main.py`](../ui/app/main.py) calls `poller.refresh_once()`
synchronously on the main thread before `MainLoop()`, so the window never
flashes empty. A refresh firing there would block the window from appearing for
the full timeout — the app would look hung on launch.

So the priming call passes `allow_refresh=False`, threaded through
`PollerThread.refresh_once(allow_refresh: bool = True)` to
`snapshot(allow_refresh=...)`. `PollerThread.run()` uses the default, and its
first iteration runs immediately, so the refresh still starts within moments of
launch — on the background thread, with the window already up.

## 7. Infrastructure — `ClaudeCliRefresher`

New file `infrastructure/claude_cli.py`:

```python
class ClaudeCliRefresher:
    def __init__(
        self,
        executable: str | None = None,
        timeout_seconds: int = 60,
        on_start: Callable[[], None] | None = None,
    ) -> None: ...

    def refresh(self) -> RefreshOutcome: ...
```

Resolution: the explicit `executable`, else `shutil.which("claude")`, else
`NOT_FOUND`.

`on_start` fires once, after the executable resolves and immediately before the
spawn. It exists because the decision to refresh is made inside `UsageService`,
so a caller cannot know in advance that a spawn is coming and cannot print a
notice ahead of it. The callback hands that moment back to whoever wired the
adapter up. It is not called when resolution fails, so a machine without
`claude` on `PATH` prints nothing. `refresh()` swallows any exception the
callback raises — a broken notice must not change the refresh outcome.

Invocation: `subprocess.run([exe, "-p", "/usage"], ...)` with

- `shell=False` — always an argv list, never a command string
- `stdin=subprocess.DEVNULL` — a Claude Code that decides to prompt (an expired
  login, a first-run consent) must hit EOF and exit rather than block until the
  timeout
- `capture_output=True` — the child's chatter must not interleave with the
  CLI's own stdout, which `--json` consumers parse
- `timeout=timeout_seconds`, `check=False`

Mapping: `TimeoutExpired` → `TIMED_OUT`; `OSError` → `FAILED`; exit 0 →
`REFRESHED`; any other exit → `FAILED`. Captured output is discarded, not
logged — it may contain account details, and `QuotaSnapshot.detail` is
documented as never carrying a payload.

**Windows:** `shutil.which("claude")` resolves via `PATHEXT` and on the
development machine finds an npm shim rather than a bare executable. The
adapter must work with whatever it resolves; §11 covers this with a real
spawn against a stub.

## 8. Configuration

`Config` (in `application/ports.py`) gains:

| Field | Default | Valid range |
|---|---|---|
| `auto_refresh: bool` | `True` | — |
| `refresh_timeout_seconds: int` | `60` | 5–600 |
| `claude_executable: str \| None` | `None` | non-empty string |

Same keys in `config.toml`, read by
[`infrastructure/config.py`](../infrastructure/config.py). `_read_int` already
covers the timeout; add `_read_bool` and `_read_str` following its established
contract — an invalid value appends a warning and returns the default, it never
raises. The `bool`-is-an-`int` guard in `_read_int` must not be copied into
`_read_bool`, where a `bool` is precisely what is wanted.

Set the `refresh_timeout_seconds` default from the duration measured in §3 if
60s proves badly calibrated.

## 9. Composition roots

Injection is the switch. When auto-refresh is off, the composition root passes
`refresher=None` and `UsageService` behaves exactly as it does today. This is
what keeps `sys`, `os`, and `subprocess` out of the application ring.

Both roots already read `Config` before building the service, so each
constructs the adapter with `executable=config.claude_executable` and
`timeout_seconds=config.refresh_timeout_seconds`. Neither adapter nor service
reads config itself.

**CLI** ([`ui/cli/main.py`](../ui/cli/main.py)) gains `--no-auto-refresh`. It
injects a refresher only when all hold:

- `--no-auto-refresh` was not passed
- `config.auto_refresh` is `True`
- `sys.stdout.isatty()`

The TTY condition is **CLI-only**. A piped or redirected caller is a script,
and a script must not spawn a Claude Code process as a side effect of asking
for JSON.

Because a refresh can take tens of seconds, the CLI passes an `on_start` (§7)
that prints a single line to **stderr** — `Refreshing quota via claude /usage…`
— so it does not appear hung. stderr keeps `--json` stdout clean. The app
passes no `on_start`; it has nowhere to print, and §2 rules out a transient
display state.

**App** ([`ui/app/main.py`](../ui/app/main.py)) injects a refresher when
`config.auto_refresh` is `True`. No TTY test: a GUI process has no controlling
terminal, so that rule would disable the feature outright in the driver that
benefits most.

The wx app gets no new flag. `--no-auto-refresh` on a long-running window is
better expressed in config, and both drivers already read the same file.

## 10. Message text

`_NO_DATA_MESSAGES[NO_QUOTA_KEY]` changes from

> `No quota data cached yet — run Claude Code once`

to

> `No quota data cached yet — open /usage in Claude Code`

Running Claude Code does not write the key; only a usage fetch does (§1). The
old wording sends the user to do something that cannot work.

Where `detail` carries a `RefreshOutcome`, both drivers append it
parenthetically, so a failed auto-refresh explains itself:
`No quota data cached yet — open /usage in Claude Code (not_found)`.

The string is duplicated in [`ui/cli/main.py`](../ui/cli/main.py) and
[`ui/app/presenter.py`](../ui/app/presenter.py) and asserted in
`tests/test_ui_cli_main.py` and `tests/test_ui_presenter.py`. All four change
together. The two sibling specs quote the old text; update those quotes so the
specs do not contradict the code.

## 11. Testing

**Application** — fake refresher plus a scripted `QuotaSource`; no filesystem,
no subprocess, no sleeping:

- fires once on `NO_QUOTA_KEY`, re-reads, returns the reading
- fires once on `NO_FILE`, same
- does **not** fire a second time while still unavailable
- re-arms after a `QuotaReading`, and fires again on a later gap
- never fires on `READ_ERROR`, and the `_last_good` fallback still works
- `allow_refresh=False` suppresses the spawn even when armed
- `refresher=None` reproduces today's behaviour exactly
- re-read happens after `TIMED_OUT` and `FAILED`, not only `REFRESHED`
- a non-`REFRESHED` outcome that stays unavailable lands in `detail`

**Infrastructure** — `ClaudeCliRefresher` against a **stub executable** written
to a temp dir, never the real `claude`:

- a stub exiting 0 → `REFRESHED`; non-zero → `FAILED`
- a sleeping stub with a short timeout → `TIMED_OUT`
- unresolvable executable → `NOT_FOUND`
- argv is exactly `[exe, "-p", "/usage"]`
- a stub reading stdin sees EOF rather than blocking
- `on_start` fires exactly once before the spawn, and not at all on `NOT_FOUND`
- an `on_start` that raises does not change the returned outcome

**Architecture** — `tests/test_architecture.py` adds `subprocess` and `shutil`
to the banned set for `domain` and `application`, so a future edit that reaches
for a process from an inner ring fails in review.

Two standing constraints, both absolute:

- **Tests never invoke the real `claude`.** Every process test uses a stub.
- **Tests never read or write the real `~/.claude.json`.** Fixtures and temp
  paths only, via the existing `--path` seam.

## 12. Risks

| Risk | Handling |
|---|---|
| `claude -p "/usage"` may not write the key | §3 blocks implementation on verifying it |
| A `-p` session may cost tokens | Measured in §3 before anything ships |
| Refresh blocks the caller for the timeout | CLI warns on stderr; app refreshes off the GUI thread and never on the priming call (§6.1) |
| A child prompting for input hangs the spawn | `stdin=DEVNULL` plus the timeout |
| Spawn storm from a long-running app | Armed once per unavailable streak; re-armed only by real data (§6) |
| Scripts spawning processes unexpectedly | TTY suppression on the CLI (§9) |
| Recursion — the app launched from inside Claude Code spawning Claude Code | Benign: the child is a separate short-lived process that exits on its own. Not guarded. |
