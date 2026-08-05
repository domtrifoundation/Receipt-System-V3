"""The `BillingServicer` gRPC servicer (`billing.proto`) — the real assembly point
wiring `subscription.SubscriptionService` to the wire surface. `CLAUDE.md`'s own "Known
gaps" section named this by name: a four-RPC surface specified in the deep-dive with no
`.proto` compiled at all.

**This never executes a charge, transfer, or refund** — `SubscriptionService` itself
tracks which tier a subscription is paying for and reports that fact (§1's own boundary);
actually moving money is each PSP provider's own job behind `psp/base.py`'s Provider
Registry, invoked from `handle_webhook`'s own verification path, not from this file.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from .subscription import SubscriptionService

DEFAULT_ADDRESS = "127.0.0.1:50085"

__all__ = ["BillingServicer", "DEFAULT_ADDRESS", "serve"]


def _subscription_to_pb(pb, subscription):
    return pb.SubscriptionInfo(
        subscription_id=subscription.subscription_id, user_id=subscription.user_id,
        tier=subscription.tier, status=subscription.status.value,
        current_period_end=subscription.current_period_end.isoformat()
        if subscription.current_period_end else "",
        created_at=subscription.created_at.isoformat(), updated_at=subscription.updated_at.isoformat(),
    )


def _subscription_response(pb, result):
    response = pb.SubscriptionResponse(error_code=result.error_code, error_detail=result.error_detail)
    if result.subscription is not None:
        response.subscription.CopyFrom(_subscription_to_pb(pb, result.subscription))
    return response


class BillingServicer:
    """Implements `BillingService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(self, service: SubscriptionService | None = None) -> None:
        self._service = service if service is not None else SubscriptionService()

    async def CreateSubscription(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import billing_pb2 as pb

        result = self._service.create_subscription(request.user_id, request.tier)
        return _subscription_response(pb, result)

    async def CancelSubscription(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import billing_pb2 as pb

        result = self._service.cancel_subscription(request.subscription_id)
        return _subscription_response(pb, result)

    async def GetSubscriptionStatus(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import billing_pb2 as pb
        from .errors import UnknownSubscription, code_for

        subscription = self._service.get(request.subscription_id)
        if subscription is None:
            exc = UnknownSubscription(request.subscription_id)
            return pb.SubscriptionResponse(error_code=code_for(exc), error_detail=str(exc))
        response = pb.SubscriptionResponse()
        response.subscription.CopyFrom(_subscription_to_pb(pb, subscription))
        return response

    async def HandleWebhook(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import billing_pb2 as pb

        result = await self._service.handle_webhook(request.payload, request.signature)
        return pb.WebhookAck(
            accepted=result.accepted, verified=result.verified,
            error_code=result.error_code, error_detail=result.error_detail,
        )


async def serve(address: str = DEFAULT_ADDRESS, *, service: SubscriptionService | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import billing_pb2_grpc

    server = grpc.aio.server()
    billing_pb2_grpc.add_BillingServiceServicer_to_server(BillingServicer(service), server)
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr)
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('billing')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())
