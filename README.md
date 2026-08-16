# claude-usage

Claude Code quota usage from the local `~/.claude.json` cache, as a
one-shot CLI or an always-on-top desktop window.

## Install

```bash
pip install -e .
```

This puts `claude-usage` (CLI) and `claude-usage-app` (desktop window) on
your `PATH`. You can also run either without installing, from the repo root:

```bash
python -m claude_usage.ui.cli.main
python -m claude_usage.ui.app.main
```

## Usage

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

## Desktop app

The same reading in a small always-on-top window, refreshed in the
background. From the repo root:

```bash
python -m claude_usage.ui.app.main
```

or, after `pip install -e .`, just `claude-usage-app`.

The window is resizable and grows to fit its content, but never shrinks
below a size you chose. It stays above other windows and never steals focus
when it refreshes — a refresh only repaints. Closing it stops the background
poller and exits.

The window includes a **Refresh** button below the quota display that invokes
`claude -p "/usage"` to refresh Claude Code's quota cache on demand. This is
useful when the window shows "No quota data cached yet". While the refresh runs,
the button displays "Refreshing…" and is disabled. If the refresh fails, hovering
the button shows a tooltip indicating the outcome (e.g., "Last refresh: not_found"
when the `claude` executable cannot be found; set `claude_executable` in
config.toml to specify its path).

The console encoding note above does not apply here: the window draws its
own text, so no `-X utf8` is needed.

### App flags

| Flag       | Effect                                               |
|------------|------------------------------------------------------|
| `--path`   | read an alternate `.claude.json` (fixtures, testing) |
| `--config` | read an alternate `config.toml` (fixtures, testing)  |

### Configuration

Optional, read once at startup from
`~/.config/claude-usage/config.toml` (on Windows,
`C:\Users\<you>\.config\claude-usage\config.toml`). No file means defaults,
silently. An unreadable or malformed file, or an out-of-range value, also
falls back to defaults but adds a warning line to the window rather than
failing.

| Key                       | Default | Range  | Effect                                    |
|---------------------------|---------|--------|-------------------------------------------|
| `poll_seconds`            | 10      | 1–600  | seconds between background refreshes      |
| `stale_after_minutes`     | 15      | 1–1440 | reading age at which the view marks STALE |
| `refresh_timeout_seconds` | 60      | 5–600  | timeout in seconds for the Refresh button's `claude -p "/usage"` subprocess |
| `claude_executable`       | absent  | string | explicit path to the `claude` executable for the Refresh button; if unset, resolved from `PATH` |

```toml
poll_seconds = 30
stale_after_minutes = 20
refresh_timeout_seconds = 60
# claude_executable = "/path/to/claude"
```

## Development

```bash
pip install -e .
pip install pytest
pytest
```
