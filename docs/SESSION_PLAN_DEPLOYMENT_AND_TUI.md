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

## Phase 3 — Supervisor (`supervisor/`) — the real "server" — DONE

All built, all live-confirmed against real launched subprocesses (`core/geo_address/service.py`),
a real Windows TCP echo server, and a real two-phase self-update flow. 65 tests.
`contracts.py`, `errors.py`, `arbitration.py` (persisted per-channel active-release JSON),
`boot_sequence.py` (topological launch order + real `grpc.aio` reachability health gate —
honestly documented as narrower than a Watchdog `Kick()` liveness check, since no Core API
built this session calls `Kick()` yet), `rollback.py`, `single_instance.py`, `version_pins.py`,
`sleep_wake/classification.py` + `state.py` + `socket_activation_linux.py` (unit-file text only,
unverified against real systemd) + `activation_proxy_windows.py` (real, live-tested relay),
`self_update/reexec.py` (two-phase verified re-exec, `--smoke-test`), `supervisor.proto` +
`service.py`. Two real bugs found and fixed: `_spawn()` wasn't passing `spec.address` as argv
to the launched subprocess (every service silently bound its own hardcoded default instead),
and `tests/unit/supervisor/test_service.py`'s `REPO_ROOT` was off by one parent directory.

## Phase 4 — Verification sweep

- [ ] Full suite + forward_compat green
- [ ] CLAUDE.md updates for every touched package
- [ ] Commit + push each phase separately (matching this session's established cadence)

## Phase 5 — TUI — shell DONE, five custom screens + webapp + wizard integration remain

Read `v3-deepdive-14-interface-api.md` in full first, confirmed real requirements (not
assumed): the TUI is Textual, menu-data-driven with one generic `MenuScreen`, a closed
8-item custom-screen exception list (run monitor, OCR diff viewer, vendor/branch editor,
Groups, staff audit queue, Fleet & Updates, Boot Sequence, credits), and localization
(English + Tagalog at launch) as a cross-cutting `t()` mechanism, never a sub-API.

**Built and live-tested this pass** (16 new tests, `tests/unit/services/interface/`, real
`Textual.App.run_test()`/`Pilot` runs — never a mocked screen tree): `theme.py`, `i18n.py`,
`menu_screen.py` (the one generic renderer), `menu_data/__init__.py` (`submenu_items()`),
`menu_data/root.py`, `custom_screens/boot_sequence.py` (real progress via a new
`boot_many(on_result=...)` callback added to `supervisor/boot_sequence.py` in the same
pass), `custom_screens/credits.py` (real dependency/license table sourced from every
`requirements.txt` in the repo), `app.py` (`InterfaceApp`: boot -> root menu, plus the
`interface.open_screen.*` convention that lets menu-data name a custom screen).

**Explicitly NOT done, tracked honestly in `services/interface/CLAUDE.md`** rather than
silently left half-finished:
- [ ] `fleet_updates`, `run_monitor`, `staff_audit_queue`, `vendor_branch_editor`, `groups`
  — five of the eight exception-list screens. Each needs real RPC wiring to an owning API
  (Supervisor, Execution Core, Review/Flagging, temporal_learning, Groups respectively)
  that doesn't expose a TUI-facing surface yet. Named in `root.py`, report "not built yet"
  honestly when selected rather than crashing or faking a result.
- [ ] `find_setting` interactive screen — the real fuzzy-matcher already exists and is
  tested (`core/agent_control/backends/local.py`), just not yet presented as its own screen.
- [ ] `ocr_diff_viewer` — not yet named in `root.py` at all (reached contextually from a
  run, not the root menu); undesigned as of this pass.
- [x] Confirm the first-time interactive setup wizard's TUI-side integration — confirmed
  real against `v3-deepdive-11-setup-api.md` §7 and the complete word-for-word
  `docs/SETUP_WIZARD_SCRIPT.md` (not assumed). Built `custom_screens/wizard_script.py`
  (the script as structured data) + `custom_screens/wizard_screen.py` (drives
  `WizardEngine.run()` **in-process, not gRPC** — the wizard runs before Supervisor boots
  the fleet, so no Setup service process exists yet to stream against). Live-tested
  end-to-end through a full PERSONAL-branch run. Each step's primary decision is real;
  Tunnel/Billing/SMS's external credential sub-flows report "not available inline yet"
  honestly rather than faking a form. **Not yet wired into an actual first-run launch
  path** (`app.py`/`bootstrap.py` don't construct a real `WizardEngine` and show this
  screen yet) — tracked in `services/interface/CLAUDE.md`.
  - [ ] `TERMS_OF_SERVICE` persistence gap (validates acceptance, persists nothing) —
    still open; matters once the screen is wired into a real launch path.
- [ ] Full settings screen with tooltips as a **structured, editable form** (current
  `settings.py` menu data is real and browsable via `MenuScreen`, but no screen yet lets an
  operator open/edit the raw settings file directly, per the explicit ask for both paths).
- [ ] Webapp (`services/interface/webapp/`) — still entirely 0-byte scaffolding.
