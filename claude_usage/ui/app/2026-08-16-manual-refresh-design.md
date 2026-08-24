# Quota Manual Refresh — Design Spec

**Status:** Approved, blocked on §3
**Date:** 2026-08-16 (rev 2 — replaces the 2026-08-13 auto-refresh revision,
formerly at `claude_usage/application/2026-08-13-auto-refresh-design.md`)
**Author:** Joseph Hoppe (drafted with Claude Code)
**Parent:** [`SPEC.md`](../../../SPEC.md)
**Sibling specs:**
[`claude_usage/ui/app/2026-08-10-quota-app-design.md`](2026-08-10-quota-app-design.md) ·
[`claude_usage/ui/cli/2026-08-05-cli-quota-poc-design.md`](../cli/2026-08-05-cli-quota-poc-design.md)

When no quota data is cached, both drivers currently dead-end on an error
message. This spec adds a **Refresh** button to the wx app that invokes
`claude -p "/usage"`, which causes Claude Code to refresh its own cache, and
corrects the misleading message in both drivers. Nothing spawns automatically:
the subprocess runs on button click, and only on button click. Rev 1 fired the
refresh automatically from an arming rule inside `UsageService`; that entire
mechanism is gone.

---

## 1. Problem

`python -m claude_usage.ui.cli.main` prints:

```text
No quota data cached yet — run Claude Code once
```

The message is accurate about the state and wrong about the remedy.

`~/.claude.json` exists and parses; it simply has no `cachedUsageUtilization`
key, which is the `NO_QUOTA_KEY` branch of
[`claude_json.py`](../../infrastructure/claude_json.py). Reading Claude Code
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

**In:** a `ClaudeCliRefresher` adapter (with its `RefreshOutcome` enum and
`QuotaRefresher` protocol) in `infrastructure/`, a **Refresh** button and a
small worker helper in the wx app, two config keys, and the message text.

**In, by entanglement:** the `NO_QUOTA_KEY` message text. "Run Claude Code
once" is actively misleading (§1), button or no button. See §9.

**Out:** any automatic refresh. No arming rule, no refresh on startup, no
refresh when the poller finds missing data, no refresh on staleness, no
retries. The user clicks, or nothing spawns.

**Out:** any spawn from the CLI. The CLI's only change is the corrected
message. A script piping `--json` must never trigger a subprocess, and with no
automatic path left there is nothing to gate — the CLI simply has no refresher.

**Out:** any write to `~/.claude.json` by this project. The file stays
read-only to us; only Claude Code writes it.

**Out:** any in-progress display state beyond the button itself. While a
refresh runs, the button is disabled and reads "Refreshing…"; `QuotaPanel`,
the presenter, and `QuotaView` are untouched. That disabled button is the
entire in-progress UI.

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
§5 must change, and a headless variant may not exist at all — in which case
abandon the feature rather than spawn an interactive terminal behind the
button.

Record the measured duration in the plan: it calibrates the default timeout in
§7, which is otherwise a guess.

**Cost note:** `claude -p` starts a session. Whether a local slash command
incurs token cost is unconfirmed. Check the duration and any session cost
during step 2. Unlike rev 1, this never runs unattended — it spends only when
the user clicks — but the user still deserves to know what a click costs.

## 4. Architecture

Onion per `AGENTS.md`. The `domain/` and `application/` rings are behaviorally
untouched; the feature lives entirely in `infrastructure/` and `ui/app/`.

```text
ui/app/main.py        (composition root — builds the adapter, wires the button)
      ↓
ui/app/frame.py (button) · ui/app/refresh.py (worker, new)
      ↓
infrastructure/  claude_cli.py (new: RefreshOutcome, QuotaRefresher,
                 ClaudeCliRefresher) · config.py
      ↓
application/     ports.py (Config gains two passive fields — data, no behavior)
```

Rev 1 routed the refresh through `UsageService` behind a `QuotaRefresher` port
in `application/ports.py`, because the service was the only place that knew
data was missing and the arming rule needed a single home shared by both
drivers. A manual trigger dissolves both reasons: the user decides when to
refresh, and only one driver has a button. Two placements were rejected:

- **Keeping the port in `application/ports.py`** leaves a port no inner ring
  calls — dead weight that implies the service participates when it does not.
  Ports belong to their consumer; the consumer is now the UI ring, which may
  import `infrastructure/` directly (outer ring importing inward), so the
  protocol moves next to its one adapter.
- **Spawning directly in the wx event handler** blocks the GUI thread for up
  to the timeout — the window would freeze for tens of seconds per click.
  Hence the worker helper in §6.

The only `application/` edit is two new fields on the `Config` dataclass (§7),
which is a frozen data carrier, not behavior. `UsageService` and `domain/` are
untouched.

## 5. Infrastructure — `ClaudeCliRefresher`

New file `infrastructure/claude_cli.py`, holding all three names:

```python
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
    ) -> None: ...

    def refresh(self) -> RefreshOutcome: ...
```

Rev 1's `on_start` callback is deleted. It existed because the service decided
to spawn and the caller needed a hook to announce it; now the user is the one
who started it, and the button's own state change is the announcement.

Resolution: the explicit `executable`, else `shutil.which("claude")`, else
`NOT_FOUND`.

`refresh()` never raises. Every failure mode is a return value, because it
runs on the worker thread (§6), where an escaping exception would die silently
and leave the button stuck on "Refreshing…".

Invocation: `subprocess.run([exe, "-p", "/usage"], ...)` with

- `shell=False` — always an argv list, never a command string
- `stdin=subprocess.DEVNULL` — a Claude Code that decides to prompt (an expired
  login, a first-run consent) must hit EOF and exit rather than block until the
  timeout
- `capture_output=True` — the child's chatter must not reach the app's
  stdout/stderr
- `creationflags=NO_CONSOLE_WINDOW` — `subprocess.CREATE_NO_WINDOW` on
  Windows, `0` elsewhere (the constant is Windows-only)
- `timeout=timeout_seconds`, `check=False`

Mapping: `TimeoutExpired` → `TIMED_OUT`; `OSError` → `FAILED`; exit 0 →
`REFRESHED`; any other exit → `FAILED`. Captured output is discarded, not
logged — it may contain account details.

**Windows:** `shutil.which("claude")` resolves via `PATHEXT` and on the
development machine finds an npm shim rather than a bare executable. The
adapter must work with whatever it resolves; §10 covers this with a real
spawn against a stub.

That shim is also why the spawn needs `CREATE_NO_WINDOW`. `claude.cmd` runs
`cmd.exe` and then `node.exe`, both console-subsystem programs, and Windows
hands such a child its own new console window whenever the parent has none —
which is the normal case here, since the app is launched with `pythonw`.
Redirecting the child's handles does not prevent it: `capture_output` sets the
handles the child is given, while console allocation is decided by the
creation flags, so only a flag can suppress the window. The flag leaves the
child a console, just no window for it, so nothing about the child's own
behaviour changes.

Testing this needs care: the spawn must come from a console-less parent or
there is nothing to observe. Under pytest the parent is attached to a console
(often a ConPTY, whose `GetConsoleWindow` is `0` despite a console being
present), the child inherits it, and no window is created either way. §10's
test therefore re-spawns itself with `DETACHED_PROCESS` to reproduce the real
condition, then asserts the stub child's `GetConsoleWindow()` is `0`.

## 6. UI — the Refresh button and worker

**Button.** [`frame.py`](frame.py) gains a `wx.Button` labeled "Refresh",
placed below `QuotaPanel`. It is always visible and always enabled, except
while a refresh is running — it serves both to repair missing data and to
force-refresh data that merely exists. `QuotaFrame.__init__` gains an
`on_refresh: Callable[[], None] | None = None` parameter; `None` (the default)
means no button is created, which keeps existing tests and any
refresher-less composition working unchanged.

`_fit_to_content` must include the button row's height in the minimum client
size it computes, or the button clips — the current computation asks only
`QuotaPanel.content_height(view)`.

**Click flow.** On the GUI thread: disable the button, set its label to
"Refreshing…", start the worker. On the worker thread: `refresher.refresh()`,
then `poller.refresh_once()` for an immediate re-read (the same guarded call
[`poller.py`](poller.py) already uses, so a raising snapshot cannot kill the
thread). Then marshal back via `wx.CallAfter`: show the new view, restore the
button label, re-enable the button, and set the outcome tooltip.

**Outcome display.** A non-`REFRESHED` outcome becomes the button's tooltip —
e.g. "Last refresh: not_found" — so a machine without `claude` on `PATH` does
not fail silently. A `REFRESHED` outcome clears the tooltip. Nothing else in
the window reports the outcome; the refreshed (or still-missing) data speaks
for itself.

**Worker.** New file `ui/app/refresh.py`, mirroring `poller.py`'s structure
(a `threading.Thread` subclass is unnecessary — each click gets a one-shot
daemon thread):

```python
class RefreshWorker:
    def __init__(
        self,
        refresher: QuotaRefresher,
        read_view: Callable[[], QuotaView],          # poller.refresh_once
        deliver: Callable[[QuotaView, RefreshOutcome], None],
        call_after: Callable[..., Any] = wx.CallAfter,
    ) -> None: ...

    def start(self) -> bool: ...   # False and no-op if already running
```

`start()` refusing reentry is a belt on top of the disabled button's braces:
the button state is GUI-thread-owned and is the primary guard, but a
programmatic double-fire must not produce two child processes. `call_after`
is injectable so tests can run delivery synchronously without wx.

## 7. Configuration

`Config` (in [`ports.py`](../../application/ports.py)) gains:

| Field | Default | Valid range |
|---|---|---|
| `refresh_timeout_seconds: int` | `60` | 5–600 |
| `claude_executable: str \| None` | `None` | non-empty string |

Same keys in `config.toml`, read by
[`infrastructure/config.py`](../../infrastructure/config.py). `_read_int`
already covers the timeout; add `_read_str` following its established
contract — an invalid value appends a warning and returns the default, it
never raises.

Rev 1's `auto_refresh: bool` is dropped, not carried. It existed to switch off
refreshes that fired unbidden; a button the user must click is its own switch.

Set the `refresh_timeout_seconds` default from the duration measured in §3 if
60s proves badly calibrated.

## 8. Composition root

Only the app root changes. [`ui/app/main.py`](main.py) constructs
`ClaudeCliRefresher(executable=config.claude_executable,
timeout_seconds=config.refresh_timeout_seconds)`, builds the `RefreshWorker`
around it and the existing poller, and passes the frame an `on_refresh`
callback that drives the click flow in §6. The button is always wired — no
config switch, no flag.

The CLI root ([`ui/cli/main.py`](../cli/main.py)) wires nothing: no flag, no
TTY rule, no refresher import. Its only change is §9's message text.

## 9. Message text

The two drivers' `NO_QUOTA_KEY` messages, currently identical, now diverge
deliberately — each names the remedy its own driver offers:

| Driver | New text |
|---|---|
| CLI ([`ui/cli/main.py`](../cli/main.py)) | `No quota data cached yet — open /usage in Claude Code` |
| app ([`presenter.py`](presenter.py)) | `No quota data cached yet — click Refresh` |

Running Claude Code does not write the key; only a usage fetch does (§1). The
old wording sends the user to do something that cannot work.

Rev 1 appended a failed refresh's `RefreshOutcome` to this message via
`QuotaSnapshot.detail`. That is gone: the service no longer knows refreshes
exist, and the outcome surfaces in the button tooltip instead (§6).

The strings are asserted in `tests/test_ui_cli_main.py` and
`tests/test_ui_presenter.py`; each driver's string and its test change
together. The two sibling specs quote the old text; update those quotes so
the specs do not contradict the code.

## 10. Testing

**Infrastructure** — `ClaudeCliRefresher` against a **stub executable** written
to a temp dir, never the real `claude`:

- a stub exiting 0 → `REFRESHED`; non-zero → `FAILED`
- a sleeping stub with a short timeout → `TIMED_OUT`
- unresolvable executable → `NOT_FOUND`
- argv is exactly `[exe, "-p", "/usage"]`
- a stub reading stdin sees EOF rather than blocking

**UI** — `RefreshWorker` with fakes: a scripted refresher, a canned
`read_view`, a recording `deliver`, and a synchronous `call_after`; no wx, no
subprocess, no sleeping:

- calls the refresher, then `read_view`, and delivers both results
- delivers through `call_after`, never directly from the worker thread
- delivers non-`REFRESHED` outcomes verbatim (the tooltip depends on it)
- `start()` returns `False` and spawns nothing while a run is in flight
- `start()` works again after a run completes

Presenter tests cover the new app message; CLI tests cover the new CLI
message. The frame's button wiring is thin glue over these tested parts.

**Architecture** — `tests/test_architecture.py` adds `subprocess` and `shutil`
to the banned set for `domain` and `application`, so a future edit that
reaches for a process from an inner ring fails in review.

Two standing constraints, both absolute:

- **Tests never invoke the real `claude`.** Every process test uses a stub.
- **Tests never read or write the real `~/.claude.json`.** Fixtures and temp
  paths only, via the existing `--path` seam.

## 11. Risks

| Risk | Handling |
|---|---|
| `claude -p "/usage"` may not write the key | §3 blocks implementation on verifying it |
| A `-p` session may cost tokens | Measured in §3; spends only on an explicit click, never unattended |
| Refresh takes tens of seconds | Runs on a worker thread; the GUI never blocks, and the disabled "Refreshing…" button shows why |
| A child prompting for input hangs the spawn | `stdin=DEVNULL` plus the timeout |
| Double-click → double spawn | Button disabled while running; `RefreshWorker.start()` refuses reentry |
| Recursion — the app launched from inside Claude Code spawning Claude Code | Benign: the child is a separate short-lived process that exits on its own. Not guarded. |

Rev 1's spawn-storm, script-side-effect, and TTY risks are gone, not
mitigated — they cannot occur without an automatic trigger.
