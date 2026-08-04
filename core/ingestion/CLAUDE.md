# Ingestion API

Ingestion API's job: acquire a source file from wherever it comes from, normalize it into one or more base images, and hand those off to Preprocessing/OCR.

## API version at x03.00.00 Zircon

`a03.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Third generation. V1 acquired receipts by globbing a configured folder and excluding the archive. V2 added Google Drive as a real second channel (`google_drive.py`, OAuth plus folder-ID polling) alongside the watched folder. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a03.00.05`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-04-ingestion-api.md`](../../docs/apis/v3-deepdive-04-ingestion-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide OCR-readability transforms** — grayscale/contrast/threshold variant generation is entirely Preprocessing API's job (§1 of that deep-dive already draws this line from its own side).
- **own malware/content-safety scanning logic** — it calls the Content Security API (file 01, #26) as every other untrusted-content entry point does; scanning logic lives there once, not duplicated per caller.
- **own the reimport/edit-flow-back-in path** — that's Persistence's Reimport sub-API (file 01, #5), even though it's conceptually "receiving a file from outside the system" the same way Ingestion's other channels are. It stays there because its actual job (diff against canonical state, resolve conflicts, apply through the normal write path) is a Persistence-write concern, not an acquisition/normalization one — already resolved and corrected into file 01/03 in this session's prior discussion.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Every source is an independently enableable Provider Registry entry. A self-hosted install with no Drive configured must degrade to direct-upload-only cleanly, never error. Drive credentials go through a swappable credential-provider interface: service account is the only strategy usable today, per-user OAuth is built behind the same interface and switches on by config once Google's verification clears — not a rewrite at that point, and not something to hardcode around now.

- **The normalization pipeline's archival branch does not always re-encode.** A plain
  raster image genuinely gets re-encoded into the owner's configured codec
  (`format_normalization/codecs.py`), but a PDF's original bytes are stored as-is — a
  multi-page container has no meaningful single-image codec to re-encode into. Confirmed
  live: the pipeline correctly branches on `sniff_format(raw_bytes) == "pdf"` before
  deciding, not just a documented intention.
- **`content_security_client.py`'s fail-closed guarantee was confirmed live both ways**,
  not just written to spec: a real, in-process Content Security service with no scan
  provider configured denies (`safe=False`, `NO_SCAN_PROVIDER_AVAILABLE`), and an
  unreachable service raises `ContentSecurityUnavailable` rather than assuming safe.
- **Google Drive (`sources/google_drive/`) and the webhook `DriveWebhookAdapter`
  (`webhook_manager/subscription.py`) are NOT live-tested this session** — no real Drive
  credentials, network call, or `google-api-python-client`/`google-auth-oauthlib` install
  exists in this environment (confirmed: both raise `ModuleNotFoundError` here). Built
  directly from the Drive v3 API's own published shape; `is_available()` correctly
  reports `False` in this real, live-confirmed state, which is itself the
  graceful-degradation path these modules exist to prove works, not a gap in testing.
  The credential-strategy swap test (deep-dive §10) IS real, though — it proves
  `GoogleDriveSource` genuinely doesn't care which `DriveCredentialProvider` it's handed,
  using fake providers implementing the same Protocol shape.
- **The webhook renewal ordering (register-new -> confirm -> deregister-old) is
  confirmed live against fake adapters**: a confirmation failure never triggers a
  deregister call, and a registration failure stops before either later step runs —
  the concrete validation of the "never open a delivery gap" guarantee, not just design
  reasoning.
- **`cv2.Stitcher` panorama stitching is confirmed live** against real synthetic
  overlapping frames (a successful stitch, an insufficient-frames failure, and an
  unmatchable-content failure all producing the real, distinct `cv2.Stitcher` status
  codes) — see `format_normalization`'s own sub-CLAUDE.md for the codec/raster-side
  findings.
- **`GoogleDriveSource` was built and independently tested but never actually
  constructed or registered anywhere in the running service — a real, complete gap
  found only by checking that every built module is genuinely reachable, not just that
  it has its own passing tests.** `IngestionServicer`'s own `SourceRegistry` previously
  only ever contained `SourceKind.DIRECT_UPLOAD`; Drive was completely unreachable
  through the running service regardless of how it was configured. Fixed:
  `drive_assembly.py` is the real assembly point — it reads `credential_strategy`
  ("service_account" | "oauth"), builds the matching credential provider, and
  constructs a real `GoogleDriveSource` that `IngestionServicer.__init__` now registers
  unconditionally (safe: `is_available()` correctly reports `False` without a
  configured folder, matching the deep-dive's own "direct-upload-only" degrade
  guarantee — confirmed live).
- **The entire `webhook_manager` sub-API was disconnected from the running service —
  the same shape of gap, at sub-API scale.** `subscription.py`, `circadian.py`, and
  `callback_handler.py` each existed and were independently tested, but nothing ever
  constructed a subscription store, tracked a Drive Changes API page token across
  calls, or recorded a delivery for Circadian — `HandleDriveWebhook` (the one real gRPC
  entry point named in `ingestion.proto`) acknowledged every callback unconditionally
  without doing anything at all. Fixed: `webhook_manager/manager.py`'s new
  `WebhookManager` is the real, stateful assembly point (register/renew/handle_callback,
  a bounded `pending_events` queue standing in for Execution Core's own not-yet-built
  debounce consumer, per deep-dive §1's "never decides run boundaries" boundary).
  `IngestionServicer` now holds one, built from the same shared credential provider as
  `GoogleDriveSource`, and `HandleDriveWebhook` genuinely delegates to it — confirmed
  live: an unregistered channel correctly returns `accepted=False`, and a full
  register -> handle_callback -> Circadian-recording sequence against fake Drive
  responses produces real `ChangeEvent`s and updates `needs_fallback_poll()` correctly.
- **`IngestionMetrics.drive_downloads` was declared and read by nothing** — the same
  shape of gap, found by the same "does every declared field have a real usage site"
  check. Fixed: `GoogleDriveSource` now takes an optional metrics collector and
  increments it on a real download; `service.py` passes its own `self._metrics` through
  `drive_assembly.build_google_drive_source()`.

**`SubmitDirectUpload` now actually triggers Execution Core processing — a real,
previously-confirmed gap closed.** It used to normalize a file and stop; nothing anywhere
told Execution Core a receipt existed to process, confirmed by direct code inspection
before this fix (no RPC call to Execution Core existed anywhere in this file).
`IngestionServicer` takes an optional `execution_core_address` (`None` degrades to
"normalize only," e.g. an isolated unit test of normalization alone); when set, a
successful normalization calls `StartRun` then `SubmitReceipt` per normalized page.
Failures in that trigger call are logged-and-swallowed rather than failing the upload
response — the file is genuinely, safely normalized and stored either way. Live-tested
end to end against six genuine running servicers (`tests/unit/core/ingestion/
test_execution_core_trigger.py`) — no mocked gRPC stub anywhere in the chain. **The
Google Drive webhook path (`HandleDriveWebhook` → `WebhookManager.pending_events`) and
the scheduled fallback poll do not yet call `SubmitReceipt`** — that queue was built as
"a stand-in for Execution Core's own not-yet-built debounce consumer" per its own
docstring below, and wiring it is the identical pattern just applied to direct upload.

**The Google Drive push-webhook and scheduled-fallback-poll paths now also trigger real
processing — closing the two remaining trigger gaps.** `HandleDriveWebhook` downloads,
normalizes, and submits every real/modified `ChangeEvent` it receives immediately,
reusing the identical `normalize_source_file`/`_submit_for_processing` path direct
upload uses. `PollDriveFallback` (new RPC) lists every file currently in the configured
Drive folder and processes it the same way — real and callable, **but nothing yet
invokes it on a timer**: `GoogleDriveConfig.fallback_poll_interval_hours` configures
`CircadianMonitor`'s own "is a poll overdue" check, but there is still no periodic
caller (Task Scheduler API is the real owner of that missing piece, not this package).
Drive ingestion has no real per-user mapping today (one shared folder, `WebhookProvider`/
`ChangeEvent` carry no user identity) — `"local"` is the honest single-tenant-mode
default every Drive-triggered receipt is submitted under, matching `common/blob_client.
py`'s own default; a real per-user Drive connection is separate, larger follow-up work.

**A real, live-found receipt-id collision bug, fixed in the same pass.**
`_submit_for_processing` originally keyed each submitted receipt's id on
`f"{run_id}:{page_index}"` — two *different* uploads from the same user that the
debounce coalescer merges into one run (§5.2 of Execution Core's own deep-dive) both
start at `page_index=0`, so the second `SubmitReceipt` call silently overwrote the
first's Persistence row under the identical id. Caught by a real live test asserting
two distinct uploaded files produced two distinct receipts — it produced one. Fixed by
keying on the blob's own content hash instead (`image.image_ref.logical_id`), which is
unique per real file regardless of how many uploads a debounce window merges together.
Live-tested end to end against real Content Security/Persistence/Preprocessing/OCR/
Execution Core servicers with a fake `GoogleDriveSource` standing in only for the one
seam real Drive credentials don't exist for in this environment (`tests/unit/core/
ingestion/test_drive_trigger.py`).

**A genuine, foundational, previously-undiscovered gap found and partly fixed: this
package's own `except Exception` best-effort catches were writing to nothing.** Direct
question, direct answer: "nothing should be silent if the Logs API is doing its job,
right?" — confirmed, Logs API was not doing its job, for a reason bigger than this one
package. `core/logs/writer.py`'s `LogWriter` (the real write path — unconditional full-
traceback capture, verbosity gating, non-blocking appends, all real and independently
tested) had **zero callers anywhere outside `core/logs/` itself**, confirmed by grep
across the entire repository, not assumed. `logs.proto` has no `Write`/`Ingest` RPC at
all — only `Query` — so the real, intended architecture (per `v3-deepdive-18-logs-api.md`'s
own "every API in this batch writes through this one for operational trace") is that
each service imports `LogWriter` directly and appends to its own file on the shared log
root, never a gRPC hop into Logs API's own process for every write. Every one of this
file's own best-effort `except Exception: pass` blocks — including the ones added in the
same pass that built them — genuinely vanished into nothing until this fix.

**Fixed here, for real, with a real end-to-end proof**: `IngestionServicer` now holds one
`LogWriter` instance (`self._log_writer`, matching that module's own "one instance per
process" convention), injectable via a new `log_writer` constructor parameter so tests
never write real files to this machine's own default log root
(`core/logs/paths.py`'s `~/.resibo/logs` fallback — confirmed live this was a real risk
before `tests/unit/core/ingestion/conftest.py` gained an autouse fixture pointing
`RESIBO_LOG_ROOT` at each test's own `tmp_path`). Every one of this file's four silent
catches now calls `log_writer.log_exception(...)`. `tests/unit/core/ingestion/
test_real_logging.py` is the real proof, not just the wiring: a forced failure inside
`_submit_for_processing`/`_process_drive_events` is read back afterward through a real
`LogReader`, with its full traceback intact — the same path Logs API's own `Query` RPC
serves from.

**Scope, stated honestly**: this fixes exactly the silent catches in this one file. The
identical gap exists across every other Core API in this repository that has its own
best-effort `except Exception` — wiring `LogWriter` into all of them is the same
mechanical pattern, real, separate, much larger follow-up work, not done here.

## Implementation status

Implemented this session — `contracts.py`, `errors.py`, `source_registry.py`,
`content_security_client.py`, `sources/` (direct upload, Google Drive, scanner
capture/stitching), `webhook_manager/` and `format_normalization/` (see their own
`CLAUDE.md` files), `metrics.py`, `service.py` + `ingestion.proto`. 42 tests, all passing.
