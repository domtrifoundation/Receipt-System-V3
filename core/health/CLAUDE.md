# Health API

Health owns two layers: **status** (service up/down, queue depth, per-instance resource utilization, external-dependency reachability) and **live diagnostic** (the bench suite's own empirical classification technique, reused continuously against real traffic). It also now owns the **live resource commitment ledger** (§4, resolved in Setup's deep-dive) — tracking which process currently holds how much VRAM on which device, distinct from Setup's own static `HardwareProfile`.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had a real health layer — `health.py`'s watchdog thread and heartbeat file, plus `metrics.py` and `hardware.py` for utilization and capability reporting. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-20-health-api.md`](../../docs/apis/v3-deepdive-20-health-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **detect what hardware exists** — that's Setup API's `HardwareProfile` (its own deep-dive §5); Health reads that published profile rather than re-probing.
- **decide rollout cutover policy** — Update API's Supervisor consumes Health's status signal to gate a release swap; Health only reports, it doesn't decide when a rollout proceeds.
- **implement Watchdog's restart mechanism itself** — Watchdog (§5) is Health's own sub-API, but the actual process-restart action is a Supervisor-level capability Watchdog triggers, not something Health performs directly on a process it doesn't own.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Setup owns static hardware *detection*; Health owns the live resource *ledger*. That split is deliberate and worked out from what each API is actually for, not from who thought of it first (`docs/PRINCIPLES.md` §1.5) — Health reads Setup's published profile rather than re-probing. Health reports; it never decides when a rollout proceeds.

**Setup API does not exist yet, so the default `HardwareProfileReader` publishes nothing and
every reservation is rejected as `UNKNOWN_DEVICE`.** That is deliberate, not a placeholder to
relax: granting against an unknown VRAM ceiling is the unsafe answer, so this is one place
where §4.2's fail-closed rule outranks §4.4's degrade-gracefully default. Wiring Setup in later
means passing a real reader, not removing a permissive default someone forgot about.

**A rejected reservation is not an error.** Deep-dive §5.1 is explicit that a rejection means
the caller falls back to CPU or queues. `ReservationOutcome.rejection_reason` carries it and
`error_code` stays empty; a caller treating a capacity rejection as a failure has misread the
API. The `.proto` says the same thing in a comment for the same reason.

**A lapsed reservation is never revived by a late refresh** (§11). The owning process is meant
to *discover* it lost its claim and abort its in-flight work through Execution Core's
checkpoint-resume. Silently extending an expired reservation would hand two processes the same
VRAM, since the second acquired it legitimately while the first was silent.

**Files here that the deep-dive's §2 package layout does not list**, added with reasons:
- `capability_drift.py` — §4's version-capability-drift check is a genuine third responsibility
  alongside `status.py` and `live_diagnostic.py`, and folding it into either would have meant
  one of them owning a concern that is not its own. Its probe registry is where **every future
  Forward-Compatibility-shimmed capability registers its own check, in the same PR that
  introduces the shim** (§4.1) — that is the concrete obligation, not a suggestion.
- `watchdog/timeout_detector.py` — named in the sub-API's own §2 layout but absent from the
  parent's; it is where the silent-past-timeout comparison lives, kept out of `kicks.py` so the
  receive path stays free of the check that reads it.
- `health.proto` + `generated/` — §8 specifies the surface but the layout predates showing where
  the `.proto` lives. Both services live in one file because Watchdog shares the parent's
  process (`docs/PROCESS_TOPOLOGY.md`), so one `.proto` per process keeps the generated stub
  layout matching the process layout. Regenerate with `python -m grpc_tools.protoc` and
  re-apply the relative-import fix in `health_pb2_grpc.py` (`from . import health_pb2`); never
  hand-edit generated files. `service.py` imports them lazily, so the package stays importable
  — and its tests still meaningful — on an interpreter with no `grpcio` wheel yet (3.15 today).
