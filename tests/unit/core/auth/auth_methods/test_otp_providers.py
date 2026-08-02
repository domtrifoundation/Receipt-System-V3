"""Email and SMS one-time codes: single use, expiry, attempt caps, and degradation."""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.auth.auth_methods.email_login_provider import EmailLoginProvider
from core.auth.auth_methods.otp import generate_code
from core.auth.auth_methods.sms_login_provider import SmsLoginProvider
from core.auth.challenges import MAX_ATTEMPTS
from core.auth.contracts import AuthError, ChallengePurpose, utcnow

from ..conftest import RecordingChannel, run


@pytest.fixture
def email_channel():
    return RecordingChannel("email")


@pytest.fixture
def sms_channel():
    return RecordingChannel("sms")


@pytest.fixture
def email(challenges, directory, profile, email_channel):
    return EmailLoginProvider(challenges, directory, profile, email_channel)


@pytest.fixture
def sms(challenges, directory, profile, sms_channel):
    return SmsLoginProvider(challenges, directory, profile, sms_channel)


def test_generated_codes_are_the_configured_length_with_leading_zeros_kept():
    codes = {generate_code(6) for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 100, "codes should not be drawn from a tiny space"
    with pytest.raises(ValueError):
        generate_code(3)


def test_a_delivered_code_authenticates_the_user(email, email_channel, client_user):
    challenge = run(email.initiate(client_user.email))
    assert challenge.ok
    assert email_channel.sent[0][0] == client_user.email
    result = run(email.verify(challenge.challenge_id, email_channel.last_code))
    assert result.authenticated and result.user_id == client_user.user_id


def test_the_challenge_never_echoes_who_the_user_is(email, client_user):
    """Before the code is proven, the response says nothing about the account."""
    challenge = run(email.initiate(client_user.email))
    assert challenge.user_id is None


def test_a_code_is_single_use(email, email_channel, client_user):
    challenge = run(email.initiate(client_user.email))
    code = email_channel.last_code
    assert run(email.verify(challenge.challenge_id, code)).authenticated
    assert run(email.verify(challenge.challenge_id, code)).error is AuthError.CHALLENGE_CONSUMED


def test_a_wrong_code_is_refused_and_costs_an_attempt(email, email_channel, client_user):
    challenge = run(email.initiate(client_user.email))
    result = run(email.verify(challenge.challenge_id, "000000"))
    assert result.error is AuthError.CODE_INVALID
    # The real code still works — one wrong guess does not invalidate the challenge.
    assert run(email.verify(challenge.challenge_id, email_channel.last_code)).authenticated


def test_guessing_is_capped(email, email_channel, client_user):
    challenge = run(email.initiate(client_user.email))
    for _ in range(MAX_ATTEMPTS):
        run(email.verify(challenge.challenge_id, "000000"))
    result = run(email.verify(challenge.challenge_id, email_channel.last_code))
    assert result.error is AuthError.TOO_MANY_ATTEMPTS


def test_an_expired_code_is_refused(email, email_channel, client_user, db):
    challenge = run(email.initiate(client_user.email))
    db.write(
        "UPDATE login_challenges SET expires_at = ? WHERE challenge_id = ?",
        ((utcnow() - timedelta(seconds=1)).isoformat(), challenge.challenge_id),
    )
    result = run(email.verify(challenge.challenge_id, email_channel.last_code))
    assert result.error is AuthError.CHALLENGE_EXPIRED


def test_an_unknown_address_is_indistinguishable_from_a_known_one(email, email_channel):
    """Enumeration safety: same response shape, no message sent, nothing can satisfy it."""
    challenge = run(email.initiate("nobody@example.test"))
    assert challenge.ok
    assert email_channel.sent == []
    assert run(email.verify(challenge.challenge_id, "123456")).error is AuthError.CODE_INVALID


def test_a_down_channel_degrades_that_method_only(email, email_channel, client_user):
    email_channel.up = False
    assert not run(email.is_available())
    challenge = run(email.initiate(client_user.email))
    assert challenge.error is AuthError.METHOD_UNAVAILABLE
    assert not challenge.ok


def test_sms_looks_up_the_user_by_phone_number(sms, sms_channel, client_user):
    challenge = run(sms.initiate(client_user.phone_number))
    result = run(sms.verify(challenge.challenge_id, sms_channel.last_code))
    assert result.authenticated and result.user_id == client_user.user_id
    assert sms_channel.sent[0][0] == client_user.phone_number


def test_the_email_address_is_not_an_sms_identifier(sms, sms_channel, client_user):
    challenge = run(sms.initiate(client_user.email))
    assert sms_channel.sent == []
    assert run(sms.verify(challenge.challenge_id, "123456")).error is AuthError.CODE_INVALID


def test_step_up_purpose_survives_the_round_trip(email, email_channel, client_user):
    challenge = run(email.initiate(client_user.email, ChallengePurpose.STEP_UP))
    result = run(email.verify(challenge.challenge_id, email_channel.last_code))
    assert result.authenticated
    assert result.purpose is ChallengePurpose.STEP_UP


def test_the_stored_code_is_not_recoverable_from_the_database(
    email, email_channel, client_user, db
):
    run(email.initiate(client_user.email))
    payload = db.query_one("SELECT payload FROM login_challenges")["payload"]
    assert email_channel.last_code not in payload
