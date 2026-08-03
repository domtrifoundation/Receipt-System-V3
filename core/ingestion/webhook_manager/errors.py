"""Webhook Subscription Manager's own error taxonomy — internal to this sub-package,
converted to `contracts.WebhookError` at whatever calls `subscription.py`/
`callback_handler.py` directly (this sub-API's own future `service.py`, when it gets one;
today the parent `core/ingestion/service.py` is the only caller)."""

from __future__ import annotations

__all__ = [
    "ConfirmationFailed",
    "RegistrationFailed",
    "RenewalFailed",
    "UnknownSubscription",
    "WebhookInternalError",
]


class WebhookInternalError(Exception):
    """Base for everything this sub-package raises internally."""


class RegistrationFailed(WebhookInternalError):
    """Registering a new push-notification channel with the provider failed."""


class ConfirmationFailed(WebhookInternalError):
    """The newly-registered channel could not be confirmed active — `subscription.py`'s
    own renewal flow must not deregister the old channel if this happens (deep-dive §3)."""


class RenewalFailed(WebhookInternalError):
    """The overall renewal sequence (register-new -> confirm -> deregister-old) failed at
    some step — the old subscription is left in place rather than left half-migrated."""


class UnknownSubscription(WebhookInternalError):
    """A callback or renewal request referenced a `channel_id` this manager has no record
    of — a stale/replayed callback, or a subscription this process never registered."""
