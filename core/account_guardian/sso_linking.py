"""SSO provider change — request intake (deep-dive §2 marks this "future": linking a second
SSO provider to one account).

**Two real gaps keep this module at the intake half of the feature, not a working mutation
end to end — both documented here rather than worked around with a guess**
(`docs/PRINCIPLES.md` §4.3):

1. Auth's own `users` table (`core/auth/store.py`) has exactly one nullable
   `sso_provider`/`sso_subject` pair per user, not a one-to-many relation — "linking a
   *second* provider" is not structurally representable in Auth's schema today. That is
   Auth's call to make, not something to route around here.
2. Even a same-provider re-link has no mutation RPC on `auth.proto` at all — only the login
   flow itself ever writes those columns (`UserDirectory.create_user`/`sync_email`).
   `gateways.py` documents this as a `CapabilityMissing` case structurally, the same as
   `list_sessions`.

So `request_link()` below does the part that *is* real: validates the provider against a
small internal Provider Registry (`contracts.KNOWN_SSO_PROVIDERS`, never a hardcoded
`if provider == "google"`), requires proof of a fresh step-up re-authentication — changing a
linked SSO account is one of `core/auth/`'s own named examples of a sensitive, step-up-gated
action (Auth deep-dive §4.5) — records the case, and reports its stage as
`PENDING_AUTH_MUTATION` rather than pretending completion.

**`step_up_confirmed` is a boolean the caller asserts, not something this module verifies
itself.** The real verification is Auth's own `InitiateStepUpReauth`/`CompleteStepUpReauth`
RPCs (`auth.proto`) — `service.py`'s own RPC handler is the layer that actually drives that
exchange and only calls `request_link()` once Auth reports it satisfied, the identical shape
`core/auth/service.py.ConfigureTwoFactor` uses for its own step-up gate. A caller that skips
that exchange and passes `step_up_confirmed=True` anyway has lied to this function, which is
a caller bug this module cannot detect from inside — the actual gate lives in `service.py`,
where the real Auth round trip happens.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from .contracts import KNOWN_SSO_PROVIDERS, SsoLinkRequest, SsoLinkResult, SsoLinkStage, utcnow
from .errors import AlreadyResolved, InvalidRequest, NotFound, OwnershipDenied, UnsupportedProvider
from .gateways import AuditGateway, PROPOSED_AUDIT_OPERATIONS
from .store import AccountGuardianDatabase, in_thread

_OPEN_STAGES = (SsoLinkStage.REQUESTED, SsoLinkStage.STEP_UP_PENDING)


def new_request_id() -> str:
    return f"sso_{uuid.uuid4().hex}"


def _row_to_request(row) -> SsoLinkRequest:
    return SsoLinkRequest(
        request_id=row["request_id"],
        user_id=row["user_id"],
        provider=row["provider"],
        requested_at=datetime.fromisoformat(row["requested_at"]),
        stage=SsoLinkStage(row["stage"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        error_detail=row["error_detail"] or "",
    )


def _get_sync(db: AccountGuardianDatabase, request_id: str) -> SsoLinkRequest | None:
    row = db.query_one("SELECT * FROM sso_link_requests WHERE request_id = ?", (request_id,))
    return _row_to_request(row) if row else None


async def get(db: AccountGuardianDatabase, request_id: str) -> SsoLinkRequest | None:
    return await in_thread(_get_sync, db, request_id)


async def list_for_user(db: AccountGuardianDatabase, user_id: str) -> tuple[SsoLinkRequest, ...]:
    def _read() -> list[SsoLinkRequest]:
        rows = db.query_all(
            "SELECT * FROM sso_link_requests WHERE user_id = ? ORDER BY requested_at DESC",
            (user_id,),
        )
        return [_row_to_request(r) for r in rows]

    return tuple(await in_thread(_read))


async def request_link(
    db: AccountGuardianDatabase,
    audit: AuditGateway,
    user_id: str,
    provider: str,
    step_up_confirmed: bool,
) -> SsoLinkResult:
    if provider not in KNOWN_SSO_PROVIDERS:
        return SsoLinkResult(
            error=UnsupportedProvider.code,
            error_detail=(
                f"{provider!r} is not one of the SSO providers Auth & Tenancy can "
                f"authenticate against: {sorted(KNOWN_SSO_PROVIDERS)}"
            ),
        )
    if not step_up_confirmed:
        return SsoLinkResult(
            error=InvalidRequest.code,
            error_detail=(
                "changing a linked SSO provider requires a fresh step-up re-authentication "
                "first (core/auth/'s own §4.5) — complete that before requesting the change"
            ),
        )

    now = utcnow()
    request = SsoLinkRequest(
        request_id=new_request_id(), user_id=user_id, provider=provider, requested_at=now,
        stage=SsoLinkStage.PENDING_AUTH_MUTATION,
        error_detail=(
            "step-up confirmed; the actual identity mutation is blocked on Auth exposing an "
            "SSO-link RPC (see this package's CLAUDE.md and gateways.py)"
        ),
    )

    def _write() -> None:
        db.write(
            "INSERT INTO sso_link_requests (request_id, user_id, provider, requested_at,"
            " stage, completed_at, error_detail) VALUES (?,?,?,?,?,NULL,?)",
            (
                request.request_id, user_id, provider, now.isoformat(), request.stage.value,
                request.error_detail,
            ),
        )

    await in_thread(_write)
    outcome = await audit.record(
        PROPOSED_AUDIT_OPERATIONS["sso_provider_change_requested"], user_id,
        target_user_id=user_id, reason="user-initiated SSO provider change request",
        details={"request_id": request.request_id, "provider": provider},
    )
    return SsoLinkResult(
        request=request, audit_recorded=outcome.recorded,
        audit_error=outcome.error_detail if not outcome.recorded else "",
    )


async def cancel(db: AccountGuardianDatabase, request_id: str, acting_user_id: str) -> SsoLinkResult:
    existing = await get(db, request_id)
    if existing is None:
        return SsoLinkResult(error=NotFound.code, error_detail=f"no such request {request_id!r}")
    if existing.user_id != acting_user_id:
        return SsoLinkResult(
            error=OwnershipDenied.code,
            error_detail=f"request {request_id!r} does not belong to this account",
        )
    if existing.stage in (SsoLinkStage.COMPLETED, SsoLinkStage.REJECTED):
        return SsoLinkResult(
            error=AlreadyResolved.code,
            error_detail=f"request {request_id!r} is already {existing.stage.value}",
        )

    def _write() -> None:
        db.write(
            "UPDATE sso_link_requests SET stage = ? WHERE request_id = ?",
            (SsoLinkStage.REJECTED.value, request_id),
        )

    await in_thread(_write)
    resolved = SsoLinkRequest(
        request_id=existing.request_id, user_id=existing.user_id, provider=existing.provider,
        requested_at=existing.requested_at, stage=SsoLinkStage.REJECTED,
        error_detail="cancelled by the requesting user",
    )
    return SsoLinkResult(request=resolved)


__all__ = ["cancel", "get", "list_for_user", "new_request_id", "request_link"]
