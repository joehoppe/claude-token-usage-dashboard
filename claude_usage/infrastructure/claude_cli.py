"""Adapter spawning `claude -p "/usage"`, which makes Claude Code refresh its
own quota cache. This project never writes ~/.claude.json — only the child
does. Captured child output is discarded, never logged: it may contain
account details.
"""
from __future__ import annotations

import shutil
import subprocess
from enum import Enum
from typing import Protocol


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
    ) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def refresh(self) -> RefreshOutcome:
        """Never raises: this runs on the refresh worker thread, where an
        escaping exception would die silently and wedge the button on
        "Refreshing…" — every failure mode is a return value.
        """
        exe = self._executable or shutil.which("claude")
        if exe is None:
            return RefreshOutcome.NOT_FOUND
        try:
            completed = subprocess.run(
                [exe, "-p", "/usage"],
                shell=False,
                stdin=subprocess.DEVNULL,  # a child that prompts must hit EOF
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RefreshOutcome.TIMED_OUT
        except OSError:
            return RefreshOutcome.FAILED
        if completed.returncode == 0:
            return RefreshOutcome.REFRESHED
        return RefreshOutcome.FAILED
