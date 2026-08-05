"""VirusTotal cloud scanner adapter — the swappable alternative to the local ClamAV default
(§9, resolved: "a well-established, genuinely multi-engine scanning API with a real free
tier... a defensible default, not a coin flip").

**The actual HTTP calls sit behind one small `HttpTransport` seam**
(`docs/PRINCIPLES.md` §1.3), separately from the ClamAV provider's own subprocess adapter but
for the identical reason. Production wiring uses `urllib.request` directly: `requests` and
`httpx` are not declared in `requirements.txt`, and adding either is outside this pass's own
write boundary (see this package's `CLAUDE.md`) — stdlib is a genuinely sufficient way to make
two authenticated HTTP calls, so no new dependency is needed to implement this for real. A test
injects any callable matching `HttpTransport`'s own shape, exercising every response-handling
branch below without a real socket — which also means this provider's own fail-closed paths
are exercised even in a sandbox with no network reachability at all, exactly the environment
this was implemented in.

VirusTotal's own v3 API returns a *per-engine* breakdown, not one verdict — this provider's own
`_to_result` collapses that breakdown into one of `CLEAN`/`SUSPICIOUS`/`MALICIOUS` for itself.
The cross-*provider* consensus that §9 actually specifies (unanimous malicious to auto-reject,
any disagreement to staff review) happens one level up, in `pipeline.py`, across this
provider's own single collapsed outcome and ClamAV's — never re-litigated at the per-engine
level here.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from ..contracts import ProviderScanResult, ScanOutcome

API_BASE = "https://www.virustotal.com/api/v3"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_MAX_POLLS = 10

#: Any engine flagging a file is enough for this provider's *own* malicious outcome — the
#: point where "how many engines is enough" gets adjudicated is the cross-provider consensus
#: rule in `pipeline.py`, not a second, independent threshold buried in this adapter.
MALICIOUS_ENGINE_THRESHOLD = 1
SUSPICIOUS_ENGINE_THRESHOLD = 1


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


#: method, url, body, headers -> response. The entire seam a test needs to fake.
HttpTransport = Callable[[str, str, "bytes | None", dict], HttpResponse]


def default_transport(method: str, url: str, data: bytes | None, headers: dict) -> HttpResponse:
    """The real transport: `urllib.request`, stdlib only (see this module's own docstring)."""
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return HttpResponse(status=response.status, body=response.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(status=exc.code, body=exc.read())


class VirusTotalProvider:
    """The cloud, multi-engine alternative (§9)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: HttpTransport = default_transport,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_polls: int = DEFAULT_MAX_POLLS,
    ) -> None:
        self._api_key = api_key
        self._transport = transport
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._max_polls = max_polls

    @property
    def name(self) -> str:
        return "virustotal"

    async def is_available(self) -> bool:
        """Whether an API key is configured — not a network probe.

        Spending a quota-limited call just to answer "are you there" would be worse than the
        alternative: a real outage encountered during an actual scan still degrades correctly,
        to `ScanOutcome.ERROR` (a deny, never treated as "unavailable, so skip it") — the
        distinction this module's own docstring already draws between availability and a
        failed invocation.
        """
        return bool(self._api_key)

    async def scan(self, content: bytes, *, blob_ref: str = "") -> ProviderScanResult:
        if not self._api_key:
            return ProviderScanResult(
                self.name, ScanOutcome.UNAVAILABLE, detail="no VirusTotal API key configured"
            )
        try:
            return await asyncio.to_thread(self._scan_sync, content)
        except Exception as exc:  # noqa: BLE001 - any transport/parsing failure denies (§4.2)
            return ProviderScanResult(self.name, ScanOutcome.ERROR, detail=f"{type(exc).__name__}: {exc}")

    # ---------------------------------------------------------------- blocking half

    def _scan_sync(self, content: bytes) -> ProviderScanResult:
        headers = {"x-apikey": self._api_key or ""}
        upload = self._transport("POST", f"{API_BASE}/files", content, headers)
        if upload.status >= 400:
            return ProviderScanResult(
                self.name, ScanOutcome.ERROR, detail=f"upload failed: HTTP {upload.status}"
            )

        analysis_id = self._extract(upload.body, "data", "id")
        if analysis_id is None:
            return ProviderScanResult(
                self.name, ScanOutcome.ERROR, detail="malformed upload response: missing analysis id"
            )

        return self._poll(analysis_id, headers)

    def _poll(self, analysis_id: str, headers: dict) -> ProviderScanResult:
        for _ in range(self._max_polls):
            poll = self._transport("GET", f"{API_BASE}/analyses/{analysis_id}", None, headers)
            if poll.status >= 400:
                return ProviderScanResult(
                    self.name, ScanOutcome.ERROR, detail=f"poll failed: HTTP {poll.status}"
                )
            try:
                payload = json.loads(poll.body)
                status = payload["data"]["attributes"]["status"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                return ProviderScanResult(
                    self.name, ScanOutcome.ERROR, detail=f"malformed poll response: {exc}"
                )
            if status == "completed":
                return self._to_result(payload)
            time.sleep(self._poll_interval)
        return ProviderScanResult(
            self.name, ScanOutcome.ERROR, detail="analysis did not complete within the poll budget"
        )

    def _to_result(self, payload: dict) -> ProviderScanResult:
        try:
            stats = payload["data"]["attributes"]["stats"]
            malicious = int(stats.get("malicious", 0))
            suspicious = int(stats.get("suspicious", 0))
        except (KeyError, TypeError, ValueError) as exc:
            return ProviderScanResult(
                self.name, ScanOutcome.ERROR, detail=f"malformed analysis stats: {exc}"
            )
        if malicious >= MALICIOUS_ENGINE_THRESHOLD:
            return ProviderScanResult(
                self.name, ScanOutcome.MALICIOUS, detail=f"{malicious} engine(s) flagged malicious"
            )
        if suspicious >= SUSPICIOUS_ENGINE_THRESHOLD:
            return ProviderScanResult(
                self.name, ScanOutcome.SUSPICIOUS, detail=f"{suspicious} engine(s) flagged suspicious"
            )
        return ProviderScanResult(self.name, ScanOutcome.CLEAN)

    @staticmethod
    def _extract(body: bytes, *path: str) -> str | None:
        try:
            value = json.loads(body)
        except json.JSONDecodeError:
            return None
        for key in path:
            if not isinstance(value, dict) or key not in value:
                return None
            value = value[key]
        return value if isinstance(value, str) else None


__all__ = ["HttpResponse", "HttpTransport", "VirusTotalProvider", "default_transport"]
