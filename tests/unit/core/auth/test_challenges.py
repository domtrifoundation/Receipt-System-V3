"""The shared challenge store: single use, purpose separation, expiry, attempt caps.

These properties live here rather than in each provider precisely so a future fifth method
cannot ship without them, and this is where that is verified.
"""

from __future__ import annotations

from datetime import timedelta

from core.auth.challenges import MAX_ATTEMPTS
from core.auth.contracts import AuthError, AuthMethod, ChallengePurpose, utcnow


def _create(challenges, purpose=ChallengePurpose.LOGIN, ttl=300):
    return challenges.create(AuthMethod.EMAIL, purpose, {"salt": "s"}, ttl, "u_1")


def test_challenge_ids_are_opaque_and_unique(challenges):
    ids = {_create(challenges).challenge_id for _ in range(50)}
    assert len(ids) == 50
    assert all(len(i) >= 32 and "u_1" not in i for i in ids)


def test_a_challenge_loads_once_and_then_reports_consumed(challenges):
    stored = _create(challenges)
    loaded, error = challenges.load(stored.challenge_id)
    assert error is None and loaded.challenge_id == stored.challenge_id
    assert challenges.consume(stored.challenge_id)
    assert challenges.load(stored.challenge_id)[1] is AuthError.CHALLENGE_CONSUMED


def test_consume_only_wins_once(challenges):
    """A conditional UPDATE, so two concurrent redemptions cannot both succeed."""
    stored = _create(challenges)
    assert challenges.consume(stored.challenge_id)
    assert not challenges.consume(stored.challenge_id)


def test_a_step_up_challenge_cannot_be_loaded_as_a_login(challenges):
    """Without this, §4.5's gate would be satisfiable by replaying an ordinary login."""
    stored = _create(challenges, ChallengePurpose.STEP_UP)
    assert challenges.load(stored.challenge_id, ChallengePurpose.LOGIN)[1] is (
        AuthError.CHALLENGE_NOT_FOUND
    )
    assert challenges.load(stored.challenge_id, ChallengePurpose.STEP_UP)[1] is None


def test_a_wrong_purpose_reads_as_not_found_not_as_wrong_purpose(challenges):
    """A caller probing ids learns nothing about which purposes exist."""
    stored = _create(challenges, ChallengePurpose.REGISTRATION)
    _, error = challenges.load(stored.challenge_id, ChallengePurpose.LOGIN)
    assert error is AuthError.CHALLENGE_NOT_FOUND
    assert challenges.load("never-existed")[1] is AuthError.CHALLENGE_NOT_FOUND


def test_expiry_is_evaluated_on_read(challenges, db):
    stored = _create(challenges)
    db.write(
        "UPDATE login_challenges SET expires_at = ? WHERE challenge_id = ?",
        ((utcnow() - timedelta(seconds=1)).isoformat(), stored.challenge_id),
    )
    assert challenges.load(stored.challenge_id)[1] is AuthError.CHALLENGE_EXPIRED


def test_attempts_are_capped(challenges):
    stored = _create(challenges)
    for expected in range(1, MAX_ATTEMPTS + 1):
        assert challenges.record_attempt(stored.challenge_id) == expected
    assert challenges.load(stored.challenge_id)[1] is AuthError.TOO_MANY_ATTEMPTS


def test_purge_is_housekeeping_only(challenges, db):
    stored = _create(challenges)
    db.write(
        "UPDATE login_challenges SET expires_at = ? WHERE challenge_id = ?",
        ((utcnow() - timedelta(minutes=5)).isoformat(), stored.challenge_id),
    )
    # Already unusable *before* the sweep — the sweep only reclaims the row.
    assert challenges.load(stored.challenge_id)[1] is AuthError.CHALLENGE_EXPIRED
    assert challenges.purge_expired() == 1
    assert challenges.load(stored.challenge_id)[1] is AuthError.CHALLENGE_NOT_FOUND


def test_payload_round_trips_as_a_mapping(challenges):
    stored = challenges.create(
        AuthMethod.SSO, ChallengePurpose.LOGIN, {"state": "abc", "nonce": "xyz"}, 60
    )
    loaded, _ = challenges.load(stored.challenge_id)
    assert loaded.payload["state"] == "abc"
    assert loaded.payload["nonce"] == "xyz"
