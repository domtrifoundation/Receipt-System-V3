"""Category-default learning (`v3-deepdive-40-temporal-learning.md` §5).

When there is no vendor-specific data at all — a genuinely new vendor nobody has seen —
but the category is known, a category-level default beats leaving every field blank. This
is a learned, evolving thing rather than a static lookup table: `confidence` is derived
from how many confirmed `GLOBAL` vendors in the category actually agree with the value,
recomputed periodically as an idle-time job, never asserted.

**A default is always a fallback.** `resolve` takes the vendor-specific fact first and only
reaches for a default when there genuinely is none — whatever `confidence` has climbed to.
A high-confidence category default overriding a real, confirmed fact about a specific
vendor would be the system deciding it knows better than its own evidence.

**Category granularity is a genuinely open question** (§12): how fine-grained categories
must be before defaults become useful needs real data to calibrate against. Nothing here
picks a granularity — it aggregates whatever categories the registry has defined.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

from common.frozen_dict import FrozenDict

from .contracts import (
    CategoryDefault,
    CategoryDefaultsResult,
    Corporation,
    Entity,
    VendorLayer,
)

#: Below this, a default is computed but not offered by `resolve`. A value two of three
#: vendors disagree with is not a default, it is noise. Reasoned, not measured — the bench
#: suite is what would settle it (`docs/PRINCIPLES.md` §5, "reasoned, then measured").
MIN_USABLE_CONFIDENCE = 0.6

#: Likewise: one agreeing vendor is an anecdote. Also reasoned, not measured.
MIN_SAMPLE_SIZE = 3


def recompute_defaults(
    entities: Iterable[Entity],
    facts: Mapping[str, Mapping[str, object]],
) -> tuple[CategoryDefault, ...]:
    """Aggregate confirmed `GLOBAL` corporations into per-category, per-field defaults.

    `facts` maps a corporation id to the field values confirmed for it — supplied by the
    caller rather than read here, because those values live in the consuming API's own
    data (Matching's vendor facts, Persistence's receipt-derived values) and Architect
    holds definitions, never instance data.

    Only `GLOBAL` entities count. A local fact is one user's private observation, and
    letting it move a shared default would leak its influence into everyone's results
    without ever passing the sharing gate.
    """
    buckets: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for entity in entities:
        if not isinstance(entity, Corporation):
            continue
        if entity.layer is not VendorLayer.GLOBAL or not entity.category_code:
            continue
        for field_name, value in (facts.get(entity.corporation_id) or {}).items():
            buckets[(entity.category_code, field_name)][_hashable(value)] += 1

    out: list[CategoryDefault] = []
    for (category, field_name), counter in sorted(buckets.items()):
        total = sum(counter.values())
        value, agreeing = counter.most_common(1)[0]
        out.append(
            CategoryDefault(
                category=category,
                field_name=field_name,
                default_value=FrozenDict({field_name: value}),
                confidence=agreeing / total if total else 0.0,
                sample_size=total,
            )
        )
    return tuple(out)


def _hashable(value: object) -> object:
    """Counter keys must hash. A mapping-shaped value becomes a sorted item tuple.

    The check is against `Mapping`, never `dict`: a `FrozenDict` value arriving here is
    not a `dict` subclass on 3.15+, would fail an `isinstance(x, dict)` test, and would
    then be used unhashed — a `TypeError` at the exact moment a caller passed a correctly
    typed value (`docs/PRINCIPLES.md` §2.1).
    """
    if isinstance(value, Mapping):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    if isinstance(value, (list, set)):
        return tuple(_hashable(v) for v in value)
    return value


class CategoryDefaults:
    """The computed defaults, queryable per category.

    Plain dict internally: a mutable table recomputed wholesale by an idle-time job, which
    is exactly the "genuinely mutable internal registry" §2.1.1 carves out.
    """

    def __init__(self, defaults: Iterable[CategoryDefault] = ()) -> None:
        self._by_category: dict[str, dict[str, CategoryDefault]] = {}
        self.replace_all(defaults)

    def replace_all(self, defaults: Iterable[CategoryDefault]) -> None:
        fresh: dict[str, dict[str, CategoryDefault]] = {}
        for default in defaults:
            fresh.setdefault(default.category, {})[default.field_name] = default
        self._by_category = fresh

    def for_category(self, category: str) -> CategoryDefaultsResult:
        found = tuple(
            sorted(self._by_category.get(category, {}).values(), key=lambda d: d.field_name)
        )
        return CategoryDefaultsResult(defaults=found)

    def resolve(
        self,
        category: str | None,
        field_name: str,
        vendor_specific: object | None = None,
    ) -> object | None:
        """The actual lookup order: vendor-specific fact, then category default, then None.

        The first branch is the load-bearing one. It returns before a default is even
        looked up, so there is no threshold, no confidence comparison, and no code path
        where a category default can win against a real fact about this vendor.
        """
        if vendor_specific is not None:
            return vendor_specific
        if category is None:
            return None
        default = self._by_category.get(category, {}).get(field_name)
        if default is None:
            return None
        if default.confidence < MIN_USABLE_CONFIDENCE or default.sample_size < MIN_SAMPLE_SIZE:
            return None
        return default.default_value.get(field_name)

    def all(self) -> tuple[CategoryDefault, ...]:
        return tuple(
            d
            for category in sorted(self._by_category)
            for d in sorted(self._by_category[category].values(), key=lambda x: x.field_name)
        )


__all__ = [
    "MIN_SAMPLE_SIZE",
    "MIN_USABLE_CONFIDENCE",
    "CategoryDefaults",
    "recompute_defaults",
]
