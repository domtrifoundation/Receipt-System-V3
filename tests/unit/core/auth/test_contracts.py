"""Contract shape: frozen, deeply immutable, and no password-shaped field anywhere."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import timedelta

import pytest

from common.frozen_dict import FrozenDict
from core.auth import contracts
from core.auth.contracts import (
    AuthChallenge,
    AuthError,
    AuthMethod,
    AuthResult,
    BreakGlassGrant,
    ChallengePurpose,
    Role,
    Session,
    utcnow,
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
    """A frozen dataclass with a plain `dict` field is only shallowly immutable."""
    for cls in _CONTRACT_TYPES:
        for f in dataclasses.fields(cls):
            assert f.type != "dict", f"{cls.__name__}.{f.name} must be a FrozenDict"


@pytest.mark.forward_compat
def test_dict_typed_fields_resolve_to_the_frozen_type():
    """Validates the `FrozenDict` shim actually resolves — on 3.15+ to the builtin, which
    is *not* a `dict` subclass, which is why every check in this package tests `Mapping`."""
    challenge = AuthChallenge(
        challenge_id="c", method=AuthMethod.EMAIL, parameters=FrozenDict({"channel": "email"})
    )
    assert isinstance(challenge.parameters, Mapping)
    assert isinstance(challenge.parameters, FrozenDict)
    with pytest.raises(Exception):
        challenge.parameters["channel"] = "sms"  # type: ignore[index]


@pytest.mark.forward_compat
def test_default_mapping_fields_are_frozen_too():
    """The default_factory path is the one that silently regresses to `{}` if someone
    "simplifies" it — a plain dict default would be shared *and* mutable."""
    result = AuthResult(authenticated=False, method=AuthMethod.SMS)
    assert isinstance(result.claims, FrozenDict)
    assert isinstance(result.claims, Mapping)


def test_session_liveness_accounts_for_revocation_and_expiry():
    now = utcnow()
    live = Session(
        session_id="s", user_id="u", role=Role.CLIENT, created_at=now, last_seen_at=now,
        expires_at=now + timedelta(hours=1),
    )
    assert live.is_active()
    assert not dataclasses.replace(live, revoked_at=now).is_active()
    assert not dataclasses.replace(live, expires_at=now - timedelta(seconds=1)).is_active()


def test_break_glass_grant_expiry_is_a_property_of_the_value():
    now = utcnow()
    grant = BreakGlassGrant(
        grant_id="g", staff_user_id="s", target_client_user_id="c", reason="ticket-1",
        granted_at=now, expires_at=now - timedelta(seconds=1),
    )
    assert not grant.is_active()


def test_auth_error_keeps_the_deep_dive_five():
    """Field-only-append discipline: the original five values must never be renamed away."""
    for name in (
        "SESSION_EXPIRED", "SESSION_INVALID", "OIDC_STATE_MISMATCH", "ROLE_INSUFFICIENT",
        "BREAK_GLASS_EXPIRED",
    ):
        assert hasattr(AuthError, name)


def test_no_password_method_exists():
    values = {m.value for m in AuthMethod}
    assert values == {"sso", "passkey", "email", "sms"}
    assert not any("password" in v for v in values)


def test_challenge_purposes_are_distinct_values():
    """Step-up must not be representable as login — that separation is the gate."""
    assert ChallengePurpose.STEP_UP is not ChallengePurpose.LOGIN
