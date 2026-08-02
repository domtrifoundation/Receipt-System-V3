"""The read side of the vendor directory — `SearchVendorDirectory` (deep-dive §7).

**Not listed in the deep-dive's own §2 package layout**, added because §7 specifies a
`SearchVendorDirectory` RPC and the layout names no module to serve it: `aliases.py` owns
alias records and `wikidata_bootstrap.py` owns seeding, and neither is the right home for
"turn a query into `VendorRecord`s".

**This searches, it does not match.** Resolution here is exact-on-normalized name, exact
alias, and exact TIN, plus a normalized substring pass for a human typing into a search
box. Deciding which corporation a noisy piece of OCR text refers to is Matching's fuzzy
scoring, and Architect performing it would be this API implementing a consuming API's own
logic — the first thing its own §1 says it does not do.

Visibility is applied here rather than left to callers: a search reaches across the whole
store, and "the caller will filter" is how one user's private local entity ends up in
another user's results.
"""

from __future__ import annotations

from ..contracts import VendorRecord, VendorSearchResult
from ..temporal_learning.contracts import Corporation
from ..temporal_learning.entities import EntityManager
from ..temporal_learning.layering import visible_to
from .aliases import AliasIndex, normalize_vendor_name

#: A search never returns an unbounded set; a caller that wants more asks for more.
DEFAULT_SEARCH_LIMIT = 25


class VendorDirectory:
    """The queryable projection over corporations, their branches and their aliases."""

    def __init__(self, entities: EntityManager, aliases: AliasIndex | None = None) -> None:
        self._entities = entities
        # `is None`, never a truthiness test: `AliasIndex` defines `__len__`, so an empty
        # but genuinely supplied index is falsy and `or` would silently discard it.
        self._aliases = aliases if aliases is not None else AliasIndex()

    @property
    def aliases(self) -> AliasIndex:
        return self._aliases

    def record_for(self, corporation: Corporation) -> VendorRecord:
        """Flatten one corporation into the read contract consumers actually receive."""
        return VendorRecord(
            corporation_id=corporation.corporation_id,
            name=corporation.name,
            corporate_tin=corporation.corporate_tin,
            layer=corporation.layer,
            category_code=corporation.category_code,
            aliases=self._aliases.surface_forms(corporation.corporation_id),
            branch_count=len(self._entities.branches_for(corporation.corporation_id)),
        )

    def search(
        self, query: str, user_id: str | None = None, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> VendorSearchResult:
        """Find corporations by name, alias or TIN.

        Ordering is deliberate and stable: an exact normalized-name or alias hit first, a
        TIN hit next, substring hits last, each group name-sorted. A caller showing one
        result should be showing the exact match, not whichever row the store happened to
        yield first.
        """
        normalized_query = normalize_vendor_name(query)
        digits = "".join(ch for ch in query if ch.isdigit())
        alias_hit = self._aliases.resolve(query)
        alias_corp_id = alias_hit.alias.corporation_id if alias_hit.alias else None

        exact: list[VendorRecord] = []
        by_tin: list[VendorRecord] = []
        partial: list[VendorRecord] = []
        for entity in self._entities.store.all_of("corporation"):
            if not isinstance(entity, Corporation) or not visible_to(entity, user_id):
                continue
            normalized_name = normalize_vendor_name(entity.name)
            record = self.record_for(entity)
            if entity.corporation_id == alias_corp_id or (
                normalized_query and normalized_name == normalized_query
            ):
                exact.append(record)
            elif digits and "".join(ch for ch in entity.corporate_tin if ch.isdigit()) == digits:
                by_tin.append(record)
            elif normalized_query and normalized_query in normalized_name:
                partial.append(record)

        ordered = (
            sorted(exact, key=lambda r: r.name)
            + sorted(by_tin, key=lambda r: r.name)
            + sorted(partial, key=lambda r: r.name)
        )
        return VendorSearchResult(records=tuple(ordered[: max(limit, 0)]))

    def get(self, corporation_id: str, user_id: str | None = None) -> VendorSearchResult:
        """One corporation by id, subject to the same visibility rule as a search."""
        found = self._entities.get("corporation", corporation_id)
        entity = found.entity
        if not isinstance(entity, Corporation) or not visible_to(entity, user_id):
            return VendorSearchResult()
        return VendorSearchResult(records=(self.record_for(entity),))


__all__ = ["DEFAULT_SEARCH_LIMIT", "VendorDirectory"]
