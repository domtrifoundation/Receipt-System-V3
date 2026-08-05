"""Webhook Subscription Manager's data contracts (`v3-deepdive-35-webhook-subscription-
manager.md` §2). Generic, provider-agnostic — nothing here is Drive-specific except
`ChangeEvent.provider` naming which provider produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WebhookProvider(str, Enum):
    GOOGLE_DRIVE = "google_drive"


class WebhookErrorCode(str, Enum):
    REGISTRATION_FAILED = "registration_failed"
    RENEWAL_FAILED = "renewal_failed"
    CONFIRMATION_FAILED = "confirmation_failed"
    UNKNOWN_SUBSCRIPTION = "unknown_subscription"


@dataclass(frozen=True)
class WebhookError:
    code: WebhookErrorCode
    detail: str = ""


@dataclass(frozen=True)
class WebhookSubscription:
    channel_id: str
    resource_id: str
    provider: WebhookProvider
    expires_at: datetime
    #: What's actually being watched (a Drive folder ID, say) — provider-specific string,
    #: opaque to this generic layer.
    watched_resource: str
    created_at: datetime = field(default_factory=utcnow)

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        return self.expires_at > now


@dataclass(frozen=True)
class ChangeEvent:
    """One "new file available" signal — this sub-API never decides run boundaries
    (deep-dive §1); Execution Core's own debounce-coalescing logic is what turns a stream
    of these into an actual run."""

    provider: WebhookProvider
    file_id: str
    change_type: str  # "added" | "modified" | "removed" — provider-reported, passed through
    detected_at: datetime = field(default_factory=utcnow)


__all__ = [
    "ChangeEvent",
    "WebhookError",
    "WebhookErrorCode",
    "WebhookProvider",
    "WebhookSubscription",
]
