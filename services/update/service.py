"""The `UpdateServicer` gRPC servicer (`update.proto`) — wires `release_manager.py`'s
real clone/channel-usage primitives to the wire surface. `CLAUDE.md`'s own "partially
implemented" note named the gap: `contracts.py` and `keymaster_client.py` were real,
everything else — `release_manager.py`, `errors.py`, `metrics.py`, and the `.proto`
surface itself — was 0-byte scaffolding.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from .contracts import ChannelName
from .keymaster_client import KeymasterClient
from .metrics import UpdateMetricsCollector
from .release_manager import clone_release, get_active_channels

DEFAULT_ADDRESS = "127.0.0.1:50089"

__all__ = ["DEFAULT_ADDRESS", "UpdateServicer", "serve"]


class UpdateServicer:
    """Implements `UpdateService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        *,
        keymaster_client: KeymasterClient | None = None,
        metrics: UpdateMetricsCollector | None = None,
    ) -> None:
        self._keymaster_client = keymaster_client
        self._metrics = metrics or UpdateMetricsCollector()

    async def CloneRelease(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import update_pb2 as pb

        try:
            channel = ChannelName(request.channel)
        except ValueError:
            return pb.ReleaseDirectoryResponse(
                ok=False, error_code="UNKNOWN_CHANNEL", error_detail=f"unknown channel {request.channel!r}",
            )

        result = await clone_release(
            request.install_root, channel,
            ref_override=request.ref_override or None,
            keymaster_client=self._keymaster_client,
            license_key=request.license_key,
            instance_id=request.instance_id or None,
            dev_mode=request.dev_mode if request.dev_mode_set else None,
            python_bin=request.python_bin or None,
            metrics=self._metrics,
        )

        response = pb.ReleaseDirectoryResponse(
            ok=result.ok, used_fallback_ref=result.used_fallback_ref,
            keymaster_token_used=result.keymaster_token_used,
            error_code=result.error_code, error_detail=result.error_detail,
        )
        if result.release is not None:
            response.path = str(result.release.path)
            response.version = result.release.version
            response.commit_hash = result.release.commit_hash
            response.ref = result.release.ref
            response.channel = result.release.channel.value
        if result.finalize is not None:
            response.finalize_ok = result.finalize.ok
        return response

    async def GetActiveChannels(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import update_pb2 as pb

        usages = get_active_channels(request.install_root)
        response = pb.ChannelListResponse()
        for usage in usages:
            response.channels.append(pb.ChannelUsageInfo(
                channel=usage.channel.value, last_release_name=usage.last_release_name,
                last_cloned_at=usage.last_cloned_at.isoformat(),
            ))
        return response


async def serve(address: str = DEFAULT_ADDRESS, *, keymaster_client: KeymasterClient | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import update_pb2_grpc

    server = grpc.aio.server()
    update_pb2_grpc.add_UpdateServiceServicer_to_server(UpdateServicer(keymaster_client=keymaster_client), server)
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
        kick_task = start_kicking_for_service('update')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())
