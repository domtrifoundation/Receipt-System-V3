"""`BillingServicer` — the real assembly point wiring `subscription.SubscriptionService`
to `billing.proto`'s wire surface. `CLAUDE.md`'s own "Known gaps" section named this by
name: a four-RPC surface specified in the deep-dive with no `.proto` compiled at all."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.billing.generated import billing_pb2 as pb  # noqa: E402
from core.billing.service import BillingServicer  # noqa: E402
from core.billing.subscription import SubscriptionService  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_create_subscription_rpc_creates_an_active_subscription():
    servicer = BillingServicer(SubscriptionService())

    response = run(servicer.CreateSubscription(pb.CreateSubRequest(user_id="user-1", tier="pro")))

    assert response.error_code == ""
    assert response.subscription.tier == "pro"
    assert response.subscription.status == "active"
    assert response.subscription.user_id == "user-1"


def test_create_subscription_rpc_rejects_a_missing_tier():
    servicer = BillingServicer(SubscriptionService())

    response = run(servicer.CreateSubscription(pb.CreateSubRequest(user_id="user-1", tier="")))

    assert response.error_code != ""
    assert not response.HasField("subscription")


def test_get_subscription_status_rpc_returns_the_real_subscription():
    servicer = BillingServicer(SubscriptionService())
    created = run(servicer.CreateSubscription(pb.CreateSubRequest(user_id="user-1", tier="pro")))

    response = run(servicer.GetSubscriptionStatus(pb.StatusRequest(subscription_id=created.subscription.subscription_id)))

    assert response.error_code == ""
    assert response.subscription.subscription_id == created.subscription.subscription_id


def test_get_subscription_status_rpc_reports_unknown_subscription():
    servicer = BillingServicer(SubscriptionService())

    response = run(servicer.GetSubscriptionStatus(pb.StatusRequest(subscription_id="does-not-exist")))

    assert response.error_code == "UNKNOWN_SUBSCRIPTION"


def test_cancel_subscription_rpc_moves_to_cancelled_and_free_tier():
    servicer = BillingServicer(SubscriptionService())
    created = run(servicer.CreateSubscription(pb.CreateSubRequest(user_id="user-1", tier="pro")))

    response = run(servicer.CancelSubscription(pb.CancelSubRequest(subscription_id=created.subscription.subscription_id)))

    assert response.error_code == ""
    assert response.subscription.status == "cancelled"
    assert response.subscription.tier == "free"


def test_cancel_subscription_rpc_reports_unknown_subscription():
    servicer = BillingServicer(SubscriptionService())

    response = run(servicer.CancelSubscription(pb.CancelSubRequest(subscription_id="does-not-exist")))

    assert response.error_code == "UNKNOWN_SUBSCRIPTION"


def test_handle_webhook_rpc_fails_closed_when_billing_is_unconfigured():
    """Billing is off by default (§3.1) — `UnconfiguredProvider.verify_webhook` never
    verifies, so a webhook is always rejected rather than accepted with nothing to
    actually check it against."""
    servicer = BillingServicer(SubscriptionService())

    response = run(servicer.HandleWebhook(pb.WebhookPayload(payload=b'{"event":"x"}', signature="sig")))

    assert response.accepted is False
    assert response.verified is False
    assert response.error_code != ""
