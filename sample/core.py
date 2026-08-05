"""Inner rings of the onion: domain model + application service.

Nothing here may import ``wx``, read a file, or know that transcripts are
JSONL. This module depends only on the Protocols declared below, which the
outer ring implements and injects. Every import is stdlib.

    shell.py  ──imports──▶  core.py  ──imports──▶  (stdlib only)

That one-way arrow *is* the architecture, and it stays honest because it is
greppable::

    grep -nE '^(from|import) (wx|json|pathlib)' core.py   # prints nothing

Ring by ring, outermost first:

    shell.py  Presentation    DashboardFrame, SnapshotPoller
    shell.py  Infrastructure  JsonlUsageSource, ClaudeJsonQuotaSource
    core.py   Application     DashboardService
    core.py   Domain          UsageRecord, QuotaReading, PricingTable
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Protocol

# ---------------------------------------------------------------------------
# Domain — entities, value objects, and the rules that govern them.
# ---------------------------------------------------------------------------

#: Claude Code's placeholder for interruptions and injected errors. Carries
#: no real cost; counting it inflates totals (SPEC.md §6.3).
SYNTHETIC_MODEL = "<synthetic>"

#: A quota reading older than this cannot be rendered as live. A stale
#: reading shown as current is the tool's primary correctness risk
#: (SPEC.md §3), so staleness is a domain concept, not a UI afterthought.
STALE_AFTER = timedelta(minutes=15)

_DATE_SUFFIX = re.compile(r"-\d{8}$")

# Multipliers applied to a model's *input* rate, by token field (§6.4).
_CACHE_READ = 0.10
_CACHE_WRITE_5M = 1.25
_CACHE_WRITE_1H = 2.00


def normalize_model_id(raw: str) -> str | None:
    """Collapse an observed model string to a priceable identifier.

    Returns ``None`` for records that must not be counted at all.

    >>> normalize_model_id("claude-haiku-4-5-20251001")
    'claude-haiku-4-5'
    >>> normalize_model_id("claude-fable-5[1m]")
    'claude-fable-5'
    >>> normalize_model_id("<synthetic>") is None
    True
    """
    if raw == SYNTHETIC_MODEL:
        return None
    without_variant = raw.split("[", 1)[0]
    return _DATE_SUFFIX.sub("", without_variant)


@dataclass(frozen=True)
class UsageRecord:
    """One assistant turn's usage, already parsed out of its transport.

    ``message_id`` is the deduplication key: the same turn reappears in
    several transcript files when a session is resumed, forked, or
    compacted (SPEC.md §6.1).
    """

    message_id: str
    model: str
    timestamp: datetime
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_5m_tokens
            + self.cache_creation_1h_tokens
        )


@dataclass(frozen=True)
class ModelRate:
    """USD per million tokens for one model."""

    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class PricingTable:
    """Rates are configuration; the arithmetic over them is domain logic.

    The shell supplies ``rates`` and ``as_of`` from somewhere it can edit
    without touching code. This class owns only the multiplier rules,
    which are stable.
    """

    rates: Mapping[str, ModelRate]
    as_of: str

    def cost_of(self, record: UsageRecord) -> float | None:
        """Cost in USD, or ``None`` if the model is unpriced.

        Never silently prices an unknown model at zero — new models
        appear, and a zero would read as "free" rather than "unknown"
        (SPEC.md §6.3).
        """
        rate = self.rates.get(record.model)
        if rate is None:
            return None
        billable_input = (
            record.input_tokens
            + record.cache_read_tokens * _CACHE_READ
            + record.cache_creation_5m_tokens * _CACHE_WRITE_5M
            + record.cache_creation_1h_tokens * _CACHE_WRITE_1H
        )
        return (
            billable_input * rate.input_per_mtok
            + record.output_tokens * rate.output_per_mtok
        ) / 1_000_000


@dataclass(frozen=True)
class LimitReading:
    """One entry from the quota cache's ``limits[]`` array."""

    kind: str
    percent: int
    severity: str
    is_active: bool
    scope_label: str | None = None

    @property
    def label(self) -> str:
        if self.scope_label:
            return f"{self.kind} ({self.scope_label})"
        return self.kind


@dataclass(frozen=True)
class QuotaReading:
    """A point-in-time snapshot of subscription utilization.

    Percentages only — there is no token or dollar denominator, so quota
    and token totals are independent metrics that can never be reconciled
    (SPEC.md §3).
    """

    measured_at: datetime
    limits: tuple[LimitReading, ...]

    def age(self, now: datetime) -> timedelta:
        return now - self.measured_at

    def is_stale(
        self, now: datetime, threshold: timedelta = STALE_AFTER
    ) -> bool:
        return self.age(now) >= threshold

    def worst(self) -> LimitReading | None:
        """The limit closest to exhaustion — the number that decides
        whether work can continue right now (SPEC.md §1)."""
        return max(self.limits, key=lambda item: item.percent, default=None)


@dataclass(frozen=True)
class ModelTotal:
    """Aggregated usage for one normalized model."""

    model: str
    tokens: int
    cost_usd: float | None

    @property
    def is_priced(self) -> bool:
        return self.cost_usd is not None


@dataclass(frozen=True)
class Snapshot:
    """The single immutable value the GUI renders.

    Frozen on purpose: it crosses a thread boundary in the outer ring,
    and an immutable payload makes that crossing safe by construction.
    """

    captured_at: datetime
    quota: QuotaReading | None
    quota_is_stale: bool
    model_totals: tuple[ModelTotal, ...]
    records_counted: int
    duplicates_skipped: int

    @property
    def total_tokens(self) -> int:
        return sum(total.tokens for total in self.model_totals)

    @property
    def total_cost_usd(self) -> float:
        return sum(total.cost_usd or 0.0 for total in self.model_totals)

    @property
    def unpriced_models(self) -> tuple[str, ...]:
        return tuple(t.model for t in self.model_totals if not t.is_priced)


# ---------------------------------------------------------------------------
# Ports — abstractions the application ring owns, the outer ring satisfies.
#
# They live here, beside their consumer, rather than beside their
# implementations. That is what inverts the dependency: the concrete JSONL
# reader in shell.py conforms to a shape core.py declared, so core.py never
# has to name it.
# ---------------------------------------------------------------------------


class UsageSource(Protocol):
    def read_usage(self) -> Iterable[UsageRecord]: ...


class QuotaSource(Protocol):
    def read_quota(self) -> QuotaReading | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


# ---------------------------------------------------------------------------
# Application — one use case, composed from ports and domain rules only.
# ---------------------------------------------------------------------------


class DashboardService:
    """Builds a :class:`Snapshot`. The only use case this sample has.

    Pure orchestration: no I/O, no widgets, no threads. Testable with
    three hand-written fakes and zero fixtures — which is the payoff for
    the import discipline at the top of this file.
    """

    def __init__(
        self,
        usage_source: UsageSource,
        quota_source: QuotaSource,
        pricing: PricingTable,
        clock: Clock,
    ) -> None:
        self._usage_source = usage_source
        self._quota_source = quota_source
        self._pricing = pricing
        self._clock = clock

    def snapshot(self) -> Snapshot:
        now = self._clock.now()
        totals, counted, duplicates = self._aggregate(
            self._usage_source.read_usage()
        )
        quota = self._quota_source.read_quota()
        return Snapshot(
            captured_at=now,
            quota=quota,
            quota_is_stale=quota.is_stale(now) if quota else True,
            model_totals=totals,
            records_counted=counted,
            duplicates_skipped=duplicates,
        )

    def _aggregate(
        self, records: Iterable[UsageRecord]
    ) -> tuple[tuple[ModelTotal, ...], int, int]:
        seen: set[str] = set()
        tokens: dict[str, int] = defaultdict(int)
        cost: dict[str, float | None] = {}
        counted = duplicates = 0

        for record in records:
            if record.message_id in seen:
                duplicates += 1
                continue
            seen.add(record.message_id)

            model = normalize_model_id(record.model)
            if model is None:  # synthetic placeholder — not real usage
                continue

            counted += 1
            tokens[model] += record.total_tokens

            priced = self._pricing.cost_of(replace(record, model=model))
            if priced is None:
                cost[model] = None  # unpriced wins; never degrade to 0.0
            elif cost.get(model, 0.0) is not None:
                cost[model] = (cost.get(model) or 0.0) + priced

        totals = tuple(
            sorted(
                (
                    ModelTotal(model, count, cost.get(model))
                    for model, count in tokens.items()
                ),
                key=lambda total: total.tokens,
                reverse=True,
            )
        )
        return totals, counted, duplicates
