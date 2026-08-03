# Supervisor

Supervisor is the **one thing that lives outside every release clone, permanently** — not inside any versioned `<version>_<commit-hash>` directory, a genuine top-level citizen alongside config and shared data (`docs/PRINCIPLES.md` §1.6). It owns: determining which release is active per channel, launching every service from the correct clone's own venv in dependency order, health-gating rollout cutover, driving rollback, and — new — sleeping/waking genuinely idle services.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no process supervision, release arbitration, or rollback — `run.bat` started the one program. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-38-supervisor.md`](../docs/apis/v3-deepdive-38-supervisor.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide business logic** — Supervisor launches processes and watches health signals; it has no opinion about what any service actually does.
- **update itself the way it updates everything else** — this is the entire reason this document exists; see §4.
- **replace Watchdog** — Watchdog (Health API's sub-API) proves a *running* service is alive via kicks; Supervisor decides whether a service should be *running at all* in the first place. Different questions, deliberately different owners.

## Forward-Compatibility Pattern applicability

No `FrozenDict`-typed field, no GIL-dependent assumption, and no `asyncio` behaviour that has changed across 3.14/3.15/3.16 in this folder as designed (`docs/PRINCIPLES.md` §3.3.1). Re-check this line in the same PR that adds one — a stale "not applicable" is the specific drift the guide's §6 warns about.

## Real gotchas specific to this folder

Structurally neither Layer 1 nor Layer 2 (`docs/PROCESS_TOPOLOGY.md` §1): it lives outside every release clone, permanently, because it is what decides which clone is active and cannot be part of what it launches. Keeping it small is a load-bearing design goal, not tidiness — it is the one component that cannot update itself the way it updates everything else. It launches processes and watches health signals; it has no opinion about what any service does.

**Every file this session was entirely 0-byte scaffolding until this pass.** `contracts.py`, `errors.py`, `arbitration.py`, `boot_sequence.py`, `rollback.py`, `single_instance.py` (§5.4, not in the deep-dive's own §2 layout — real, substantial staged-restart logic that belongs in its own module), `version_pins.py` (§5.2, also not in §2's layout, for the identical reason), `sleep_wake/classification.py`, `sleep_wake/state.py` (live tracking, not in §2's layout — `classification.py` only answers the static policy question), `sleep_wake/socket_activation_linux.py`, `sleep_wake/activation_proxy_windows.py`, `self_update/reexec.py`, plus `supervisor.proto` + `service.py`. 65 tests, all live-confirmed.

**The Boot Sequence health gate is a real gRPC-reachability probe, not a Watchdog kick — a real, named, honest gap.** Watchdog's own `Kick` RPC (`core/health/health.proto`) is real and tested, but **no Core API built this session actually calls it** — none of this repo's ~25 servicers send their own periodic heartbeat to Watchdog. Wiring self-kicks into every Core API is real, separate, substantially larger future work. Until that lands, `wait_until_reachable()` (`boot_sequence.py`) answers "is this service up" the same honest way this session's other servicers answer "is this dependency reachable" — a real `grpc.aio.insecure_channel` + `channel_ready_future` probe, confirmed live against real launched subprocesses. It proves the process accepted a real connection; it does not prove the deeper Watchdog liveness contract the deep-dive's own prose describes.

**A real, live-found bug in `_spawn()`: the launched subprocess must be told which address to bind to.** Every servicer's own `__main__` block accepts an optional address override via `sys.argv[1]` (`core/geo_address/service.py`'s own `addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS`), but the first version of `_spawn()` launched with no argument at all — the subprocess silently bound its own hardcoded `DEFAULT_ADDRESS` instead of `spec.address`, so the health gate waited out its own full timeout probing a port nothing was listening on. Confirmed live before the fix (a real subprocess launched and ran fine, health check still failed) and after (real reachability confirmed in well under a second).

**Isolation for Boot Sequence's own dependency-order failure is fail-closed, matching Migration API's own "a missing step stops the walk."** `boot_many()` stops launching further services the moment one fails, rather than continuing past a dependency gap the rest of the fleet may need — confirmed live: a three-service chain with a broken middle service correctly launches the first, fails the second, and never even attempts the third.

**`GetActiveChannels`-shaped state (`ChannelArbitrator`, `VersionPinStore`) is a small, persisted JSON file each, matching §3.1's own "a small local record (not a full database — this is genuinely simple state)."** Both persist under `<install-root>/supervisor/`, a sibling of every release clone — Supervisor's own permanent top-level home (`docs/PRINCIPLES.md` §1.6).

**The Windows activation proxy (§6.3) is real and live-confirmed on this development machine** — a genuine bidirectional relay, real wake-on-first-connection, real second-connection-skips-wake behaviour. **The Linux systemd path (`socket_activation_linux.py`) is unverified against a real `systemd`** — this development machine is Windows; what is real and tested is the unit-file text generation (pure string formatting) and `is_systemd_available()`'s own live subprocess probe (confirmed correctly reporting unavailable here). The deeper runtime question — whether this project's `grpc.aio.server()` processes accept a passed-in `SD_LISTEN_FDS`-style socket, or whether the simpler `systemd-socket-proxyd` fallback is what a real deployment actually wires in — is flagged honestly as still open, not assumed working.

**§4.2's own named "single most important test in this entire document" is real and passing**: `self_update/reexec.py`'s `update_supervisor()`, given a deliberately broken new build, confirms `handoff` is never called and the failure is reported cleanly — the old Supervisor instance keeps running untouched. Also confirmed: an unconfirmed owner request is refused before the smoke test even runs, and a hanging smoke test times out cleanly without ever handing off.

**`RestartServiceOnVersion`'s own step-1-before-step-2 asymmetry (§5.4, §7's own named testing hook) is confirmed live, not just described**: a target version with no release clone at all, and a target with a release clone but no provisioned venv for the service, both fail at `confirming_target` — before `stopping_old` is ever reached. Step 1's own "health-check-capable" check is honestly narrower than a full launch rehearsal — this codebase has no sandboxed dry-run launch mode, so it treats "the clone directory exists and names a real venv for this service" as the real, checkable proxy, documented as such rather than claimed to be the deeper guarantee.

**`ForceWake`/`PinServiceVersion` are Audit-logged (§11's own resolved "yes" for both) using the exact same gap-shape `core/review_flagging/gateways.py` already documents** — Audit's own closed operation vocabulary does not register Supervisor's own operations yet, so a real call today returns `recorded=False, error_code="UNKNOWN_ACTION"`, surfaced honestly (best-effort, never fails the operation it describes) rather than silently dropped.
