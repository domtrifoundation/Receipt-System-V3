# V3 Deep Dive: Reimport (Persistence sub-API)

**Parent API:** `v3-deepdive-13-persistence-api.md` §6. **Companion files:** `v3-deepdive-04-ingestion-api.md` (Content Security scanning, identical to any other untrusted file), `v3-deepdive-06-account-guardian-api.md` (the export→edit→reimport round trip's origin story).

**Status:** Sub-API deep-dive, full treatment. This session resolves the conflict-resolution policy Persistence's own deep-dive left as an open question — a real design, not deferred again.

---

## 1. Scope & boundary

Reimport owns **ingesting a hand-edited exported file and reconciling it against current canonical state**. It does not:
- **own the export itself** — that's Export Framework (its own deep-dive); Reimport consumes what that produced, doesn't generate it.
- **own content scanning** — Content Security API scans every reimported file exactly like any other untrusted external upload, no special-cased trust just because it's "the user's own file coming back."
- **silently resolve genuine conflicts** — §4 below is the actual design; the short version is that a real conflict always surfaces to a human, never gets silently picked one way.

---

## 2. Package layout

```
core/persistence/reimport/
  __init__.py
  contracts.py            # ReimportRequest, ReimportResult, FieldConflict, error types
  parser.py                  # reads the reimported Excel file — see §3
  three_way_diff.py            # the actual conflict-resolution algorithm — see §4
  errors.py
```

---

## 3. Parsing the reimported file
`openpyxl` (`pip install openpyxl`) reads the reimported `.xlsx` — the same library Export Framework's own `excel_general.py` provider writes with (its deep-dive §7), so round-tripping the same file format stays symmetric rather than reading with one library and writing with another. The export snapshot embeds a hidden reference cell (the Historian event ID and timestamp current at export time, not visible in the normal print view) — this is what makes the three-way diff in §4 possible at all; without a snapshot reference, there'd be no way to distinguish "the user changed this field" from "this field just happens to differ from current canonical state."

---

## 4. Three-way diff and conflict resolution — resolved, not left open
Persistence's own deep-dive flagged this as genuinely undecided. Resolved here with a real design, borrowing the same three-way-merge shape version control systems use for exactly this class of problem (a base snapshot, two independent sets of changes since):

```python
@dataclass(frozen=True)
class FieldConflict:
    field: str
    original_value: Any       # what the export snapshot had
    canonical_value: Any        # what's in the DB now
    reimported_value: Any        # what the user's edited file has

def three_way_resolve(original: FrozenDict, canonical: FrozenDict, reimported: FrozenDict) -> tuple[FrozenDict, tuple[FieldConflict, ...]]:
    resolved = {}
    conflicts = []
    for field in reimported:
        orig, canon, reimp = original.get(field), canonical.get(field), reimported.get(field)
        user_changed = reimp != orig
        canonical_changed = canon != orig
        if not user_changed:
            resolved[field] = canon          # user didn't touch it — canonical's own newer value wins, a stale export never silently reverts a real correction
        elif user_changed and not canonical_changed:
            resolved[field] = reimp          # only the user changed it — apply cleanly
        else:
            # BOTH changed since export, and not to the same value — a
            # genuine conflict. Never silently pick one; always surface
            # to a human, consistent with this project's standing
            # "never silently override, always transparent" principle
            # (break-glass logged not silent, Historian recording actor,
            # etc.)
            resolved[field] = canon           # canonical stays authoritative until a human resolves it
            conflicts.append(FieldConflict(field, orig, canon, reimp))
    return FrozenDict(resolved), tuple(conflicts)
```
**Decision, stated plainly**: a field only the user touched applies cleanly; a field only canonical state touched (via an automated correction, another session's edit) keeps winning, since a stale local export shouldn't be able to silently undo a newer correction just because the user's copy predates it; a field **both** touched, to different values, is a genuine conflict — surfaced as a Review/Flagging flag (`reimport_conflict`, already named in file 01's taxonomy) rather than resolved by any automatic rule, since guessing wrong on a genuine conflict is exactly the kind of silent-data-loss failure this whole project's design philosophy has repeatedly ruled out elsewhere.

---

## 5. Actor tagging
Every field successfully applied from a reimported file is written through Persistence's normal path (Historian sub-package) tagged `actor: "human:<user_id>-via-reimport"` — distinguishable from a direct in-app edit by the same user, since the provenance (came back through a downloaded-then-reuploaded file, not live editing) is genuinely useful audit context, not a detail worth losing.

---

## 6. Asyncio
File parsing (`openpyxl`) is CPU-bound but typically small/fast for a single reimported file — not worth its own executor-dispatch discussion at this API's actual scale; inherits Persistence's own async SQLite wrapper for the actual write path.

---

## 7. gRPC surface

```protobuf
service ReimportService {
  rpc SubmitReimport(ReimportUpload) returns (ReimportResult);
}

message ReimportResult {
  int32 fields_applied = 1;
  repeated FieldConflict conflicts = 2;
  string flag_id = 3;    // populated if any conflicts were found — the created reimport_conflict flag
}
```

---

## 8. Testing hooks
- **Three-way resolution matrix test**: every combination of (user changed / didn't, canonical changed / didn't) against every possible outcome — the concrete validation of §4's decision table, not just trusted from the code reading correctly once.
- **Missing snapshot-reference test**: a reimported file with a stripped or corrupted hidden reference cell (a user manually deleting a row/column that happened to contain it) fails cleanly with an actionable error, not a silent full-canonical-overwrite.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Stale snapshot-reference, resolved: treated as a genuine conflict requiring a fresh export.** If the referenced export record no longer exists (purged, or older than Historian's own retention window), there's no valid baseline to diff against — the reimport is rejected with a clear message asking for a new export, rather than attempting to guess at or silently skip the missing baseline. The same "never silently resolve what can't actually be resolved" discipline every other check in this project follows.
- (Bulk reimport batch-review UX — resolved, no longer open. Already covered by the existing screen design, not a separate one-at-a-time-vs-batch choice needing its own answer: `v3-deepdive-49-reimport-diff-ui.md` §4 already tracks progress across many simultaneous conflicts on one screen — "12 of 47 conflicts resolved" — which is itself the batch-review capability this question was asking whether existed.)
