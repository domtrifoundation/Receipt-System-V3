"""The real, central `ServiceSpec` registry — the piece nothing previously built.

`_spawn()`/`ServiceSpec.address` were always meant to be centrally assigned (see
`boot_sequence.py`'s own docstring), never each service's own hardcoded
`DEFAULT_ADDRESS` — those constants are local dev-convenience defaults for running one
service by hand, not a real multi-service boot's actual address assignment. This module
is what should have been assigning that centrally from the start.

Discovers every service with a real `__main__` entrypoint by reading its own source (not
importing it) — building this list never requires a given service's own third-party
dependencies to be installed, matching `venv_provisioning.py`'s own posture. Checks both
`service.py` (most services) and `grpc_servicer.py` (Persistence, Task Scheduler, whose
own real gRPC wiring lives there instead) for the real launchable module.

`auth`, `ingestion`, `persistence`, `task_scheduler` were previously excluded (missing
`__main__`, or a `BlobStoreGateway`/multi-collaborator constructor needing real wiring) —
all four now have real, working entrypoints (`common/blob_client.py`'s
`GrpcBlobStoreClient` for the blob-dependent ones; direct construction of Auth's seven
real collaborators for `auth`). Nothing excluded anymore.

**No general dependency ordering is modeled yet** (`depends_on=()` for every entry not
listed in `_KNOWN_DEPENDENCIES` below) — a real, stated limitation; a full dependency
graph across every service is real, separate, larger design work.

**`_KNOWN_DEPENDENCIES` is a targeted fix for one confirmed, live-found defect, not an
attempt at that larger graph.** `ExecutionCoreServicer` resolves its own peer addresses
(`preprocessing`/`ocr`/`persistence`/`review_flagging`) exactly once, at its own
`__main__` startup, via `common/blob_client.resolve_service_address` reading whatever
Supervisor has written to `service_addresses.json` *at that moment*. With every spec's
`depends_on=()`, `topological_order`'s Kahn's-algorithm tie-break is plain alphabetical
order — `execution_core` sorts before all four of its real dependencies, so it always
started before any of them had a real address recorded, permanently locking in their
hardcoded fallback defaults (ports nothing was ever listening on) for its entire
process lifetime. Confirmed live: `SubmitReceipt`'s own real preprocessing gateway call
failed with a raw connection-refused error on every single real receipt submission,
against a real fully-booted fleet, until this fix.
"""

from __future__ import annotations

import re
from pathlib import Path

from services.setup.venv_provisioning import discover_services
from supervisor.contracts import ServiceSpec
from supervisor.sleep_wake.classification import policy_for

__all__ = ["build_fleet_specs"]

_ADDR_RE = re.compile(r'DEFAULT_ADDRESS\s*=\s*"([^"]+)"')
_LAUNCHABLE_FILENAMES = ("service.py", "grpc_servicer.py")

#: See this module's own docstring for why this exists and what it deliberately does not
#: attempt to solve.
_KNOWN_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "execution_core": ("preprocessing", "ocr", "persistence", "review_flagging"),
}


def build_fleet_specs(clone_dir: Path) -> tuple[ServiceSpec, ...]:
    specs: list[ServiceSpec] = []
    for svc in discover_services(clone_dir):
        name = svc.import_path.rsplit(".", 1)[-1]
        for filename in _LAUNCHABLE_FILENAMES:
            launch_file = svc.source_dir / filename
            if not launch_file.is_file():
                continue
            text = launch_file.read_text(encoding="utf-8")
            if "__main__" not in text:
                continue
            match = _ADDR_RE.search(text)
            if not match:
                continue
            specs.append(
                ServiceSpec(
                    name=name, import_path=svc.import_path,
                    serve_module=f"{svc.import_path}.{filename[:-3]}",
                    address=match.group(1), sleep_policy=policy_for(name),
                    depends_on=_KNOWN_DEPENDENCIES.get(name, ()),
                )
            )
            break
    return tuple(specs)
