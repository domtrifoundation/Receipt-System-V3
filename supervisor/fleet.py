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

**No dependency ordering is modeled yet** (`depends_on=()` for every entry) — a real,
stated limitation. Sleep policy comes from the already-built, already-tested
classification in `sleep_wake/classification.py`.
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
                )
            )
            break
    return tuple(specs)
