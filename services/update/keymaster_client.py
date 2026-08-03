"""`KeymasterClient` — the outbound HTTP call to Keymaster (deep-dive §4).

**Keymaster is not part of this repo.** `v3-plan-02-architecture.md` is explicit about why:
license-validation logic that ships inside every self-hosted clone would sit on the exact
machine it is meant to be checking, fully readable and patchable by the person it is meant to
validate — "not a real check." Keymaster lives in its own separate, DOMTRI-only repo whose
source never reaches a customer's machine. What this module is: a plain outbound HTTPS call,
"the same category as calling PayMongo/GitHub/LocationIQ" (§4) — this project already calls
external paid/closed services elsewhere and always through one small adapter, never scattered
call sites (`docs/PRINCIPLES.md` §1.3).

**The wire contract below is this project's own design** (Keymaster's own repo is what actually
implements the server side; nothing in this corpus specifies field names) — kept deliberately
minimal and RESTful, matching this project's existing PSP/geocoding client shapes:

    POST {base_url}/v1/clone-tokens
    { "license_key": "RESIBO-XXXX-XXXX-XXXX-XXXX", "instance_id": "<uuid>" }

    200 OK
    { "token": "<short-lived scoped GitHub token>", "expires_at": "<RFC 3339>" }

    any other status -> a single generic rejection, deliberately without a machine-readable
    reason in the body: §4's own "every failure mode (wrong key, unactivated, expired) returns
    an identical generic rejection" — a validator that reveals *why* a key failed leaks
    information an attacker could use to narrow down real keys. This module still distinguishes
    *locally* between "the network was unreachable" and "the server rejected the request" for an
    operator's own logs (`KeymasterRejectionReason`, `contracts.py`) — that distinction is
    private to this client's own observation of its own request, never sent anywhere Keymaster
    or an attacker could read it back.

**Fail-open, always** (§4): this client never raises. A network error, a rejection, and a
malformed response are all `KeymasterResult`s with `token=None` — the caller's own policy
decides what that means (refuse a clone against a private repo; proceed unauthenticated against
today's still-public one; the bootstrap script's raw shell/batch equivalent of this same call
makes the same decision independently, since it runs before this module is even on disk).
"""

from __future__ import annotations

from datetime import datetime

import httpx

from .contracts import KeymasterRejectionReason, KeymasterResult, KeymasterToken

__all__ = ["CLONE_TOKEN_PATH", "KeymasterClient"]

CLONE_TOKEN_PATH = "/v1/clone-tokens"


class KeymasterClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def get_scoped_clone_token(self, license_key: str, instance_id: str) -> KeymasterResult:
        if not license_key:
            return KeymasterResult(rejection=KeymasterRejectionReason.NO_KEY_CONFIGURED)

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}{CLONE_TOKEN_PATH}",
                    json={"license_key": license_key, "instance_id": instance_id},
                )
        except httpx.HTTPError:
            return KeymasterResult(rejection=KeymasterRejectionReason.NETWORK_UNREACHABLE)

        if response.status_code != 200:
            return KeymasterResult(rejection=KeymasterRejectionReason.SERVER_REJECTED)

        try:
            body = response.json()
            token = KeymasterToken(
                token=body["token"],
                expires_at=datetime.fromisoformat(body["expires_at"]),
            )
        except (ValueError, KeyError, TypeError):
            return KeymasterResult(rejection=KeymasterRejectionReason.MALFORMED_RESPONSE)

        return KeymasterResult(token=token)
