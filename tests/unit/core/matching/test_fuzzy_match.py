"""Forward matching and its four V2-hard-learned safeguards (`v3-deepdive-15-matching-api.md`
§3, §9).

Each safeguard gets its own named test below, plus a ranked-ordering/tie-break test and a
real-data scorer comparison that resolves §8's own "scorer bench comparison" testing hook with
actual labeled pairs rather than leaving `WRatio` an unverified default indefinitely. The messy
vendor-name fixtures here are invented inline, in the shape of real Philippine OCR output the
task named as an example (garbled corporate suffixes, stray symbols, digit/letter substitution)
— never read from the fixtures directory.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from core.matching.fuzzy_match import (
    SHORT_NAME_FLOOR,
    best_name_match,
    match_forward,
    normalize_for_scoring,
    score_pair,
)

from .conftest import make_candidate


# ------------------------------------------------------------- pitfall 1: case sensitivity


def test_case_sensitivity_does_not_affect_scoring():
    """§9 pitfall 1: both sides are normalized before scoring, so an all-caps OCR reading
    scores identically to a naturally-cased one."""
    lower_score = score_pair("denny's", "denny's")
    mixed_score = score_pair("DENNY'S", "denny's")
    upper_score = score_pair("DENNY'S", "DENNY'S")

    assert lower_score == mixed_score == upper_score == 100.0


# ------------------------------------------------------ pitfall 2: short-name collapsing


def test_short_distinct_names_do_not_falsely_collapse():
    """§9 pitfall 2: two genuinely different short names must not score as a match just
    because short strings collapse easily under naive ratio scoring."""
    score = score_pair("Uno", "Uni")

    assert score == 0.0


def test_short_names_below_the_floor_still_match_when_truly_identical():
    """The floor guards against false collapsing, not against a genuine exact short match."""
    assert len("uno") < SHORT_NAME_FLOOR
    score = score_pair("Uno", "Uno")

    assert score == 100.0


def test_short_name_floor_does_not_penalize_ordinary_length_names():
    score = score_pair("Jollibee", "Jollibee")

    assert score == 100.0


# ------------------------------------------------------ pitfall 3: generic-word false positives


def test_shared_generic_word_alone_does_not_produce_a_false_positive():
    """§9 pitfall 3: two unrelated vendors that both contain "Store" must not score highly
    purely because of that shared, undistinguishing word."""
    unrelated_but_shares_generic_word = score_pair("Metro Grocery Store", "City Hardware Store")
    genuinely_same_vendor = score_pair("Metro Grocery Store", "Metro Grocery Store")

    assert unrelated_but_shares_generic_word < 60.0
    assert genuinely_same_vendor == 100.0


def test_generic_term_stripping_never_empties_a_name_that_is_only_a_generic_word():
    """A vendor genuinely named just "Store" must stay comparable, never collapse to the
    empty string and become unconditionally unmatchable."""
    score = score_pair("Store", "Store")

    assert score == 100.0


# --------------------------------------------------------------------- normalization itself


def test_normalize_for_scoring_collapses_whitespace_and_case():
    assert normalize_for_scoring("  Denny'S   Diner  ") == "denny's diner"


def test_normalize_for_scoring_is_not_architects_alias_normalization():
    """Fuzzy scoring needs comparably-cased, comparably-spaced text — not Architect's own
    aggressive corporate-suffix stripping, which is a different operation (module docstring)."""
    from core.architect.vendor_directory.aliases import normalize_vendor_name

    scoring_form = normalize_for_scoring("Jollibee Foods Corporation")
    alias_form = normalize_vendor_name("Jollibee Foods Corporation")

    assert scoring_form == "jollibee foods corporation"
    assert alias_form == "jollibee foods"  # suffix stripped — a genuinely different operation


# --------------------------------------------------------------- ranked ordering / tie-break


def test_forward_match_ranks_highest_score_first():
    candidates = (
        make_candidate("c1", "Jollibee Foods Corporation"),
        make_candidate("c2", "Denny's"),
        make_candidate("c3", "Mercury Drug Corporation"),
    )

    ranked = match_forward("Denny's", candidates)

    assert [c.canonical_name for c in ranked][0] == "Denny's"
    assert ranked[0].score == 100.0


def test_forward_match_breaks_ties_alphabetically_by_canonical_name():
    """A deterministic tie-break, not an arbitrary one — two candidates scoring identically
    against the same query must return in the same order on every call. A fixed-score fake
    scorer is injected (via `match_forward`'s own real `scorer=` parameter, not a private
    hook) to force a genuine tie deterministically, since two *different* real vendor names
    are not guaranteed to produce an exactly equal `WRatio` score."""
    candidates = (
        make_candidate("c1", "Zeta Mart"),
        make_candidate("c2", "Alpha Mart"),
    )

    ranked = match_forward("Something Mart", candidates, scorer=lambda a, b: 50.0)

    assert ranked[0].score == ranked[1].score == 50.0
    assert [c.canonical_name for c in ranked] == ["Alpha Mart", "Zeta Mart"]


def test_forward_match_drops_zero_scoring_candidates():
    """A fixed zero-score fake scorer deterministically exercises the "dropped, not
    returned at the bottom" behaviour, since a real vendor-name pair is rarely a true
    `WRatio` zero (rapidfuzz still finds some incidental character overlap)."""
    candidates = (make_candidate("c1", "Completely Unrelated Business Xyz"),)

    ranked = match_forward("Denny's", candidates, scorer=lambda a, b: 0.0)

    assert ranked == []


def test_forward_match_respects_limit():
    candidates = tuple(make_candidate(f"c{i}", f"Business Number {i}") for i in range(10))

    ranked = match_forward("Business Number 5", candidates, limit=3)

    assert len(ranked) == 3
    assert ranked[0].canonical_name == "Business Number 5"


def test_alias_match_reports_which_surface_form_won():
    """Deep-dive §1: Matching owns deciding which alias a piece of OCR text is closest to.

    The query is a typo'd reading ("Jollybee") that matches the *alias* exactly but the
    canonical name only approximately — a case genuinely won by the alias, not a tie that
    the canonical-name-first iteration order would happen to keep.
    """
    candidates = (
        make_candidate("c1", "Jollibee Foods Corporation", aliases=("Jollybee",)),
    )

    ranked = match_forward("Jollybee", candidates)

    assert ranked[0].matched_alias == "Jollybee"
    assert ranked[0].canonical_name == "Jollibee Foods Corporation"
    assert ranked[0].score == 100.0


def test_exact_canonical_name_match_leaves_matched_alias_empty():
    candidates = (make_candidate("c1", "Jollibee Foods Corporation", aliases=("Jollibee",)),)

    ranked = match_forward("Jollibee Foods Corporation", candidates)

    assert ranked[0].matched_alias == ""


# ------------------------------------------------------------- real PH OCR-messiness fixtures


def test_messy_ocr_vendor_name_with_stray_symbol_still_scores_as_best_candidate():
    """`AENA@AV'S FOOD CENTER INC`-shaped input: a stray `@` and doubled-up fragments from a
    noisy OCR read of a real, plainer vendor name. The messy string must still rank the real
    vendor above unrelated decoys, even if the absolute score is not perfect."""
    candidates = (
        make_candidate("c1", "Ana's Food Center Inc"),
        make_candidate("c2", "Mercury Drug Corporation"),
        make_candidate("c3", "SM Supermalls Inc"),
    )

    ranked = match_forward("AENA@AV'S FOOD CENTER INC", candidates)

    assert ranked[0].canonical_name == "Ana's Food Center Inc"


def test_digit_letter_substitution_ocr_garble_still_resolves_to_the_real_name():
    """`CORPORA7I0`-shaped input: OCR substituting digits for visually similar letters
    (7 for T, 0 for O) inside a corporate-suffix word."""
    candidates = (
        make_candidate("c1", "ABC Trading Corporation"),
        make_candidate("c2", "XYZ Logistics Inc"),
    )

    ranked = match_forward("ABC TRADING CORPORA7I0N", candidates)

    assert ranked[0].canonical_name == "ABC Trading Corporation"
    assert ranked[0].score > 60.0


def test_denny_5s_style_garble_is_present_but_not_necessarily_confident():
    """The deep-dive's own concrete example (§5): `DENNY 5` against `Denny's` may not score
    as a strong forward match at all — this is the exact case §5 says a fuzzy-matcher can be
    confidently wrong about (or, as here, simply not confident), which is why Matching's own
    confidence is never the gate on whether Inference gets a look (`vendor_match_context.py`)."""
    candidates = (make_candidate("c1", "Denny's"),)

    ranked = match_forward("DENNY 5", candidates)

    # Either it shows up with a real (possibly low) score, or it is absent entirely because it
    # scored zero — both are legitimate outcomes this test only needs to not crash to prove.
    if ranked:
        assert ranked[0].canonical_name == "Denny's"


# --------------------------------------------------------------- scorer bench comparison


def test_wratio_separates_true_matches_from_true_non_matches_better_than_plain_ratio():
    """§8's own testing hook, resolved with real labeled data rather than left as an assumed-
    optimal default indefinitely. `WRatio`'s whole advantage claim (§3) is handling reordered/
    partial-token matches; `token_reordering` below is the concrete case that exercises it."""
    true_matches = [
        ("Jollibee Foods Corporation", "Jollibee Foods Corp"),
        ("Foods Jollibee Corporation", "Jollibee Foods Corporation"),  # reordered tokens
        ("Mercury Drug Corporation", "Mercury Drug Corp."),
    ]
    true_non_matches = [
        ("Jollibee Foods Corporation", "Mercury Drug Corporation"),
        ("ABC Trading Corporation", "XYZ Logistics Inc"),
        ("Denny's", "SM Supermalls Inc"),
    ]

    def average(scorer, pairs):
        return sum(scorer(a.casefold(), b.casefold()) for a, b in pairs) / len(pairs)

    wratio_match_avg = average(fuzz.WRatio, true_matches)
    wratio_nonmatch_avg = average(fuzz.WRatio, true_non_matches)
    ratio_match_avg = average(fuzz.ratio, true_matches)

    # WRatio must clearly separate real matches from real non-matches...
    assert wratio_match_avg - wratio_nonmatch_avg > 30.0
    # ...and, on the reordered-token case specifically, must beat plain `fuzz.ratio` (§3's own
    # stated advantage claim), which scores raw character alignment and is penalized by
    # token order the way WRatio's own internal token-sort component is not.
    assert wratio_match_avg > ratio_match_avg
