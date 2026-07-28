# V3 Deep Dive: temporal_learning (Architect API sub-API)

**Parent:** `v3-deepdive-26-architect-api.md` §4 (the section this document expands and replaces the brief version of). Explicitly named with its own package path (`architect/temporal_learning/`) in file 01 — the strongest candidate for a missed sub-API, per the corpus-wide sweep that found it.

**Companion files:** `v3-deepdive-07-tool-call-api.md` §4 (the "safe to self-apply" mutating-tool gate this pipeline provides), `v3-deepdive-12-background-workers-api.md` §6.2 (Curate's own job registry entry, previously listed as an open question with no mechanism behind it — §7 below is that mechanism), `v3-deepdive-44-webapp.md` §5.5 (the manual-management screen this document's §8 specified, now actually designed there).

**Status:** New dedicated document, corrected out of a one-paragraph treatment inside Architect's own deep-dive. Revised again to add the Corporation/Branch/Franchiser data model, the explicit local-to-shared consent gate, staff's direct-to-global path, and the manual-management UI requirement — all real gaps in the first version of this document, not present in the original one-paragraph treatment it replaced.

---

## 1. Scope & boundary

temporal_learning owns **how the system's vendor/branch/franchiser knowledge changes over time** — every write to the live Vendor Directory, staged through review (with one deliberate exception, §6.2), never direct except for that one case. It does not:
- **own the Vendor Directory's initial seed data** — that's Architect's own `vendor_directory/wikidata_bootstrap.py` (its deep-dive §3), a one-time/occasional bootstrap concern, genuinely separate from the ongoing learning process this document owns.
- **decide what counts as a valid contribution category** — the taxonomy of what CAN be contributed is Architect's own registry definitions (its deep-dive §1); this sub-API processes contributions of those already-registered types, never invents a new category of fact to learn.
- **perform the actual matching** — Matching API (its own deep-dive) does the fuzzy-matching that determines *which* corporation/branch a receipt refers to; temporal_learning only handles what happens when someone (or the pipeline itself) proposes a *correction or addition* to that data.
- **own the UI itself** — §8 states the requirement precisely; the actual screens are Interface API's own future work.

---

## 2. Package layout

```
core/architect/temporal_learning/
  __init__.py
  contracts.py             # Corporation, Branch, Franchiser, Contribution, VendorLayer, CurationCandidate, error types
  moderation_queue.py         # staged writes — LLM-prescreen → staff review → merge, see §6
  layering.py                    # local vs. global, the sharing gate — see §3
  entities.py                      # Corporation/Branch/Franchiser CRUD — see §4
  category_defaults.py               # category-level fallback learning — see §5
  curate.py                            # self-cleaning pass — see §7
  audit_mirror.py                        # the git-tracked collaborative-review layer, see §6
  errors.py
```

---

## 3. Local/global layering, and the explicit sharing gate this revision adds

```python
class VendorLayer(str, Enum):
    LOCAL = "local"       # visible only within the contributing user's/instance's own context
    GLOBAL = "global"       # merged into the shared directory every user/instance sees
```
A new fact (a corporation, a branch, a franchiser, or a correction to any of them) is observed first in the context of one specific user's own receipts — it's written directly to `LOCAL`, genuinely useful immediately (that user's own future receipts from the same corporation benefit right away), with **no review of any kind**, since a private, local-only fact can't hurt anyone but the user who created it. This is the mechanism Tool Call API's own deep-dive (§4) relies on as the "safe to self-apply" gate — an automated pipeline can freely write `LOCAL` facts unattended.

### 3.1 The sharing gate — a real, previously-missing consent step
**A `LOCAL` fact does not enter the moderation queue automatically just because it exists.** A user (or the automated pipeline acting on their behalf) must take an explicit *share* action before a local fact is even eligible for `GLOBAL` promotion consideration — this was genuinely missing from the first version of this document, which implied any local contribution could be silently swept toward global review. Concretely:
```python
async def share_entity(entity_id: str, entity_type: Literal["corporation", "branch", "franchiser"], requesting_user_id: str) -> Contribution:
    """The explicit consent step. Only after this call does a
    LOCAL-layer entity's data get packaged into a Contribution and
    enter the moderation queue (§6) at all. Never triggered
    automatically by the learning pipeline itself — sharing is
    always a deliberate act, whether taken by the user themselves
    (a UI action, §8) or configured as an explicit opt-in default
    a user has set for their own future local learning."""
```
This matters for a real reason beyond caution: a user's own local corrections might reference details specific to their own situation (an internal note, a locally-relevant alias) that were never meant to become everyone's shared truth — requiring an explicit share action keeps that distinction real rather than assumed away.

### 3.2 Staff's direct-to-global path — a deliberate, different route from user sharing
Staff (via the same manual-management UI, §8) can create or edit `GLOBAL`-layer entities directly, without going through a user's own local layer at all — the concrete meaning of "staff in global" as a genuinely different, more trusted path than the user-share-then-review flow. A staff-authored contribution still runs LLM-prescreen (catching a genuine formatting/malformed mistake has real value regardless of who submitted it) but **skips the separate human staff-review step** — the actor's own role already carries that authority, and requiring a second staff member to approve the first staff member's own submission would be a circular, low-value gate rather than a real safety check. Every staff-authored write is still fully Historian-logged with `actor: "human:<staff_user_id>"`, so this isn't a loss of accountability, just a shorter path to the same audit-visible outcome.

---

## 4. The Corporation/Branch/Franchiser data model — a real structural gap in the first version of this document

The first version of this document never actually specified what a "vendor fact" concretely contains — `Contribution.proposed_change` was left as an opaque `FrozenDict` with no defined shape underneath it. Fixed here with a real three-entity model, driven by a genuine PH-specific business reality: local franchise operators often put their *own* corporation's name and TIN on a receipt, alongside or instead of the parent franchise corporation's own TIN.

```python
@dataclass(frozen=True)
class Corporation:
    """The overall franchise/parent entity — e.g. 'McDonald's
    Philippines' as a corporation, distinct from any one physical
    location."""
    corporation_id: str
    name: str
    corporate_tin: str            # the parent corporation's own TIN
    layer: VendorLayer
    shared: bool                    # see §3.1

@dataclass(frozen=True)
class Franchiser:
    """A standalone entity, deliberately NOT embedded per-branch — the
    direct fix for a real problem: one franchiser can operate branches
    under multiple different corporations (a McDonald's AND a Burger
    King), and embedding franchiser data on every Branch record would
    duplicate that same franchiser's own name/TIN across every branch
    they operate, instead of every branch referencing one shared entry."""
    franchiser_id: str
    name: str                        # the local operator's own corporation name
    franchiser_tin: str                # the local operator's own TIN — genuinely distinct from corporate_tin
    layer: VendorLayer
    shared: bool

@dataclass(frozen=True)
class Branch:
    """One physical location. Associates with exactly one Corporation
    (which overall franchise it belongs to) and, optionally, one
    Franchiser (who actually operates it) via a reference, never
    embedded franchiser data."""
    branch_id: str
    corporation_id: str
    address: str
    franchiser_id: str | None          # a LINK into the Franchiser list — the actual fix, see the class docstring above
    layer: VendorLayer
    shared: bool
```

**The concrete scenario this resolves**: one franchiser owns both a McDonald's branch and a Burger King branch — two different `Branch` records, two different `corporation_id` values (McDonald's Corporation, Burger King Corporation), two different addresses, but both `Branch.franchiser_id` fields pointing at the *same* `Franchiser` record. Without this split, the franchiser's own name and TIN would have needed to be duplicated on both branch entries, with no structural guarantee they'd ever be recognized as the same franchiser at all — exactly the kind of data-quality problem this whole learning pipeline exists to prevent, not create.

`Contribution.proposed_change`'s target is now concrete rather than opaque:
```python
@dataclass(frozen=True)
class Contribution:
    contribution_id: str
    contributor: str                # "worker" | "llm" | "human:<user_id>"
    target_entity_type: Literal["corporation", "branch", "franchiser"]
    target_entity_id: str | None      # None for a genuinely new entity, set for a correction to an existing one
    proposed_change: FrozenDict         # FrozenDict per the project-wide policy, Tool Call API deep-dive §6
    target_layer: VendorLayer
    llm_prescreen_verdict: str | None
    staff_review_status: Literal["not_applicable", "pending", "approved", "rejected"]   # "not_applicable" for staff's own direct-to-global writes, §3.2
```

---

## 5. Category-default learning — a real, previously-unspecified mechanism

When Architect has no vendor-specific data at all (a genuinely new vendor, never seen before) but does know its general *category* (fast food, pharmacy, hardware), category-level defaults provide a reasonable fallback rather than leaving every field blank. This is itself a learned, evolving thing, not a static lookup table:
```python
@dataclass(frozen=True)
class CategoryDefault:
    category: str
    field: str                 # e.g. "vat_treatment"
    default_value: FrozenDict
    confidence: float             # derived from how many confirmed vendors in this category actually match this default
    sample_size: int
```
Recomputed periodically (an idle-time job, registered the same way as any other Background Workers job) by aggregating confirmed `GLOBAL`-layer vendor facts within a category — the more vendors in "fast food" that confirm the same VAT treatment, the higher `confidence` climbs. A category default is a *fallback*, always overridden by any actual vendor-specific fact once one exists — never authoritative over real, confirmed data for that specific vendor.

---

## 6. The moderation pipeline and its audit mirror

**LLM-prescreen → staff review → merge** for user-shared contributions (§3.1); **LLM-prescreen → merge** for staff's own direct-to-global writes (§3.2) — a first automated pass filtering obviously-malformed or duplicate submissions either way, a human confirming or rejecting what's left *only* in the user-share case, and only an approval (or a staff author's own submission) actually merges into the `GLOBAL` layer. **The git-tracked collaborative-review layer**: alongside the queryable SQLite store, a parallel git-tracked mirror gives the *review process itself* a real, diffable history — a staff member's approve/reject decisions visible as a reviewable diff, not just a final SQL state. Worth this dual representation specifically because the review process benefits from git's own tooling in a way the live queryable data doesn't (the same reasoning that correctly kept Historian *out* of git, applied in the opposite direction here).

---

## 7. Curate — the self-cleaning pass, finally given a real mechanism instead of staying an open question

Both Reconciliation's and Architect's own earlier deep-dives flagged this as unresolved: a self-cleaning pass over the learned vendor list, distinct from ordinary contribution moderation, never actually designed. **Designed here, fresh — not from V2, from what this pipeline's own accumulated state actually needs over time**:

```python
@dataclass(frozen=True)
class CurationCandidate:
    candidate_type: Literal["low_confidence_stale", "near_duplicate_merge", "abandoned_pending_review"]
    target_entries: tuple[str, ...]    # one entry for stale/abandoned, two+ for a proposed merge
    reasoning: str                        # human-readable — why this was flagged
```
Three real cleanup patterns worth distinguishing, not one generic "clean stuff up" job:
- **`low_confidence_stale`** — a `LOCAL`-layer entry with very few confirming observations that hasn't been touched in a long time (genuinely never going to accumulate enough confidence to be promotion-worthy, just clutter).
- **`near_duplicate_merge`** — two vendor entries that Matching API's own fuzzy-scoring (its deep-dive §3) flags as suspiciously similar, that never actually got reconciled into one entry (a spelling variant that should have merged with the canonical form but didn't).
- **`abandoned_pending_review`** — a contribution that's sat in `staff_review_status: "pending"` far longer than this system's own normal review turnaround, worth surfacing rather than silently aging forever.

**Curate never deletes or merges anything automatically — it stages a `CurationCandidate` through the exact same moderation pipeline (§6) a new contribution would go through.** This is the load-bearing design choice: self-cleaning doesn't get a shortcut around the review gate just because it's "only cleanup" — a wrongly-merged vendor or a wrongly-pruned entry is a real, if smaller, version of the same mistake an unreviewed bad contribution would be, and `docs/PRINCIPLES.md` §4.3's "never silently override" principle applies here identically. Registered as a real Background Workers idle-time job (`v3-deepdive-12-background-workers-api.md` §6.2's own entry, which previously had nothing behind it) — this document is what that entry was actually waiting on.

---

## 8. Manual management UI — webapp and TUI, a real requirement, not yet designed anywhere else
A genuinely new requirement surfaced directly for this document: users and staff both need a real interface for browsing and manually managing learned corporations, branches, and franchisers — not just whatever the automated pipeline happens to learn on its own.

**What this needs to support, at minimum**: browsing/searching the vendor directory (by corporation, branch, or franchiser); viewing a corporation's full branch list and each branch's own franchiser link; manually adding a new corporation/branch/franchiser (entering `LOCAL`, unshared, per §3); explicitly sharing a local entry (§3.1's consent action); and, for staff, both reviewing pending shared contributions (§6) and creating/editing `GLOBAL` entities directly (§3.2). This is a real, moderately complex CRUD-plus-review surface — closer in shape to Review/Flagging's own staff audit-review queue (an enumerated custom-screen exception, Interface deep-dive §2) than to a simple settings toggle, and genuinely needed in both the webapp (for regular users managing their own local entries) and the TUI (for staff review work, consistent with the TUI's own admin/staff-facing role established throughout Interface's deep-dive).

**Not designed here** — this document states the requirement precisely (the operations above, the layer/sharing/staff-direct distinctions each screen needs to respect) so Interface API's own future work has a real specification to build against, rather than inventing the requirement from scratch later. The actual screen layouts, navigation, and webapp component structure are Interface API's own scope.

---

## 9. Asyncio and profiling
LLM-prescreen is a batch Inference API call (Background Workers' own principle — LLM-driven background work is a dispatched Inference job, not a separate subsystem). Category-default recomputation and Curate's own candidate-scanning are periodic aggregation queries over Architect's own database — I/O-bound, no compute-heavy work of this sub-API's own beyond what Matching API's fuzzy-scoring already does for the near-duplicate detection case, reused rather than reimplemented. **Forward-compatibility check, explicit rather than assumed**: no new dependency of any kind is introduced by this sub-API — `rapidfuzz` (via Matching API, reused not reimplemented) is already a tracked Telemetrees entry from OCR's own deep-dive; nothing here adds a second tracking obligation, and no compute-bound pure-Python work exists in this document's own scope for free-threading to meaningfully help with.

---

## 10. gRPC surface

```protobuf
service TemporalLearningService {
  rpc CreateEntity(CreateEntityRequest) returns (EntityResponse);          // corporation | branch | franchiser, always LOCAL+unshared unless caller is staff (§3.2)
  rpc UpdateEntity(UpdateEntityRequest) returns (EntityResponse);
  rpc ShareEntity(ShareEntityRequest) returns (ContributionResponse);        // §3.1's explicit consent step
  rpc ListEntities(ListEntitiesRequest) returns (ListEntitiesResponse);       // §8's browse/search surface
  rpc SubmitContribution(ContributionRequest) returns (ContributionResponse);
  rpc ReviewContribution(ReviewRequest) returns (ContributionResponse);
  rpc GetCategoryDefaults(CategoryRequest) returns (CategoryDefaultsResponse);
  rpc ListCurationCandidates(CurationListRequest) returns (CurationListResponse);
  rpc ResolveCurationCandidate(ResolveCurationRequest) returns (ContributionResponse);   // routes through §6's same review pipeline
}
```

---

## 11. Testing hooks
- **Layer-promotion gate test**: confirms a user-shared `LOCAL` contribution never becomes visible to another user/instance without an explicit staff approval (the §3.1 path) — while a staff-authored direct-to-global write correctly skips that same approval step by design (§3.2) — the concrete validation that both paths behave exactly as their own section specifies, neither one silently adopting the other's rule.
- **Sharing-gate test**: confirms a `LOCAL`, unshared entity is never picked up by the moderation queue on its own — only an explicit `ShareEntity` call creates a `Contribution` at all. The direct fix for the exact gap §3.1 closed.
- **Staff direct-to-global test**: confirms a staff-authored `Contribution` merges after LLM-prescreen alone, with no second staff member's approval required, while still landing a real Historian-logged, Audit-visible event.
- **Franchiser reference-not-duplication test**: two `Branch` records under different `Corporation`s, both referencing the same `Franchiser` — confirms a franchiser correction (a TIN fix) updates once and is reflected by both branches, never requiring the same fix applied twice.
- **Curate never auto-applies test**: every `CurationCandidate` type, confirming each one lands in the pending-review queue and never directly mutates the live directory.
- **Category-default override test**: confirms an actual vendor-specific fact always wins over a category default, even a high-confidence one.

---

## 12. Open questions for this deep-dive (logged, not guessed at)
- **`abandoned_pending_review`'s actual staleness threshold, resolved: 14 days.** The same reasoned convenience-window already applied to Support Ticketing's own stale-resolved-ticket auto-close (`v3-deepdive-52-support-ticketing.md` §9) — a consistent number for the same underlying "has this sat untouched long enough to be worth surfacing" judgment, rather than inventing a separate value for structurally the same question.
- **Category granularity** — how fine-grained categories need to be before defaults become genuinely useful genuinely needs real data to calibrate against; stays open as a real pre-launch calibration task, not a design gap.
- **Wikidata SPARQL filter re-investigation** — still Architect's own open question (its deep-dive §7), not this sub-API's to resolve, noted here only because it's the other half of the same Vendor Directory this document's own contributions eventually populate.
- **Default sharing behavior, resolved: sharing always stays a one-at-a-time explicit action, no standing auto-share preference.** A standing "always share automatically" toggle would quietly erode the whole point of §3.1's own consent gate — the explicit, per-entity nature of that gate is what makes it meaningful, and a convenience shortcut that bypasses it defeats its own purpose.
- **Franchiser-less branches, resolved: yes, genuinely and permanently optional, not a placeholder.** Plenty of real branches are corporate-owned with no local franchise operator involved at all — `franchiser_id: None` is a legitimate, permanent end state for those, not "not yet filled in." Confirmed explicitly rather than left ambiguous.
- (The manual-management UI's own detailed screen design — resolved, no longer open. Webapp: `v3-deepdive-44-webapp.md` §5.5. TUI: already covered by Interface's own enumerated exception list, now updated to reflect this document's current Corporation/Branch/Franchiser model, `v3-deepdive-14-interface-api.md` §3.2.)
