"""Install-shape resolution: the 2FA floor, session TTLs, and the single-tenant short-circuit."""

from __future__ import annotations

import pytest

from common.frozen_dict import FrozenDict
from core.auth.contracts import Role, TenancyMode, TwoFactorPolicy
from core.auth.errors import SingleTenantShortCircuit, TwoFactorPolicyFloor
from core.auth.tenancy import (
    SESSION_TTL_HOURS,
    assert_multi_tenant,
    enforce_policy_floor,
    implicit_owner_session,
    policy_floor,
    resolve_profile,
    resolve_session_ttl_hours,
    resolve_two_factor_policy,
    two_factor_required,
)


def test_single_tenant_defaults_to_optional_two_factor():
    profile = resolve_profile({"tenancy_mode": "single"})
    assert profile.two_factor_policy is TwoFactorPolicy.OPTIONAL
    assert profile.short_circuited


def test_private_multi_tenant_defaults_to_optional_but_may_be_raised():
    profile = resolve_profile({"tenancy_mode": "multi", "public_facing": False})
    assert profile.two_factor_policy is TwoFactorPolicy.OPTIONAL
    raised = resolve_two_factor_policy(
        TenancyMode.MULTI, False, "required_for_all"
    )
    assert raised is TwoFactorPolicy.REQUIRED_FOR_ALL


def test_public_multi_tenant_defaults_to_required_for_elevated():
    profile = resolve_profile({"tenancy_mode": "multi", "public_facing": True})
    assert profile.two_factor_policy is TwoFactorPolicy.REQUIRED_FOR_ELEVATED


def test_public_install_cannot_configure_two_factor_back_down():
    """The floor is the point of §4.6.1 — it must not be a suggestion."""
    with pytest.raises(TwoFactorPolicyFloor):
        resolve_profile({
            "tenancy_mode": "multi", "public_facing": True,
            "two_factor": {"policy": "optional"},
        })
    with pytest.raises(TwoFactorPolicyFloor):
        enforce_policy_floor(TwoFactorPolicy.OPTIONAL, TenancyMode.MULTI, True)
    # ...but raising above the floor stays allowed.
    assert enforce_policy_floor(
        TwoFactorPolicy.REQUIRED_FOR_ALL, TenancyMode.MULTI, True
    ) is TwoFactorPolicy.REQUIRED_FOR_ALL


def test_policy_floor_is_optional_when_not_publicly_exposed():
    assert policy_floor(TenancyMode.MULTI, False) is TwoFactorPolicy.OPTIONAL
    assert policy_floor(TenancyMode.SINGLE, True) is TwoFactorPolicy.OPTIONAL


def test_required_for_elevated_covers_owner_and_staff_only():
    policy = TwoFactorPolicy.REQUIRED_FOR_ELEVATED
    assert two_factor_required(policy, Role.OWNER)
    assert two_factor_required(policy, Role.STAFF)
    assert not two_factor_required(policy, Role.CLIENT)
    assert two_factor_required(TwoFactorPolicy.REQUIRED_FOR_ALL, Role.CLIENT)


def test_session_ttl_resolution_follows_exposure():
    assert resolve_session_ttl_hours(False) == SESSION_TTL_HOURS["default"] == 720
    assert resolve_session_ttl_hours(True) == SESSION_TTL_HOURS["public_facing"] == 168
    assert resolve_session_ttl_hours(True, 12) == 12
    with pytest.raises(ValueError):
        resolve_session_ttl_hours(False, 0)


def test_multi_tenant_machinery_is_structurally_refused_in_single_mode():
    single = resolve_profile({"tenancy_mode": "single"})
    with pytest.raises(SingleTenantShortCircuit):
        assert_multi_tenant(single, "the OIDC handshake")
    session = implicit_owner_session(single)
    assert session.role is Role.OWNER
    assert session.is_active()


@pytest.mark.forward_compat
def test_config_resolution_accepts_a_frozen_mapping():
    """`isinstance(cfg, dict)` would silently take the "no config" branch on 3.15+, where
    the builtin frozendict is not a dict subclass — and hand back defaults on a fully
    configured install."""
    config = FrozenDict({
        "tenancy_mode": "multi",
        "public_facing": True,
        "session": FrozenDict({"ttl_hours": "auto"}),
        "otp": FrozenDict({"code_length": 8}),
    })
    profile = resolve_profile(config)
    assert profile.public_facing is True
    assert profile.session_ttl_hours == 168
    assert profile.otp_code_length == 8
    assert profile.two_factor_policy is TwoFactorPolicy.REQUIRED_FOR_ELEVATED
