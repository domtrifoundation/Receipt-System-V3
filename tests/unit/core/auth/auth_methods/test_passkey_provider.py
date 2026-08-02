"""Passkey registration and login against a fake WebAuthn engine.

The real ceremony is `py_webauthn`'s job; what these assert is Auth's own half — that a
credential is stored against the right user, that a stale sign counter is refused, and that
an unavailable library degrades the method instead of the process.
"""

from __future__ import annotations

import json

import pytest

from core.auth.auth_methods.passkey_provider import PasskeyProvider
from core.auth.contracts import AuthError, ChallengePurpose

from ..conftest import FakeWebAuthnEngine, run


@pytest.fixture
def engine():
    return FakeWebAuthnEngine()


@pytest.fixture
def provider(challenges, directory, engine):
    return PasskeyProvider(challenges, directory, rp_id="app.example.test", engine=engine)


def _assertion(credential_id="cred-1"):
    return json.dumps({"id": credential_id, "response": {"signature": "…"}})


def _register(provider, engine, user_id):
    challenge = run(provider.begin_registration(user_id))
    assert challenge.ok and challenge.purpose is ChallengePurpose.REGISTRATION
    return run(provider.complete_registration(challenge.challenge_id, _assertion()))


def test_registration_stores_the_public_key_against_the_user(
    provider, engine, directory, client_user
):
    result = _register(provider, engine, client_user.user_id)
    assert result.authenticated
    stored = directory.get_passkey(engine.credential_id)
    assert stored.user_id == client_user.user_id
    assert stored.public_key == engine.public_key


def test_registration_for_an_unknown_user_is_refused(provider):
    challenge = run(provider.begin_registration("nobody"))
    assert challenge.error is AuthError.UNKNOWN_USER


def test_a_failing_ceremony_is_reported_as_data(provider, engine, client_user):
    engine.fail = True
    challenge = run(provider.begin_registration(client_user.user_id))
    result = run(provider.complete_registration(challenge.challenge_id, _assertion()))
    assert result.error is AuthError.PASSKEY_VERIFICATION_FAILED


def test_login_authenticates_the_credential_owner(provider, engine, client_user):
    _register(provider, engine, client_user.user_id)
    engine.next_sign_count = 2
    challenge = run(provider.initiate(client_user.user_id))
    result = run(provider.verify(challenge.challenge_id, _assertion()))
    assert result.authenticated and result.user_id == client_user.user_id


def test_a_stalled_sign_counter_is_refused(provider, engine, directory, client_user):
    """The standard cloned-authenticator signal — refused rather than shrugged at."""
    _register(provider, engine, client_user.user_id)
    engine.next_sign_count = 1  # same as stored: no advance
    challenge = run(provider.initiate(client_user.user_id))
    result = run(provider.verify(challenge.challenge_id, _assertion()))
    assert result.error is AuthError.PASSKEY_VERIFICATION_FAILED
    assert "counter" in result.error_detail


def test_the_sign_counter_advances_on_success(provider, engine, directory, client_user):
    _register(provider, engine, client_user.user_id)
    engine.next_sign_count = 7
    challenge = run(provider.initiate(client_user.user_id))
    run(provider.verify(challenge.challenge_id, _assertion()))
    assert directory.get_passkey(engine.credential_id).sign_count == 7


def test_an_unknown_credential_id_fails_before_any_verification(provider, engine, client_user):
    _register(provider, engine, client_user.user_id)
    challenge = run(provider.initiate(client_user.user_id))
    result = run(provider.verify(challenge.challenge_id, _assertion("someone-elses")))
    assert result.error is AuthError.PASSKEY_VERIFICATION_FAILED


def test_a_login_challenge_is_single_use(provider, engine, client_user):
    _register(provider, engine, client_user.user_id)
    engine.next_sign_count = 3
    challenge = run(provider.initiate(client_user.user_id))
    assert run(provider.verify(challenge.challenge_id, _assertion())).authenticated
    engine.next_sign_count = 4
    assert run(provider.verify(challenge.challenge_id, _assertion())).error is (
        AuthError.CHALLENGE_CONSUMED
    )


def test_no_rp_id_means_the_method_is_unavailable(challenges, directory, engine):
    provider = PasskeyProvider(challenges, directory, rp_id="", engine=engine)
    assert not run(provider.is_available())
    assert run(provider.initiate("u")).error is AuthError.METHOD_UNAVAILABLE


def test_a_missing_library_degrades_rather_than_raising(challenges, directory, monkeypatch):
    from core.auth.auth_methods import passkey_provider as module

    monkeypatch.setattr(module.PyWebAuthnEngine, "available", staticmethod(lambda: False))
    provider = module.PasskeyProvider(challenges, directory, rp_id="app.example.test")
    assert not run(provider.is_available())
    assert run(provider.initiate("u")).error is AuthError.METHOD_UNAVAILABLE
