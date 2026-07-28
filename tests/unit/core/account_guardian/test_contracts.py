"""Contract shape: frozen, deeply immutable, and reusing Auth's own vocabulary rather than a
second copy of it."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import datetime, timezone

import pytest

from common.frozen_dict import FrozenDict
from core.account_guardian import contracts
from core.account_guardian.contracts import (
    KNOWN_SSO_PROVIDERS,
    AuthMethod,
    DeletionRequest,
    DeletionStage,
    RecoveryVerificationChecklist,
    Role,
)

_CONTRACT_TYPES = [
    obj for obj in vars(contracts).values()
    if dataclasses.is_dataclass(obj) and isinstance(obj, type)
]


def test_every_contract_type_is_frozen():
    assert _CONTRACT_TYPES, "no dataclasses found — the import above is wrong"
    for cls in _CONTRACT_TYPES:
        assert cls.__dataclass_params__.frozen, f"{cls.__name__} is not frozen"


def test_no_contract_field_is_a_plain_dict():
    """A frozen dataclass with a plain `dict` field is only shallowly immutable
    (`docs/PRINCIPLES.md` §2.1) — every dict-shaped field in this package is a `FrozenDict`."""
    for cls in _CONTRACT_TYPES:
        for f in dataclasses.fields(cls):
            assert f.type != "dict", f"{cls.__name__}.{f.name} must be a FrozenDict"


@pytest.mark.forward_compat
def test_known_sso_providers_is_a_frozen_dict_not_a_plain_dict():
    """A module-level constant lookup table nothing should ever write is a `FrozenDict`
    (`docs/PRINCIPLES.md` §2.1.1), and the Python 3.15+ builtin is *not* a `dict` subclass —
    `isinstance(x, dict)` would silently miss it. This is this package's own instance of the
    exact gotcha `common/frozen_dict.py` documents."""
    assert isinstance(KNOWN_SSO_PROVIDERS, Mapping)
    assert isinstance(KNOWN_SSO_PROVIDERS, FrozenDict)
    with pytest.raises(Exception):
        KNOWN_SSO_PROVIDERS["evil"] = "Evil Corp"  # type: ignore[index]


def test_role_and_auth_method_are_reused_from_auth_not_redeclared():
    """`docs/PRINCIPLES.md` §3.4-adjacent reuse: this package must not define a second,
    driftable copy of Auth's own closed vocabularies."""
    from core.auth.contracts import AuthMethod as RealAuthMethod
    from core.auth.contracts import Role as RealRole

    assert Role is RealRole
    assert AuthMethod is RealAuthMethod


def test_recovery_checklist_requires_at_least_one_satisfied_check():
    empty = RecoveryVerificationChecklist()
    assert not empty.any_check_satisfied

    assert RecoveryVerificationChecklist(knowledge_check_passed=True).any_check_satisfied
    assert RecoveryVerificationChecklist(recovery_contact_verified=True).any_check_satisfied
    assert not RecoveryVerificationChecklist(recovery_contact_verified=False).any_check_satisfied
    assert RecoveryVerificationChecklist(vouched_by_user_id="staff_2").any_check_satisfied


def test_recovery_contact_tristate_distinguishes_unset_from_failed():
    """`None` ("no recovery contact was ever on file") must stay distinguishable from
    `False` ("one was on file and did not verify") — collapsing them would silently make an
    account with no recovery contact look like one that failed verification."""
    unset = RecoveryVerificationChecklist()
    failed = RecoveryVerificationChecklist(recovery_contact_verified=False)
    assert unset.recovery_contact_verified is None
    assert failed.recovery_contact_verified is False
    assert unset.recovery_contact_verified is not failed.recovery_contact_verified


def test_deletion_request_cancellable_matches_the_documented_stages():
    now = datetime.now(timezone.utc)
    for stage in (DeletionStage.REQUESTED, DeletionStage.GRACE_PERIOD, DeletionStage.BILLING_HOLD):
        req = DeletionRequest(request_id="d", user_id="u", requested_at=now, stage=stage)
        assert req.cancellable, f"{stage} should be cancellable"
    for stage in (DeletionStage.PROCESSING, DeletionStage.COMPLETE, DeletionStage.CANCELLED):
        req = DeletionRequest(request_id="d", user_id="u", requested_at=now, stage=stage)
        assert not req.cancellable, f"{stage} should not be cancellable"


def test_frozen_dataclasses_actually_reject_mutation():
    from core.account_guardian.contracts import DeviceSession

    now = datetime.now(timezone.utc)
    device = DeviceSession(
        session_id="s", created_at=now, last_seen_at=now, user_agent_summary="x",
        is_current=True,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        device.is_current = False  # type: ignore[misc]
