"""Geo/Address API data contracts (`v3-deepdive-16-geo-address-api.md` §2, §3, §6).

Types only, no logic beyond pure accessors (`docs/PRINCIPLES.md` §1.1) — this is the single
module other packages import from. Nothing outside `core/geo_address/` should ever need to
import `providers`, `corroboration`, `cache`, or `service` directly.

Every type here is `@dataclass(frozen=True)` and every dict-typed field is a `FrozenDict`
(§2.1): a frozen dataclass holding a plain `dict` is only shallowly immutable, and a
`ProviderCandidateResult.raw` payload is handed across threads (the `asyncio.gather` fan-out
in `corroboration.py`, §5) and potentially across the gRPC boundary via `cache.py`'s stored
JSON round-trip. `KNOWN_PROVIDERS` is a module-level lookup table and is therefore `FrozenDict`
too — `docs/PRINCIPLES.md` §2.1.1.

**`isinstance` against any of these must test `collections.abc.Mapping`, never `dict`.** The
Python 3.15 builtin `frozendict` is not a `dict` subclass, so `isinstance(x, dict)` silently
returns False and the wrong branch is taken.

Errors are data here, never raised across the boundary (§4.1): `GeoResult.error` and
`ok` follow the identical shape Architect's own `ArchitectError`/result contracts already use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from common.frozen_dict import FrozenDict

#: The registered provider identifiers this build ships an adapter for, with a short note on
#: each one's own coverage — read by `service.py`'s default registry wiring and by tests that
#: want a real name rather than a magic string. `FrozenDict` per §2.1.1: a module-level
#: constant lookup table nothing should ever write.
KNOWN_PROVIDERS: FrozenDict = FrozenDict(
    {
        "locationiq": "OSM-derived, worldwide coverage, free tier (§3)",
        "mapbox": "independent worldwide dataset, free tier (§3)",
        "nominatim_self_hosted": "unlimited-throughput, PH-only OSM extract (§3)",
    }
)


class AgreementLevel(str, Enum):
    """How strongly the corroboration set agreed on one candidate string's own answer.

    Resolved open question (deep-dive §9): this reuses OCR API's own tiered
    deterministic-then-escalate shape (`v3-deepdive-01-ocr-api.md` §7.3) rather than a second,
    independently-invented voting scheme — confirmed as the right fit here too, not merely
    assumed. `SPLIT` is deliberately not "an error": a genuine disagreement is real information
    (`docs/PRINCIPLES.md` §4.3), surfaced rather than silently resolved by picking one answer.
    """

    UNANIMOUS = "unanimous"
    MAJORITY = "majority"
    SPLIT = "split"
    SINGLE_SOURCE = "single_source"
    NONE = "none"


#: Selection priority when choosing which OCR candidate string's own answer to report — the
#: second, distinct corroboration axis file 01 and this API's own §3 both call out. Higher is
#: preferred; ties broken by confidence, then by the candidate's own OCR rank (`corroboration.
#: py`). `FrozenDict` per §2.1.1.
AGREEMENT_RANK: FrozenDict = FrozenDict(
    {
        AgreementLevel.UNANIMOUS: 4,
        AgreementLevel.MAJORITY: 3,
        AgreementLevel.SINGLE_SOURCE: 2,
        AgreementLevel.SPLIT: 1,
        AgreementLevel.NONE: 0,
    }
)


@dataclass(frozen=True)
class GeoError:
    """An error as data. `code` is stable and machine-readable; `detail` is for humans
    (`docs/PRINCIPLES.md` §4.1) — the same shape Architect's `ArchitectError` already uses."""

    code: str
    detail: str = ""


@dataclass(frozen=True)
class GeoAddress:
    """A normalized address, shaped for this project's actual domain: Philippine receipts
    (root `CLAUDE.md` — "Philippine BIR-relevant exports"). `barangay`/`city`/`province`/
    `region` are the real PH administrative tiers a receipt's address maps onto, not a generic
    "state"/"county" pair borrowed from a US-shaped schema — every provider adapter maps its
    own raw response onto *these* fields rather than each inventing its own naming.

    `country_code` defaults to `"PH"` because that is this project's whole addressing domain;
    a non-PH result is a real, expected case (a vendor with a foreign-registered address, or a
    provider genuinely covering somewhere else) and is represented faithfully, never coerced.
    """

    formatted: str
    line1: str = ""
    barangay: str = ""
    city: str = ""
    province: str = ""
    region: str = ""
    postal_code: str = ""
    country_code: str = "PH"
    latitude: float | None = None
    longitude: float | None = None

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass(frozen=True)
class ProviderCandidateResult:
    """One provider's answer for one OCR candidate string — the raw material corroboration
    reduces (§3). `error` is set instead of `address` on a failed call; `corroboration.py`
    is the one place that turns a raised provider exception into this shape (§4.1, §4.4) —
    provider adapters themselves just raise.

    `matched_business_name` is the reverse-check half of this API's own two-capability scope
    (deep-dive §1): the name a provider's own POI/reverse data associates with this address,
    used to cross-corroborate an OCR-read vendor name against what is actually there.
    """

    provider: str
    candidate_string: str
    address: GeoAddress | None = None
    confidence: float = 0.0
    matched_business_name: str = ""
    raw: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    error: GeoError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class GeoQuery:
    """A geocode request — the one shape both legitimate callers build (`docs/PRINCIPLES.md`
    §1.9): Execution Core's synchronous `GEOD` stage for a new receipt, and Reconciliation's
    idle-time sweep against an already-written, older one. Neither caller gets its own request
    shape; both go through `corroboration.geocode_with_corroboration`.

    `candidate_strings` is **ranked**, index 0 the highest-confidence OCR reading — matching
    `geo_address.proto`'s own `candidate_strings` field order — not just the single best guess
    (§3's second corroboration axis: every provider agreeing confidently on a *wrong* top
    reading is a real failure mode that only searching several candidates guards against).

    `providers` empty means "every registered, enabled provider" (matches `GeocodeRequest`'s
    own proto3 empty-means-unset convention). `vendor_name_hint` is the OCR-read vendor name,
    carried through so the reverse-check phase has something to compare a resolved address's
    own business name against; empty means the caller has nothing to corroborate that way and
    the reverse-check phase is skipped entirely rather than run against nothing.
    """

    candidate_strings: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    country_code: str = "PH"
    vendor_name_hint: str = ""


@dataclass(frozen=True)
class GeoResult:
    """Response for one `geocode_with_corroboration` call. Errors are data (§4.1): `error`
    is set only for a malformed request (empty candidates, an unresolvable provider filter),
    never for "every provider was unavailable this run" — that is a legitimate, honestly
    low-confidence answer, not a failed run (`docs/PRINCIPLES.md` §4.4).

    `conflict=True` is the one case this API refuses to resolve on its own (§4.3): providers
    genuinely disagreeing about an address is surfaced, with `normalized_address` left `None`
    rather than a silently-chosen guess, so a human (or the caller's own escalation policy —
    matching OCR API's own `AgreementLevel.SPLIT` boundary) decides what happens next.

    `cache_stale` marks the one deliberate exception to "cache only ever answers with fresh
    data": every provider being unavailable this run degrades to the last known-good cached
    answer rather than nothing (§4.4 again) — the caller still receives that fact honestly.
    """

    normalized_address: GeoAddress | None = None
    confidence: float = 0.0
    agreement: AgreementLevel = AgreementLevel.NONE
    matched_candidate_string: str = ""
    provider_results: tuple[ProviderCandidateResult, ...] = ()
    vendor_name_at_address: str = ""
    vendor_name_discrepancy: bool = False
    conflict: bool = False
    conflict_detail: str = ""
    degraded_providers: tuple[str, ...] = ()
    from_cache: bool = False
    cache_stale: bool = False
    error: GeoError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class GeoMetrics:
    """An immutable snapshot of the counters `metrics.py` keeps."""

    geocode_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_stale_hits: int = 0
    provider_calls: int = 0
    provider_failures: int = 0
    provider_unavailable: int = 0
    conflicts_detected: int = 0
    vendor_discrepancies_detected: int = 0
    all_providers_down: int = 0


__all__ = [
    "AGREEMENT_RANK",
    "KNOWN_PROVIDERS",
    "AgreementLevel",
    "GeoAddress",
    "GeoError",
    "GeoMetrics",
    "GeoQuery",
    "GeoResult",
    "ProviderCandidateResult",
]
