"""Encrypted OAuth token storage (deep-dive §5) — access/refresh tokens live encrypted,
associated with the user's own record, never in a plain queryable table alongside
business data. `SyncConnection` (`contracts.py`) itself deliberately carries no token
material; this module is the only place a real token value exists in memory at all
outside a provider's own SDK call.

**Symmetric encryption via `cryptography`'s `Fernet`** — a well-vetted, standard choice
for "encrypt small secrets at rest with a single key this process holds," not a novel
scheme. The encryption key itself is this module's own caller's responsibility to supply
(from a real secrets-management source — an environment variable, a KMS-backed value —
never hardcoded or derived here).

**`TokenStoreBackend` is a real Protocol seam, not a finished persistence layer.** The
shipped `InMemoryTokenStoreBackend` is genuinely functional (used directly by every test
in this package) but is not what a running install actually uses — a real durable,
encrypted-at-rest table structurally separate from Persistence's own business-data tables
(deep-dive §5's own "don't let a broadly-queried table also be where secrets live"
instinct) is a real, deliberately out-of-scope-for-this-pass integration point, the same
"deliberately simple for now, a real seam for later" posture `core/inference/model_
registry.py`'s own model-directory resolution takes.
"""

from __future__ import annotations

import json
import threading
from typing import Protocol

__all__ = ["InMemoryTokenStoreBackend", "TokenStore", "TokenStoreBackend"]


class TokenStoreBackend(Protocol):
    async def read(self, user_id: str, provider: str) -> bytes | None: ...
    async def write(self, user_id: str, provider: str, encrypted_tokens: bytes) -> None: ...
    async def delete(self, user_id: str, provider: str) -> None: ...


class InMemoryTokenStoreBackend:
    """A real, working backend — not a mock — genuinely thread-safe, genuinely storing
    encrypted bytes exactly as a durable backend would receive them. Not durable across a
    process restart, which is the one respect it differs from a real deployment's own
    backend (see this module's own docstring)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[tuple[str, str], bytes] = {}

    async def read(self, user_id: str, provider: str) -> bytes | None:
        with self._lock:
            return self._store.get((user_id, provider))

    async def write(self, user_id: str, provider: str, encrypted_tokens: bytes) -> None:
        with self._lock:
            self._store[(user_id, provider)] = encrypted_tokens

    async def delete(self, user_id: str, provider: str) -> None:
        with self._lock:
            self._store.pop((user_id, provider), None)


class TokenStore:
    def __init__(self, encryption_key: bytes, backend: TokenStoreBackend | None = None) -> None:
        from cryptography.fernet import Fernet

        self._fernet = Fernet(encryption_key)
        self._backend = backend or InMemoryTokenStoreBackend()

    async def store_tokens(self, user_id: str, provider: str, tokens: dict) -> None:
        plaintext = json.dumps(tokens).encode("utf-8")
        encrypted = self._fernet.encrypt(plaintext)
        await self._backend.write(user_id, provider, encrypted)

    async def load_tokens(self, user_id: str, provider: str) -> dict | None:
        encrypted = await self._backend.read(user_id, provider)
        if encrypted is None:
            return None
        plaintext = self._fernet.decrypt(encrypted)
        return json.loads(plaintext.decode("utf-8"))

    async def delete_tokens(self, user_id: str, provider: str) -> None:
        await self._backend.delete(user_id, provider)
