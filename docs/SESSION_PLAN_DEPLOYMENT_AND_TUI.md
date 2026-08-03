# Deployment Infrastructure + TUI — Execution Plan

Working plan for completing the remaining real gaps before the TUI, per direct instruction.
Updated as phases complete. Not a permanent doc — delete or fold into CLAUDE.md files once done.

## Already confirmed complete (verified via research, no work needed)

- **Setup API** (`services/setup/`) — bootstrap.py, wizard.py (11-step interactive first-run
  wizard, `WizardEngine.run()` as an async generator), venv_provisioning.py, dev_mode_strip.py,
  hardware detection/scoring, `setup.proto` + real bidirectional-streaming `RunWizard` RPC +
  `DetectHardware`/`ProvisionVenvs`. One named gap: `TERMS_OF_SERVICE` step validates but
  doesn't persist `TermsAcceptance` — no seam owns that storage yet (fix in Phase 5 if time).
- **Health API** (`core/health/`) — status.py, live_diagnostic.py, resource_ledger.py,
  capability_drift.py, watchdog/, real `health.proto` + service.py.
- **Execution Core** (`services/execution_core/`) — pipeline.py, scheduler.py, state_machine.py,
  checkpointing.py, retry_policy.py, watchdog_hooks.py, real `execution_core.proto` + service.py.

## Phase 1 — Update/Deployment API (`services/update/`) — DONE (commit 2b65496)

`release_manager.py`, `errors.py`, `metrics.py`, `update.proto` + service.py all built and
live-confirmed against a real local git remote. `CloneRelease`/`GetActiveChannels` real.
A real Windows `shutil.rmtree`-on-read-only-git-files bug found and fixed along the way.

## Phase 2 — Proving Grounds (`services/update/proving_grounds/`) — DONE

All real: contracts.py, errors.py, download.py (real streamed downloads + HF bearer auth),
test_runner.py (BenchDispatcherRegistry + real Docker subprocess isolation check),
promotion.py, changelog_watcher.py (thin, non-triggering), proto + service.py. 19 tests,
all live-confirmed against real HTTP servers / real Docker-absence detection.

## Phase 3 — Supervisor (`supervisor/`) — the real "server"

All 0 bytes currently except CLAUDE.md. This is the most load-bearing piece — nothing else in
Layer 1 starts without it per the boot sequence.
- [ ] `contracts.py` — `ActiveRelease`, `ServiceState`, `SleepPolicy`, `ServiceVersionPin`
- [ ] `arbitration.py` — per-channel active-release resolution
- [ ] `boot_sequence.py` — dependency-ordered launch, Watchdog health-gate between each
- [ ] `rollback.py` — revert `ActiveRelease` to prior release dir on post-cutover health failure
- [ ] `self_update/reexec.py` — two-phase verified re-exec with `--smoke-test`
- [ ] `sleep_wake/` — `classification.py` (NEVER/IDLE_TIMEOUT/SCHEDULED_ONLY per the deep-dive's
  own named service list), `socket_activation_linux.py`, `activation_proxy_windows.py`
- [ ] `errors.py`
- [ ] `supervisor.proto` + service.py — `GetActiveRelease`, `TriggerRollback`,
  `GetSleepStatus`, `ForceWake`, `PinServiceVersion`, `ListServiceVersionPins`,
  `RestartServiceOnVersion` (streaming)
- [ ] Tests, live-confirmed: boot a small set of fake/real services in dependency order against
  real health checks, confirm rollback path, confirm sleep/wake classification.

## Phase 4 — Verification sweep

- [ ] Full suite + forward_compat green
- [ ] CLAUDE.md updates for every touched package
- [ ] Commit + push each phase separately (matching this session's established cadence)

## Phase 5 — TUI

- [ ] Confirm the "first-time interactive setup TUI" is a real, sourced requirement (check
  `docs/apis/v3-deepdive-11-setup-api.md` and Interface's own deep-dive for exactly how the TUI
  drives Setup's `RunWizard` stream) before building — do not assume shape.
  - [ ] TERMS_OF_SERVICE persistence gap (Phase 0 note above) — fix if it blocks the wizard flow.
- [ ] Read `docs/apis/v3-deepdive-??-interface-api.md` (TUI + webapp) fully for the complete
  screen list, and `services/interface/` current state (contracts.py, tui/, webapp/).
- [ ] Build the TUI shell against Supervisor's boot sequence (loading screen -> handoff).
- [ ] Build every screen the deep-dive names, including the full settings screen with tooltips.
- [ ] Settings TUI must both open/edit the raw settings file AND provide the structured
  form-based config path — confirm both are real, sourced requirements before building.
