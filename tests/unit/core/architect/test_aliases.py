"""Alias list and name normalization (`v3-deepdive-26-architect-api.md` §3).

The conflict case is the one that matters most: `docs/PRINCIPLES.md` §4.3 says a genuine
conflict is surfaced to a human and never silently overridden, and an alias quietly
repointing at a different corporation is exactly that — the loser stops being findable
under a name it is genuinely known by, with nothing recorded anywhere.
"""

from __future__ import annotations

from core.architect.errors import ErrorCode
from core.architect.vendor_directory.aliases import AliasIndex, normalize_vendor_name


def test_corporate_suffixes_normalize_to_the_same_form():
    assert normalize_vendor_name("Jollibee Foods Corporation") == normalize_vendor_name(
        "Jollibee Foods Corp."
    )
    assert normalize_vendor_name("Mercury Drug, Inc.") == normalize_vendor_name("Mercury Drug")


def test_normalization_never_strips_the_last_word():
    """A corporation genuinely named 'Company' must not normalize to the empty string."""
    assert normalize_vendor_name("Company") == "company"
    assert normalize_vendor_name("Inc.") == "inc"


def test_normalization_folds_case_accents_and_punctuation():
    assert normalize_vendor_name("  Café  del   Mar!! ") == "cafe del mar"


def test_leading_words_matching_a_suffix_survive():
    """Only trailing corporate-form words are stripped."""
    assert normalize_vendor_name("Philippine Airlines") == "philippine airlines"


def test_alias_resolution_is_exact_on_normalized():
    index = AliasIndex()
    index.add("Jollibee Foods Corporation", "corp-1")
    assert index.resolve("jollibee foods corp").alias.corporation_id == "corp-1"
    # Nothing fuzzy: a genuinely different string does not resolve.
    assert not index.resolve("jolibee").ok


def test_conflicting_alias_is_surfaced_never_silently_repointed():
    index = AliasIndex()
    index.add("Metro Mart", "corp-1")
    conflict = index.add("metro mart", "corp-2")
    assert not conflict.ok
    assert conflict.error is not None and conflict.error.code == ErrorCode.DUPLICATE_DEFINITION
    assert index.resolve("Metro Mart").alias.corporation_id == "corp-1"


def test_re_adding_the_same_pairing_is_idempotent():
    index = AliasIndex()
    first = index.add("Metro Mart", "corp-1")
    again = index.add("Metro Mart", "corp-1")
    assert again.ok and again.alias == first.alias
    assert len(index) == 1


def test_repoint_is_the_explicit_way_to_move_an_alias():
    index = AliasIndex()
    index.add("Metro Mart", "corp-1")
    moved = index.repoint("Metro Mart", "corp-2")
    assert moved.ok
    assert index.resolve("Metro Mart").alias.corporation_id == "corp-2"
    assert index.aliases_for("corp-1") == ()
    assert index.surface_forms("corp-2") == ("Metro Mart",)


def test_empty_alias_is_refused():
    index = AliasIndex()
    assert not index.add("   ", "corp-1").ok
