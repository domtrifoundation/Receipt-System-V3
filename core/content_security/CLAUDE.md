# Content Security API

Content Security owns **scanning every untrusted incoming file** — real file-type verification (magic bytes, never trusting an extension or client-supplied MIME type), malware/exploit scanning, polyglot detection, and container-level bomb checks for archives.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no file-type verification, malware scanning, polyglot detection, or archive-bomb checking — the only occurrence of the word "antivirus" in its source is a help string about engines failing to start. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-27-content-security-api.md`](../../docs/apis/v3-deepdive-27-content-security-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide what happens after a rejection** — flagging, notifying, and any staff review of a rejected file are Review/Flagging's and Notifications' own jobs; this API's contract is a pass/fail verdict plus detail, not a downstream workflow.
- **get bypassed or reimplemented per-caller** — Ingestion calls it (its deep-dive §6, explicitly fail-closed with no local bypass path), and Persistence's Reimport calls the exact same shared logic for its own uploads (file 01) rather than either API rolling its own scanning.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Fail-closed is a contract-level guarantee, not a caller convention (`docs/PRINCIPLES.md` §4.2): if the scan call fails, times out, or the service is briefly unavailable, every caller treats the file as unscanned and therefore unsafe. Archive-bomb detection reads `zipfile.infolist()` metadata *before* any extraction — never unpack a hostile archive to measure it. Two passes, not one: the container, then each file it yielded.

**The `.proto` has no field capable of expressing "could not check", and that is deliberate.**
The §4 guarantee is only really enforceable if the protocol gives no way to say anything other
than safe or not-safe; a future `unknown` or `scan_skipped` field would reopen exactly the hole
this API exists to close. `tests/unit/core/content_security/test_service_and_contracts.py`
asserts the field set against the generated descriptor so that change fails before anything can
depend on it.

**`safe=True` has exactly one origin in this package**: `pipeline.ContentScanner._resolve`,
reached only when every enabled, *available* provider returned `CLEAN`. Nothing in `service.py`
constructs it. If you find yourself adding a second place that can set it, that is the bug.

**`clamscan` reloads its entire signature database from disk on every single invocation —
confirmed live at ~11 seconds just to load, before scanning anything — and a full-fleet
concurrent-submission test found that's a real capacity ceiling, not a theoretical one.**
8 concurrent scans (this service's own `ThreadPoolExecutor(max_workers=8)`) contending for
CPU/memory to each reload the database blew straight past Ingestion's 15-second client
timeout, and most of a real concurrent batch failed closed with `content_security_unavailable`
as a direct result. `providers/clamd_provider.py`'s new `ClamdProvider` is the fix: it talks
to an already-running `clamd` daemon over its own TCP `INSTREAM` protocol instead (no new
dependency — a small adapter over the wire protocol, matching `clamav_provider.py`'s own
"the adapter is this file, not a wrapper library" stance), so the database loads once at the
daemon's own startup and every scan after that only pays for the actual scan (confirmed live:
~1s warm vs. ~11s cold). Set `RESIBO_CLAMD_HOST` (and optionally `RESIBO_CLAMD_PORT`, default
3310) to opt in — `service.py`'s `__main__` then registers `ClamdProvider` enabled and
`ClamAVProvider` registered-but-disabled as a manually-flippable fallback, never both enabled
at once: they share one signature database, so running both adds no real corroboration (unlike
ClamAV vs. VirusTotal's independent heuristics), only `clamscan`'s own reload cost on every
scan. **This adapter does not start, manage, or configure the `clamd` process itself** — an
operator points it at an already-running daemon, the same relationship every other provider in
this package has with its own external service.

**A provider that ran and failed poisons the whole verdict, not just its own share of it.** A
caller cannot tell a verdict reached despite a failure apart from one that would have been
different had that provider actually run, so `SCAN_PROVIDER_FAILED` is a deny even when another
scanner returned clean. This is stricter than it looks at first glance and it is intentional.

**Three outcomes, not two** (§9's resolved staff-review threshold): unanimous `CLEAN` passes;
unanimous `MALICIOUS` is an outright reject; *anything else* — a genuine disagreement between
scanners, or a single scanner's own low-confidence result — is `requires_staff_review`, denied
but not condemned. `provider_verdicts` publishes each provider's raw answer precisely so the
conflict is inspectable rather than folded into one boolean (`docs/PRINCIPLES.md` §4.3).

**Files here that the deep-dive's §2 package layout does not list**, added with reasons:
- `pipeline.py` — the orchestrator composing `scanning/` (pure, synchronous, in-memory) with
  `providers/` (async, subprocess or network) into the two verdict types. The alternative was
  putting it in `service.py`, which would have made the fail-closed guarantee a property of the
  gRPC servicer rather than of the package — and therefore absent for the in-process caller.
- `service.py` + `content_security.proto` + `generated/` — §7 specifies the surface but the
  layout predates showing where the `.proto` lives. Regenerate with
  `python -m grpc_tools.protoc` and re-apply the relative-import fix in
  `content_security_pb2_grpc.py` (`from . import content_security_pb2`); never hand-edit
  generated files. `service.py` imports them lazily, so the package stays importable — and its
  tests still meaningful — on an interpreter with no `grpcio` wheel yet (3.15 today).
