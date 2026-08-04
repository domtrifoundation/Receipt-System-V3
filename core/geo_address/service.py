"""The `GeoAddressService` gRPC servicer (§6) — thin by design.

Every real decision lives in `corroboration.py`, `cache.py` and `providers/`. This file
translates protobuf messages to and from the contract types and nothing else, which is what
keeps `docs/PRINCIPLES.md` §1.9's guarantee a property of the package rather than of this one
file: Execution Core's `GEOD` stage and Reconciliation's idle sweep both reach the identical
`geocode_with_corroboration` through this identical RPC, so neither can drift from the other
by calling some other in-process shortcut.

**Errors are data** (§4.1): `GeocodeResponse.error_code`/`error_detail` are set only for a
malformed request; a genuine cross-provider conflict or an all-providers-down run are real,
honest answers on `result`, never an error.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/logs/service.py` and `core/health/service.py` both do, so this package stays importable
— and its tests meaningful — on an interpreter with no `grpcio` wheel yet.
"""

from __future__ import annotations

from concurrent import futures
from collections.abc import Sequence

from .cache import GeoCache
from .contracts import GeoQuery, GeoResult
from .corroboration import geocode_with_corroboration
from .metrics import GeoMetricsCollector
from .providers.base import GeoProvider
from .providers.locationiq import LocationIQProvider
from .providers.mapbox import MapboxProvider
from .providers.nominatim_self_hosted import NominatimSelfHostedProvider

DEFAULT_ADDRESS = "127.0.0.1:50066"


def default_providers(
    *,
    locationiq_api_key: str = "",
    mapbox_api_key: str = "",
    nominatim_endpoint: str = "",
) -> tuple[GeoProvider, ...]:
    """The §3 default registry: LocationIQ and Mapbox as the always-registered corroboration
    pair, self-hosted Nominatim addable the same way (config presence, not a separate enabled
    flag — deep-dive §7's own resolved config-consistency fix). Constructing this never makes
    a network call: an empty key/endpoint means that provider's own adapter reports itself
    unavailable (`providers/base.py`'s `UnavailableTransport` default).
    """
    return (
        LocationIQProvider(api_key=locationiq_api_key),
        MapboxProvider(api_key=mapbox_api_key),
        NominatimSelfHostedProvider(endpoint=nominatim_endpoint),
    )


def to_query(request) -> GeoQuery:
    """Wire request -> `GeoQuery`. Empty strings/lists mean "unset", per proto3 semantics."""
    return GeoQuery(
        candidate_strings=tuple(request.candidate_strings),
        providers=tuple(request.providers),
        country_code=request.country_code or "PH",
        vendor_name_hint=request.vendor_name_hint,
    )


def _address_to_wire(address, pb):
    if address is None:
        return None
    return pb.GeoAddressProto(
        formatted=address.formatted,
        line1=address.line1,
        barangay=address.barangay,
        city=address.city,
        province=address.province,
        region=address.region,
        postal_code=address.postal_code,
        country_code=address.country_code,
        latitude=address.latitude if address.latitude is not None else 0.0,
        longitude=address.longitude if address.longitude is not None else 0.0,
    )


def _provider_result_to_wire(result, pb):
    return pb.ProviderCandidateResultProto(
        provider=result.provider,
        candidate_string=result.candidate_string,
        address=_address_to_wire(result.address, pb),
        confidence=result.confidence,
        matched_business_name=result.matched_business_name,
        error_code=result.error.code if result.error else "",
        error_detail=result.error.detail if result.error else "",
    )


def to_response(result: GeoResult, pb):
    """`GeoResult` -> wire response. A malformed-request `error` (`errors.InvalidQuery`) is
    the only case that populates the top-level `error_code`; every other `GeoResult` —
    including a real conflict or an all-providers-down run — is a normal `result` (§4.1, §4.4).
    """
    if result.error is not None:
        return pb.GeocodeResponse(error_code=result.error.code, error_detail=result.error.detail)
    return pb.GeocodeResponse(
        result=pb.GeoResultProto(
            normalized_address=_address_to_wire(result.normalized_address, pb),
            confidence=result.confidence,
            agreement=result.agreement.value,
            matched_candidate_string=result.matched_candidate_string,
            provider_results=[_provider_result_to_wire(r, pb) for r in result.provider_results],
            vendor_name_at_address=result.vendor_name_at_address,
            vendor_name_discrepancy=result.vendor_name_discrepancy,
            conflict=result.conflict,
            conflict_detail=result.conflict_detail,
            degraded_providers=list(result.degraded_providers),
            from_cache=result.from_cache,
            cache_stale=result.cache_stale,
        )
    )


class GeoAddressServicer:
    """Implements `GeoAddressService`. Registered by name, so importing the generated stubs
    is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        *,
        providers: Sequence[GeoProvider] = (),
        cache: GeoCache | None = None,
        metrics: GeoMetricsCollector | None = None,
    ) -> None:
        self._providers = tuple(providers) or default_providers()
        self._cache = cache
        self._metrics = metrics or GeoMetricsCollector()

    def Geocode(self, request, context):  # noqa: N802 - gRPC method naming
        import asyncio

        from .generated import geo_address_pb2 as pb

        query = to_query(request)
        result = asyncio.run(
            geocode_with_corroboration(
                query, self._providers, cache=self._cache, metrics=self._metrics
            )
        )
        return to_response(result, pb)


def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    providers: Sequence[GeoProvider] = (),
    cache: GeoCache | None = None,
):
    """Start the service. Returns the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one — the actually-bound address is attached to the
    returned server as `bound_address`. Windows reserves scattered ranges in the 50000s, so a
    fixed high port is not reliably bindable across machines.
    """
    import grpc

    from .generated import geo_address_pb2_grpc as pb_grpc

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_GeoAddressServiceServicer_to_server(
        GeoAddressServicer(providers=providers, cache=cache), server
    )
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import sys

    addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    srv = serve(addr)
    print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
    print(f"GeoAddressService listening on {srv.bound_address}", file=sys.stderr)
    print(f"running under: {sys.executable} ({sys.version.split()[0]})", file=sys.stderr)
    from common.watchdog_client import ThreadedKicker
    kicker = ThreadedKicker('geo_address')
    try:
        srv.wait_for_termination()
    finally:
        kicker.stop()
__all__ = [
    "DEFAULT_ADDRESS",
    "GeoAddressServicer",
    "default_providers",
    "serve",
    "to_query",
    "to_response",
]
