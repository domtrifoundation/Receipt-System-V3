"""Cookie attributes and the CSRF synchronizer token — including the failure injection
§11 asks for: a mutating request with no token must be rejected, not waved through on
`SameSite=Lax` alone."""

from __future__ import annotations

import pytest

from core.auth.contracts import AuthError
from core.auth.session.cookie import (
    SESSION_COOKIE_NAME,
    build_clear_cookie,
    build_set_cookie,
    check_csrf,
    read_session_cookie,
    requires_csrf,
)


def test_issued_cookie_is_httponly_secure_and_samesite_lax():
    header = build_set_cookie("abc123", max_age_seconds=3600)
    assert header.startswith(f"{SESSION_COOKIE_NAME}=abc123")
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=Lax" in header
    assert "Max-Age=3600" in header


def test_secure_is_only_dropped_when_explicitly_asked_for():
    """A localhost developer install is the only reason to drop it, and it has to be a
    visible decision at the call site."""
    assert "Secure" not in build_set_cookie("abc", 60, secure=False)
    assert "Secure" in build_set_cookie("abc", 60)


def test_clear_cookie_expires_immediately():
    header = build_clear_cookie()
    assert "Max-Age=0" in header
    assert f"{SESSION_COOKIE_NAME}=" in header


def test_reading_a_cookie_header():
    assert read_session_cookie(f"other=1; {SESSION_COOKIE_NAME}=xyz") == "xyz"
    assert read_session_cookie("") is None
    assert read_session_cookie(None) is None
    assert read_session_cookie("garbage-without-equals") is None


@pytest.mark.parametrize("method", ["POST", "put", "PATCH", "delete"])
def test_mutating_methods_require_a_token(method):
    assert requires_csrf(method)


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_read_methods_do_not(method):
    assert not requires_csrf(method)
    assert check_csrf(method, None, None) is None


def test_missing_token_on_a_mutating_request_is_rejected():
    """Failure injection, §11: the request is refused rather than silently accepted."""
    assert check_csrf("POST", None, "expected") is AuthError.CSRF_TOKEN_INVALID
    assert check_csrf("POST", "", "expected") is AuthError.CSRF_TOKEN_INVALID


def test_unknown_session_fails_closed():
    """No expected token means an unknown or dead session. Fail closed — never a
    "cannot check, allow it" branch (`docs/PRINCIPLES.md` §4.2)."""
    assert check_csrf("DELETE", "anything", None) is AuthError.CSRF_TOKEN_INVALID
    assert check_csrf("DELETE", "anything", "") is AuthError.CSRF_TOKEN_INVALID


def test_mismatched_token_is_rejected_and_matching_token_passes():
    assert check_csrf("POST", "wrong", "right") is AuthError.CSRF_TOKEN_INVALID
    assert check_csrf("POST", "right", "right") is None
