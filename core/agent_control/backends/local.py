"""The Phase-1 backend: real answers where a real source exists, honest failure elsewhere.

Agent Control is implemented ahead of every other Core API by design
(`docs/PHASE_1_KICKOFF.md` §1.5), so its MCP server and CLI are usable from the moment
Phase 2 starts. That leaves a real question this file answers deliberately: what should a
tool return when the service it wraps does not exist yet?

The answer is never "plausible-looking data." `find_setting` resolves against genuine
declarative menu data, so it returns a real result. Every tool whose owning service is not
implemented raises `CoreUnavailable` and says which API it is waiting on. A fabricated
health report or invented run status would be actively worse than an error — it would look
like the system works, and an agent would reason from it.
"""

from __future__ import annotations

from typing import Any

from ..errors import CoreUnavailable

try:  # V2's own technique, carried forward as a technique (deep-dive §3.1)
    from rapidfuzz import fuzz as _fuzz
except ImportError:  # pragma: no cover - optional, degrades to substring matching
    _fuzz = None


def _load_menu_items() -> list:
    """Menu data is owned by Interface API; this backend only reads it."""
    from services.interface.tui.menu_data.settings import SETTINGS_MENU

    return list(SETTINGS_MENU)


def _score(query: str, item) -> float:
    """Fuzzy match over the fields a person would actually describe a setting by.

    V2 used `rapidfuzz.fuzz.partial_ratio` with a plain-substring fallback when rapidfuzz
    was absent — a genuinely good design kept essentially as-is. The fallback matters: this
    tool must not hard-fail on an install that skipped an optional dependency
    (`docs/PRINCIPLES.md` §4.4).
    """
    haystacks = [item.label, item.path, item.tooltip]
    if _fuzz is not None:
        return max(_fuzz.partial_ratio(query.lower(), h.lower()) for h in haystacks)
    q = query.lower()
    return max(100.0 if q in h.lower() else 0.0 for h in haystacks)


class LocalCoreBackend:
    """Implements `CoreBackend` (structurally — see `base.CoreBackend`)."""

    def name(self) -> str:
        return "local"

    def is_available(self) -> bool:
        return True

    # --- READ_ONLY ----------------------------------------------------------
    def find_setting(self, query: str, limit: int = 5) -> dict[str, Any]:
        if not query or not query.strip():
            return {"query": query, "matches": [], "note": "empty query"}

        items = _load_menu_items()
        scored = sorted(
            ((_score(query, i), i) for i in items), key=lambda p: p[0], reverse=True
        )
        matches = [
            {
                "path": item.path,
                "label": item.label,
                "tooltip": item.tooltip,
                "target": item.target,
                "kind": item.kind,
                "docs_ref": item.docs_ref,
                "score": round(float(score), 1),
            }
            for score, item in scored[:limit]
            if score > 0
        ]

        if not matches:
            # The relocation fallback (§3.1): a saved deep-link or stale doc reference
            # should still resolve rather than silently failing.
            for item in items:
                if any(query.strip() == fp for fp in item.former_paths):
                    matches.append({
                        "path": item.path, "label": item.label, "tooltip": item.tooltip,
                        "target": item.target, "kind": item.kind,
                        "docs_ref": item.docs_ref, "score": 100.0,
                        "resolved_via": "former_paths",
                    })
                    break

        return {
            "query": query,
            "matches": matches,
            "matcher": "rapidfuzz.partial_ratio" if _fuzz else "substring-fallback",
            "menu_items_searched": len(items),
        }

    def persistence_query(self, **filters: Any) -> dict[str, Any]:
        raise CoreUnavailable(
            "persistence_query wraps Search/Query API, which is scaffolded but not "
            "implemented until Phase 2 (core/search_query/)."
        )

    # --- MUTATING_STAGED ----------------------------------------------------
    def propose_setting_change(self, key: str, value: str) -> dict[str, Any]:
        raise CoreUnavailable(
            "propose_setting_change stages into a review queue owned by Architect API's "
            "moderation mechanism, not implemented until Phase 2 "
            "(core/architect/temporal_learning/). Deliberately not faked: a staged proposal "
            "that is silently dropped is worse than a refusal."
        )

    # --- DEV_OBSERVABILITY --------------------------------------------------
    def get_run_status(self, run_id: str) -> dict[str, Any]:
        raise CoreUnavailable(
            "get_run_status wraps Execution Core's GetRunStatus RPC "
            "(services/execution_core/), not implemented until Phase 2."
        )

    def get_system_health(self) -> dict[str, Any]:
        raise CoreUnavailable(
            "get_system_health wraps Health API's live diagnostic layer (core/health/), "
            "not implemented until Phase 2."
        )

    def get_historian_narrative(self, receipt_id: str) -> dict[str, Any]:
        raise CoreUnavailable(
            "get_historian_narrative wraps Historian's narrative track "
            "(core/persistence/historian/), not implemented until Phase 2."
        )

    def tail_logs(self, service: str, level: str = "INFO", limit: int = 100) -> dict[str, Any]:
        raise CoreUnavailable(
            "tail_logs wraps Logs API's query surface (core/logs/), not implemented "
            "until Phase 2."
        )

    def check_dependency_status(self) -> dict[str, Any]:
        raise CoreUnavailable(
            "check_dependency_status wraps Telemetrees' tracked-fact inventory "
            "(core/telemetrees/dependencies_warden/), not implemented until Phase 2."
        )
