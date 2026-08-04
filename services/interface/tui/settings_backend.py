"""Real gRPC calls behind a real subset of `menu_data/settings.py`'s own dotted targets —
the actual backend the Settings screen was missing entirely before this pass (every leaf
used to resolve to `"<target> is not wired to a live backend yet"`, confirmed live against
a running install). Each entry here is genuinely wired to a real, tested RPC on the
owning API (`core/auth`, `services/setup`, `core/telemetrees`) — not fabricated data.

**Address resolution mirrors every other Core API's own real pattern**: this module
resolves its own install root the identical way `core/auth/service.py`'s `__main__` does
(`common/install_paths.resolve_install_root`), then looks up each service's real,
dynamically-bound address via `common/blob_client.resolve_service_address` — the same
registry Supervisor's own `StreamBootProgress` writes. Falls back to each service's own
hardcoded `DEFAULT_ADDRESS` in a dev checkout (no install root resolvable), matching every
other graceful-degradation seam in this project.

**This is a real, honest, partial slice — not every setting.** `settings.py`'s own
`update_channel`, `dependency_testing_opt_in`, `log_verbosity`, `google_drive_enabled`,
`archival_codec`, and `tunnel_exposure_enabled` are not backed here yet — Update, Logs,
and Ingestion have no config RPCs of their own yet, and Gateway does not exist as a
package at all. Adding one of those is the identical mechanical pattern this module
already demonstrates four times over: a real `Get`/`Set` RPC pair on the owning API,
backed by `common/local_config_store.LocalConfigStore`, called from a new entry below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Literal

_DEFAULT_ADDRESSES = {
    "auth": "127.0.0.1:50056",
    "setup": "127.0.0.1:50069",
    "telemetrees": "127.0.0.1:50088",
}


def _resolve_address(service_name: str) -> str:
    from common.blob_client import resolve_service_address
    from common.install_paths import resolve_install_root

    fallback = _DEFAULT_ADDRESSES[service_name]
    install_root = resolve_install_root(Path(__file__))
    if install_root is None:
        return fallback
    return resolve_service_address(install_root, service_name, fallback)


@dataclass(frozen=True)
class SettingBackend:
    """`kind` drives `SettingValueScreen`'s own rendering: `"bool_ro"` shows the value with
    no edit control (`dev_mode`'s own "not convertible on a live install"), `"bool_rw"`
    shows a toggle, `"choice_rw"` shows a picker over `choices`."""

    kind: Literal["bool_ro", "bool_rw", "choice_rw"]
    get: Callable[[], Awaitable[tuple[bool, str]]]
    """Returns `(known, value)` — `value` is `"true"`/`"false"` for bool kinds, the current
    choice string for `"choice_rw"`. `known=False` means no install root could be resolved
    (a dev checkout) — the real, honest "cannot read this here" case."""
    set: Callable[[str], Awaitable[bool]] | None = None
    """`None` for `"bool_ro"`. Takes the new value as a string (`"true"`/`"false"`, or the
    chosen option), returns whether the write succeeded."""
    choices: tuple[str, ...] = ()
    restart_required_note: str = ""


async def _get_dev_mode() -> tuple[bool, str]:
    import grpc

    from services.setup.generated import setup_pb2 as pb
    from services.setup.generated import setup_pb2_grpc as pb_grpc

    async with grpc.aio.insecure_channel(_resolve_address("setup")) as channel:
        response = await pb_grpc.SetupServiceStub(channel).GetDevMode(pb.ConfigRequest())
    return response.known, str(response.dev_mode).lower()


async def _get_run_on_startup() -> tuple[bool, str]:
    import grpc

    from services.setup.generated import setup_pb2 as pb
    from services.setup.generated import setup_pb2_grpc as pb_grpc

    async with grpc.aio.insecure_channel(_resolve_address("setup")) as channel:
        response = await pb_grpc.SetupServiceStub(channel).GetRunOnStartup(pb.ConfigRequest())
    return response.known, str(response.run_on_startup).lower()


async def _set_run_on_startup(value: str) -> bool:
    import grpc

    from services.setup.generated import setup_pb2 as pb
    from services.setup.generated import setup_pb2_grpc as pb_grpc

    async with grpc.aio.insecure_channel(_resolve_address("setup")) as channel:
        response = await pb_grpc.SetupServiceStub(channel).SetRunOnStartup(
            pb.SetRunOnStartupRequest(run_on_startup=value == "true")
        )
    return response.known


async def _get_tenancy_mode() -> tuple[bool, str]:
    import grpc

    from core.auth.generated import auth_pb2 as pb
    from core.auth.generated import auth_pb2_grpc as pb_grpc

    async with grpc.aio.insecure_channel(_resolve_address("auth")) as channel:
        response = await pb_grpc.AuthServiceStub(channel).GetTenancyMode(pb.TenancyConfigRequest())
    return response.known, response.tenancy_mode


async def _set_tenancy_mode(value: str) -> bool:
    import grpc

    from core.auth.generated import auth_pb2 as pb
    from core.auth.generated import auth_pb2_grpc as pb_grpc

    async with grpc.aio.insecure_channel(_resolve_address("auth")) as channel:
        response = await pb_grpc.AuthServiceStub(channel).SetTenancyMode(
            pb.SetTenancyModeRequest(tenancy_mode=value)
        )
    return response.known


async def _get_telemetrees_opt_in() -> tuple[bool, str]:
    import grpc

    from core.telemetrees.generated import telemetrees_pb2 as pb
    from core.telemetrees.generated import telemetrees_pb2_grpc as pb_grpc

    async with grpc.aio.insecure_channel(_resolve_address("telemetrees")) as channel:
        response = await pb_grpc.TelemetreesServiceStub(channel).GetOptIn(pb.OptInConfigRequest())
    return response.known, str(response.opt_in).lower()


async def _set_telemetrees_opt_in(value: str) -> bool:
    import grpc

    from core.telemetrees.generated import telemetrees_pb2 as pb
    from core.telemetrees.generated import telemetrees_pb2_grpc as pb_grpc

    async with grpc.aio.insecure_channel(_resolve_address("telemetrees")) as channel:
        response = await pb_grpc.TelemetreesServiceStub(channel).SetOptIn(
            pb.SetOptInRequest(opt_in=value == "true")
        )
    return response.known


#: Keyed by `MenuItemSpec.target` exactly as it appears in `menu_data/settings.py` — no
#: menu-data renaming needed, this dict is the only place that knows a given target is
#: now real rather than an inert placeholder.
SETTINGS_BACKENDS: dict[str, SettingBackend] = {
    "setup.get_dev_mode": SettingBackend(kind="bool_ro", get=_get_dev_mode),
    "setup.set_run_on_startup": SettingBackend(kind="bool_rw", get=_get_run_on_startup, set=_set_run_on_startup),
    "auth.get_tenancy_mode": SettingBackend(
        kind="choice_rw", get=_get_tenancy_mode, set=_set_tenancy_mode, choices=("single", "multi"),
        restart_required_note="Takes effect on the next restart of Auth & Tenancy.",
    ),
    "telemetrees.set_opt_in": SettingBackend(kind="bool_rw", get=_get_telemetrees_opt_in, set=_set_telemetrees_opt_in),
}

__all__ = ["SETTINGS_BACKENDS", "SettingBackend"]
