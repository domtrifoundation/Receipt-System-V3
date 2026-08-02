"""Category-default learning (`v3-deepdive-40-temporal-learning.md` §5, §11).

The deep-dive's own **category-default override test** is the first one here: an actual
vendor-specific fact always wins over a category default, even a high-confidence one. The
rest cover the aggregation itself — confidence derived from agreement, locals excluded so
one user's private observation cannot move everyone's fallback.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict
from core.architect.temporal_learning.category_defaults import (
    CategoryDefaults,
    recompute_defaults,
)
from core.architect.temporal_learning.contracts import CategoryDefault, Corporation, VendorLayer


def _corp(corporation_id, category, layer=VendorLayer.GLOBAL):
    return Corporation(
        corporation_id=corporation_id, name=corporation_id, corporate_tin="1",
        layer=layer, shared=layer is VendorLayer.GLOBAL, category_code=category,
    )


def test_a_vendor_specific_fact_always_beats_a_high_confidence_default():
    defaults = CategoryDefaults(
        (
            CategoryDefault(
                category="fast_food", field_name="vat_treatment",
                default_value=FrozenDict({"vat_treatment": "vatable"}),
                confidence=1.0, sample_size=99,
            ),
        )
    )
    assert defaults.resolve("fast_food", "vat_treatment", vendor_specific="zero_rated") == "zero_rated"


def test_the_default_is_used_only_when_there_is_no_vendor_specific_fact():
    defaults = CategoryDefaults(
        (
            CategoryDefault(
                category="fast_food", field_name="vat_treatment",
                default_value=FrozenDict({"vat_treatment": "vatable"}),
                confidence=0.9, sample_size=10,
            ),
        )
    )
    assert defaults.resolve("fast_food", "vat_treatment") == "vatable"
    assert defaults.resolve(None, "vat_treatment") is None
    assert defaults.resolve("pharmacy", "vat_treatment") is None


def test_a_weak_default_is_computed_but_not_offered():
    defaults = CategoryDefaults(
        (
            CategoryDefault(
                category="fast_food", field_name="vat_treatment",
                default_value=FrozenDict({"vat_treatment": "vatable"}),
                confidence=0.4, sample_size=10,
            ),
            CategoryDefault(
                category="pharmacy", field_name="vat_treatment",
                default_value=FrozenDict({"vat_treatment": "vatable"}),
                confidence=1.0, sample_size=1,
            ),
        )
    )
    assert defaults.resolve("fast_food", "vat_treatment") is None
    assert defaults.resolve("pharmacy", "vat_treatment") is None
    assert len(defaults.all()) == 2


def test_confidence_is_derived_from_agreement_not_asserted():
    entities = [_corp("c1", "fast_food"), _corp("c2", "fast_food"), _corp("c3", "fast_food")]
    facts = {
        "c1": {"vat_treatment": "vatable"},
        "c2": {"vat_treatment": "vatable"},
        "c3": {"vat_treatment": "zero_rated"},
    }
    computed = recompute_defaults(entities, facts)
    assert len(computed) == 1
    default = computed[0]
    assert default.sample_size == 3
    assert round(default.confidence, 2) == 0.67
    assert default.default_value["vat_treatment"] == "vatable"


def test_local_entities_never_move_a_shared_default():
    entities = [
        _corp("c1", "fast_food"),
        _corp("c2", "fast_food", layer=VendorLayer.LOCAL),
        _corp("c3", "fast_food", layer=VendorLayer.LOCAL),
    ]
    facts = {
        "c1": {"vat_treatment": "vatable"},
        "c2": {"vat_treatment": "zero_rated"},
        "c3": {"vat_treatment": "zero_rated"},
    }
    computed = recompute_defaults(entities, facts)
    assert computed[0].sample_size == 1
    assert computed[0].default_value["vat_treatment"] == "vatable"


def test_a_mapping_shaped_value_is_aggregated_rather_than_crashing():
    """A `FrozenDict` value must be handled by the `Mapping` branch, not fall through.

    An `isinstance(value, dict)` check here would miss the 3.15 builtin, leave the value
    unhashed, and raise `TypeError` at exactly the moment a caller passed a correctly
    typed value (`docs/PRINCIPLES.md` §2.1).
    """
    entities = [_corp("c1", "pharmacy"), _corp("c2", "pharmacy")]
    facts = {
        "c1": {"discounts": FrozenDict({"senior": 0.2})},
        "c2": {"discounts": FrozenDict({"senior": 0.2})},
    }
    computed = recompute_defaults(entities, facts)
    assert computed[0].confidence == 1.0
    assert computed[0].sample_size == 2


def test_entities_with_no_category_are_ignored():
    entities = [_corp("c1", None)]
    assert recompute_defaults(entities, {"c1": {"vat_treatment": "vatable"}}) == ()
