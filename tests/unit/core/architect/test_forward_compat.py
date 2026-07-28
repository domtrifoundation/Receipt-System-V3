"""Forward-Compatibility validation for Architect (`docs/PRINCIPLES.md` §3.3.1).

Marked `forward_compat` because every test here depends on `FrozenDict`'s *resolved type*
rather than merely importing something that uses it. `nox -s forward_compat` runs them
under 3.14 and 3.15, which is what turns "the Mapping-not-dict discipline is followed" into
"confirmed it is, on an interpreter where the difference is real".

The specific hazard: on 3.15+ the builtin `frozendict` is not a `dict` subclass, so an
`isinstance(x, dict)` gate silently takes the wrong branch. Architect has four such gates —
definition registration, entity field validation, contribution construction, and
category-default aggregation — and each one is exercised below with a genuine `FrozenDict`,
so a regression to `dict` fails here rather than in production on a newer interpreter.
"""

from __future__ import annotations

import collections.abc

import pytest

from common.frozen_dict import FrozenDict
from core.architect.contracts import DefinitionKind, FlagType, VendorSeedRecord
from core.architect.errors import ERROR_MESSAGES
from core.architect.metrics import COUNTER_DESCRIPTIONS, ArchitectMetrics
from core.architect.registry.read import DefinitionRegistry
from core.architect.temporal_learning.category_defaults import recompute_defaults
from core.architect.temporal_learning.contracts import Corporation, VendorLayer
from core.architect.temporal_learning.contribution import contribution_for_correction
from core.architect.temporal_learning.entities import (
    _ENTITY_CLASSES,
    _ID_FIELDS,
    _REQUIRED_FIELDS,
    EntityManager,
)
from core.architect.temporal_learning.errors import LEARNING_ERROR_MESSAGES
from core.architect.vendor_directory.aliases import CORPORATE_SUFFIXES
from core.architect.vendor_directory.wikidata_bootstrap import (
    WIKIDATA_CLASS_TO_CATEGORY,
    WIKIDATA_CONFIG_DEFAULTS,
)

pytestmark = pytest.mark.forward_compat


def test_every_module_level_lookup_table_is_a_frozen_dict():
    """`docs/PRINCIPLES.md` §2.1.1 — a constant table read across real OS threads."""
    for table in (
        ERROR_MESSAGES,
        LEARNING_ERROR_MESSAGES,
        COUNTER_DESCRIPTIONS,
        CORPORATE_SUFFIXES,
        WIKIDATA_CLASS_TO_CATEGORY,
        WIKIDATA_CONFIG_DEFAULTS,
        # These three were plain dicts: genuine constant lookup tables (entity class,
        # id field and required fields per type), read from every method in `entities.py`
        # and never written, which is §2.1.1's case and not its mutable-registry carve-out.
        _ENTITY_CLASSES,
        _ID_FIELDS,
        _REQUIRED_FIELDS,
    ):
        assert isinstance(table, FrozenDict)
        assert isinstance(table, collections.abc.Mapping)
        with pytest.raises(TypeError):
            table["new key"] = "value"  # type: ignore[index]


def test_contract_dict_fields_are_frozen_dicts():
    seed = VendorSeedRecord(source="s", external_id="Q1", name="Some Chain")
    assert isinstance(seed.raw, collections.abc.Mapping)
    with pytest.raises(TypeError):
        seed.raw["x"] = 1  # type: ignore[index]


def test_registration_accepts_a_frozen_dict_attributes_payload():
    """The gate is `Mapping`; an `isinstance(x, dict)` gate would reject this on 3.15+."""
    registry = DefinitionRegistry(seed=False)
    result = registry.register(
        FlagType(code="fc", label="FC", attributes=FrozenDict({"owner": "reconciliation"}))
    )
    assert result.ok
    stored = registry.get(DefinitionKind.FLAG_TYPE, "fc").definition
    assert isinstance(stored.attributes, collections.abc.Mapping)


def test_entity_validation_accepts_a_frozen_dict_of_fields():
    entities = EntityManager()
    result = entities.create(
        "corporation",
        FrozenDict({"name": "Chain", "corporate_tin": "123-456-789"}),
        actor_user_id="user-1",
    )
    assert result.ok


def test_contribution_construction_accepts_a_frozen_dict_change():
    built = contribution_for_correction(
        "corporation", None, FrozenDict({"name": "Chain", "corporate_tin": "1"}), "worker"
    )
    assert built.ok
    assert isinstance(built.contribution.proposed_change, collections.abc.Mapping)


def test_category_aggregation_hashes_a_frozen_dict_valued_fact():
    """The `Mapping` branch in `_hashable` — a `dict` check would raise `TypeError` here."""
    entities = [
        Corporation(corporation_id=f"c{i}", name=f"c{i}", corporate_tin="1",
                    layer=VendorLayer.GLOBAL, shared=True, category_code="pharmacy")
        for i in range(2)
    ]
    facts = {c.corporation_id: {"discounts": FrozenDict({"senior": 0.2})} for c in entities}
    computed = recompute_defaults(entities, facts)
    assert computed[0].sample_size == 2


def test_a_metrics_snapshot_cannot_be_edited_by_its_reader():
    metrics = ArchitectMetrics()
    metrics.increment("contributions_submitted")
    snapshot = metrics.snapshot()
    assert snapshot.get("contributions_submitted") == 1
    with pytest.raises(TypeError):
        snapshot.counters["contributions_submitted"] = 99  # type: ignore[index]
    # The live collector moving on does not retroactively change a taken snapshot.
    metrics.increment("contributions_submitted")
    assert snapshot.get("contributions_submitted") == 1
