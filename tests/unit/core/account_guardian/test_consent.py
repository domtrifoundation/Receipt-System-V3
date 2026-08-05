"""Consent tracking (`consent.py`, deep-dive §7 — added beyond the deep-dive's own §2 package
layout, see this package's `CLAUDE.md`).

The one guarantee this file exists to prove above ordinary CRUD coverage: publishing a new
document version never retroactively counts as an existing user having accepted it (§7.2),
and the re-consent gate only actually bites for a version an owner flagged
`requires_reconsent=True` (§7.3–§7.4).
"""

from __future__ import annotations

import pytest

from core.account_guardian import consent
from core.account_guardian.contracts import ConsentDocumentType
from core.account_guardian.errors import ReconsentRequired

from .conftest import run

TOS = ConsentDocumentType.TERMS_OF_SERVICE


def test_no_version_ever_published_means_nothing_to_gate_on(db):
    result = run(consent.check_consent(db, "user_a", TOS))
    assert result.has_valid_consent
    assert result.current_version is None


def test_a_non_reconsent_version_does_not_block_a_user_with_no_record_at_all(db):
    run(consent.publish_version(db, TOS, "v1", "config/tos_v1.md", requires_reconsent=False))

    result = run(consent.check_consent(db, "user_a", TOS))

    assert result.has_valid_consent


def test_a_reconsent_flagged_version_blocks_until_explicitly_accepted(db):
    run(consent.publish_version(db, TOS, "v2", "config/tos_v2.md", requires_reconsent=True))

    before = run(consent.check_consent(db, "user_a", TOS))
    assert not before.has_valid_consent
    assert before.current_version.version == "v2"

    run(consent.record_consent(db, "user_a", TOS, "v2"))
    after = run(consent.check_consent(db, "user_a", TOS))
    assert after.has_valid_consent


def test_accepting_an_old_version_does_not_satisfy_a_newer_reconsent_flagged_one(db):
    """§7.2's own stated property: acceptance is tied to a *specific* version."""
    run(consent.publish_version(db, TOS, "v1", "config/tos_v1.md", requires_reconsent=True))
    run(consent.record_consent(db, "user_a", TOS, "v1"))
    assert run(consent.check_consent(db, "user_a", TOS)).has_valid_consent

    run(consent.publish_version(db, TOS, "v2", "config/tos_v2.md", requires_reconsent=True))

    result = run(consent.check_consent(db, "user_a", TOS))
    assert not result.has_valid_consent, "publishing v2 must not retroactively count v1's acceptance"


def test_document_types_are_tracked_independently(db):
    privacy = ConsentDocumentType.PRIVACY_POLICY
    run(consent.publish_version(db, TOS, "v1", "config/tos_v1.md", requires_reconsent=True))
    run(consent.publish_version(db, privacy, "v1", "config/privacy_v1.md", requires_reconsent=True))
    run(consent.record_consent(db, "user_a", TOS, "v1"))

    assert run(consent.check_consent(db, "user_a", TOS)).has_valid_consent
    assert not run(consent.check_consent(db, "user_a", privacy)).has_valid_consent


def test_assert_consented_raises_the_internal_gate_when_blocked(db):
    """Internal-only, never crosses the gRPC boundary (`errors.py`) — `service.py` is what
    turns this into a data result on every RPC except the consent RPCs themselves."""
    run(consent.publish_version(db, TOS, "v1", "config/tos_v1.md", requires_reconsent=True))

    with pytest.raises(ReconsentRequired):
        run(consent.assert_consented(db, "user_a", TOS))

    run(consent.record_consent(db, "user_a", TOS, "v1"))
    run(consent.assert_consented(db, "user_a", TOS))  # must not raise now


def test_publishing_a_new_version_replaces_which_one_is_current(db):
    run(consent.publish_version(db, TOS, "v1", "config/tos_v1.md"))
    run(consent.publish_version(db, TOS, "v2", "config/tos_v2.md"))

    current = run(consent.current_version(db, TOS))

    assert current.version == "v2"
