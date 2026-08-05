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

from common.execution_provider import EXECUTION_PROVIDERS
from common.frozen_dict import FrozenDict

from .contracts import (
    BlobRef,
    ContentBlock,
    ContentBlockType,
    GenerationRequest,
    Message,
    MessageRole,
    ProvisionStatus,
    ToolSpec,
)
from .model_provisioning import preset_status, provision_preset
from .model_registry import InferenceConfig, InferenceModelRegistry
from .metrics import InferenceMetricsCollector
from .presets import MODEL_PRESETS

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
        self, config: InferenceConfig | None = None, blob_store=None, *,
        worker_factory=None, hub_lister=None, install_root=None,
    ) -> None:
        self._config = config or InferenceConfig()
        self._metrics = InferenceMetricsCollector()
        #: `None` in a dev checkout — `SetPresetDevice` reports that plainly rather than
        #: pretending a write succeeded, matching `SetupServicer`'s own `install_root=None`
        #: posture for `GetDevMode`/`SetRunOnStartup`. Also forwarded to the registry below
        #: so a NuGet-distributed EP plugin (`ep_plugins.py`) can be found/registered.
        self._install_root = install_root
        self._registry = InferenceModelRegistry(
            self._config, blob_store, self._metrics, worker_factory=worker_factory,
            install_root=install_root,
        )
        #: Injectable so real streaming-RPC tests (`test_a_real_client_can_...`-shaped)
        #: never touch the real Hugging Face Hub, same seam
        #: `model_provisioning.HubFilesLister` already establishes.
        from .model_provisioning import _default_hub_lister

        self._hub_lister = hub_lister or _default_hub_lister
        #: `ProvisionStatus.DOWNLOADING`/`FAILED` overlay on top of `preset_status()`'s
        #: own pure disk check (`contracts.ProvisionStatus`'s own docstring) — real,
        #: in-memory, this-process-lifetime state, the same scope Execution Core's
        #: `RunRegistry` already documents for its own live tracking. Reset to whatever
        #: the disk actually says on every process restart, never assumed persistent.
        self._live_status: dict[str, ProvisionStatus] = {}

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
        """`preset_statuses` never makes a real network call *per request* — `presets.py`'s
        own `model_registry.py` docstring already establishes this rule for model-directory
        resolution ("must never make a network call... a one-time provisioning step"),
        and the identical reasoning applies here. The one real Hub round trip
        `preset_status()` needs happens at most once per preset per process lifetime,
        cached into `self._live_status` afterward — every later call, and every call once
        a real `ProvisionPreset` stream has run, is a pure in-memory read.
        """
        from .generated import inference_pb2 as pb

        response = pb.ListPresetsResponse()
        response.available_presets.extend(sorted(self._registry.available_presets()))
        response.enabled_presets.extend(sorted(self._registry.enabled_presets()))
        for name in sorted(MODEL_PRESETS):
            device = self._registry.device_for(name)
            if name not in self._live_status:
                self._live_status[name] = preset_status(
                    name, device, self._registry.models_dir(), hub_lister=self._hub_lister,
                )
            msg = response.preset_statuses.add()
            msg.name = name
            msg.status = self._live_status[name].value
            msg.device = device
        return response

    async def ProvisionPreset(self, request, context=None):  # noqa: N802 - gRPC naming
        """Server-streaming, matching Supervisor's `StreamBootProgress` exactly (§ this
        module's own `.proto` comment): a background task runs the real download, an
        `asyncio.Queue` bridges its per-file progress to this generator, a `complete`
        sentinel update ends the stream. Real, resumable, retrying downloads underneath
        (`model_provisioning.provision_preset`) — this method's own job stops at
        translating that into wire messages and tracking the live status overlay
        `ListPresets` reads.
        """
        import asyncio

        from .generated import inference_pb2 as pb

        preset = request.preset
        device_family = request.device_family or "cpu"

        if preset not in MODEL_PRESETS:
            yield pb.ProvisionProgressMessage(
                preset=preset, complete=True, ok=False,
                error_code="PRESET_NOT_CONFIGURED", error_detail=f"no such preset: {preset!r}",
            )
            return

        self._live_status[preset] = ProvisionStatus.DOWNLOADING
        queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()

        def on_progress(progress) -> None:
            queue.put_nowait(progress)

        async def _run() -> None:
            report = await provision_preset(
                preset, device_family, self._registry.models_dir(),
                on_progress=on_progress, hub_lister=self._hub_lister,
            )
            queue.put_nowait((_DONE, report))

        task = asyncio.ensure_future(_run())
        try:
            while True:
                item = await queue.get()
                if isinstance(item, tuple) and item and item[0] is _DONE:
                    report = item[1]
                    self._live_status[preset] = (
                        ProvisionStatus.READY if report.ok else ProvisionStatus.FAILED
                    )
                    yield pb.ProvisionProgressMessage(
                        preset=preset, complete=True, ok=report.ok,
                        error_code=report.error_code, error_detail=report.error_detail,
                    )
                    break
                yield pb.ProvisionProgressMessage(
                    preset=item.preset, current_file=item.current_file,
                    bytes_downloaded=item.bytes_downloaded, total_bytes=item.total_bytes,
                    files_completed=item.files_completed, files_total=item.files_total,
                )
        finally:
            await task

    async def ListExecutionProviders(self, request, context=None):  # noqa: N802 - gRPC naming
        """The real, honest device catalog (`common/execution_provider.EXECUTION_
        PROVIDERS`) — manual EP selection needs the operator to see confidence and real
        installability, not just a bare list of names."""
        from .generated import inference_pb2 as pb

        response = pb.ListExecutionProvidersResponse()
        for ep in EXECUTION_PROVIDERS:
            msg = response.providers.add()
            msg.device = ep.device
            msg.label = ep.label
            msg.confidence = ep.confidence
            msg.installable = ep.installable
            msg.note = ep.note
        return response

    async def SetPresetDevice(self, request, context=None):  # noqa: N802 - gRPC naming
        """Persists a manual per-preset override (`device_overrides.py`) — effective on
        the *next* Inference process start, never live (that module's own docstring has
        the full "why not live" account, matching `settings_backend.py`'s existing
        `takes_effect_on_restart` precedent for a different setting)."""
        from .generated import inference_pb2 as pb

        if self._install_root is None:
            return pb.SetPresetDeviceResponse(
                ok=False, error_code="NO_INSTALL_ROOT",
                error_detail="no install root known (a dev checkout has nowhere to persist this)",
            )
        if request.preset not in MODEL_PRESETS:
            return pb.SetPresetDeviceResponse(
                ok=False, error_code="PRESET_NOT_CONFIGURED",
                error_detail=f"no such preset: {request.preset!r}",
            )

        from .device_overrides import write_device_override

        write_device_override(self._install_root, request.preset, request.device)
        return pb.SetPresetDeviceResponse(ok=True, takes_effect_on_restart=True)

    async def warm_up(self) -> None:
        """Loads every enabled preset's full worker pool before the process reports
        itself ready — a direct, live-found fix. `get_worker()` loads a `worker_pool_size`
        pool under one shared `asyncio.Lock` per preset (`model_registry.py`), and every
        concurrent caller blocks on that same lock, not just the first one in. Without
        this, the first wave of real concurrent requests against a freshly-started
        process races each other into that lock and all stall behind one cold multi-
        replica load (live-measured: 5 concurrent receipts, `worker_pool_size=3`,
        332s identical stall on two of them before either failed). Calling `get_worker`
        once per enabled preset here pays that same real cost exactly once, at startup,
        serially, before any client can connect and race it."""
        for preset_name in self._registry.enabled_presets():
            await self._registry.get_worker(preset_name)


async def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    config: InferenceConfig | None = None,
    blob_store=None,
    install_root=None,
):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import inference_pb2_grpc

    server = grpc.aio.server()
    servicer = InferenceServicer(config, blob_store, install_root=install_root)
    inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    server.servicer = servicer  # type: ignore[attr-defined] -- lets __main__ warm up before announcing ready
    await server.start()
    return server


def _config_from_env(*, install_root=None) -> InferenceConfig:
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
    worker_pool_size = os.environ.get("RESIBO_INFERENCE_WORKER_POOL_SIZE")
    if worker_pool_size:
        # Real knob for the real, live-found "Inference has no genuine multi-request
        # parallelism" fix (`model_registry.py`'s own `worker_pool_size` docstring) --
        # unparseable/non-positive values degrade to the safe default of 1 rather than
        # crashing service startup over a malformed env var.
        try:
            parsed = int(worker_pool_size)
        except ValueError:
            parsed = 1
        config = replace(config, worker_pool_size=max(1, parsed))

    # Manual, persisted per-preset overrides (`SetPresetDevice`/`device_overrides.py`) —
    # applied on top of the uniform env-var default above, real per-preset precision an
    # operator set explicitly through the TUI winning over a machine-wide default, the
    # same "more specific wins" shape `InferenceModelRegistry._device_for` already applies
    # between `device_by_preset` and the hardware-derived fallback (Phase D).
    if install_root is not None:
        from .device_overrides import read_device_overrides

        overrides = read_device_overrides(install_root)
        if overrides:
            merged = dict(config.device_by_preset)
            merged.update(overrides)
            config = replace(config, device_by_preset=FrozenDict(merged))

    return config


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main():
        from common.install_paths import resolve_install_root
        from pathlib import Path as _Path

        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        install_root = resolve_install_root(_Path(__file__))
        srv = await serve(addr, config=_config_from_env(install_root=install_root), install_root=install_root)
        print("warming up enabled presets' worker pools before accepting real load...", file=sys.stderr, flush=True)
        await srv.servicer.warm_up()
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('inference')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())
