"""Billing error taxonomy.

Surfaced as `error_code`/`error_detail` on the result contracts rather than raised across the
boundary (`docs/PRINCIPLES.md` §4.1).

**§5's webhook verification is the one place this package fails closed hard**, and the
deep-dive is unusually direct about why: "an unverified webhook endpoint is a real,
exploitable surface (anyone who discovers the URL could fake a 'payment succeeded' event
without this check), not a theoretical concern." So an unverifiable signature is a rejection,
never a warning, never a "process it and flag it" — the whole point is that an attacker who
finds the URL learns nothing and achieves nothing.

Everywhere else the posture is ordinary graceful degradation. An unreachable PSP means a charge
whose status is *unknown*, and unknown is deliberately not failure: treating silence as failure
would either refund money that was taken or re-charge a card that already paid.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class BillingError(Exception):
    """Base for everything this API raises internally, never across its boundary."""


class BillingNotConfigured(BillingError):
    """A paid operation attempted while billing is off or has no credentials (§3.1).

    Not an error state to route around — it is the shipped default. A fresh install runs every
    tier free with no PSP configured, and any code path that treated this as a failure would
    break the ordinary case rather than an exceptional one.
    """


class UnknownSubscription(BillingError):
    """An operation naming a subscription nothing has recorded."""


class WebhookSignatureInvalid(BillingError):
    """§5's hard requirement: the payload was not signed by the configured provider.

    Rejected outright. Anyone who discovers the webhook URL could otherwise fake a
    "payment succeeded" event, which would grant a paid tier for free — and, worse, would look
    identical to a real payment in every downstream record.
    """


class DuplicateWebhookEvent(BillingError):
    """A correctly-signed event this API has already processed.

    Kept distinct from a signature rejection, because the two mean opposite things to whoever
    is investigating: one is an attack surface working as designed, the other is a PSP retrying
    delivery, which is normal and expected behaviour from every payment provider.
    """


class ChargesBlockedByDeletionHold(BillingError):
    """A new charge attempted against a subscription in `PENDING_DELETION_HOLD` (§4).

    A deletion request "stops new charges immediately". Charging a user who has asked to be
    deleted is the kind of thing that ends up in a complaint rather than a bug report.
    """


class ProviderUnavailable(BillingError):
    """The PSP could not be reached.

    Yields an *unknown* charge status, never a failed one. See this module's docstring: guessing
    either way costs real money in one direction or the other.
    """


class InvalidTierChange(BillingError):
    """A tier change to the tier already held, or to an empty tier name."""


ERROR_CODES: FrozenDict = FrozenDict(
    {
        BillingNotConfigured: "BILLING_NOT_CONFIGURED",
        UnknownSubscription: "UNKNOWN_SUBSCRIPTION",
        WebhookSignatureInvalid: "WEBHOOK_SIGNATURE_INVALID",
        DuplicateWebhookEvent: "DUPLICATE_WEBHOOK_EVENT",
        ChargesBlockedByDeletionHold: "CHARGES_BLOCKED_BY_DELETION_HOLD",
        ProviderUnavailable: "PROVIDER_UNAVAILABLE",
        InvalidTierChange: "INVALID_TIER_CHANGE",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "BILLING_NOT_CONFIGURED": "Billing is not enabled or has no provider credentials.",
        "UNKNOWN_SUBSCRIPTION": "No subscription exists with that id.",
        "WEBHOOK_SIGNATURE_INVALID": "The webhook payload was not signed by the configured provider.",
        "DUPLICATE_WEBHOOK_EVENT": "That webhook event has already been processed.",
        "CHARGES_BLOCKED_BY_DELETION_HOLD": (
            "The subscription is on a deletion hold; new charges are stopped."
        ),
        "PROVIDER_UNAVAILABLE": "The payment provider could not be reached.",
        "INVALID_TIER_CHANGE": "That tier change is not a real change.",
        "INTERNAL": "An unmapped internal error.",
    }
)


def code_for(exc: BaseException) -> str:
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "BillingError",
    "BillingNotConfigured",
    "ChargesBlockedByDeletionHold",
    "DuplicateWebhookEvent",
    "InvalidTierChange",
    "ProviderUnavailable",
    "UnknownSubscription",
    "WebhookSignatureInvalid",
    "code_for",
    "summary_for",
]
