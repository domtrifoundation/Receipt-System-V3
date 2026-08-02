# Hand-off: remote session → local Claude Code

Written at `x00.00.23`, branch `claudi/wave-1-foundational-apis-ezvtmr`, PR #9 (draft).
Everything below is pushed. Nothing is uncommitted.

---

## Paste this into the local session

> I'm continuing Phase 2 of DOMTRI/Resibo V3 from a remote Claude Code session. Read
> `docs/HANDOFF_TO_LOCAL.md` first, then `docs/PHASE_2_STATE.md` and `docs/PRINCIPLES.md`.
>
> Standing rules that carry over, every session, no exceptions:
> - Develop on `claudi/wave-1-foundational-apis-ezvtmr`. Never push to another branch without
>   my explicit permission.
> - Every `gh` command runs as the domtrifoundation account:
>   `GH_TOKEN=$(gh auth token --user domtrifoundation) gh <command>`. If that account isn't
>   authenticated locally, stop and tell me.
> - **Never put user data in this repository.** `tests/fixtures/real_receipts/` holds 701 real
>   Philippine receipts with real TINs, names and purchase histories. It is gitignored via a
>   broad `**/real_receipts/` rule and this repo is public. Keep it that way.
> - V2 is never a source of code, patterns, data, or "good practices" — only of evidence about
>   what broke.
> - Use dynamic workflows to parallelize, and let subagents use worktrees.
>
> Start with the "Do this first" section of the hand-off.

---

## Where the work actually stands

**Twenty packages implemented and tested. `1628 passed, 3 skipped`** (wave-1 baseline was 607).

| Wave | Packages |
|---|---|
| 1 | Persistence, Auth, Audit, Logs, Architect, Agent Control (pre-existing) |
| 2 | Health + Watchdog, Content Security, Notifications, Account Guardian, Tool Call, Geo/Address, Groups, Task Scheduler |
| 3 | Background Workers, Telemetrees + Dependencies Warden, Search/Query, Review/Flagging, Matching, Migration, Support Ticketing, Billing |
| 4 | **Execution Core** (new, `x00.00.22`), **Reconciliation** (`x00.00.23`) |

### Still 0-byte Phase-1 scaffolding

Run this to confirm at any time — it is the honest inventory:

```bash
for d in core/*/; do n=$(find "$d" -name '*.py' -size +0c | wc -l); t=$(find "$d" -name '*.py' | wc -l); echo "$d $n/$t"; done
```

- `core/ocr/` — **needs your local hardware.** Tesseract/PaddleOCR/OpenCV stack.
- `core/preprocessing/` — same.
- `core/inference/` — same, plus a real model.
- `core/ingestion/` — buildable anywhere; a remote agent started it and died on an API limit.
- `core/accounting_sync/` — buildable anywhere; same.

Each of those carries an **"Implementation status"** section in its `CLAUDE.md` saying it is
unimplemented and naming itself for deletion in the commit that implements it. The file lists
look exactly like finished packages from the outside, which is why the note exists — delete it
when you build the package.

---

## Do this first

1. **Verify CI is green on `35353f9`.** Eight checks. The last one I watched go green was on
   `a9f1bfc`; `3b2824b` and `35353f9` were still running when this session ended.
2. **Update PR #9's body.** It currently describes state as of `x00.00.21` / sixteen packages.
   Execution Core and Reconciliation have landed since. The PR checklist is CI-enforced and
   `pr_checklist_enforcement.yml` genuinely fails on an unchecked box or on a hollow
   justification for Forward-Compatibility Hygiene or Backward-Carrying Capability — the
   existing body has real justifications you can extend rather than rewrite.
3. **Then wave 4 proper**, in the order below.

---

## What to build next, in priority order

### 1. OCR, Preprocessing, Inference — the reason you moved local

`docs/PHASE_2_KICKOFF.md` §1 is explicit that these need real hardware and real receipts, which
is why Phase 2 was meant to run locally. You now have both. This is the highest-value work
available and it could not be done remotely.

Deep-dives: `v3-deepdive-02-ocr-api.md`, `-03-preprocessing-api.md`, `-05-inference-api.md`
(check exact filenames in `docs/apis/`).

**Execution Core is already built and waiting for them.** `core/execution_core/pipeline.py`
takes stages as a mapping of `ReceiptStage` → zero-argument awaitable, so wiring OCR in is
supplying a callable, not modifying Execution Core. `ReceiptStage` already has `PREPROCESSED`,
`OCRD` and `INFERRED` in `STAGE_SEQUENCE`.

The 701 real receipts are your calibration set. **Do not commit anything derived from them that
contains a real TIN, vendor name, or amount** — not in a test fixture, not in a docstring, not
in a golden file. Aggregate accuracy numbers are fine; individual receipt contents are not.

### 2. Ingestion (`core/ingestion/`)

Deep-dive `v3-deepdive-04-ingestion-api.md`. Sub-packages `webhook_manager/` and
`format_normalization/` already have their own real `CLAUDE.md`s stating what they own — read
those, they constrain the build. Security-critical surface: archive extraction bounds
(zip-bomb, path traversal) is fail-closed per §4.2, and content-hash dedup is on **original
bytes, never mtime** — cloud sync touches mtime on unchanged bytes, which is a V2 bug.

### 3. Accounting Sync (`core/accounting_sync/`)

Deep-dive `v3-deepdive-50-accounting-sync.md`, only 101 lines — the smallest remaining piece.
Both providers must be real per §1.2, with **separate** status vocabularies; `core/billing/psp/`
is the worked example of exactly that.

### 4. The three flagged decisions — these are yours, not mine

I surfaced these repeatedly rather than guessing. They still need you:

- **Tool Call and Background Workers have no `.proto`.** Neither deep-dive specifies a gRPC
  surface, while `PROCESS_TOPOLOGY.md` establishes every Core API as its own gRPC-reachable
  process. Those cannot both be right. Background Workers' §1 says it is "a contract and
  scheduling logic, not new infrastructure to deploy", with workers running inside Execution
  Core's process — a real argument its surface is legitimately in-process only. **One decision
  should cover both.**
- **Task Scheduler §7's five-RPC surface has no `.proto`.** Not a conflict, just unfinished.
  (Migration, Support Ticketing and Billing are in the same position.)
- **Persistence adapters** for Support Ticketing, Billing, and Execution Core's `RunRegistry` —
  all three keep state in memory today, each recorded in its own `CLAUDE.md`.

---

## Things I got wrong that you should not re-derive

- **A remote agent reported `core/reconciliation/` had no tests because it had no code.** It was
  right and I had told it otherwise. Trust the `find -size +0c` inventory over any prose,
  including mine.
- **I claimed float VAT arithmetic produces wrong answers at receipt magnitudes. It does not.**
  I searched three million centavo values and found zero disagreements. Integer centavos is
  still correct — the guarantee shouldn't depend on the tolerance being generous, and it matches
  Billing — but the *reason* in the docstring is now the accurate one. Don't let anyone
  "restore" the overclaim.
- **All three parallel subagents died on a weekly API limit** partway through wave 4. Locally
  you have your own limits; the pattern that worked was disjoint file ownership per agent (one
  package each, no overlap) with me auditing and fixing afterwards.

---

## Two corrections to deep-dive sketches that are load-bearing

Both are implemented, tested, and documented in the owning `CLAUDE.md`. If a future session
"fixes" the code back toward the sketch, it reintroduces a real bug.

1. **Execution Core §7's retry sketch** calls `create_flag` unconditionally whenever the cap
   check trips — creating a fresh flag on every subsequent sweep. §7's own stated motivating bug
   is "one bad scan produced 57 identical warnings in a single session". The sketch reintroduces
   that bug with flags instead of warnings. Escalation is latched;
   `test_escalation_creates_exactly_one_flag_no_matter_how_often_the_receipt_is_swept` holds it.
2. **Reconciliation §4.1's VAT sketch** computes 12% unconditionally, which flags every
   zero-rated and VAT-exempt receipt in the Philippines.

---

## Repo conventions worth not re-deriving

- `contracts.py` holds types and no logic; it is the only module other packages import from
  (§1.1). Soft target 300–400 lines per file. Test files too — I had to split a 1453-line test
  file to match; the repo's largest is ~520.
- Frozen dataclasses at every boundary; dict fields and module-level constant tables use
  `common/frozen_dict.py`'s `FrozenDict`. `isinstance` against one tests
  `collections.abc.Mapping`, never `dict`.
- Errors are data (§4.1). Nothing raises across a gRPC boundary except Auth's deliberate
  session/role carve-out.
- Sibling APIs are reached through `Protocol` seams you define and inject, never a direct
  `core.x` import — that is what keeps packages importable and testable in isolation.
- `.proto` → `generated/` via `python -m grpc_tools.protoc`, then apply the relative-import fix
  (`from . import X_pb2 as X__pb2`) and import stubs lazily inside `service.py` methods.
- No `pytest-asyncio` — it is deliberately absent. Use a small `asyncio.run(...)` helper; every
  suite has one.
- **No new third-party dependency, ever**, without the `new_dependency` template.
- `common/version.py`'s `PROGRAM_VERSION` ticks its `pp` every commit, and the touched API's
  `CLAUDE.md` "Current API version" ticks in the same commit.

### Test style, which is what the work is judged on

- Test **names** state the guarantee:
  `test_a_zero_rated_receipt_with_no_vat_is_not_a_math_error`.
- Test **docstrings** say what breaks in the real world without it, citing the deep-dive § and
  the PRINCIPLES clause.
- Never stub the thing under test. Compute real hashes and signatures, then tamper with them.
- Read the actual `Protocol` before writing a fake of it — mismatched fakes were the single most
  common failure across this whole phase. Every suite now has a
  `test_doubles_conform.py`-style guard; keep writing them.
- Write tests that pin **non**-findings, not just findings. A check that flags a batch-scanned
  three-year-old receipt gets switched off, and a switched-off check is worse than no check.

---

## Known wrinkle in the history

Two commits both carry `x00.00.12`. They were squashed locally to keep `pp` incrementing per
commit, but the rewrite could not be pushed, so both remain and numbering continues from 13.
Recorded in the PR body rather than hidden. Not worth fixing.
