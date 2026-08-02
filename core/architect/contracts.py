"""Architect API data contracts (`v3-deepdive-26-architect-api.md` §2).

This is the only module in this package other packages import from
(`docs/PRINCIPLES.md` §1.1), and it is load-bearing for more of the system than any
other contracts module: Persistence's reference-identifier types, Review/Flagging's
flag types, Matching's and Inference's category taxonomy, Billing's tier profiles and
Interface's menu-data schema are all *defined here and nowhere else* (§3.4). An API that
wants a new typed/learned/schema thing registers it as a `RegistryDefinition` of an
existing `DefinitionKind`; it never declares a parallel taxonomy of its own.

Every type here is `@dataclass(frozen=True)` and every dict-typed field is a `FrozenDict`
(`docs/PRINCIPLES.md` §2.1) — a frozen dataclass holding a plain dict is only shallowly
immutable, and these values are cached, shared across threads, and handed across a
process boundary. Any `isinstance` check against one of those fields must test
`collections.abc.Mapping`; the 3.15 builtin `frozendict` is not a `dict` subclass.

Errors are data here, never raised across the boundary (§4.1): every result type carries
an `error: ArchitectError | None` field and an `ok` property, and the `code`/`detail`
pair maps directly onto the `error_code`/`error_detail` fields of `architect.proto`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from common.frozen_dict import FrozenDict

from .temporal_learning.contracts import VendorLayer

#: Severity of a flag type, as Reconciliation's own checks already express it
#: (`v3-deepdive-17-reconciliation-api.md` §4.1 returns `severity="medium"`). Declared
#: once here rather than re-spelled by every API that raises a flag.
FlagSeverity = Literal["low", "medium", "high"]


class DefinitionKind(str, Enum):
    """The complete set of things this registry is allowed to define.

    Five entries because five separate APIs independently reinvented the same
    "extensible typed thing" pattern before this API existed to consolidate it
    (`v3-plan-01-core-apis.md` #25). Adding a *definition* is routine — an API registers
    a new flag type or category any day of the week. Adding a *kind* is not: it means a
    genuinely new species of schema data exists, and it goes through
    `docs/templates/new_taxonomy_type.md` first.
    """

    TAXONOMY_CATEGORY = "taxonomy_category"
    REFERENCE_IDENTIFIER_TYPE = "reference_identifier_type"
    FLAG_TYPE = "flag_type"
    TIER_PROFILE = "tier_profile"
    MENU_DATA_SCHEMA = "menu_data_schema"


@dataclass(frozen=True)
class RegistryDefinition:
    """One registered definition. The base shape every kind shares.

    `deprecated` rather than deletion is deliberate and mirrors the `.proto`
    only-add-fields discipline: instance data written against a definition outlives any
    decision to stop using it, so a definition stops being *offered* long before it can
    stop being *resolvable*.
    """

    code: str
    label: str
    kind: DefinitionKind
    description: str = ""
    deprecated: bool = False
    attributes: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class TaxonomyType(RegistryDefinition):
    """A node in the category taxonomy (`fast_food`, `pharmacy`, `hardware`).

    Architect defines the taxonomy and never performs a classification with it — that is
    Matching's and Inference's own work (deep-dive §5). Hierarchy is by `parent_code`
    reference rather than a nested structure so a subtree can be re-parented without
    rewriting anything below it.
    """

    kind: DefinitionKind = DefinitionKind.TAXONOMY_CATEGORY
    parent_code: str | None = None


@dataclass(frozen=True)
class ReferenceIdentifierType(RegistryDefinition):
    """A typed reference identifier a receipt may carry zero or more of.

    Persistence stores `type`/`value` pairs against whatever types are registered here
    and never adds a column per type (`v3-deepdive-13-persistence-api.md` §1).
    `value_pattern` is a *structural* check only — it catches OCR misreads and malformed
    entries, never validity against an issuing authority's own records.
    """

    kind: DefinitionKind = DefinitionKind.REFERENCE_IDENTIFIER_TYPE
    value_pattern: str = ""
    example: str = ""
    multi_valued: bool = True


@dataclass(frozen=True)
class FlagType(RegistryDefinition):
    """A flag Review/Flagging can raise.

    `flag_type` there is "a type Architect's registry has defined — never invented here"
    (`v3-deepdive-25-review-flagging-api.md` §4).
    """

    kind: DefinitionKind = DefinitionKind.FLAG_TYPE
    default_severity: FlagSeverity = "medium"
    raised_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class VendorRecord:
    """The read-side projection of a vendor, as a consumer of the directory sees it.

    Architect defines what a valid vendor record *looks like* and never holds instance
    data of its own (deep-dive §1). The authoritative entities are temporal_learning's
    `Corporation`/`Branch`/`Franchiser`; this is the flattened view Matching searches
    against, deliberately carrying `branch_count` rather than the branch list so a search
    response does not drag an entire branch table across the wire.
    """

    corporation_id: str
    name: str
    corporate_tin: str
    layer: VendorLayer
    category_code: str | None = None
    aliases: tuple[str, ...] = ()
    branch_count: int = 0


@dataclass(frozen=True)
class VendorSeedRecord:
    """One bootstrap-sourced vendor, before it becomes anything in the directory.

    Name and category only. Wikidata is a reasonable source for "this business exists and
    is roughly this kind of business" and is genuinely unreliable for TIN/franchise data,
    so those fields are structurally absent here rather than optional (deep-dive §3).
    """

    source: str
    external_id: str
    name: str
    category_code: str | None = None
    country_code: str = "PH"
    raw: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class SparqlFilter:
    """Inputs to the corrected bootstrap query (deep-dive §3.1).

    `query_version` is carried on the filter, not buried in the query builder, so a
    re-pull caused by the query itself changing is distinguishable from a routine
    scheduled one (§3.2).
    """

    root_class_qid: str = "Q4830453"
    country_qid: str = "Q928"
    language: str = "en"
    limit: int = 5000
    query_version: int = 2


@dataclass(frozen=True)
class VendorAlias:
    """An alternate surface form for a corporation.

    Architect owns the alias *list*; Matching owns the fuzzy scoring that decides which
    alias a piece of OCR text is closest to. Alias resolution here is exact-on-normalized
    only, which is why this contract carries the normalized form explicitly rather than
    leaving every caller to re-derive it and disagree about how.
    """

    alias: str
    normalized: str
    corporation_id: str
    source: str = "learned"


@dataclass(frozen=True)
class ArchitectError:
    """An error as data. `code` is stable and machine-readable; `detail` is for humans."""

    code: str
    detail: str = ""


@dataclass(frozen=True)
class TaxonomyResult:
    """Response for `GetTaxonomy`. Empty `definitions` with no error is a real answer."""

    definitions: tuple[RegistryDefinition, ...] = ()
    error: ArchitectError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class DefinitionResult:
    """Response for a single-definition lookup or registration."""

    definition: RegistryDefinition | None = None
    error: ArchitectError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class AliasResult:
    """Response for an alias registration or resolution.

    Carries `alias` rather than a bare success flag because the caller usually wants the
    normalized form back — recomputing it independently is how two call sites end up
    disagreeing about what "the same name" means.
    """

    alias: VendorAlias | None = None
    error: ArchitectError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class VendorSearchResult:
    """Response for `SearchVendorDirectory`."""

    records: tuple[VendorRecord, ...] = ()
    error: ArchitectError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class BootstrapResult:
    """Response for one seed-source pull.

    A source that is unavailable is reported as `degraded_reason`, not as a failure of
    the pull as a whole (`docs/PRINCIPLES.md` §4.4) — the other registered sources still
    contribute, and the directory is never worse off than before the run.
    """

    source: str
    records: tuple[VendorSeedRecord, ...] = ()
    degraded_reason: str = ""
    error: ArchitectError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


__all__ = [
    "AliasResult",
    "ArchitectError",
    "BootstrapResult",
    "DefinitionKind",
    "DefinitionResult",
    "FlagSeverity",
    "FlagType",
    "ReferenceIdentifierType",
    "RegistryDefinition",
    "SparqlFilter",
    "TaxonomyResult",
    "TaxonomyType",
    "VendorAlias",
    "VendorLayer",
    "VendorRecord",
    "VendorSearchResult",
    "VendorSeedRecord",
]
