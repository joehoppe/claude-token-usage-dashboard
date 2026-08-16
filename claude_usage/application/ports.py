"""Ports the application ring declares; infrastructure conforms structurally."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from claude_usage.domain.quota import STALE_AFTER, QuotaReading, QuotaUnavailable


class QuotaSource(Protocol):
    def read_quota(self) -> QuotaReading | QuotaUnavailable: ...
    def read_error_detail(self) -> str | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class Config:
    poll_seconds: int = 10
    stale_after: timedelta = STALE_AFTER
    refresh_timeout_seconds: int = 60
    claude_executable: str | None = None
    warnings: tuple[str, ...] = ()


class ConfigSource(Protocol):
    def read_config(self) -> Config: ...
