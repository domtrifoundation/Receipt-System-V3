"""Real behavior of the QuickBooks/Xero adapters that doesn't require the actual SDKs
to be installed — the `is_available()`/unconfigured-degrade paths, which ARE exercised
for real in this environment (neither `intuitlib`/`quickbooks` nor `xero_python` is
installed here, confirmed via `ModuleNotFoundError`, so these are genuine, not mocked,
outcomes). The authenticated-call paths themselves are not exercised — see each
provider module's own docstring."""

from __future__ import annotations

import asyncio

import pytest

Fernet = pytest.importorskip("cryptography.fernet").Fernet

from core.accounting_sync.providers.quickbooks import QuickBooksConfig, QuickBooksProvider  # noqa: E402
from core.accounting_sync.providers.xero import XeroConfig, XeroProvider  # noqa: E402
from core.accounting_sync.token_store import TokenStore  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _store() -> TokenStore:
    return TokenStore(Fernet.generate_key())


def test_quickbooks_is_unavailable_without_configured_credentials():
    provider = QuickBooksProvider(QuickBooksConfig(), _store())

    assert run(provider.is_available()) is False


def test_quickbooks_authenticate_reports_a_real_error_when_unavailable():
    provider = QuickBooksProvider(QuickBooksConfig(), _store())

    result = run(provider.authenticate("user-1"))

    assert result.error is not None
    assert result.url == ""


def test_quickbooks_is_connected_false_for_a_user_with_no_stored_tokens():
    provider = QuickBooksProvider(QuickBooksConfig(client_id="id", client_secret="secret", redirect_uri="https://x/callback"), _store())

    assert run(provider.is_connected("nobody")) is False


def test_xero_is_unavailable_without_configured_credentials():
    provider = XeroProvider(XeroConfig(), _store())

    assert run(provider.is_available()) is False


def test_xero_authenticate_reports_a_real_error_when_unavailable():
    provider = XeroProvider(XeroConfig(), _store())

    result = run(provider.authenticate("user-1"))

    assert result.error is not None
    assert result.url == ""


def test_xero_is_connected_false_for_a_user_with_no_stored_tokens():
    provider = XeroProvider(XeroConfig(client_id="id", client_secret="secret", redirect_uri="https://x/callback"), _store())

    assert run(provider.is_connected("nobody")) is False


def test_quickbooks_disconnect_is_idempotent_when_nothing_was_ever_connected():
    provider = QuickBooksProvider(QuickBooksConfig(), _store())

    run(provider.disconnect("nobody"))  # must not raise
