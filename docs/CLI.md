# CLI

A one-shot terminal view of the same reading the desktop window shows:
Claude Code quota usage from the local `~/.claude.json` cache.

After `pip install -e .` the CLI is on your `PATH` as `claude-usage`. You can
also run it without installing, from the repo root:

```bash
python -m claude_usage.ui.cli.main
```

## Usage

```console
> python -m claude_usage.ui.cli.main
USAGE                                as of 18m ago · STALE

  Session (5hr)                   3%  ░░░░░░░░░░░░░░░  resets in 3h
  Weekly (7 day)      ● active    9%  █░░░░░░░░░░░░░░  resets in 6h

  +50% weekly limits promo through Aug 19 · clau.de/cc-50-promo
```

## Flags

| Flag         | Effect                                                     |
|--------------|------------------------------------------------------------|
| `--json`     | emit the snapshot as JSON instead of the bar view          |
| `--no-color` | suppress ANSI colour                                       |
| `--ascii`    | ASCII bar glyphs (`#`/`-`) instead of unicode block glyphs |
| `--path`     | read an alternate `.claude.json` (fixtures, testing)       |

## Windows: UnicodeEncodeError

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
