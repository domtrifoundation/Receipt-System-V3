# Reconciliation API

Reconciliation owns two related things: **propagating corrections** (when Architect's registry data changes — a vendor's TIN gets fixed, a branch gets merged — pushing that correction to every affected receipt already in the canonical database) and **running validation checks** (VAT math, TIN format, date plausibility, and the rest of V2's real check inventory) that surface a Review/Flagging flag on a hit.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2's `reconcile.py` (121 KB, its single largest module) did exactly this — VAT math, duplicate detection, field backfill, and the rest of the check inventory V3's own twelve checks were independently re-derived from. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-17-reconciliation-api.md`](../../docs/apis/v3-deepdive-17-reconciliation-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the flag taxonomy** — Architect's registry defines what flag types exist (Audit deep-dive §1 already states this distinction); Reconciliation's checks *produce* flags of types Architect already registered, never inventing a new flag type inline.
- **own the learning mechanism** — a vendor's TIN getting corrected happens in Architect's `temporal_learning`; Reconciliation only reacts to that correction already having happened, propagating its consequences.
- **run as a competing scheduler** — every check and propagation batch runs on Background Workers' execution substrate (its own deep-dive), scheduled and routed by that API's per-job classification, not a Reconciliation-owned thread pool.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Checks run on Background Workers' substrate, never a scheduler owned here. A check produces flags of types Architect has already registered — inventing a flag type inline is the specific violation `docs/PRINCIPLES.md` §3.4 exists to prevent.

**Money is integer centavos everywhere, never a float.** §4.1's own sketch is written with
`float` subtotals and a `0.02` tolerance. Worth being accurate about the stake rather than
overstating it: at the magnitudes a Philippine receipt actually occupies the tolerance is wide
enough to absorb float drift, and a test verifies that agreement rather than asserting a bug
that is not there. What integer arithmetic buys is that the guarantee does not *depend* on the
tolerance being generous — tightening it to zero centavos later would silently turn an absorbed
rounding artefact into a stream of false findings. Related and provable: at 12% the rounding
*mode* cannot matter, because `12c ≡ 50 (mod 100)` has no solutions. A test pins that, so a
future rate change to 10% or 15% surfaces the question rather than making half-up-versus-
half-even quietly load-bearing in a tax filing.

**A zero-rated or VAT-exempt receipt is not a VAT math error**, and §4.1's sketch would flag
every one of them. Computing 12% unconditionally would flag every export sale and every
senior-citizen or PWD discounted purchase in the country — an enormous false-positive class in a
Philippine system specifically. An unrecognised treatment is `INCONCLUSIVE` rather than assumed
vatable, because applying a 12% test under a rule this code has never heard of produces confident
findings about arithmetic it has no basis to judge.

**`INCONCLUSIVE` is a real third outcome and is not a pass.** §4.12 states this for ATP directly
— an illegible or uncaptured field "is a genuinely different, softer case than a confirmed
date-outside-window mismatch, and conflating the two would misrepresent the actual finding" — and
it generalises to the whole inventory. A two-state result forces one into the other and both
directions are wrong: missing data read as a hit floods the review queue, missing data read as a
pass silently certifies unchecked receipts as clean. Flagging an absent ATP window would tell a
filer their vendor's authority had expired when what actually happened is that a scan was blurry
— an automatically generated false accusation about a third party, at scale.

**Nothing here ever corrects anything** (`docs/PRINCIPLES.md` §4.3). Every check surfaces a
discrepancy without deciding which side is right — the vendor's registered category might be
wrong, or the items might be miscategorised, and nothing in this package can tell which.
Propagation follows the same rule: a receipt whose current value disagrees with the correction
goes into `PropagationJob.conflicts` and is left alone, because a bulk sweep quietly overwriting
a value someone had already fixed by hand would do it to thousands of rows before anyone noticed.
§4.5's duplicates are never auto-merged for the sharpest version of this: two receipts that look
identical may be two genuine transactions at the same shop on the same day for the same price,
and merging them silently deletes a real expense from someone's tax filing.

**The `docs/PRINCIPLES.md` §1.9 seams are injected, and their identity is what tests pin.** Three
of them, each named by the deep-dive: §4.11's geo cross-reference reaches
`core.geo_address.reverse_check.reverse_check` — "the identical underlying Geo/Address function
Execution Core's own GEOD stage calls for new receipts, not a separate 'old receipt'
implementation"; §4.10's archive check reaches Disaster Recovery's own `BlobLocation` verification;
and §8's propagation atomicity reuses `services.execution_core.checkpointing.run_stage`, "the same
mechanism, not a second implementation of 'resume after a crash.'" All three arrive by injection
rather than import, because `contracts.py` is the only module other packages import from (§1.1)
and a direct import would make this package unimportable wherever those APIs are not installed
(§1.3). The tests assert **object identity**, not agreement — two functions that agree today pass
an agreement test right up until one is changed and the other is not, and the failure is silent
in the worst direction, with a retroactive sweep applying last year's logic and reporting old
receipts as clean by a standard nothing else uses any more.

**§4.11 is budget-gated and must stay that way** (§5). It is a genuine network call, and firing a
geocode for every receipt in a ten-thousand-row retroactive sweep is a real bill and a real
rate-limit breach. With no geo context supplied the check is `INCONCLUSIVE`, never `PASSED` — the
gate is the caller's to open.

**A check that raises must not take down the sweep.** `CheckRegistry.run_all` converts an escaped
exception into an `INCONCLUSIVE` result naming the check, so one broken check leaves the other ten
reporting. A sweep over ten thousand old receipts aborting on one malformed row is the failure that
makes retroactive checking unusable in practice, which is exactly what §1.9 promises it will not be.

**Files here that the deep-dive's §2 package layout does not list**: `surfacing.py`,
`reconciliation.proto` and `generated/`, plus `CLAUDE.md`. `surfacing.py` holds §4.8's reimport
conflict and §4.9's confirmed-malicious content, both of which §4 explicitly describes as
"surfaced, not owned, here" — Persistence's Reimport sub-API and Content Security already reached
those verdicts. They are deliberately not in `checks/`, because a "check" that re-derives a
conclusion another API owns is the second implementation §1.9 exists to prevent, and for §4.9
specifically it would be a second, weaker scanner whose disagreement with Content Security's own
verdict has no defined resolution — against a §4.2 rule that says security failures are closed,
not negotiated. §2 lists eleven check modules against §4's twelve numbered subsections because
§4.6 covers two genuinely distinct checks and §4.8/§4.9 are not checks.

## Known gaps, flagged rather than silently filled

- **`PropagateCorrection` on the gRPC surface returns `not_wired`.** The RPC exists and the
  message shapes are real; `propagation.propagate_correction` is the working entry point and is
  fully tested, including §7's atomicity hook. What is missing is Persistence's writer and
  Execution Core's checkpoint store being injected at the servicer, which needs a Persistence
  adapter that does not exist yet.
- **`RunChecks` builds a bare `ReceiptSnapshot` from the receipt id.** Every check runs and
  reports honestly against it, but nothing yet loads a receipt's real fields out of Persistence,
  so over gRPC most checks correctly report `INCONCLUSIVE`. The in-process `run_checks` entry
  point takes a populated snapshot and is what Background Workers' sweep should call.
- **§3's Historian change-event subscription is not wired.** `propagate_correction` is the
  callable a subscription would dispatch; nothing yet subscribes to Architect's table changes.
- **§8's Rescue follow-up is not implemented.** That resolution — flag immediately, and let
  Rescue auto-resolve the flag later with a note if its retry succeeds — needs Rescue, which does
  not exist in this repo yet. The flag half is done; the auto-resolve half is not.
