"""Ports the application ring declares; infrastructure conforms structurally."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from claude_usage.domain.quota import QuotaReading, QuotaUnavailable


class QuotaSource(Protocol):
    def read_quota(self) -> QuotaReading | QuotaUnavailable: ...
    def read_error_detail(self) -> str | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
