# V3 Deep Dive: Geo/Address API

**Companion files:** all prior deep-dives, especially `v3-deepdive-10-execution-core-api.md` (the `GEOD` synchronous pipeline stage, for new receipts) and `v3-deepdive-17-reconciliation-api.md` (the same capability applied retroactively to old receipts, `docs/PRINCIPLES.md` §1.9), `v3-deepdive-07-tool-call-api.md` (its `geo_tools.py` wraps this API) and `v3-deepdive-15-matching-api.md` (a sibling corroboration-shaped API).

**Status:** Sixteenth deep-dive session. File 02's own Concurrency Model table explicitly flags this API as a known real-world stall point in V2 (`urllib.request.urlopen()` sequential loop) — this deep-dive treats that flag as a hard requirement, not a suggestion.

---

## 1. Scope & boundary

Geo/Address API owns geocoding — two genuinely distinct capabilities, not one: **completing or correcting an incomplete/incorrect address** read off a receipt, and **reverse-checking what business is actually located at that address**, as a real cross-corroboration signal for the vendor match itself (an OCR-read vendor name that doesn't match what's actually at the geocoded address is a real, useful discrepancy signal, not just an address-quality check). It does not:
- **decide when a geo lookup is worth its cost** — a per-run call budget and whether a given receipt even needs address correction is caller policy, the same boundary every other corroboration-shaped API in this project draws for itself (OCR's cloud tier, Inference's reasoning-preset budget). **This API genuinely has two legitimate callers, not one** — a real correction made after tracing the pipeline found only one connected and assumed that was the whole picture: **Execution Core** calls it synchronously as the `GEOD` stage for new receipts during the live run (`v3-deepdive-10-execution-core-api.md` §3, between `MATCHED` and `INFERRED`); **Reconciliation** calls the identical underlying function against already-written, older receipts during its own idle-time sweep — the concrete case `docs/PRINCIPLES.md` §1.9's own backward-carrying-capability principle was written from. When this API's own provider set or corroboration logic improves, that improvement should be able to reach old receipts too, not just ones processed going forward — which is only actually possible because both callers invoke the same underlying capability rather than each having their own copy.
- **own the address data it corrects into** — the corrected/canonical address becomes part of a receipt's own record via Persistence's normal write path; this API just returns a result.

---

## 2. Package layout

```
core/geo_address/
  __init__.py
  contracts.py            # GeoQuery, GeoResult, error types
  service.py                 # thin gRPC service implementation
  providers/
    __init__.py
    base.py                    # GeoProvider protocol — Provider Registry
    locationiq.py
    mapbox.py
    nominatim_self_hosted.py
  cache.py                    # response caching in the canonical SQLite database — see §4
  corroboration.py              # multi-provider + multi-candidate cross-check — see §3
  errors.py
  metrics.py
```

---

## 3. Provider Registry — parallel corroboration, and a distinct multi-candidate axis
Default providers: **LocationIQ + Mapbox**, both free at this project's expected scale, genuinely independent underlying data sources — real corroboration value, not redundant calls to the same underlying dataset wearing two API keys. **Self-hosted Nominatim** (a PH-only OSM extract) is available as an unlimited-throughput option, valuable specifically for a fully cloud-independent self-hosted install or at genuine scale where the free-tier providers' rate limits become the bottleneck. **A real, actionable setup guide exists for this** — `docs/SELF_HOSTED_NOMINATIM.md`, covering VPS choice (Oracle Cloud's Always Free Ampere A1 tier as the reference recommendation), the current de-facto `mediagis/nominatim` Docker image, the import process, and ongoing replication — linked from this API's own TUI settings entry (its own `docs_ref` field, the same pattern Audit API's retention setting already uses for its own legal citation, `v3-deepdive-08-audit-event-log-api.md` §5) rather than duplicated inline here.

**A second, distinct axis worth being precise about — file 01 names this explicitly, and it's easy to conflate with plain multi-provider corroboration**: within a *single* provider's own results, search several plausible vendor/address strings ranked by frequency across OCR's own multiple readings (its deep-dive's corroboration output), not just the single best-guess string. This catches a case multi-provider corroboration alone wouldn't: every provider correctly geocoding a *wrong* input string (because OCR's top-ranked reading was itself wrong) produces confident-looking agreement on a wrong answer — searching several OCR candidate strings, not just the top one, against the same provider(s) is what actually guards against that failure mode.
```python
async def geocode_with_corroboration(candidates: list[OcrTextCandidate], providers: list[GeoProvider]) -> GeoResult:
    """Two independent axes, not one: (1) which providers to query — a
    Provider Registry corroboration set; (2) which OCR-reading candidate
    strings to feed each provider — a multi-candidate axis within each
    provider. Both run concurrently via asyncio.gather, not nested
    sequential loops — see §5 for why sequential is the specific bug
    this API exists to not repeat."""
```

---

## 4. Response caching — stretches every provider's free tier
Keyed by normalized query string, stored in the canonical SQLite database (no separate cache service, consistent with this project's repeated preference against extra infrastructure — same reasoning Auth's session store and Notifications' inbox already gave for staying on SQLite rather than reaching for Redis). A repeated lookup for the same normalized address across different receipts (a common vendor, queried many times) never re-hits a rate-limited provider for data already known.

---

## 5. Asyncio — flagged, not optional, the actual fix for a real V2 bug
File 02 calls this out explicitly: V2's `urllib.request.urlopen()` ran geo lookups in a **sequential loop**, a genuine, real stall point in the pipeline. This isn't a nice-to-have async wrapper the way it might be framed for a lower-stakes API — **every provider call and every candidate-string variant in §3's corroboration logic must run via `asyncio.gather`, never a `for` loop of blocking calls**, or this API reproduces the exact bug it exists to fix. Per-provider rate limiting (Nominatim's well-known 1 request/second limit specifically) is enforced via a per-provider `asyncio.Semaphore` or token-bucket, not by simply slowing down a sequential loop to match the limit — the corroboration set as a whole should still complete in roughly the time of its slowest single provider, not the sum of all of them.

---

## 6. gRPC surface

```protobuf
service GeoAddressService {
  rpc Geocode(GeocodeRequest) returns (GeocodeResponse);
}

message GeocodeRequest {
  repeated string candidate_strings = 1;   // OCR's ranked candidates, not just the top one — see §3
  repeated string providers = 2;             // which registered providers to query, empty = all enabled
}

message GeocodeResponse {
  repeated GeoResult results = 1;
}

message GeoResult {
  string normalized_address = 1;
  float confidence = 2;
  string provider = 3;
  string matched_candidate_string = 4;   // which of the input candidates this result came from
}
```

---

## 7. Config surface

```
geo_address:
  providers_enabled: [locationiq, mapbox]     # nominatim_self_hosted is addable here too, once configured — see docs/SELF_HOSTED_NOMINATIM.md
  locationiq:
    api_key: ""
  mapbox:
    api_key: ""
  nominatim_self_hosted:
    endpoint: ""                                # presence in providers_enabled above is what actually turns it on — no separate enabled flag, for consistency with locationiq/mapbox
  max_calls_per_run: 10
```
**A real config-consistency fix, found while checking this API's own modularity**: an earlier version of this config gave `nominatim_self_hosted` its own separate `enabled: true/false` flag, structurally different from how `locationiq`/`mapbox` get enabled (inclusion in the `providers_enabled` list). Fixed — all three providers are enabled the identical way now, genuine peers behind the same `GeoProvider` Protocol, not two different mechanisms for what's conceptually the same action.

---

## 8. Testing hooks
- **Sequential-loop regression guard**: a test that measures corroboration-call wall-clock time against a mocked-slow provider, confirming it scales with the slowest single call, not the sum — direct validation of §5's core requirement, since this is exactly the kind of regression that could silently creep back in without an explicit check.
- **Nominatim rate-limit compliance test**: confirms the token-bucket/semaphore genuinely caps at 1 req/sec against that specific provider even under a burst of corroboration requests.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Cross-provider result reconciliation, resolved: reuses OCR API's own tiered deterministic-then-escalate corroboration pattern, not a second voting scheme.** When LocationIQ and Mapbox genuinely disagree, the same approach OCR's own corroboration layer already applies (its deep-dive §7 — deterministic agreement where possible, escalate to a flag when it isn't) is the right fit here too, confirmed explicitly rather than left as a likely-but-unconfirmed reuse. No new merge/voting logic needed.
- (Self-hosted Nominatim VPS operational ownership — resolved, no longer just "an operations question, not addressed here." A real setup guide now exists, `docs/SELF_HOSTED_NOMINATIM.md`, ending with an explicit "read this before committing" section stating plainly that the operator takes on real, ongoing responsibility — security updates, replication cadence, disk growth — that LocationIQ/Mapbox don't require. Linked from this API's own TUI settings entry rather than duplicated in-app.)
