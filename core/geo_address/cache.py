"""Response cache over the geocoding Provider Registry (`v3-deepdive-16-geo-address-api.md`
§4). Keyed by normalized query string, so a repeated lookup for the same address across many
receipts — a common vendor, queried by many different users — never re-hits a rate-limited
free-tier provider for data this build already has.

**Its own small top-level SQLite database, not a table inside Persistence's per-user
canonical database.** The deep-dive's own §4 says "the canonical SQLite database," written
before this project's per-user-vs-cross-tenant database split was fully worked out in Wave 1
(Audit's `db.py`, Auth's session store, Architect's registry each got their own small
top-level database rather than a table in a per-user Persistence folder,
`docs/PRINCIPLES.md` §1.6). A geocode cache entry is not any one user's data — the same
normalized address is looked up across every user who has a receipt from that vendor — so it
follows the identical cross-tenant pattern those three already established, not the per-user
one. Nothing here is taxonomy or learned data either (§3.4 is Architect's domain): this is a
plain response cache, the same "accelerator, never a source of truth" shape as Logs' own
SQLite index.

**A cache that cannot be read or written degrades to a miss, never to a failed geocode call**
(§4.4) — `errors.CacheUnavailable` is raised only at construction (a database that cannot even
be opened), and every per-call method below catches `sqlite3.Error` itself rather than letting
a corrupt row or a locked file cost the run that was only ever trying to save a provider call.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from common.frozen_dict import FrozenDict

from .contracts import AgreementLevel, GeoAddress, GeoError, GeoResult, ProviderCandidateResult
from .errors import CacheUnavailable

SCHEMA = """
CREATE TABLE IF NOT EXISTS geo_cache (
    cache_key   TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    cached_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_geo_cache_cached_at ON geo_cache(cached_at);
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_cache_db_path() -> Path:
    """This cache's own small top-level SQLite database (see module docstring).

    `RESIBO_TOP_LEVEL` is how Supervisor tells a service where the shared top-level
    installation directory is — the same environment variable Audit's and Logs' own path
    resolution already read. The fallback resolves outside the repository, never into
    `data/`, so a bare developer checkout stays runnable without becoming a home for
    real cached lookups (`docs/PRINCIPLES.md` §1.6, §2.4).
    """
    top = os.environ.get("RESIBO_TOP_LEVEL")
    base = Path(top) if top else Path.home() / ".resibo"
    return base / "geo_address_cache.sqlite"


@dataclass(frozen=True)
class CachePolicy:
    """§4's own staleness knob. `stale_after_days` is a reasoned default, not yet measured
    against real vendor-address churn (`docs/PRINCIPLES.md` §5's "reasoned, then measured"
    discipline) — 90 days matches Logs' own `RetentionPolicy` default for the same reason: a
    small business relocating or closing inside three months is the real, if uncommon, case
    this guards against, and there is no bench-suite measurement yet to justify a tighter or
    looser number.
    """

    stale_after_days: int = 90


def normalize_query(
    candidate_strings: Sequence[str], country_code: str, providers: Sequence[str]
) -> str:
    """A stable cache key: whitespace-collapsed, case-folded, and independent of input
    ordering artifacts that would otherwise fragment the cache (a `providers` filter supplied
    in a different order should still hit the same entry).
    """
    normalized_candidates = tuple(
        " ".join(c.strip().lower().split()) for c in candidate_strings if c and c.strip()
    )
    normalized_providers = tuple(sorted(p.strip().lower() for p in providers if p.strip()))
    payload = {
        "candidates": normalized_candidates,
        "country_code": (country_code or "").strip().upper(),
        "providers": normalized_providers,
    }
    return json.dumps(payload, sort_keys=True)


class GeoCache:
    """One connection, one small database, matching Audit's own `db.py` shape: WAL mode so a
    read and a write never block each other, and every method degrades rather than raising
    into a caller whose whole reason for consulting the cache was to avoid real work."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        policy: CachePolicy | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._policy = policy or CachePolicy()
        self._now = now
        resolved = Path(path) if path is not None else default_cache_db_path()
        is_memory = str(resolved) == ":memory:"
        if not is_memory:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(resolved), check_same_thread=False)
        except sqlite3.Error as exc:
            raise CacheUnavailable(str(exc)) from exc
        self._conn.row_factory = sqlite3.Row
        if not is_memory:
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    def normalize(
        self, candidate_strings: Sequence[str], country_code: str, providers: Sequence[str]
    ) -> str:
        return normalize_query(candidate_strings, country_code, providers)

    def get(self, key: str) -> tuple[GeoResult, bool] | None:
        """`(result, is_stale)`, or `None` on a genuine miss — including a miss manufactured
        by a read failure, since a caller cannot tell "never cached" from "cache unreadable
        right now" apart in any way that would change what it does next (§4.4)."""
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT result_json, cached_at FROM geo_cache WHERE cache_key = ?", (key,)
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            cached_at = datetime.fromisoformat(row["cached_at"])
            result = _decode(row["result_json"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None
        age_days = (self._now() - cached_at).total_seconds() / 86400.0
        return result, age_days > self._policy.stale_after_days

    def put(self, key: str, result: GeoResult) -> None:
        """A write that fails costs nothing but the caching benefit — never the call it was
        asked to accelerate (§4.4)."""
        try:
            payload = _encode(result)
            with self._lock:
                self._conn.execute(
                    "INSERT INTO geo_cache (cache_key, result_json, cached_at) VALUES (?, ?, ?)"
                    " ON CONFLICT(cache_key) DO UPDATE SET"
                    " result_json = excluded.result_json, cached_at = excluded.cached_at",
                    (key, payload, self._now().isoformat()),
                )
                self._conn.commit()
        except sqlite3.Error:
            return

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------- serialization


def _address_to_dict(address: GeoAddress | None) -> dict | None:
    if address is None:
        return None
    return {
        "formatted": address.formatted,
        "line1": address.line1,
        "barangay": address.barangay,
        "city": address.city,
        "province": address.province,
        "region": address.region,
        "postal_code": address.postal_code,
        "country_code": address.country_code,
        "latitude": address.latitude,
        "longitude": address.longitude,
    }


def _address_from_dict(data: dict | None) -> GeoAddress | None:
    return None if data is None else GeoAddress(**data)


def _error_to_dict(error: GeoError | None) -> dict | None:
    return None if error is None else {"code": error.code, "detail": error.detail}


def _error_from_dict(data: dict | None) -> GeoError | None:
    return None if data is None else GeoError(**data)


def _provider_result_to_dict(result: ProviderCandidateResult) -> dict:
    return {
        "provider": result.provider,
        "candidate_string": result.candidate_string,
        "address": _address_to_dict(result.address),
        "confidence": result.confidence,
        "matched_business_name": result.matched_business_name,
        "raw": dict(result.raw),
        "error": _error_to_dict(result.error),
    }


def _provider_result_from_dict(data: dict) -> ProviderCandidateResult:
    return ProviderCandidateResult(
        provider=data["provider"],
        candidate_string=data["candidate_string"],
        address=_address_from_dict(data["address"]),
        confidence=data["confidence"],
        matched_business_name=data["matched_business_name"],
        raw=FrozenDict(data["raw"]),
        error=_error_from_dict(data["error"]),
    )


def _encode(result: GeoResult) -> str:
    payload = {
        "normalized_address": _address_to_dict(result.normalized_address),
        "confidence": result.confidence,
        "agreement": result.agreement.value,
        "matched_candidate_string": result.matched_candidate_string,
        "provider_results": [_provider_result_to_dict(r) for r in result.provider_results],
        "vendor_name_at_address": result.vendor_name_at_address,
        "vendor_name_discrepancy": result.vendor_name_discrepancy,
        "conflict": result.conflict,
        "conflict_detail": result.conflict_detail,
        "degraded_providers": list(result.degraded_providers),
        "error": _error_to_dict(result.error),
    }
    return json.dumps(payload, sort_keys=True)


def _decode(raw: str) -> GeoResult:
    data = json.loads(raw)
    return GeoResult(
        normalized_address=_address_from_dict(data["normalized_address"]),
        confidence=data["confidence"],
        agreement=AgreementLevel(data["agreement"]),
        matched_candidate_string=data["matched_candidate_string"],
        provider_results=tuple(
            _provider_result_from_dict(r) for r in data["provider_results"]
        ),
        vendor_name_at_address=data["vendor_name_at_address"],
        vendor_name_discrepancy=data["vendor_name_discrepancy"],
        conflict=data["conflict"],
        conflict_detail=data["conflict_detail"],
        degraded_providers=tuple(data["degraded_providers"]),
        error=_error_from_dict(data["error"]),
        from_cache=True,
    )


__all__ = [
    "SCHEMA",
    "CachePolicy",
    "GeoCache",
    "default_cache_db_path",
    "normalize_query",
]
