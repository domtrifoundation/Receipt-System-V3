# Architect API

Architect owns two related things: the **read registry** (definitions — what taxonomy categories, reference-identifier types, and flag types exist) and **temporal learning** (the write submodule — how the system learns new vendor/branch/taxonomy data over time, staged through review).

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new as a consolidated registry. V2 reinvented the extensible-typed-thing pattern ad hoc in several places rather than owning it once — that repetition is what this API exists to stop. Its `temporal_learning` submodule has its own separate V2 lineage; see that folder's own `CLAUDE.md`. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.03`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-26-architect-api.md`](../../docs/apis/v3-deepdive-26-architect-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **implement any consuming API's own logic** — Matching does the actual fuzzy-matching, Reconciliation runs the actual checks; Architect only defines what a valid vendor record or flag type looks like, never performs the matching or checking itself. `vendor_directory/directory.py` searches by exact-on-normalized name, alias and TIN for exactly this reason: resolving noisy OCR text to a corporation is Matching's, and doing it here would be this API implementing a consumer's logic.
- **allow any other API to define its own parallel taxonomy** — this is file 02's binding rule #7, no exceptions: any new schema/taxonomy/learned-data type goes through this API's registry, full stop.
- **own disk.** Persistence owns every write to storage. `EntityStore` here is a Protocol with an in-memory implementation because Architect is implemented before Persistence's write path exists; the Persistence-backed store drops in behind that same Protocol, and no module here opens a database.
- **own the vendor-management UI.** `v3-deepdive-40` §8 states the requirement (browse, share, staff review, staff direct edit); the actual screens are Interface API's and the webapp's own work.
- **classify anything.** It defines the category taxonomy; Matching and Inference are what decide which category a given receipt or vendor falls into (deep-dive §5).

## Forward-Compatibility Pattern applicability

Yes, and now with real code behind it. Contracts are `@dataclass(frozen=True)` with `FrozenDict` dict-typed fields (`docs/PRINCIPLES.md` §2.1), and the module-level lookup tables — `errors.ERROR_MESSAGES`, `metrics.COUNTER_DESCRIPTIONS`, `vendor_directory/aliases.CORPORATE_SUFFIXES`, `wikidata_bootstrap.WIKIDATA_CLASS_TO_CATEGORY`, `WIKIDATA_CONFIG_DEFAULTS` and `temporal_learning/entities.py`'s `_ENTITY_CLASSES` / `_ID_FIELDS` / `_REQUIRED_FIELDS` — are `FrozenDict` per §2.1.1.

**Four `isinstance` gates in this API decide behaviour on a mapping and every one of them tests `collections.abc.Mapping`, never `dict`**: `registry/read.py`'s definition validator, `temporal_learning/entities.py`'s field validator, `temporal_learning/contribution.py`'s change validator, and `temporal_learning/category_defaults.py`'s `_hashable`. On 3.15+ the builtin `frozendict` is not a `dict` subclass, so a regression to `dict` in any of them silently rejects (or crashes on) a correctly-typed caller. `tests/unit/core/architect/test_forward_compat.py` exercises all four with a real `FrozenDict` and is marked `forward_compat` for `nox -s forward_compat`.

No free-threading or `asyncio`-version-sensitive assumptions: the async surface is `await`-on-I/O only (`asyncio.gather` in the seed-source registry), and nothing here holds shared mutable state across threads beyond the registries described below.

## Real gotchas specific to this folder

`docs/PRINCIPLES.md` §3.4 is binding and has no exceptions: no API defines its own ad hoc typed thing, spins up its own table for learned/schema data, or invents a parallel taxonomy, even for one narrow case. This rule exists because the same pattern was independently reinvented five separate times before this API was created to consolidate it. Architect defines what is allowed to exist; it never holds instance data.

**Adding a definition is routine; adding a `DefinitionKind` is not.** A consumer registering a new flag type or category through `DefinitionRegistry.register` is the intended everyday path. A sixth `DefinitionKind` means a genuinely new species of schema data exists and goes through `docs/templates/new_taxonomy_type.md` first.

**Definitions are deprecated, never deleted.** Instance data written against a definition outlives the decision to stop offering it, so `deprecate` hides a definition from `list` while `get` keeps resolving it.

**Files here the deep-dive's §2 package layout does not name**, added with reasons:
- `registry/seed_definitions.py` — the shipped seed set, split out to keep `read.py` inside the file-length target. The flag types map one-to-one onto Reconciliation's own check modules; they are seeds, not a closed enumeration.
- `vendor_directory/seed_sources.py` — the seed-source Provider Registry. §3 describes Wikidata as one source with stated coverage limits, which is the case where parallel providers beat one config-selected provider (`docs/PRINCIPLES.md` §1.2).
- `vendor_directory/directory.py` — serves §7's `SearchVendorDirectory`; the layout names no module for it.
- `architect.proto` — §7's surface. The layout predates showing where a `.proto` lives.

**Nothing here makes a network call unless a transport is wired in.** `WikidataSeedSource` defaults to `UnavailableTransport`, which reports itself unreachable rather than quietly hitting a public endpoint from a fresh install. Swapping the HTTP client, pointing at a self-hosted Wikibase, or replaying a captured response are all the same operation: a different `SparqlTransport`.

**Beware truthiness on this package's own collection-like objects.** `AliasIndex`, `ReviewAuditMirror` and several others define `__len__`, so an empty-but-genuinely-supplied instance is falsy — constructor defaults use `x if x is not None else Default()`, never `x or Default()`. That exact bug detached a caller's alias index from the directory during implementation.

**`service.py`/`architect.proto`'s generated stubs did not exist at all until this session — a real, complete gap, not a documented placeholder.** Every module `ArchitectServicer` calls (`registry/read.py`'s `DefinitionRegistry`, `temporal_learning/moderation_queue.py`'s `ModerationQueue`, `vendor_directory/directory.py`'s `VendorDirectory`) already existed and was independently tested, but nothing in this package ever constructed one of each and answered a single RPC. `architect.proto` defined a contract that Persistence, Matching, Review/Flagging, Billing and Execution Core are all meant to call, and there was no server on the other end of it. Confirmed live: `GetTaxonomy` against the real seeded categories, a full `SubmitContribution` -> prescreen -> `ReviewContribution` -> merge round trip that shows up in a subsequent `SearchVendorDirectory` call, the staff direct-to-global path (`staff_authored=True`) merging without a separate review call, and a rejected contribution correctly never reaching the directory.

**`ContributionRequest.staff_authored` is trusted verbatim from the request — a real, NOT-enforced gap, not silently glossed over.** The proto's own comment states this must be "resolved by the server" from the caller's session role, never taken as a claim the caller makes about itself. No Auth API client exists anywhere in this codebase's `service.py` files yet to check a role against (confirmed by checking every other API's `service.py`), so this servicer cannot enforce that today. Documented in `service.py`'s own module docstring: do not expose this RPC to an untrusted caller until a Gateway-level or Auth-backed role check is wired in front of it.

**`ReviewContribution` merges immediately on approval — there is no separate merge RPC in `architect.proto`.** `ModerationQueue.review()` and `.merge()` are two distinct calls in `moderation_queue.py`'s own API; the servicer chains them because there is no reason a caller would want to hold an approved, eligible contribution unmerged, and the proto's own single `ReviewRequest` -> `ContributionResponse` shape has no room for a caller to ask for the two steps separately.
