"""Subscription register/renew/deregister — the generic, provider-agnostic machinery
(deep-dive §1, §3). `renew()`'s own ordering is the one load-bearing correctness property
this module exists to guarantee: **register-new -> confirm-active -> deregister-old,
never stop-then-start** — stop-then-start would open a real delivery gap between the old
channel dying and the new one being confirmed live, during which an arriving file would
simply never trigger anything.

`WebhookProviderAdapter` is the seam a real provider's own quirks hide behind — today only
`DriveWebhookAdapter` exists, and it is **not live-tested this session** (no real Drive
API/network call made; `google-api-python-client` is not installed in this session's
`.venv` either, same as `sources/google_drive/`'s own honestly-flagged modules). The
renewal *orchestration* logic itself — the actual thing deep-dive §9 names as the required
regression test — is fully tested against fake adapters, since that logic is provider-
independent by design.
"""

from __future__ import annotations

from typing import Protocol

from .contracts import WebhookSubscription
from .errors import ConfirmationFailed, RegistrationFailed, RenewalFailed

__all__ = ["DriveWebhookAdapter", "WebhookProviderAdapter", "renew"]


class WebhookProviderAdapter(Protocol):
    async def register(self, watched_resource: str) -> WebhookSubscription:
        """Registers a genuinely NEW channel — never reuses an existing channel ID."""
        ...

    async def confirm_active(self, subscription: WebhookSubscription) -> bool:
        """A real check the channel is actually live, not just that registration
        returned successfully."""
        ...

    async def deregister(self, subscription: WebhookSubscription) -> None:
        """Best-effort — a failure here does not undo an already-confirmed new channel."""
        ...


async def renew(
    old_subscription: WebhookSubscription, adapter: WebhookProviderAdapter
) -> WebhookSubscription:
    """Deep-dive §3, verbatim in shape. Raises `RenewalFailed` if registration or
    confirmation fails — the old subscription is left untouched in that case, since it is
    still (presumably) active and deregistering it would be strictly worse than doing
    nothing."""
    try:
        new_subscription = await adapter.register(old_subscription.watched_resource)
    except Exception as exc:  # noqa: BLE001 - any registration failure blocks renewal
        raise RenewalFailed(f"registration failed: {exc}") from exc

    try:
        confirmed = await adapter.confirm_active(new_subscription)
    except Exception as exc:  # noqa: BLE001 - any confirmation failure blocks renewal
        raise RenewalFailed(f"confirmation check failed: {exc}") from exc
    if not confirmed:
        raise ConfirmationFailed(
            f"newly registered channel {new_subscription.channel_id!r} did not confirm active"
        )

    # Only now, after confirmation, is it safe to deregister the old channel — deregister
    # failures are logged/best-effort, not fatal to the renewal itself, since the new
    # channel is already confirmed live and is what actually matters going forward.
    try:
        await adapter.deregister(old_subscription)
    except Exception:  # noqa: BLE001 - best-effort cleanup, see docstring
        pass

    return new_subscription


class DriveWebhookAdapter:
    """`WebhookProviderAdapter` for Google Drive's `files.watch()` push notifications.

    **Not live-tested this session** — no real Drive credentials/network call was made;
    same honesty posture as `sources/google_drive/`'s own unverified modules. Built
    directly from the Drive v3 API's own published `watch`/`channels.stop` shapes.
    """

    def __init__(self, credentials, callback_url: str) -> None:
        self._credentials = credentials
        self._callback_url = callback_url

    async def register(self, watched_resource: str) -> WebhookSubscription:
        import asyncio
        import uuid
        from datetime import datetime, timedelta, timezone

        from .contracts import WebhookProvider

        loop = asyncio.get_running_loop()
        try:
            service = await loop.run_in_executor(None, self._credentials.get_service)
            channel_id = str(uuid.uuid4())
            body = {"id": channel_id, "type": "web_hook", "address": self._callback_url}
            response = await loop.run_in_executor(
                None,
                lambda: service.files().watch(fileId=watched_resource, body=body).execute(),
            )
        except Exception as exc:  # noqa: BLE001 - any Drive API failure is a registration failure
            raise RegistrationFailed(f"{type(exc).__name__}: {exc}") from exc

        expiration_ms = response.get("expiration")
        expires_at = (
            datetime.fromtimestamp(int(expiration_ms) / 1000, tz=timezone.utc)
            if expiration_ms else datetime.now(timezone.utc) + timedelta(days=7)
        )
        return WebhookSubscription(
            channel_id=response.get("id", channel_id),
            resource_id=response.get("resourceId", ""),
            provider=WebhookProvider.GOOGLE_DRIVE,
            expires_at=expires_at,
            watched_resource=watched_resource,
        )

    async def confirm_active(self, subscription: WebhookSubscription) -> bool:
        # Drive has no direct "is this channel alive" query — registration succeeding is
        # the only confirmation signal the API itself offers. A real liveness check here
        # would need Circadian's own delivery-rhythm inference (`circadian.py`), which
        # operates on a longer timescale than a synchronous renewal call can wait for.
        return bool(subscription.channel_id and subscription.resource_id)

    async def deregister(self, subscription: WebhookSubscription) -> None:
        import asyncio

        loop = asyncio.get_running_loop()
        service = await loop.run_in_executor(None, self._credentials.get_service)
        await loop.run_in_executor(
            None,
            lambda: service.channels().stop(
                body={"id": subscription.channel_id, "resourceId": subscription.resource_id}
            ).execute(),
        )
