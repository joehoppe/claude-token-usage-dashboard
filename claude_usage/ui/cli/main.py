"""Composition root: argparse -> adapters -> UsageService -> render -> print."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from claude_usage.application.usage import UsageService
from claude_usage.domain.quota import QuotaSnapshot, QuotaUnavailable
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


if __name__ == "__main__":
    raise SystemExit(main())
