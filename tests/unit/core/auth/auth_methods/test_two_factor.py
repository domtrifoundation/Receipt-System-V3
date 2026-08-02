"""TOTP against RFC 6238's own test vectors, plus the policy gate and its floor.

The vectors matter: a homegrown TOTP that is subtly wrong fails only against real
authenticator apps, which is the worst place to discover it.
"""

from __future__ import annotations

import base64

import pytest

from core.auth.auth_methods.two_factor import (
    StdlibTotpEngine,
    TwoFactorGate,
)
from core.auth.contracts import AuthError, Role, TwoFactorConfig, TwoFactorPolicy
from core.auth.errors import TwoFactorPolicyFloor
from core.auth.tenancy import resolve_profile

from ..conftest import run

#: RFC 6238 Appendix B's shared secret, "12345678901234567890", base32-encoded — the
#: standard's own vector, not a value invented here.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
#: (unix time, expected 8-digit HMAC-SHA1 code) from the same appendix, truncated to the
#: 6 digits this implementation issues.
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
]


@pytest.fixture
def engine():
    return StdlibTotpEngine()


@pytest.mark.parametrize(("moment", "expected"), RFC_VECTORS)
def test_totp_matches_rfc6238_vectors(engine, moment, expected):
    assert engine.code_at(RFC_SECRET, moment) == expected[-6:]


def test_verification_accepts_one_step_of_clock_drift(engine):
    moment = 1111111109
    assert engine.verify(RFC_SECRET, engine.code_at(RFC_SECRET, moment), moment)
    assert engine.verify(RFC_SECRET, engine.code_at(RFC_SECRET, moment - 30), moment)
    assert engine.verify(RFC_SECRET, engine.code_at(RFC_SECRET, moment + 30), moment)
    assert not engine.verify(RFC_SECRET, engine.code_at(RFC_SECRET, moment + 120), moment)


def test_malformed_codes_are_rejected_without_comparison(engine):
    for bad in ("", "12345", "abcdef", "1234567"):
        assert not engine.verify(RFC_SECRET, bad, 59)


def test_generated_secrets_are_distinct_and_decodable(engine):
    secrets_seen = {engine.generate_secret() for _ in range(50)}
    assert len(secrets_seen) == 50
    for secret in secrets_seen:
        assert engine.code_at(secret, 0).isdigit()


def test_provisioning_uri_carries_the_issuer(engine):
    uri = engine.provisioning_uri(RFC_SECRET, "client@example.test", "DOMTRI")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=DOMTRI" in uri and RFC_SECRET in uri


def test_enrolment_is_two_step_and_starts_disabled(directory, profile, client_user):
    gate = TwoFactorGate(directory, profile)
    secret, uri = run(gate.begin_totp_enrolment(client_user.user_id, client_user.email))
    assert secret and uri
    assert not directory.get_two_factor(client_user.user_id).enabled

    engine = StdlibTotpEngine()
    assert not run(gate.confirm_totp_enrolment(client_user.user_id, "000000"))
    import time

    assert run(gate.confirm_totp_enrolment(
        client_user.user_id, engine.code_at(secret, time.time())
    ))
    assert directory.get_two_factor(client_user.user_id).enabled


def test_second_factor_verification_is_data_not_an_exception(directory, profile, client_user):
    gate = TwoFactorGate(directory, profile)
    assert run(gate.verify_second_factor(client_user.user_id, "000000")) is (
        AuthError.SECOND_FACTOR_REQUIRED
    )
    import time

    secret, _ = run(gate.begin_totp_enrolment(client_user.user_id, client_user.email))
    assert run(gate.confirm_totp_enrolment(
        client_user.user_id, StdlibTotpEngine().code_at(secret, time.time())
    ))
    assert run(gate.verify_second_factor(client_user.user_id, "000000")) is (
        AuthError.SECOND_FACTOR_INVALID
    )
    code = StdlibTotpEngine().code_at(secret, time.time())
    assert run(gate.verify_second_factor(client_user.user_id, code)) is None


def test_policy_optional_leaves_a_client_ungated(directory, profile, client_user):
    gate = TwoFactorGate(directory, profile)
    decision = gate.decide(client_user.user_id, Role.CLIENT)
    assert not decision.required and decision.satisfiable


def test_voluntary_enrolment_is_honoured_even_when_policy_is_optional(
    directory, profile, client_user
):
    directory.set_two_factor(TwoFactorConfig(client_user.user_id, True, "totp"))
    decision = TwoFactorGate(directory, profile).decide(client_user.user_id, Role.CLIENT)
    assert decision.required and decision.configured


def test_public_install_requires_a_second_factor_from_staff(
    directory, public_profile, staff_user
):
    gate = TwoFactorGate(directory, public_profile)
    decision = gate.decide(staff_user.user_id, Role.STAFF)
    assert decision.required
    # ...and the login cannot proceed until they enrol, rather than silently skipping it.
    assert not decision.satisfiable


def test_staff_cannot_switch_two_factor_off_on_a_public_install(
    directory, public_profile, staff_user
):
    gate = TwoFactorGate(directory, public_profile)
    with pytest.raises(TwoFactorPolicyFloor):
        gate.configure(staff_user.user_id, Role.STAFF, enabled=False, method=None)


def test_a_client_may_still_switch_it_off_under_required_for_elevated(
    directory, public_profile, client_user
):
    gate = TwoFactorGate(directory, public_profile)
    config = gate.configure(client_user.user_id, Role.CLIENT, enabled=False, method=None)
    assert not config.enabled


def test_unsupported_second_factor_methods_are_refused(directory, profile, client_user):
    gate = TwoFactorGate(directory, profile)
    with pytest.raises(ValueError):
        gate.configure(client_user.user_id, Role.CLIENT, enabled=True, method="password")


def test_policy_cannot_be_lowered_through_the_gate(directory, public_profile):
    gate = TwoFactorGate(directory, public_profile)
    with pytest.raises(TwoFactorPolicyFloor):
        gate.set_policy(TwoFactorPolicy.OPTIONAL)
    raised = gate.set_policy(TwoFactorPolicy.REQUIRED_FOR_ALL)
    assert raised.two_factor_policy is TwoFactorPolicy.REQUIRED_FOR_ALL
    # The profile is a frozen contract — raising the policy produced a new one.
    assert public_profile.two_factor_policy is TwoFactorPolicy.REQUIRED_FOR_ELEVATED


def test_private_install_may_lower_its_policy(directory):
    profile = resolve_profile({
        "tenancy_mode": "multi", "public_facing": False,
        "two_factor": {"policy": "required_for_all"},
    })
    gate = TwoFactorGate(directory, profile)
    assert gate.set_policy(TwoFactorPolicy.OPTIONAL).two_factor_policy is (
        TwoFactorPolicy.OPTIONAL
    )


# --------------------------------------------------------------------------------------
# Regression: beginning a TOTP enrolment must not be a second path around the §4.6.1 floor.
# Before this was fixed, `begin_totp_enrolment` wrote `TwoFactorConfig(enabled=False)`
# straight through `set_two_factor`, so an owner or staff member on a `public_facing`
# install could switch their own — or, via the servicer, anyone's — second factor off by
# *starting* an enrolment they never finished. `configure()` refuses that exact change with
# `TwoFactorPolicyFloor`; the enrolment path was reaching the same end state around it.
# --------------------------------------------------------------------------------------


def test_beginning_an_enrolment_never_disables_an_existing_second_factor(
    directory, public_profile, staff_user
):
    import time

    gate = TwoFactorGate(directory, public_profile)
    first, _ = run(gate.begin_totp_enrolment(staff_user.user_id, staff_user.email))
    assert run(gate.confirm_totp_enrolment(
        staff_user.user_id, StdlibTotpEngine().code_at(first, time.time())
    ))
    assert directory.get_two_factor(staff_user.user_id).enabled

    # The honest path is refused by the floor...
    with pytest.raises(TwoFactorPolicyFloor):
        gate.configure(staff_user.user_id, Role.STAFF, False, None)
    # ...and so, now, is the enrolment path's side effect: 2FA stays on throughout.
    second, _ = run(gate.begin_totp_enrolment(staff_user.user_id, staff_user.email))
    assert second != first
    assert directory.get_two_factor(staff_user.user_id).enabled
    # The live secret is untouched until the new one is actually confirmed.
    assert directory.get_totp_secret(staff_user.user_id) == first
    assert run(gate.verify_second_factor(
        staff_user.user_id, StdlibTotpEngine().code_at(first, time.time())
    )) is None


def test_an_abandoned_enrolment_leaves_no_usable_secret(directory, profile, client_user):
    import time

    gate = TwoFactorGate(directory, profile)
    secret, _ = run(gate.begin_totp_enrolment(client_user.user_id, client_user.email))
    # Never confirmed: nothing is enabled, and the pending secret cannot satisfy a login.
    assert not directory.get_two_factor(client_user.user_id).enabled
    assert directory.get_totp_secret(client_user.user_id) is None
    assert run(gate.verify_second_factor(
        client_user.user_id, StdlibTotpEngine().code_at(secret, time.time())
    )) is AuthError.SECOND_FACTOR_REQUIRED


def test_confirmation_promotes_the_pending_secret_and_clears_it(
    directory, profile, client_user
):
    import time

    gate = TwoFactorGate(directory, profile)
    secret, _ = run(gate.begin_totp_enrolment(client_user.user_id, client_user.email))
    assert directory.get_pending_totp_secret(client_user.user_id) == secret
    assert run(gate.confirm_totp_enrolment(
        client_user.user_id, StdlibTotpEngine().code_at(secret, time.time())
    ))
    assert directory.get_totp_secret(client_user.user_id) == secret
    assert directory.get_pending_totp_secret(client_user.user_id) is None
    # A replayed confirmation has nothing left to promote.
    assert not run(gate.confirm_totp_enrolment(
        client_user.user_id, StdlibTotpEngine().code_at(secret, time.time())
    ))
