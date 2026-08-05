"""The `InferenceServicer` gRPC servicer (`inference.proto`) — thin by design, matching
`core/ocr/service.py`'s own stated posture. Every real decision lives in
`model_registry.py`; this file translates protobuf messages to and from that module's own
contract types and nothing else.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly
as `core/ocr/service.py` and `core/preprocessing/service.py` do, so this package stays
importable — and its tests meaningful — on an interpreter with no `grpcio` wheel yet
(`docs/MAINTENANCE.md` §8.1).
"""

from __future__ import annotations

import json
from dataclasses import replace

from common.frozen_dict import FrozenDict

from .contracts import (
    BlobRef,
    ContentBlock,
    ContentBlockType,
    GenerationRequest,
    Message,
    MessageRole,
    ToolSpec,
)
from .model_registry import InferenceConfig, InferenceModelRegistry
from .metrics import InferenceMetricsCollector

DEFAULT_ADDRESS = "127.0.0.1:50073"


def _content_block_from_pb(msg) -> ContentBlock:
    block_type = ContentBlockType(msg.type)
    image_ref = BlobRef(logical_id=msg.image_blob_ref) if msg.image_blob_ref else None
    return ContentBlock(type=block_type, text=msg.text or None, image_ref=image_ref)


def _message_from_pb(msg) -> Message:
    return Message(
        role=MessageRole(msg.role),
        content=tuple(_content_block_from_pb(c) for c in msg.content),
    )


def _tool_spec_from_pb(msg) -> ToolSpec:
    schema = json.loads(msg.parameters_schema_json) if msg.parameters_schema_json else {}
    return ToolSpec(name=msg.name, description=msg.description, parameters_schema=FrozenDict(schema))


class InferenceServicer:
    """Implements `InferenceService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self, config: InferenceConfig | None = None, blob_store=None, *, worker_factory=None
    ) -> None:
        self._config = config or InferenceConfig()
        self._metrics = InferenceMetricsCollector()
        self._registry = InferenceModelRegistry(
            self._config, blob_store, self._metrics, worker_factory=worker_factory
        )

    async def Generate(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import inference_pb2 as pb

        response_schema = None
        if request.response_schema_json:
            response_schema = FrozenDict(json.loads(request.response_schema_json))

        generation_request = GenerationRequest(
            run_id=request.run_id,
            user_id=request.user_id,
            preset=request.preset,
            messages=tuple(_message_from_pb(m) for m in request.messages),
            tools=tuple(_tool_spec_from_pb(t) for t in request.tools),
            response_schema=response_schema,
            max_tokens=request.max_tokens or 512,
            temperature=request.temperature,
            timeout_ms=request.timeout_ms or self._config.per_request_timeout_ms,
        )
        result = await self._registry.generate(generation_request)

        response = pb.GenerateResponse()
        response.text = result.text
        response.finish_reason = result.finish_reason.value
        response.schema_valid = result.schema_valid
        response.device = result.device
        response.duration_ms = result.duration_ms
        if result.tool_call is not None:
            response.tool_call.name = result.tool_call.name
            response.tool_call.arguments_json = json.dumps(dict(result.tool_call.arguments))
        if result.error is not None:
            response.error_code = result.error.code.value
            response.error_detail = result.error.detail
        return response

    async def ListPresets(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import inference_pb2 as pb

        response = pb.ListPresetsResponse()
        response.available_presets.extend(sorted(self._registry.available_presets()))
        response.enabled_presets.extend(sorted(self._registry.enabled_presets()))
        return response


async def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    config: InferenceConfig | None = None,
    blob_store=None,
):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import inference_pb2_grpc

    server = grpc.aio.server()
    inference_pb2_grpc.add_InferenceServiceServicer_to_server(
        InferenceServicer(config, blob_store), server
    )
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


def _config_from_env() -> InferenceConfig:
    """Real, live-found gap: unlike every other service in this repo that reads an
    external-resource path from an env var (`RESIBO_CLAMAV_DATABASE_DIR`,
    `RESIBO_CLAMD_HOST`), this one had no seam at all — `InferenceConfig.models_dir`'s
    `"models"` default and `device_by_preset`'s empty default were the only values a real
    install could ever get, with no way for an operator to point this at real downloaded
    model weights or a real non-CPU device without editing code. Confirmed live: this is
    exactly what blocked testing this service against a real, actually-downloaded model.

    `RESIBO_INFERENCE_DEVICE`, if set, applies to every enabled preset uniformly — a real
    install has one machine with one chosen execution provider, not a different device
    per preset; `device_by_preset`'s own per-preset shape stays available for a caller
    that constructs `InferenceConfig` directly and wants finer control than this
    environment-variable convenience offers.
    """
    import os

    config = InferenceConfig()
    models_dir = os.environ.get("RESIBO_INFERENCE_MODELS_DIR")
    if models_dir:
        config = replace(config, models_dir=models_dir)
    presets_enabled = os.environ.get("RESIBO_INFERENCE_PRESETS_ENABLED")
    if presets_enabled:
        config = replace(
            config, presets_enabled=frozenset(p.strip() for p in presets_enabled.split(",") if p.strip())
        )
    device = os.environ.get("RESIBO_INFERENCE_DEVICE")
    if device:
        config = replace(
            config, device_by_preset=FrozenDict({p: device for p in config.presets_enabled})
        )
    return config


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main():
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr, config=_config_from_env())
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('inference')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())
