"""Execution Core API — the pipeline run: scheduling, sequencing, checkpointing, cancellation.

Deliberately empty of re-exports. `contracts.py` is the only module anything outside this
package imports from (`docs/PRINCIPLES.md` §1.1); re-exporting `Pipeline` here would make
`from core.execution_core import Pipeline` look like the supported entry point when the
supported entry point is the gRPC service in `service.py`.

Execution Core owns the *run* and nothing inside a stage (§1). It calls Ingestion,
Preprocessing, OCR, Matching, Geo/Address, Inference and Persistence through their own
contracts; it never reimplements a fragment of what any of them do, and it never launches a
process — that is the Supervisor's job, structurally separate so that the thing deciding
whether Execution Core's own release should be swapped is never Execution Core itself.
"""

from __future__ import annotations

__all__: list[str] = []
