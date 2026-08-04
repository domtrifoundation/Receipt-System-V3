"""Real GitHub App authentication — minting a signed App JWT and exchanging it for a
short-lived installation access token, exactly the mechanism the owning plan document
specifies: "Authenticated via a GitHub App, not a personal access token... a GitHub App
is org-owned, installable on just the specific repo(s), scoped precisely to `issues`
read/write and nothing else, and issues short-lived auto-rotating installation tokens
instead of one long-lived static secret" (`v3-plan-01-core-apis.md` #27).

**No `PyJWT` dependency** — `cryptography` is already a real dependency elsewhere in
this project (Accounting Sync's OAuth token storage), and RS256 JWT signing is a small
enough operation to implement directly against it rather than adding a second JWT
library for one function.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

__all__ = ["mint_app_jwt", "mint_installation_token"]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_app_jwt(app_id: str, private_key_pem: bytes, *, now: int | None = None) -> str:
    """A real RS256-signed JWT per GitHub's own App authentication spec — `iat`/`exp`
    windowed per GitHub's documented tolerance (issued 60s in the past to tolerate clock
    drift, expires in 9 minutes — GitHub's own hard ceiling is 10)."""
    issued_at = now if now is not None else int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": issued_at - 60, "exp": issued_at + 540, "iss": app_id}

    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}." \
                    f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"

    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    signature = private_key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


async def mint_installation_token(app_id: str, private_key_pem: bytes, installation_id: str) -> str:
    """Exchanges a real App JWT for a real, short-lived installation access token —
    GitHub's own documented two-step App auth flow. Raises `httpx.HTTPStatusError` on
    any failure; callers decide how to surface that (`issue_filer.py`'s own `file_issue`
    turns it into data, never lets it escape as an exception)."""
    app_jwt = mint_app_jwt(app_id, private_key_pem)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        return response.json()["token"]
