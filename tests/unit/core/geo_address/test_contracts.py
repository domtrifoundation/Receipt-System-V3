"""Geo/Address's frozen contracts and their `FrozenDict` fields (`docs/PRINCIPLES.md` §2.1).

The `forward_compat`-marked tests here are the ones this package genuinely needs across
interpreters: `ProviderCandidateResult.raw` and the module-level lookup tables are
`FrozenDict`-typed, and on 3.15 the builtin `frozendict` is **not** a `dict` subclass. Any
code that reached for `isinstance(x, dict)` would silently take the wrong branch.
"""

from __future__ import annotations

import collections.abc
import dataclasses

import pytest

from common.frozen_dict import FrozenDict
from core.geo_address import contracts
from core.geo_address.contracts import (
    AGREEMENT_RANK,
    KNOWN_PROVIDERS,
    AgreementLevel,
    GeoAddress,
    GeoError,
    GeoMetrics,
    GeoQuery,
    GeoResult,
    ProviderCandidateResult,
)
from core.geo_address.errors import ERROR_CODES, ERROR_SUMMARIES


@pytest.mark.parametrize(
    "cls",
    [
        GeoAddress,
        GeoError,
        ProviderCandidateResult,
        GeoQuery,
        GeoResult,
        GeoMetrics,
    ],
)
def test_every_contract_is_frozen(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen, f"{cls.__name__} crosses a boundary unfrozen"


def test_geo_address_has_coordinates_reflects_both_fields_not_either():
    with_both = GeoAddress(formatted="x", latitude=14.6, longitude=120.9)
    with_one = GeoAddress(formatted="x", latitude=14.6)
    with_neither = GeoAddress(formatted="x")

    assert with_both.has_coordinates
    assert not with_one.has_coordinates
    assert not with_neither.has_coordinates


def test_provider_candidate_result_ok_reflects_error_field():
    ok = ProviderCandidateResult(provider="locationiq", candidate_string="q")
    failed = ProviderCandidateResult(
        provider="locationiq", candidate_string="q", error=GeoError(code="X")
    )

    assert ok.ok
    assert not failed.ok


def test_geo_result_ok_reflects_error_field():
    assert GeoResult().ok
    assert not GeoResult(error=GeoError(code="INVALID_QUERY")).ok


def test_country_code_defaults_to_ph_for_this_projects_own_domain():
    """Root `CLAUDE.md`: this is a Philippine-receipt system end to end. A query or an
    address that never says otherwise should default into that domain, not a generic one."""
    assert GeoAddress(formatted="x").country_code == "PH"
    assert GeoQuery().country_code == "PH"


# ------------------------------------------------------------- forward compat


@pytest.mark.forward_compat
def test_module_level_lookup_tables_are_frozen_dicts():
    """`docs/PRINCIPLES.md` §2.1.1 — a table every module reads and nothing should ever
    write, shared across real OS threads under free-threading. The assertion is against
    `Mapping` plus a mutation attempt rather than against `dict`, because the 3.15 builtin
    is not a `dict` subclass and a `dict` check would pass on 3.14 and fail on 3.15."""
    for table in (KNOWN_PROVIDERS, AGREEMENT_RANK, ERROR_CODES, ERROR_SUMMARIES):
        assert isinstance(table, collections.abc.Mapping)
        assert type(table) is FrozenDict
        with pytest.raises(TypeError):
            table["injected"] = "value"  # type: ignore[index]


@pytest.mark.forward_compat
def test_provider_candidate_result_raw_is_a_frozen_dict_not_a_plain_dict():
    """`raw` is handed across the `asyncio.gather` fan-out in `corroboration.py` and round
    trips through `cache.py`'s JSON encoding — exactly the kind of field a shallow-immutable
    plain `dict` would let a careless caller mutate in place after the fact."""
    result = ProviderCandidateResult(
        provider="locationiq", candidate_string="q", raw=FrozenDict({"display_name": "x"})
    )

    assert isinstance(result.raw, collections.abc.Mapping)
    assert type(result.raw) is FrozenDict
    with pytest.raises(TypeError):
        result.raw["display_name"] = "y"  # type: ignore[index]


@pytest.mark.forward_compat
def test_default_raw_factory_produces_an_independent_frozen_dict():
    """A shared mutable `{}` default would be both mutable and shared across every result
    that omitted the field — the same default-factory gotcha Audit's own contracts guard."""
    a = ProviderCandidateResult(provider="p", candidate_string="a")
    b = ProviderCandidateResult(provider="p", candidate_string="b")

    assert type(a.raw) is FrozenDict
    assert a.raw is not b.raw or len(a.raw) == 0


def test_contracts_module_exposes_no_mutating_result_type():
    """This API never owns the address data it corrects into (`core/geo_address/CLAUDE.md`'s
    own "does NOT own" list) — the absence of any `Update`/`Delete` contract is the check for
    that boundary staying true as the module grows."""
    names = [n for n in dir(contracts) if not n.startswith("_")]
    assert not [n for n in names if "Update" in n or "Delete" in n], names


def test_agreement_rank_orders_unanimous_above_everything_else():
    assert AGREEMENT_RANK[AgreementLevel.UNANIMOUS] > AGREEMENT_RANK[AgreementLevel.MAJORITY]
    assert AGREEMENT_RANK[AgreementLevel.MAJORITY] > AGREEMENT_RANK[AgreementLevel.SINGLE_SOURCE]
    assert AGREEMENT_RANK[AgreementLevel.SINGLE_SOURCE] > AGREEMENT_RANK[AgreementLevel.SPLIT]
    assert AGREEMENT_RANK[AgreementLevel.SPLIT] > AGREEMENT_RANK[AgreementLevel.NONE]
