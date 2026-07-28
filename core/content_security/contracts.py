"""Content Security API data contracts (`v3-deepdive-27-content-security-api.md` §2, §4, §7).

Types only, no logic beyond pure accessors (`docs/PRINCIPLES.md` §1.1) — this is the single
module other packages import from. Nothing outside `core/content_security/` should ever need
to import `pipeline`, `scanning`, `providers`, or `service`.

Every type here is `@dataclass(frozen=True)` and every dict-typed field is a `FrozenDict`
(§2.1) — `ScanVerdict.provider_verdicts` and `ContainerScanVerdict.member_verdicts` cross a
process boundary, and a frozen dataclass holding a plain `dict` is only shallowly immutable.
**`isinstance` against either must test `collections.abc.Mapping`, never `dict`** — the Python
3.15 builtin `frozendict` is not a `dict` subclass, so `isinstance(x, dict)` silently returns
False and the wrong branch is taken.

**`ScanVerdict.safe` is the only field a caller may act on for the accept/reject decision.**
Deliberately, there is no `.ok`-style "did the call itself succeed" property here, unlike the
result contracts in `core/logs` and `core/audit`. Those APIs distinguish "the operation failed"
from "the operation succeeded and returned a negative answer" because a caller needs to tell
apart, say, a query that legitimately found nothing from one that could not run at all.
Content Security's whole contract (`docs/PRINCIPLES.md` §4.2) is that those two cases must NOT
be distinguishable to a caller deciding whether to accept a file: a provider crash, a timeout,
an unavailable scanner, and a confirmed-malicious verdict are all, from the caller's point of
view, exactly the same instruction — do not accept this file. Giving this contract a second,
"was the check itself okay" field would hand a future caller exactly the footgun §4.2 exists
to remove: a plausible-looking reason to treat "the scan errored" as different from "the scan
said no."

`requires_staff_review` is the one legitimate three-way split of an intrinsically binary
`safe` field, and it is deliberate rather than a modelling compromise. §9 of the deep-dive
resolves the corroboration question with a rule that has three real outcomes, not two: every
enabled scanner agreeing on "malicious" is an outright, confirmed reject; every scanner
agreeing on "clean" is an accept; and anything in between — scanners disagreeing with each
other, or a single scanner returning its own low-confidence/borderline result — is neither.
`docs/PRINCIPLES.md` §4.3 says a genuine conflict is surfaced to a human, never silently
resolved by an automatic rule in either direction, so that third outcome cannot collapse into
either extreme: it is expressed as `safe=False` (the file is not released to normal
processing — fail-closed, §4.2, applies to an ambiguous signal exactly as it does to an
outright one) with `requires_staff_review=True` alongside it, which is what tells a caller
"this is not the same as a confirmed-malicious reject; a human needs to look at it" rather than
quietly discarding the file as if it had been condemned outright.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    """Timezone-aware UTC, matching every other API's own timestamp discipline in this repo."""
    return datetime.now(timezone.utc)


class ScanOutcome(str, Enum):
    """One provider's own verdict on one file (§5.1, §9).

    `SUSPICIOUS` exists because a real scanner's own output is not always a clean malicious/
    clean split — VirusTotal's per-engine breakdown routinely has some engines flag a file
    and most not, and ClamAV's own heuristic detections carry a real false-positive rate. §9
    names "a single scanner's own low-confidence/borderline result" as one of the two things
    that route to `requires_staff_review` rather than either extreme, and this member is what
    lets a provider express that case honestly instead of forcing it into `CLEAN` (an accept
    the evidence does not earn) or `MALICIOUS` (a reject stronger than the evidence supports).

    `ERROR` and `UNAVAILABLE` are deliberately different members, not the same thing spelled
    two ways: `UNAVAILABLE` is `is_available()` returning False before a scan is ever
    attempted (a missing ClamAV binary, no VirusTotal API key configured) and is a graceful
    degradation (§4.4) — the provider is excluded from the registry's run, same as an OCR
    engine that never started. `ERROR` is a provider that *was* available and was actually
    invoked, and the invocation itself failed, crashed, or timed out. That case is never
    degraded away: `pipeline.py` turns any `ERROR` outcome into an outright deny, because a
    scan that could not complete is not evidence of anything and §4.2 forbids treating it as
    permission.
    """

    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ScanRequest:
    """One untrusted file, as bytes already in memory (§6 — the magic-byte and polyglot
    passes are pure-Python work over bytes already read; there is no reason to make this a
    filesystem reference and force every caller, including a unit test, to first stage a
    temp file).

    `blob_ref` is optional and carries no authority of its own: it is Persistence's own
    `logical_id`/blob identifier, threaded through purely so a scan result can be correlated
    back to the blob it was run against in logs and in a container member's own scan request
    (`pipeline.py` derives one member `blob_ref` per extracted entry). This package never
    resolves a `blob_ref` to bytes itself — Persistence's blob store is the only thing that
    does that — which is exactly why `content` carries the actual bytes rather than this type
    asking its caller for a reference it would then have to go fetch.
    """

    content: bytes
    claimed_mime_type: str = ""
    claimed_filename: str = ""
    blob_ref: str = ""
    requesting_user_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class ProviderScanResult:
    """One provider's own raw answer, before cross-provider corroboration (§9).

    `pipeline.py` is the only place these are resolved into a `ScanVerdict`; nothing else in
    this package should need to inspect one directly.
    """

    provider_name: str
    outcome: ScanOutcome
    detail: str = ""
    #: The malware family/signature name a scanner reported, when it has one. Never used for
    #: the safe/unsafe decision itself — only `outcome` is — but worth carrying through to a
    #: human doing staff review (§5) rather than discarding it at the provider boundary.
    signature_name: str | None = None


@dataclass(frozen=True)
class ScanVerdict:
    """The result of `ScanFile` (§7). See this module's own docstring for why `safe` is the
    only field a caller may act on, and for what `requires_staff_review` means.

    `provider_verdicts` publishes each enabled provider's own raw outcome (provider name ->
    outcome string) precisely so a disagreement is *inspectable*, not just asserted —
    `docs/PRINCIPLES.md` §4.3's "surface a genuine conflict to a human" only means something
    if the conflict itself is visible on the result, not folded into one boolean with the
    disagreement thrown away.
    """

    safe: bool
    detected_type: str = ""
    rejection_reason: str = ""
    requires_staff_review: bool = False
    #: Stable wire code from `errors.py`, empty when `safe` is True. Kept separate from
    #: `rejection_reason` the same way `core/audit` and `core/logs` split a stable code from a
    #: human detail string — a caller matches on the code, a person reads the reason.
    error_code: str = ""
    provider_verdicts: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class BombCheckResult:
    """The container-level, pre-extraction check (§3): `zipfile.infolist()` metadata only.

    `bad_entries` are individually bomb-prone or nested-archive entries that *could* be
    stripped by `scanning.bomb_check.remediate_or_reject` (§3.1) rather than forcing a reject
    of the whole container — distinct from `safe=False`, which means the container's own
    *aggregate* shape (total entries, total uncompressed size, overall ratio) is unsafe
    regardless of which individual entries are responsible, and remediation would not fix it.
    """

    safe: bool
    reason: str = ""
    entry_count: int = 0
    total_uncompressed_bytes: int = 0
    compression_ratio: float = 0.0
    bad_entries: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContainerScanRequest:
    """Same shape as `ScanRequest`; a distinct type because a container is scanned through a
    genuinely different RPC (`ScanContainer`) and two-pass pipeline (§3), not because the
    fields differ."""

    content: bytes
    claimed_mime_type: str = ""
    claimed_filename: str = ""
    blob_ref: str = ""
    requesting_user_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class RemediationResult:
    """§3.1's own resolution: on Python new enough for `zipfile.ZipFile.remove()`/`.repack()`
    (feature-detected, not version-gated), a bad member is stripped and the rest is still
    usable (`action="stripped_and_extracted"`); otherwise the existing safe default applies
    and the whole archive is rejected (`action="rejected_whole_archive"`). `"not_needed"` is
    the ordinary case where `BombCheckResult.bad_entries` was already empty.
    """

    action: str
    removed: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContainerScanVerdict:
    """The result of `ScanContainer` (§7). `member_verdicts` carries every extracted member's
    own full `ScanVerdict`, keyed by its archive entry name — the container passing its own
    bomb check says nothing about whether an individual extracted file is safe (§3), and a
    caller needs to see *which* member failed, not just that the container as a whole did.
    """

    safe: bool
    bomb_check: BombCheckResult = field(default_factory=lambda: BombCheckResult(safe=True))
    member_verdicts: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    remediation: RemediationResult = field(
        default_factory=lambda: RemediationResult(action="not_needed")
    )
    rejection_reason: str = ""
    error_code: str = ""
    requires_staff_review: bool = False


@dataclass(frozen=True)
class DetectedFileType:
    """Real file-type verification via magic bytes (§1) — never the extension, never a
    client-supplied MIME type. `"application/octet-stream"` is the honest fallback for bytes
    matching no known signature; it is a real answer, not an error."""

    mime_type: str
    matched_signature: str = ""


@dataclass(frozen=True)
class PolyglotFinding:
    """A file valid as more than one format simultaneously (§8's testing hook) — a classic
    real attack technique (an image with a smuggled archive appended, for one concrete case),
    caught by checking for a *second* format's own signature rather than stopping at whichever
    format matched first."""

    is_polyglot: bool
    primary_type: str = ""
    embedded_types: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class ContentSecurityMetrics:
    """An immutable snapshot of the counters `metrics.py` keeps."""

    scans_performed: int = 0
    scans_passed_clean: int = 0
    scans_denied_malicious: int = 0
    scans_denied_staff_review: int = 0
    scans_denied_provider_error: int = 0
    scans_denied_no_provider: int = 0
    polyglots_detected: int = 0
    container_scans_performed: int = 0
    archive_bombs_rejected: int = 0
    remediations_performed: int = 0
    provider_unavailable_events: int = 0


__all__ = [
    "BombCheckResult",
    "ContainerScanRequest",
    "ContainerScanVerdict",
    "ContentSecurityMetrics",
    "DetectedFileType",
    "PolyglotFinding",
    "ProviderScanResult",
    "RemediationResult",
    "ScanOutcome",
    "ScanRequest",
    "ScanVerdict",
    "utcnow",
]
