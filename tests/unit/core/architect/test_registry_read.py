"""The read registry (`v3-deepdive-26-architect-api.md` §1).

The rule these tests actually protect is `docs/PRINCIPLES.md` §3.4: this registry is the
only place a typed/learned/schema thing may be defined, so it has to be genuinely usable
for that — a consumer must be able to register its own types, get told clearly when a
registration is refused, and never lose a definition instance data was written against.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict
from core.architect.contracts import (
    DefinitionKind,
    FlagType,
    ReferenceIdentifierType,
    TaxonomyType,
)
from core.architect.errors import ErrorCode
from core.architect.registry.read import DefinitionRegistry


def test_seed_set_covers_every_reconciliation_check():
    """Every check module Reconciliation ships has a flag type defined here, not there."""
    registry = DefinitionRegistry()
    codes = {d.code for d in registry.list(DefinitionKind.FLAG_TYPE).definitions}
    for expected in (
        "vat_math_mismatch", "tin_format_malformed", "date_implausible", "account_outlier",
        "semantic_duplicate", "vendor_group_mismatch", "items_vendor_mismatch",
        "bir_completeness", "orphaned_archive_reference", "geo_vendor_cross_reference",
        "atp_validity",
    ):
        assert expected in codes


def test_consumer_can_register_its_own_definition():
    registry = DefinitionRegistry(seed=False)
    result = registry.register(FlagType(code="my_check", label="My check"))
    assert result.ok
    assert registry.get(DefinitionKind.FLAG_TYPE, "my_check").definition is not None


def test_duplicate_registration_is_refused_as_data():
    registry = DefinitionRegistry(seed=False)
    registry.register(FlagType(code="dupe", label="First"))
    second = registry.register(FlagType(code="dupe", label="Second"))
    assert not second.ok
    assert second.error is not None and second.error.code == ErrorCode.DUPLICATE_DEFINITION
    # The original survives — a refused registration never half-applies.
    kept = registry.get(DefinitionKind.FLAG_TYPE, "dupe").definition
    assert kept is not None and kept.label == "First"


def test_unknown_parent_is_refused():
    registry = DefinitionRegistry(seed=False)
    result = registry.register(TaxonomyType(code="child", label="Child", parent_code="nope"))
    assert result.error is not None and result.error.code == ErrorCode.INVALID_PARENT


def test_register_many_reports_every_error_and_keeps_the_good_ones():
    registry = DefinitionRegistry(seed=False)
    errors = registry.register_many(
        (
            FlagType(code="good_one", label="Good"),
            FlagType(code="", label="No code"),
            FlagType(code="good_two", label="Also good"),
        )
    )
    assert len(errors) == 1
    codes = {d.code for d in registry.list(DefinitionKind.FLAG_TYPE).definitions}
    assert codes == {"good_one", "good_two"}


def test_deprecate_hides_but_never_deletes():
    """Instance data outlives the decision to stop offering a definition."""
    registry = DefinitionRegistry(seed=False)
    registry.register(FlagType(code="old_flag", label="Old"))
    registry.deprecate(DefinitionKind.FLAG_TYPE, "old_flag")

    listed = {d.code for d in registry.list(DefinitionKind.FLAG_TYPE).definitions}
    assert "old_flag" not in listed
    assert registry.get(DefinitionKind.FLAG_TYPE, "old_flag").definition is not None
    with_deprecated = registry.list(DefinitionKind.FLAG_TYPE, include_deprecated=True)
    assert {d.code for d in with_deprecated.definitions} == {"old_flag"}


def test_taxonomy_hierarchy_walks_by_reference():
    registry = DefinitionRegistry()
    ancestors = registry.ancestors("fast_food")
    assert [d.code for d in ancestors.definitions] == ["food_service", "business_category"]
    assert registry.is_descendant_of("fast_food", "business_category")
    assert not registry.is_descendant_of("fast_food", "document_type")


def test_children_of_unknown_parent_is_an_error_not_an_empty_list():
    """Empty and wrong are different answers and a caller cannot otherwise tell them apart."""
    registry = DefinitionRegistry()
    result = registry.children("not_a_category")
    assert result.error is not None and result.error.code == ErrorCode.UNKNOWN_DEFINITION


def test_identifier_validation_is_structural_only():
    registry = DefinitionRegistry()
    assert registry.validate_identifier("tin", "123-456-789").ok
    assert registry.validate_identifier("tin", "123456789000").ok
    assert not registry.validate_identifier("tin", "12-34").ok
    assert not registry.validate_identifier("tin", "not-a-tin").ok
    assert not registry.validate_identifier("tin", "").ok


def test_identifier_type_without_a_pattern_accepts_any_non_empty_value():
    registry = DefinitionRegistry(seed=False)
    registry.register(ReferenceIdentifierType(code="freeform", label="Freeform"))
    assert registry.validate_identifier("freeform", "anything at all").ok
    assert not registry.validate_identifier("freeform", "").ok


def test_frozen_dict_attributes_are_accepted():
    """The validator tests `Mapping`, so a `FrozenDict` attributes payload is valid.

    An `isinstance(x, dict)` check here would reject every correctly-typed definition on
    3.15+, where the builtin frozendict is not a dict subclass.
    """
    registry = DefinitionRegistry(seed=False)
    result = registry.register(
        FlagType(code="attrs", label="Attrs", attributes=FrozenDict({"owner": "reconciliation"}))
    )
    assert result.ok
