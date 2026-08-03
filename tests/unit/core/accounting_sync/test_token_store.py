"""`TokenStore` — real `Fernet` symmetric encryption, not a mock (deep-dive §5)."""

from __future__ import annotations

import asyncio

import pytest

# `cryptography` has no wheel guaranteed on the `forward_compat` sessions' minimal
# install list (`noxfile.py`'s `FORWARD_COMPAT_DEPS`), same collection-time-skip pattern
# `core/auth`'s and `core/account_guardian`'s own tests use for their own gRPC-dependent gaps.
cryptography_fernet = pytest.importorskip("cryptography.fernet")
Fernet = cryptography_fernet.Fernet
InvalidToken = cryptography_fernet.InvalidToken

from core.accounting_sync.token_store import TokenStore  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_stored_bytes_do_not_contain_the_plaintext_secret():
    key = Fernet.generate_key()
    store = TokenStore(key)

    run(store.store_tokens("user-1", "quickbooks", {"access_token": "super-secret-value"}))

    raw = run(store._backend.read("user-1", "quickbooks"))
    assert raw is not None
    assert b"super-secret-value" not in raw


def test_round_trip_returns_the_original_tokens():
    key = Fernet.generate_key()
    store = TokenStore(key)
    tokens = {"access_token": "a", "refresh_token": "b", "realm_id": "123"}

    run(store.store_tokens("user-1", "quickbooks", tokens))
    loaded = run(store.load_tokens("user-1", "quickbooks"))

    assert loaded == tokens


def test_load_tokens_returns_none_when_nothing_stored():
    store = TokenStore(Fernet.generate_key())

    assert run(store.load_tokens("nobody", "quickbooks")) is None


def test_delete_tokens_removes_the_stored_record():
    key = Fernet.generate_key()
    store = TokenStore(key)
    run(store.store_tokens("user-1", "quickbooks", {"access_token": "a"}))

    run(store.delete_tokens("user-1", "quickbooks"))

    assert run(store.load_tokens("user-1", "quickbooks")) is None


def test_decrypting_with_the_wrong_key_raises_invalid_token():
    store_a = TokenStore(Fernet.generate_key())
    store_b = TokenStore(Fernet.generate_key())
    run(store_a.store_tokens("user-1", "quickbooks", {"access_token": "a"}))

    raw = run(store_a._backend.read("user-1", "quickbooks"))
    run(store_b._backend.write("user-1", "quickbooks", raw))

    with pytest.raises(InvalidToken):
        run(store_b.load_tokens("user-1", "quickbooks"))


def test_two_users_tokens_do_not_collide():
    store = TokenStore(Fernet.generate_key())
    run(store.store_tokens("user-1", "quickbooks", {"access_token": "a"}))
    run(store.store_tokens("user-2", "quickbooks", {"access_token": "b"}))

    assert run(store.load_tokens("user-1", "quickbooks"))["access_token"] == "a"
    assert run(store.load_tokens("user-2", "quickbooks"))["access_token"] == "b"
