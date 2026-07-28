# Geo/Address API

Geo/Address API owns geocoding — two genuinely distinct capabilities, not one: **completing or correcting an incomplete/incorrect address** read off a receipt, and **reverse-checking what business is actually located at that address**, as a real cross-corroboration signal for the vendor match itself (an OCR-read vendor name that doesn't match what's actually at the geocoded address is a real, useful discrepancy signal, not just an address-quality check).

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had real geocoding — `geo_lookup.py` with OSM/Nominatim and Google Places providers, forward and reverse lookups. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a02.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-16-geo-address-api.md`](../../docs/apis/v3-deepdive-16-geo-address-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide when a geo lookup is worth its cost** — a per-run call budget and whether a given receipt even needs address correction is caller policy, the same boundary every other corroboration-shaped API in this project draws for itself (OCR's cloud tier, Inference's reasoning-preset budget). **This API genuinely has two legitimate callers, not one** — a real correction made after tracing the pipeline found only one connected and assumed that was the whole picture: **Execution Core** calls it synchronously as the `GEOD` stage for new receipts during the live run (`v3-deepdive-10-execution-core-api.md` §3, between `MATCHED` and `INFERRED`); **Reconciliation** calls the identical underlying function against already-written, older receipts during its own idle-time sweep — the concrete case `docs/PRINCIPLES.md` §1.9's own backward-carrying-capability principle was written from. When this API's own provider set or corroboration logic improves, that improvement should be able to reach old receipts too, not just ones processed going forward — which is only actually possible because both callers invoke the same underlying capability rather than each having their own copy.
- **own the address data it corrects into** — the corrected/canonical address becomes part of a receipt's own record via Persistence's normal write path; this API just returns a result.
- **define an extensible address-component taxonomy, or any other learned/schema data** (`docs/PRINCIPLES.md` §3.4) — `contracts.GeoAddress`'s `barangay`/`city`/`province`/`region` fields are fixed contract fields for this project's own fixed PH addressing domain, not an ad hoc typed thing this API invented; if a genuinely new category of typed address data were ever needed, it goes through Architect API, no exceptions.
- **decide what a cross-provider conflict or a vendor-name discrepancy means for the receipt** — `GeoResult.conflict`/`vendor_name_discrepancy` are signals surfaced as data (`docs/PRINCIPLES.md` §4.3); Matching and Reconciliation decide what to do with them (flag it, escalate it, ignore it below some threshold), this API never resolves one on its own.
- **make a network call without being configured to** — every provider adapter defaults to `providers.base.UnavailableTransport`; constructing the default registry (`service.default_providers`) never touches a network, matching Architect's own `SparqlTransport` default for the identical reason.

## Forward-Compatibility Pattern applicability

Yes. `contracts.ProviderCandidateResult.raw` is a `FrozenDict`-typed field (a frozen dataclass holding a plain `dict` is only shallowly immutable, and `raw` is handed across the `asyncio.gather` fan-out in `corroboration.py` and round-trips through `cache.py`'s JSON encoding), so it uses `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against it must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass; `cache.py`'s own decode path is the one place people miss, since `FrozenDict(json.loads(...))` has to be reconstructed explicitly rather than assumed. Module-level lookup tables are `FrozenDict` too, per §2.1.1: `contracts.KNOWN_PROVIDERS`, `contracts.AGREEMENT_RANK`, `errors.ERROR_CODES`, `errors.ERROR_SUMMARIES`. `tests/unit/core/geo_address/test_contracts.py` and `test_cache.py` carry the `@pytest.mark.forward_compat` tests covering all of this.

No free-threading-specific shared mutable state beyond `metrics.py`'s own lock-guarded counters (the same pattern Logs' and Health's own `metrics.py` already use) and `cache.py`'s single SQLite connection guarded by its own `threading.Lock`. No `asyncio`-version-sensitive behaviour beyond ordinary `asyncio.gather`/`asyncio.sleep` usage.

## Real gotchas specific to this folder

Same two-caller rule as Matching (`docs/PRINCIPLES.md` §1.9) — Execution Core's `GEOD` stage and Reconciliation's idle sweep call the identical `corroboration.geocode_with_corroboration` (exposed over gRPC by `service.GeoAddressServicer.Geocode`, never a separate in-process shortcut). A better provider must be able to improve old receipts, not just new ones.

**The response cache is this API's own small top-level SQLite database, not a table inside Persistence's per-user canonical database.** The deep-dive's own §4 says "the canonical SQLite database," written before this project's per-user-vs-cross-tenant database split was fully worked out in Wave 1. A cache entry is not any one user's data — the same normalized address is looked up across every user with a receipt from that vendor — so `cache.py` follows the identical cross-tenant pattern Audit's `db.py`, Auth's session store and Architect's registry already established (`docs/PRINCIPLES.md` §1.6), resolved here rather than left as a literal reading of the deep-dive's own pre-Wave-1 phrasing. **This is this session's resolution of that gap, not a deep-dive open question** — the deep-dive's own §9 open questions (cross-provider reconciliation, self-hosted Nominatim's ops guide) were both already resolved in the document itself; this cache-placement detail is a design decision this implementation pass had to make that the deep-dive did not fully anticipate. Bypassing `cache.py` in a new code path has a real cost: it is what makes LocationIQ's and Mapbox's free tiers viable at this project's actual scale.

**Every provider adapter defaults to `providers.base.UnavailableTransport` and constructing the default registry never makes a network call** — the same seam Architect's `SparqlTransport`/`UnavailableTransport` already established for the identical reason (`docs/PRINCIPLES.md` §1.3, §4.4). No unit test in this package touches the network; every test injects a fake `GeoHttpTransport` (provider-adapter tests) or a fake `GeoProvider` entirely in memory (corroboration-layer tests).

**Self-hosted Nominatim is PH-only by construction, not by convention.** `NominatimSelfHostedProvider.is_scoped_to` refuses an out-of-scope `country_code` before ever reaching the transport — a coverage question, not a network failure, degraded honestly rather than guessed at.

**A genuine cross-provider disagreement (`AgreementLevel.SPLIT`) leaves `normalized_address` at `None` and sets `conflict=True`/`conflict_detail`** — never a silently-picked answer (`docs/PRINCIPLES.md` §4.3). `corroboration._agreement_for_group` reuses OCR API's own tiered deterministic-then-escalate shape (deep-dive §9's resolved reuse), and `_pick_winning_candidate` is the second, distinct corroboration axis: it scores every OCR candidate string's own cross-provider agreement and reports whichever scores best, not simply the top-ranked reading, which is what catches a top OCR guess that no provider (or only one) can resolve while a lower-ranked reading is genuinely corroborated.

**Files here that the deep-dive's §2 package layout does not name**, added with reasons:
- `reverse_check.py` — the deep-dive's own §1 names the reverse-check capability as this API's second, genuinely distinct job, but its own §2 layout gives `corroboration.py` only "multi-provider + multi-candidate cross-check" for the *forward* geocode. A separate module keeps `corroboration.py` inside the file-length target (`docs/PRINCIPLES.md` §1.1, §3.1) — the same split Health's own `live_diagnostic.py`/`capability_drift.py` already applies for its own two distinct responsibilities. Called only from `corroboration.geocode_with_corroboration`, never invoked standalone by either orchestrator.
- `geo_address.proto` + `generated/` — §6 sketches the surface but the layout predates showing where the `.proto` lives. Regenerate with `python -m grpc_tools.protoc` and re-apply the relative-import fix in `geo_address_pb2_grpc.py` (`from . import geo_address_pb2`); never hand-edit generated files. `service.py` imports them lazily, so the package stays importable — and its tests still meaningful — on an interpreter with no `grpcio` wheel yet.
