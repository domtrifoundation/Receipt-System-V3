# V3 Deep Dive: Architect API

**Companion files:** nearly every prior deep-dive references this one — Matching's Vendor Directory, Reconciliation's flag taxonomy, Persistence's reference-identifier types, Tool Call's vendor-write tools, Review/Flagging's flag types all defer to this API's registry rather than owning their own.

**Status:** Twenty-sixth deep-dive session. Central by design — file 02's rule #7 makes this API's registry the *only* place any new schema/taxonomy/learned-data type is ever allowed to be defined, specifically because the same pattern was independently reinvented five separate times before this API was created to consolidate it.

---

## 1. Scope & boundary

Architect owns two related things: the **read registry** (definitions — what taxonomy categories, reference-identifier types, and flag types exist) and **temporal learning** (the write submodule — how the system learns new vendor/branch/taxonomy data over time, staged through review). It does not:
- **implement any consuming API's own logic** — Matching does the actual fuzzy-matching, Reconciliation runs the actual checks; Architect only defines what a valid vendor record or flag type looks like, never performs the matching or checking itself.
- **allow any other API to define its own parallel taxonomy** — this is file 02's binding rule #7, no exceptions: any new schema/taxonomy/learned-data type goes through this API's registry, full stop.

---

## 2. Package layout

```
core/architect/
  __init__.py
  contracts.py             # TaxonomyType, ReferenceIdentifierType, FlagType, VendorRecord, error types
  registry/
    __init__.py
    read.py                    # definitions — what types exist
  temporal_learning/
    __init__.py
    contribution.py               # staged writes, see §4
    moderation_queue.py             # LLM-prescreen → staff-review pipeline
  vendor_directory/
    __init__.py
    wikidata_bootstrap.py           # see §3
    aliases.py
  errors.py
  metrics.py
```

---

## 3. Vendor Directory — Wikidata-seeded, now on a recurring schedule, with the real root cause of the filtering bug identified
File 03 already found the real problem with V2's SPARQL bootstrap: it returned only ~2,600 entries and missed real PH SMBs (e.g. "Chooks To Go"). **The root cause is now identified, verified against Wikidata's own official documentation, not just suspected.** Wikidata's own SPARQL tutorial confirms the exact failure mode: a bare `wdt:P31 wd:Q4830453` clause ("instance of: business," directly) only matches items tagged with that *exact* class — it silently misses every item classified under a more specific subclass instead, since P31 (instance of) alone doesn't traverse the class hierarchy. "Chooks To Go" is a fast-food/restaurant chain, almost certainly classified under a sibling subclass rather than the generic "business" class directly — exactly the gap this bug would produce. **Worth being precise about what's confirmed and what isn't**: the root-cause diagnosis and the standard fix pattern are both confirmed against Wikidata's own documentation; the exact resulting entry count after applying the fix hasn't been empirically measured against the live endpoint, and shouldn't be presented as if it has been. **Scope is deliberately limited: name/category only, not TIN/franchise data** — Wikidata is a reasonable source for "this business exists and is roughly this kind of business," genuinely unreliable for the specific financial/legal identifiers this project actually needs to get right, which come from the system's own learned contributions instead (§4).

### 3.1 The actual fix — subclass traversal, not a bare class match
```python
async def bootstrap_from_wikidata(query_filter: SparqlFilter) -> list[VendorSeedRecord]:
    """The corrected query pattern, per Wikidata's own documented
    convention for this exact problem: `wdt:P31/wdt:P279* wd:Q4830453`
    — 'instance of business, or instance of any subclass of business,
    transitively' — not the bare `wdt:P31 wd:Q4830453` V2's own query
    almost certainly used, which only matches the exact class and
    silently misses every subclass (restaurant chain, retail chain,
    fast-food chain, brand, etc.) a real PH business is far more
    likely to actually be classified under. Combined with a location
    filter (P17 country, or P159 headquarters location, set to the
    Philippines) rather than relying on name-matching alone, so a
    business classified under any commercial subclass — not just the
    single class the original query checked — gets caught as long as
    its own location data identifies it as Philippine."""
```
This is a real, evidence-based fix — confirmed against Wikidata's own official tutorial documentation, which names this exact `P31/P279*` pattern as the standard solution to exactly this class of undercounting bug — not a guess dressed up as one.

### 3.2 Now a recurring, configurable poll — not a one-time bootstrap
**Resolved with real direction**: Wikidata bootstrap runs on a recurring, owner-configurable interval, not once at first setup and never again — so new Wikidata entries (a business added to Wikidata after this instance's own last pull) actually get picked up over time, rather than this project's own vendor coverage being permanently frozen at whatever existed the day the instance was set up.
```
architect:
  wikidata:
    poll_interval_days: 30            # not too frequent by default — Wikidata's own business-listing data doesn't change fast enough to justify a tighter default, and this is a courtesy to a public, shared endpoint other projects also rely on
    query_version: 2                    # bumped when the query itself changes (e.g. this fix), so a re-pull after a query change is distinguishable from a routine scheduled one
```
Registered as a real Background Workers job (its own consolidated registry, `v3-deepdive-12-background-workers-api.md` §6.1), `SCHEDULED_ONLY`-shaped in Supervisor's own sleep/wake sense (`v3-deepdive-38-supervisor.md` §6.2) — genuinely infrequent, no reason for anything to stay resident waiting on a monthly-at-most trigger. New entries pulled on each run get merged into the existing directory the same way any other `GLOBAL`-layer contribution would (temporal_learning's own moderation pipeline, §4 below) — a Wikidata-sourced entry isn't specially privileged over a system-learned one, it goes through the same real review path.

---

## 4. Temporal learning
**Full treatment in `v3-deepdive-40-temporal-learning.md`** — corrected out of this document after a corpus-wide sweep found it explicitly named with its own package path in file 01 and genuinely comparable in scope to Historian or Reimport. Covers: a real Corporation/Branch/Franchiser data model (a franchiser is its own standalone entity, referenced by branches rather than duplicated across them — the fix for a franchiser operating branches under multiple different corporations), local/global data layering with an explicit user-consent sharing gate (a local fact never enters the moderation queue automatically), a separate staff direct-to-global path, category-default learning, the LLM-prescreen-then-staff-review moderation pipeline, Curate's own self-cleaning mechanism, and a specified (not yet implemented) manual-management UI requirement for both webapp and TUI. Summary: every consumer that wants to teach the system something new writes to `LOCAL` freely with no review at all, and only an explicit share action or a staff member's own direct authority ever moves a fact toward `GLOBAL` — the mechanism Tool Call API's own deep-dive (§4) relies on as the "safe to self-apply" gate during automated processing.

---

## 5. Category classification — a named capability spanning Matching and Inference
File 03 names this explicitly as spanning two APIs, not owned by either alone: Architect defines the category taxonomy itself (what categories exist, their hierarchy); Matching and Inference each consume it for their own purposes (Matching's items-vendor mismatch check, Inference's own classification-assisting prompts) — Architect never performs a classification itself, it's purely the taxonomy's source of truth.

---

## 6. Asyncio and profiling
Registry reads are fast, cacheable lookups — genuinely async I/O, no different from any other SQLite-backed API in this batch. The moderation queue's LLM-prescreen step is a batch Inference API call (Background Workers API deep-dive §5's own principle — LLM-driven background work is just a dispatched Inference job, not a separate subsystem), not a compute-bound concern of this API's own.

---

## 7. gRPC surface

```protobuf
service ArchitectService {
  rpc GetTaxonomy(TaxonomyRequest) returns (TaxonomyResponse);
  rpc SubmitContribution(ContributionRequest) returns (ContributionResponse);
  rpc ReviewContribution(ReviewRequest) returns (ContributionResponse);
  rpc SearchVendorDirectory(VendorSearchRequest) returns (VendorSearchResponse);
}
```

---

## 8. Testing hooks
- **Rule #7 enforcement check** (§1): a CI-level check scanning for any new SQLite table or ad hoc typed structure defined outside this API's own package — the concrete mechanism that turns the binding rule from a documented convention into something actually enforced, not just trusted to be remembered.
- **Contribution pipeline test**: confirms a contribution never reaches the live directory without passing through both prescreen and staff approval — no shortcut path.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Wikidata SPARQL filter, root cause and fix now confirmed against Wikidata's own documentation (§3.1) — one real thing still genuinely outstanding.** The diagnosis (missing subclass traversal) and the fix pattern (`wdt:P31/wdt:P279*`) are both confirmed, not guessed at. What hasn't happened yet: running the corrected query live against the real Wikidata endpoint to confirm the actual resulting entry count and spot-check real PH businesses like "Chooks To Go" now appear. That's real, hands-on verification work, not a design question — stays open until that pass actually happens.
- (Moderation queue staff-assignment/workload distribution — resolved, no longer open. The same shared-open-queue, self-assign shape as Support Ticketing and Review/Flagging's own identical questions, `v3-deepdive-52-support-ticketing.md` §4 — one consistent staff-queue pattern across all three, not three independently-invented routing philosophies for the same underlying problem.)
- (V2's "Curate" idle-time self-cleaning pass — resolved, no longer open. Full mechanism designed in `v3-deepdive-40-temporal-learning.md` §6: three distinct cleanup patterns, each staged through the same moderation pipeline as any other contribution, never auto-applied.)
