"""Ports the application ring declares; infrastructure conforms structurally."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from claude_usage.domain.quota import QuotaReading


class QuotaSource(Protocol):
    def read_quota(self) -> QuotaReading | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
