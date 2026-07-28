"""The Core-API transport adapter (`docs/PRINCIPLES.md` §1.3).

Agent Control is a genuine third client of the same gRPC core the TUI and Gateway talk to
(`v3-deepdive-55-agent-control-api.md` §1) — it is not a backdoor around either, and every
tool it exposes is a wrapper around an RPC some other API already owns.

**Why this is an interface rather than direct stub calls at each call site**: §1.3 requires
every external integration to sit behind one small internal adapter, so swapping the
implementation is an edit to one file rather than to scattered call sites. Here that buys
something concrete and immediate — in Phase 1 the callee services genuinely do not exist
yet, so `CoreUnavailable` is the honest answer for most tools, and Phase 2 fills them in by
implementing this one Protocol rather than by rewriting the tool layer.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CoreBackend(Protocol):
    """One method per Core API capability Agent Control's tool set wraps.

    Each returns a plain JSON-serializable mapping, or raises `CoreUnavailable` when the
    owning service is not reachable. Nothing here invents data when a service is missing —
    a fabricated health report is worse than an honest "the cluster is not running."
    """

    def name(self) -> str:
        """Short identifier for diagnostics."""
        ...

    def is_available(self) -> bool:
        """Whether the underlying core cluster is genuinely reachable right now."""
        ...

    # --- READ_ONLY (Tool Call API's existing inventory) ---------------------
    def find_setting(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Interface API's fuzzy setting search (`v3-deepdive-14-interface-api.md` §3.1)."""
        ...

    def persistence_query(self, **filters: Any) -> dict[str, Any]:
        """Search/Query API's FTS5-backed structured search."""
        ...

    # --- MUTATING_STAGED ----------------------------------------------------
    def propose_setting_change(self, key: str, value: str) -> dict[str, Any]:
        """Stages a proposed change into a review queue — never applies directly."""
        ...

    # --- DEV_OBSERVABILITY (§4.1) ------------------------------------------
    def get_run_status(self, run_id: str) -> dict[str, Any]:
        """Execution Core's `GetRunStatus`."""
        ...

    def get_system_health(self) -> dict[str, Any]:
        """Health API's live diagnostic plus capability-drift findings."""
        ...

    def get_historian_narrative(self, receipt_id: str) -> dict[str, Any]:
        """Historian's narrative track (`v3-deepdive-29-historian.md` §5)."""
        ...

    def tail_logs(self, service: str, level: str = "INFO", limit: int = 100) -> dict[str, Any]:
        """Logs API's query surface."""
        ...

    def check_dependency_status(self) -> dict[str, Any]:
        """Telemetrees' tracked-fact inventory."""
        ...
