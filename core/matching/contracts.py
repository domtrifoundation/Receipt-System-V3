"""Matching API data contracts (`v3-deepdive-15-matching-api.md` §1, §3-§5, §7).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1) and is the only file other
packages import from. Nothing here defines a taxonomy of its own: `VendorCandidate` is this
API's own read-only echo of whatever Architect's `SearchVendorDirectory` handed a caller for
one call — Matching never stores it, never re-fetches it on its own, and never learns from a
match (that is Architect's `temporal_learning`, invoked separately — this API's own CLAUDE.md,
"does NOT own"). `EntityKind` mirrors the two entity shapes a caller may hand in (`"corporation"`
or `"franchiser"`, deep-dive §9's resolved open question #2) without Matching itself declaring
a new schema type — the string values are Architect's own `temporal_learning.contracts.
EntityType` shape carried through as a caller-supplied label, not a registered definition.

Every type here is `@dataclass(frozen=True)` and every dict-typed field is a `FrozenDict`
(`docs/PRINCIPLES.md` §2.1): `MatchCandidate.raw` crosses the gRPC boundary and is read
concurrently by whichever corroboration-policy check runs over a batch of results, so a
shallowly-immutable plain `dict` would not actually protect it. Any `isinstance` check against
it must test `collections.abc.Mapping`, never `dict` — the Python 3.15 builtin `frozendict` is
not a `dict` subclass. `GENERIC_TERMS` in `fuzzy_match.py` is a module-level constant lookup
table and is `FrozenDict` too, per §2.1.1.

Errors are data here, never raised across the boundary (§4.1): `MatchResult.error` and
`MatchContext.error` follow the same `code`/`detail` shape every other API's own result
contracts already use, with an `ok` property so a caller checks one thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from common.frozen_dict import FrozenDict

#: The two entity shapes a `VendorCandidate` may represent (deep-dive §9's resolved open
#: question #2). Not a registered Architect definition — a caller-supplied label carried
#: through unchanged, the same way `VendorLayer`'s "local"/"global" strings are carried
#: through proto fields elsewhere without Matching re-declaring that taxonomy either.
EntityKind = Literal["corporation", "franchiser"]

#: Forward match's default candidate-list length. Reasoned, not measured (`docs/PRINCIPLES.md`
#: §5, "reasoned then measured" discipline) — five ranked candidates is enough for a human or
#: Inference to review without drowning either in noise; bench validation can tune this later.
DEFAULT_FORWARD_LIMIT: int = 5

#: The reverse gazetteer's own cost-bounding window (deep-dive §4): chars of `raw_ocr_text`
#: actually scanned, never the full text against the full known-vendor universe. 500 is a
#: reasoned placeholder scoped to "where a receipt's vendor line typically lives," explicitly
#: named in the deep-dive as worth bench-tuning against real receipt layouts, not a blocking
#: gap (§9's first open question, shipped as its own stated default rather than guessed at).
DEFAULT_PLAUSIBILITY_WINDOW: int = 500

#: The `BELOW_THRESHOLD` policy's default bar, on `rapidfuzz.fuzz.WRatio`'s own 0-100 scale
#: (§5.2). Reasoned, not measured — a score below this is treated as "worth Inference's own
#: review under that policy"; the deep-dive itself says the corroboration mechanism's own
#: thresholds are exactly the kind of thing this project's bench suite settles later.
DEFAULT_BELOW_THRESHOLD_SCORE: float = 80.0


class MatchSource(str, Enum):
    """Which half of the two-way match (deep-dive §4) produced a candidate.

    Wire-stable strings — `matching.proto`'s own `source` field carries these values
    literally, so adding a member is fine but renaming one is a breaking change.
    """

    FORWARD = "forward"
    REVERSE_GAZETTEER = "reverse_gazetteer"


class VendorCorroborationPolicy(str, Enum):
    """The resolved §5.2 setting — whether Inference reviews Matching's own candidates.

    `ALWAYS` is the default and the actual fix §5 exists to state: a deterministic
    fuzzy-matcher can be *confidently wrong*, not just uncertain (the deep-dive's own
    "Denny 5s" vs "Denny's" example), so gating Inference's review behind Matching's own
    confidence score would never give Inference the chance to catch that class of error at
    all. `BELOW_THRESHOLD` and `NEVER` stay available as a deliberate, informed cost/
    thoroughness tradeoff for a resource-constrained self-hosted install — not the
    recommended default, but never removed out from under an owner who chose it.
    """

    ALWAYS = "always"
    BELOW_THRESHOLD = "below_threshold"
    NEVER = "never"


@dataclass(frozen=True)
class VendorCandidate:
    """One directory entry Matching scores against — this API's own read-only echo of one
    row of whatever Architect's `SearchVendorDirectory` returned for this call, never a
    second copy of the directory itself (`docs/PRINCIPLES.md` §3.4; this API's own CLAUDE.md,
    "does NOT own").

    `aliases` is Architect's own alias *list* for this entity (deep-dive §1: "Architect owns
    the alias list; Matching owns the fuzzy scoring that decides which alias a piece of OCR
    text is closest to") — `fuzzy_match.best_name_match` is the one place that scoring
    actually happens.
    """

    entity_id: str
    name: str
    entity_kind: EntityKind = "corporation"
    tin: str = ""
    category_code: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchCandidate:
    """One ranked answer (`matching.proto`'s own `MatchCandidateProto`).

    `raw` carries scorer diagnostics (which scorer ran, its own unrounded output) — never
    load-bearing for the ranking itself, which is decided before this object is built, but
    real material for the deep-dive §8's own "scorer bench comparison" testing hook and for
    an operator trying to understand why one candidate outranked another.
    """

    canonical_name: str
    score: float
    source: MatchSource
    entity_id: str = ""
    entity_kind: EntityKind = "corporation"
    tin: str = ""
    category_code: str | None = None
    matched_alias: str = ""
    raw: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class MatchError:
    """An error as data. `code` is stable and machine-readable; `detail` is for humans
    (`docs/PRINCIPLES.md` §4.1)."""

    code: str
    detail: str = ""


@dataclass(frozen=True)
class MatchRequest:
    """One call's worth of input to `two_way_match.match_vendor` — the single reusable
    function `docs/PRINCIPLES.md` §1.9 asks for. Execution Core's synchronous `MATCHED`
    stage builds one of these per new receipt; Reconciliation's idle-time sweep builds the
    identical shape against an already-written, older one. Neither caller gets its own
    request shape.

    `candidates` is supplied by the caller, never fetched by Matching itself — this API
    consumes Architect's Vendor Directory, it does not hold a copy of it. An empty tuple is
    a legitimate request (no directory candidates yet resolved for this receipt), not a
    malformed one; only a request with nothing to match *against a string* at all
    (`extracted_text` and `raw_ocr_text` both empty) is genuinely invalid (`docs/PRINCIPLES.md`
    §4.4 vs §4.1's actual dividing line, drawn in `two_way_match.py`).
    """

    extracted_text: str = ""
    raw_ocr_text: str = ""
    candidates: tuple[VendorCandidate, ...] = ()
    limit: int = DEFAULT_FORWARD_LIMIT
    plausibility_window: int = DEFAULT_PLAUSIBILITY_WINDOW


@dataclass(frozen=True)
class MatchResult:
    """Response for `match_vendor`/`MatchVendor`/`ReverseGazetteerScan`.

    `candidates` is always ranked, highest score first (deep-dive §7's own proto comment).
    An empty tuple with no `error` is a real, honest answer — no candidate scored above
    zero, or none were supplied — never conflated with the genuine `error` case of a
    malformed request (`docs/PRINCIPLES.md` §4.4).
    """

    candidates: tuple[MatchCandidate, ...] = ()
    error: MatchError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class VendorMatchContextRequest:
    """Input to `get_vendor_match_context` (§5.1) — a `MatchRequest` plus the caller's own
    `VendorCorroborationPolicy` and, for `BELOW_THRESHOLD`, the bar it gates on.

    Carried as its own contract rather than extra fields bolted onto `MatchRequest` itself:
    a plain `MatchVendor` caller may have no opinion about corroboration policy at all, and
    `matching.proto`'s own `GetVendorMatchContext` RPC is the one surface that does.
    """

    match_request: MatchRequest
    policy: VendorCorroborationPolicy = VendorCorroborationPolicy.ALWAYS
    threshold: float = DEFAULT_BELOW_THRESHOLD_SCORE


@dataclass(frozen=True)
class MatchContext:
    """§5.1's actual mechanism, as data: what Execution Core folds into Inference's own
    extraction request for the `INFERRED` stage.

    `candidates` is populated regardless of `included` — for transparency and logging, so an
    operator can see what Matching found even under a policy that excludes it from Inference's
    own context this run. `included` is the one field a caller must respect; an emptied
    `candidates` list standing in for the gate would hide the "what was found" fact the
    `NEVER`/`BELOW_THRESHOLD` policies are explicitly not supposed to hide, only to not act on.
    """

    candidates: tuple[MatchCandidate, ...] = ()
    included: bool = True
    policy: VendorCorroborationPolicy = VendorCorroborationPolicy.ALWAYS
    top_score: float = 0.0
    error: MatchError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class MatchMetrics:
    """This API's own counters, snapshotted (`metrics.py`).

    Field names are the counter names — `metrics.py` derives them from this contract so the
    two cannot drift apart.
    """

    forward_match_calls: int = 0
    reverse_scan_calls: int = 0
    two_way_match_calls: int = 0
    candidates_scored: int = 0
    candidates_returned: int = 0
    empty_candidate_sets: int = 0
    malformed_requests: int = 0
    context_calls: int = 0
    context_included: int = 0
    context_excluded_by_policy: int = 0


__all__ = [
    "DEFAULT_BELOW_THRESHOLD_SCORE",
    "DEFAULT_FORWARD_LIMIT",
    "DEFAULT_PLAUSIBILITY_WINDOW",
    "EntityKind",
    "MatchCandidate",
    "MatchContext",
    "MatchError",
    "MatchMetrics",
    "MatchRequest",
    "MatchResult",
    "MatchSource",
    "VendorCandidate",
    "VendorCorroborationPolicy",
    "VendorMatchContextRequest",
]
