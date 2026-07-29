"""Matching's frozen contracts and their `FrozenDict` fields (`docs/PRINCIPLES.md` §2.1).

The `forward_compat`-marked tests here are the ones this package genuinely needs across
interpreters: `MatchCandidate.raw` is `FrozenDict`-typed, and on 3.15 the builtin `frozendict`
is **not** a `dict` subclass. Code that reached for `isinstance(x, dict)` would silently take
the wrong branch and, for `raw`, would treat a correctly-typed diagnostics payload as if it
were not a mapping at all.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from common.frozen_dict import FrozenDict
from core.matching.contracts import (
    MatchCandidate,
    MatchContext,
    MatchError,
    MatchResult,
    MatchSource,
    VendorCorroborationPolicy,
)
from core.matching.errors import ERROR_CODES, ERROR_SUMMARIES
from core.matching.fuzzy_match import GENERIC_TERMS


@pytest.mark.forward_compat
def test_match_candidate_raw_is_a_mapping_not_a_dict_subclass():
    """The check every `FrozenDict` consumer must make is `Mapping`, never `dict`.

    On 3.14 the PyPI `frozendict` happens to satisfy both; on 3.15 the builtin satisfies only
    `Mapping`. A test asserting `Mapping` passes on both and is the one that stays true when
    the interpreter moves — which is the whole point of the marker.
    """
    candidate = MatchCandidate(
        canonical_name="Denny's",
        score=87.5,
        source=MatchSource.FORWARD,
        raw=FrozenDict({"scorer": "WRatio"}),
    )

    assert isinstance(candidate.raw, Mapping)
    assert candidate.raw["scorer"] == "WRatio"


@pytest.mark.forward_compat
def test_match_candidate_raw_rejects_mutation():
    """Shallow immutability is not enough — a frozen dataclass with a plain `dict` is mutable."""
    candidate = MatchCandidate(
        canonical_name="Denny's", score=87.5, source=MatchSource.FORWARD,
        raw=FrozenDict({"scorer": "WRatio"}),
    )

    with pytest.raises(Exception):
        candidate.raw["scorer"] = "something else"  # type: ignore[index]


@pytest.mark.forward_compat
def test_generic_terms_table_is_a_mapping_not_a_dict_subclass():
    """§2.1.1: a module-level constant lookup table is a `FrozenDict` too."""
    assert isinstance(GENERIC_TERMS, Mapping)
    assert "store" in GENERIC_TERMS
    with pytest.raises(Exception):
        GENERIC_TERMS["store"] = "mutated"  # type: ignore[index]


def test_error_tables_are_frozen_dicts():
    assert isinstance(ERROR_CODES, Mapping)
    assert isinstance(ERROR_SUMMARIES, Mapping)
    with pytest.raises(Exception):
        ERROR_SUMMARIES["INTERNAL"] = "mutated"  # type: ignore[index]


def test_match_result_ok_reflects_absence_of_error():
    ok_result = MatchResult(candidates=())
    error_result = MatchResult(error=MatchError(code="INVALID_MATCH_REQUEST"))

    assert ok_result.ok
    assert not error_result.ok


def test_match_context_ok_reflects_absence_of_error():
    ok_context = MatchContext(included=True, policy=VendorCorroborationPolicy.ALWAYS)
    error_context = MatchContext(error=MatchError(code="INVALID_CORROBORATION_POLICY"))

    assert ok_context.ok
    assert not error_context.ok


def test_match_candidate_is_frozen():
    candidate = MatchCandidate(canonical_name="Denny's", score=87.5, source=MatchSource.FORWARD)

    with pytest.raises(Exception):
        candidate.score = 0.0  # type: ignore[misc]


def test_match_request_candidates_default_to_empty_tuple_not_none():
    from core.matching.contracts import MatchRequest

    request = MatchRequest(extracted_text="Denny's")

    assert request.candidates == ()
