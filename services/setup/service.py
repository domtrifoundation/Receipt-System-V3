"""The `SetupServicer` gRPC servicer (`setup.proto`) — thin by design, matching
`core/geo_address/service.py`'s own stated posture. Every real decision lives in
`hardware/detect.py`, `wizard.py`, and `venv_provisioning.py`; this file translates protobuf
messages to and from those modules' own contract types and nothing else.

The generated stubs are imported lazily inside the methods and inside `serve()`, exactly as
`core/geo_address/service.py`, `core/logs/service.py` and `core/health/service.py` all do, so
this package stays importable — and its tests meaningful — on an interpreter with no `grpcio`
wheel yet (this project's own live gap: `grpcio` has no prebuilt wheel for 3.15,
`docs/MAINTENANCE.md` §8.1).

**`RunWizard` is `grpc.aio`, not classic sync `grpc`** — the same choice
`services/execution_core/service.py` already made for its own streaming RPC, and the only choice
that fits here: `WizardEngine.run()` is itself an async generator, and bidirectional streaming
needs an async request iterator on the way in as well as an async generator on the way out.

`map<string, string>` wire values that are not plain strings (booleans, credential dicts,
provider choices with structured payloads) are JSON-encoded on the way out and JSON-decoded on
the way in, falling back to the raw string when a value is not valid JSON — so `"personal"`
round-trips as the bare string it already is, while `{"enable": true}` round-trips as a real
Python `bool`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

from .bootstrap import read_dev_mode, read_run_on_startup, write_run_on_startup
from .contracts import HardwareProfile, WizardAnswer, WizardStepId
from .hardware.detect import default_detector
from .hardware.report_import import DEFAULT_CANDIDATE_DIRS, find_and_merge
from .venv_provisioning import provision_clone
from .wizard import WizardEngine

DEFAULT_ADDRESS = "127.0.0.1:50069"


def _encode_map(data: Mapping) -> dict[str, str]:
    """Python value -> wire string. Plain strings pass through unencoded so the common case
    (`"personal"`, `"sso"`) stays human-readable on the wire rather than becoming `'"personal"'`.
    """
    encoded: dict[str, str] = {}
    for key, value in data.items():
        encoded[key] = value if isinstance(value, str) else json.dumps(value)
    return encoded


def _decode_map(wire_map: Mapping[str, str]) -> dict:
    """Wire string -> Python value. A value that is not valid JSON is kept as the raw string it
    already is, rather than raising — `"personal"` is not a JSON literal (a bare word isn't
    valid JSON) and is exactly the common case this must not fail on."""
    decoded: dict = {}
    for key, value in wire_map.items():
        try:
            decoded[key] = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            decoded[key] = value
    return decoded


def _profile_to_pb(profile: HardwareProfile, pb):
    response = pb.HardwareProfileResponse()
    response.cpu_name = profile.cpu_name
    response.cores = profile.cores
    response.threads = profile.threads
    if profile.ram_gb is not None:
        response.ram_gb = profile.ram_gb
    response.npus.extend(profile.npus)
    response.detected_at = profile.detected_at.isoformat()
    response.source = profile.source
    for gpu in profile.gpus:
        gpu_msg = response.gpus.add()
        gpu_msg.name = gpu.name
        gpu_msg.vendor = gpu.vendor
        gpu_msg.discrete = gpu.discrete
        if gpu.vram_gb is not None:
            gpu_msg.vram_gb = gpu.vram_gb
        gpu_msg.compute_api = gpu.compute_api
        if gpu.shader_core_count is not None:
            gpu_msg.shader_core_count = gpu.shader_core_count
    return response


class SetupServicer:
    """Implements `SetupService`. Registered by name, so importing the generated stubs is
    `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        *,
        launcher_path: Path = Path("start.sh"),
        wizard_engine_factory=None,
        install_root: Path | None = None,
    ) -> None:
        self._launcher_path = launcher_path
        #: `None` in a dev checkout (`common/install_paths.resolve_install_root()`
        #: returns `None` there) — `GetDevMode`/`GetRunOnStartup`/`SetRunOnStartup` report
        #: `known=false` rather than fabricating a value when this is unset and the
        #: request carries no explicit `install_root` override either.
        self._install_root = install_root
        # A factory rather than one shared WizardEngine: `docs/VENV_AND_IMPORTS.md`-adjacent
        # reasoning applies here too — one wizard run per install, and a fresh WizardEngine's
        # own `self.progress` must never leak between two concurrent RunWizard calls (e.g. a
        # hosted multi-tenant hardware-detection probe running alongside an unrelated wizard
        # invocation). Defaults to the real, unconfigured engine — every collaborator seam left
        # `None`, degrading gracefully per `docs/PRINCIPLES.md` §4.4.
        self._wizard_engine_factory = wizard_engine_factory or (
            lambda: WizardEngine(launcher_path=self._launcher_path)
        )

    async def DetectHardware(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import setup_pb2 as pb

        detector = default_detector()
        profile = await detector.detect()

        search_paths = tuple(Path(p) for p in request.extra_report_search_paths) or DEFAULT_CANDIDATE_DIRS
        profile = await find_and_merge(profile, search_paths)

        return _profile_to_pb(profile, pb)

    async def RunWizard(  # noqa: N802 - gRPC naming
        self, request_iterator: AsyncIterator, context=None
    ):
        """Bidirectional streaming — see the module docstring for why, over §9's original
        server-streaming sketch. Drives a fresh `WizardEngine` in lockstep with the client:
        yield one `WizardStepMessage`, read one `WizardAnswerMessage`, repeat.
        """
        from .generated import setup_pb2 as pb

        engine = self._wizard_engine_factory()
        gen = engine.run()
        answers = request_iterator.__aiter__()

        prompt = await anext(gen)
        while True:
            step_msg = pb.WizardStepMessage()
            step_msg.step_id = prompt.step_id.value
            step_msg.context.update(_encode_map(prompt.context))
            step_msg.is_final = prompt.step_id is WizardStepId.FINALIZE
            yield step_msg

            if prompt.step_id is WizardStepId.FINALIZE:
                return  # FINALIZE's own answer (if the client sends one) closes the stream;
                #          nothing further to drive once the last real prompt has been shown.

            answer_msg = await anext(answers)
            answer = WizardAnswer(
                step_id=WizardStepId(answer_msg.step_id),
                skipped=answer_msg.skipped,
                data=_decode_map(answer_msg.data),
            )
            try:
                prompt = await gen.asend(answer)
            except StopAsyncIteration:
                return

    async def ProvisionVenvs(self, request, context=None):  # noqa: N802 - gRPC naming
        """`provision_clone` is synchronous — it runs real `pip`/`venv` subprocesses via its own
        internal thread pool and blocks until they finish. Dispatched via `run_in_executor` so
        that real, potentially multi-second blocking work never runs on the asyncio event loop
        thread this servicer shares with `RunWizard`'s own concurrent streaming calls."""
        import asyncio

        from .generated import setup_pb2 as pb

        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(
            None, lambda: provision_clone(Path(request.clone_dir), python_bin=request.python_bin or None)
        )

        response = pb.ProvisionVenvsResponse()
        response.fully_provisioned = report.fully_provisioned
        for outcome in report.outcomes:
            msg = response.outcomes.add()
            msg.import_path = outcome.import_path
            msg.venv_dir = str(outcome.venv_dir)
            msg.created = outcome.created
            if outcome.error is not None:
                msg.error_code = outcome.error.code.value
                msg.error_detail = outcome.error.detail
        return response

    def _resolve_install_root(self, request_install_root: str) -> Path | None:
        if request_install_root:
            return Path(request_install_root)
        return self._install_root

    async def GetDevMode(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import setup_pb2 as pb

        install_root = self._resolve_install_root(request.install_root)
        if install_root is None:
            return pb.DevModeResponse(known=False)
        value = read_dev_mode(install_root)
        return pb.DevModeResponse(dev_mode=bool(value), known=value is not None)

    async def GetRunOnStartup(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import setup_pb2 as pb

        install_root = self._resolve_install_root(request.install_root)
        if install_root is None:
            return pb.RunOnStartupResponse(known=False)
        return pb.RunOnStartupResponse(run_on_startup=read_run_on_startup(install_root), known=True)

    async def SetRunOnStartup(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import setup_pb2 as pb

        install_root = self._resolve_install_root(request.install_root)
        if install_root is None:
            return pb.RunOnStartupResponse(known=False)
        write_run_on_startup(install_root, request.run_on_startup)
        return pb.RunOnStartupResponse(run_on_startup=request.run_on_startup, known=True)


async def serve(address: str = DEFAULT_ADDRESS, *, launcher_path: Path = Path("start.sh"), install_root: Path | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import setup_pb2_grpc

    server = grpc.aio.server()
    setup_pb2_grpc.add_SetupServiceServicer_to_server(
        SetupServicer(launcher_path=launcher_path, install_root=install_root), server
    )
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main():
        from common.install_paths import resolve_install_root

        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        server = await serve(addr, install_root=resolve_install_root(Path(__file__)))
        print(f"BOUND_ADDRESS={server.bound_address}", flush=True)
        print(f"listening on {server.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('setup')
        try:
            await server.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())
