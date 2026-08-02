"""OIDC login, mocked at the Authlib client boundary — no network anywhere.

The first test is the regression §11 names explicitly: a session's identity keys on the IdP
subject, not the email. That assumption breaks silently and expensively, which is why it has
a test of its own rather than a comment.
"""

from __future__ import annotations

import json

import pytest

from core.auth.contracts import AuthError, AuthMethod, ChallengePurpose, Role, User
from core.auth.auth_methods.sso_provider import (
    OidcProviderConfig,
    SsoProvider,
    pkce_pair,
)

from ..conftest import FakeOidcClient, run


@pytest.fixture
def config():
    return OidcProviderConfig(
        name="google", client_id="client-id", client_secret="secret",
        redirect_uri="https://app.example.test/callback",
    )


@pytest.fixture
def client():
    return FakeOidcClient()


@pytest.fixture
def provider(challenges, directory, config, client):
    return SsoProvider(challenges, directory, config, client)


def _callback(challenge, code="auth-code"):
    return json.dumps({"code": code, "state": challenge.parameters["state"]})


def test_identity_keys_on_the_subject_not_the_email(provider, directory, staff_user, client):
    """The IdP moved the account's email. It is the same user, and the stored email is
    re-synced — keying on email would have created a stranger instead."""
    client.claims = {"sub": staff_user.sso_subject, "email": "renamed@example.test"}
    challenge = run(provider.initiate("google"))
    result = run(provider.verify(challenge.challenge_id, _callback(challenge)))
    assert result.authenticated
    assert result.user_id == staff_user.user_id
    assert directory.get(staff_user.user_id).email == "renamed@example.test"
    assert directory.get(staff_user.user_id).sso_subject == staff_user.sso_subject


def test_a_matching_email_with_a_different_subject_is_not_the_same_user(
    provider, directory, staff_user, client
):
    """The inverse of the test above, and the actually dangerous direction."""
    client.claims = {"sub": "some-other-subject", "email": staff_user.email}
    challenge = run(provider.initiate("google"))
    result = run(provider.verify(challenge.challenge_id, _callback(challenge)))
    assert not result.authenticated
    assert result.error is AuthError.UNKNOWN_USER


def test_state_mismatch_is_reported_as_a_replay_indicator(provider, staff_user):
    challenge = run(provider.initiate("google"))
    forged = json.dumps({"code": "auth-code", "state": "not-the-issued-state"})
    result = run(provider.verify(challenge.challenge_id, forged))
    assert result.error is AuthError.OIDC_STATE_MISMATCH


def test_missing_state_is_also_a_mismatch(provider, staff_user):
    challenge = run(provider.initiate("google"))
    result = run(provider.verify(challenge.challenge_id, json.dumps({"code": "c"})))
    assert result.error is AuthError.OIDC_STATE_MISMATCH


def test_pkce_verifier_is_never_sent_to_the_browser(provider, challenges):
    challenge = run(provider.initiate("google"))
    assert "code_verifier" not in challenge.parameters
    assert "nonce" not in challenge.parameters
    stored, error = challenges.load(challenge.challenge_id)
    assert error is None and stored.payload["code_verifier"]


def test_pkce_pair_is_s256_of_the_verifier():
    import base64
    import hashlib

    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    assert challenge == expected
    assert "=" not in challenge


def test_the_verifier_reaches_the_token_exchange(provider, staff_user, client, challenges):
    challenge = run(provider.initiate("google"))
    stored, _ = challenges.load(challenge.challenge_id)
    run(provider.verify(challenge.challenge_id, _callback(challenge)))
    assert client.exchanges[0][1] == stored.payload["code_verifier"]


def test_a_callback_can_arrive_as_a_query_string(provider, staff_user):
    challenge = run(provider.initiate("google"))
    query = f"?code=auth-code&state={challenge.parameters['state']}"
    assert run(provider.verify(challenge.challenge_id, query)).authenticated


def test_a_challenge_is_single_use(provider, staff_user):
    challenge = run(provider.initiate("google"))
    assert run(provider.verify(challenge.challenge_id, _callback(challenge))).authenticated
    second = run(provider.verify(challenge.challenge_id, _callback(challenge)))
    assert second.error is AuthError.CHALLENGE_CONSUMED


def test_a_failed_token_exchange_is_data_not_an_exception(provider, staff_user, client):
    client.fail_exchange = True
    challenge = run(provider.initiate("google"))
    result = run(provider.verify(challenge.challenge_id, _callback(challenge)))
    assert not result.authenticated and result.error is AuthError.CODE_INVALID


def test_unconfigured_sso_is_unavailable_rather_than_broken(challenges, directory):
    provider = SsoProvider(challenges, directory, OidcProviderConfig(), client=None)
    assert not run(provider.is_available())
    challenge = run(provider.initiate("google"))
    assert challenge.error is AuthError.METHOD_UNAVAILABLE
    assert not challenge.ok


def test_a_provider_that_is_not_enabled_is_refused(provider):
    assert run(provider.initiate("okta")).error is AuthError.METHOD_UNAVAILABLE


def test_step_up_purpose_is_carried_through(provider, staff_user):
    challenge = run(provider.initiate("google", ChallengePurpose.STEP_UP))
    result = run(provider.verify(challenge.challenge_id, _callback(challenge)))
    assert result.purpose is ChallengePurpose.STEP_UP
    assert result.method is AuthMethod.SSO


def test_a_second_account_on_the_same_provider_stays_distinct(provider, directory, client):
    directory.create_user(User(
        user_id="u_a", role=Role.CLIENT, email="a@example.test",
        sso_provider="google", sso_subject="sub-a",
    ))
    directory.create_user(User(
        user_id="u_b", role=Role.CLIENT, email="b@example.test",
        sso_provider="google", sso_subject="sub-b",
    ))
    client.claims = {"sub": "sub-b", "email": "b@example.test"}
    challenge = run(provider.initiate("google"))
    assert run(provider.verify(challenge.challenge_id, _callback(challenge))).user_id == "u_b"
