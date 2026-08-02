# Phase 2 — current state and open decisions

Written mid-Phase-2 when the working session had to be transferred. This is the handoff:
what is actually true right now, what is blocked on a human decision, and what the next
session should **not** redo.

Read this alongside `PHASE_1_COMPLETE.md` (Phase 1 + the audit pass) and `PHASE_2_KICKOFF.md`.

---

## 1. Where the work actually is

- Branch: **`claudi/phase-2-implementation`**, cut from `origin/main` at the Phase 1.5 merge.
- **No API implementation has started yet.** Phase 2 got as far as required reading, state
  verification, and the two setup items below. Build-order wave 1 (Persistence, Auth &
  Tenancy, Audit, Logs) has not been begun.
- Merged so far: `x00.00.01`/`x00.00.02` (Phase 1, PR #1), `x00.00.03` (Phase 1.5, PR #4).
- Dependabot PRs **#2 and #3** (`actions/checkout` 4→7, `actions/setup-python` 5→7) are
  still open and unreviewed. They are real, working proof the repaired `dependabot.yml`
  functions; they are not blocking anything.

## 2. Real receipt fixtures — present locally, do not re-request

**701 real receipt files are already on this machine** at
`tests/fixtures/real_receipts/`, supplied by the repo owner. Structure is
`done /<VENDOR NAME>/<Scanned_*.pdf>` — real Philippine receipts (7-Eleven, Alfamart,
Ayala, Bonchon, Chooks To Go, Citadines, and many more), several hundred vendors, most as
scanned PDFs. Vendor folder names are themselves raw OCR output in places
(`AENA@AV'S FOOD CENTER INC`, `CORPORA7I0`, `DENNY 5`), which is useful signal about the
real-world mess `PRE_STABLE_BENCH_VALIDATION.md` describes — not a problem to clean up.

**They are gitignored and must stay that way.** `.gitignore` now carries a deliberately
broad rule (`**/real_receipts/`, not just the one example path
`PRE_STABLE_BENCH_VALIDATION.md` happens to name) — verified with a real probe file, not
assumed. Never commit these: a real receipt carries a real TIN, a real purchase history,
sometimes a real name, and this repository is public.

Nothing about them is checked in, so a fresh clone will not have them. If the next session
is running somewhere else, ask the owner again — but on *this* machine they are already
present, and re-requesting them would be a wasted round-trip.

## 3. Two open decisions — blocked, need the repo owner

Neither was silently guessed at. Both change every subsequent commit, so they want
answering before wave 1 starts.

### 3.1 What the API version line in each `CLAUDE.md` actually means

**There is a genuine conflict between what Phase 1 wrote and what Phase 2 requires.**

- All **52** `CLAUDE.md` files currently carry a section headed
  *"## API version at x03.00.00 Zircon"* stating a value like `a02.00.00`. That is a
  **target**: the version that API is expected to be at *when Zircon ships*. Phase 1 chose
  the `.00.00` tail by reasoning that Zircon is "a deliberate jump," and flagged it at the
  time as reasoned-not-determined (`PHASE_1_COMPLETE.md` §3).
- Phase 2's instruction is different and explicit: *"each API's own CLAUDE.md has a line
  stating its **current** version. Update that line in the SAME commit as the behavior
  change."* That requires a **running** value that ticks its `pp` per commit — which by
  Zircon would read something like `a02.14.03`, not `a02.00.00`.

A target and a running counter cannot be the same line. Options, with the recommendation
first:

1. **Convert the line to a running current version** (`a<MM>.00.00` today, ticking from
   here), and either drop the Zircon-target framing or keep it as a separate sentence. The
   valuable part of Phase 1's work — the `MM` lineage determination, which was derived from
   actually reading V1 and V2 source — is unaffected either way and should be preserved
   verbatim.
2. Keep the Zircon-target line and add a second, separate current-version line.
3. Something else the owner has in mind.

**The `MM` values themselves are settled and should not be re-derived** — they came from
real source inspection (V2 cloned and grepped, V1's skill file read), and the per-API
evidence is recorded in `PHASE_1_COMPLETE.md` §3.

### 3.2 Where the program version actually lives

`x00.00.03` currently exists **only in git commit-message subjects**. There is no
`VERSION` file, no `__version__` constant, no tag (`git tag -l` is empty).

That is not sufficient for what the architecture already assumes. `PROCESS_TOPOLOGY.md` §7
and Health API's own design both have version/commit riding on the heartbeat response so
Watchdog can report which version each running service is on; the Interface API's codename
banner is keyed off `MM`; and Phase 2 requires the program `pp` to tick on **every** commit
including process-only ones. All of that needs the version to be a real value the running
program can read, not a string in a commit log.

Recommendation: a single `common/version.py` constant as the one source of truth, imported
by anything that needs to report it — consistent with `common/frozen_dict.py` already being
the established home for genuinely cross-cutting shared code. Not created yet, because
where the program version lives is a real decision and §3.1 above may change its shape.

## 4. Setup items — one done, one already in place

- **Real-fixture gitignore: done this session**, verified with a probe file (§2).
- **Multi-version validation: already complete from Phase 1.5**, no action needed.
  `noxfile.py` exists with a `forward_compat` session across 3.14/3.15 running only
  `@pytest.mark.forward_compat` tests; `nox -s forward_compat` was confirmed passing
  against both real interpreters; `PYTHON_BIN` works in both launchers, verified by
  actually launching under each; `noxfile.py` is classified dev-only in
  `check_stripped_content_list.py`. Full detail in `MAINTENANCE.md` §8.
- **The per-commit version-tick practice is NOT yet written into `CONTRIBUTING.md`.**
  Phase 2 requires it to be documented as a standing repo practice rather than followed
  silently. Deliberately not added yet — its exact wording depends on §3.1 and §3.2, and
  documenting a mechanism before deciding what the mechanism is would just need rewriting.

## 5. Known environment facts worth not rediscovering

- **`grpcio`/`grpcio-tools` have no CPython 3.15 wheel yet**, and building from source
  fails on this machine against 3.15.0b4 — confirmed for both. Already recorded in
  `MAINTENANCE.md` §3's tracked-dependency inventory and worked around in `noxfile.py`
  (narrow explicit deps) and `tests/integration/test_agent_control_roundtrip.py`
  (`pytest.importorskip`). Do not "fix" those workarounds without re-checking the wheel.
- **Bare `python` on this machine currently resolves to 3.15**, not the pinned 3.14. Worth
  knowing before diagnosing anything interpreter-shaped; `py -3.14` / `py -3.15` are the
  reliable selectors on Windows.
- Python **3.14.6 is not the free-threaded build**, and 3.16 is not installed at all —
  both already flagged in `PHASE_1_COMPLETE.md` §6.4 and still true.
- The `domtrifoundation` token used across these sessions was printed into a session
  transcript and **should still be rotated** (`PHASE_1_COMPLETE.md` §6.8).

## 6. What the next session should do first

1. Get answers to §3.1 and §3.2.
2. Write the per-commit version-tick practice into `CONTRIBUTING.md` (§4), using whatever
   §3.1/§3.2 resolve to.
3. Verify the wave-1 build order against `PROCESS_TOPOLOGY.md` and
   `v3-plan-02-architecture.md` rather than trusting the sequence as given — the Phase 2
   brief explicitly asks for that check, and it has not been done yet.
4. Then start wave 1: Persistence → Auth & Tenancy → Audit → Logs, reading each API's own
   deep-dive at the moment that API's implementation starts, not batched up front.
