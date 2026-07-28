# V3 Deep Dive: Ingestion API

**Companion files:** `v3-plan-00-index.md` · `v3-plan-01-core-apis.md` · `v3-plan-02-architecture.md` · `v3-plan-03-decisions.md` · `v3-plan-04-v2-audit-findings.md` · `v3-deepdive-01-ocr-api.md` · `v3-deepdive-02-inference-api.md` · `v3-deepdive-03-preprocessing-api.md`

**Status:** Fourth deep-dive session. Same ground rules as the prior three. This session also folds in and formalizes several corrections already made directly to file 01/03 in the prior chat discussion (Drive credential strategy, single owner-selected archival codec, Reimport's scope) — this document is the authoritative detailed version of those, not a duplicate decision.

---

## 1. Scope & boundary

Ingestion API's job: acquire a source file from wherever it comes from, normalize it into one or more base images, and hand those off to Preprocessing/OCR. It does not:
- **decide OCR-readability transforms** — grayscale/contrast/threshold variant generation is entirely Preprocessing API's job (§1 of that deep-dive already draws this line from its own side).
- **own malware/content-safety scanning logic** — it calls the Content Security API (file 01, #26) as every other untrusted-content entry point does; scanning logic lives there once, not duplicated per caller.
- **own the reimport/edit-flow-back-in path** — that's Persistence's Reimport sub-API (file 01, #5), even though it's conceptually "receiving a file from outside the system" the same way Ingestion's other channels are. It stays there because its actual job (diff against canonical state, resolve conflicts, apply through the normal write path) is a Persistence-write concern, not an acquisition/normalization one — already resolved and corrected into file 01/03 in this session's prior discussion.

**Owner controls which sources are active, independently — this is the central modularity requirement for this whole API.** Google Drive, direct web upload, the in-browser scanner, and any future channel (email-in, another cloud drive provider) are each an independently enableable Provider Registry entry (rule #5, same pattern as OCR's engines and Preprocessing's variant kinds), not a fixed set baked into the pipeline. Disabling a source the owner doesn't want offered is a config toggle; adding a new source in the future means writing one new provider behind the existing `IngestionSource` interface, never touching the sources already in place. Direct upload is a reasonable always-on default (it's also the fallback path Gateway calls directly, file 01's Gateway entry), but nothing about this API assumes it's the only one, and nothing assumes Drive specifically is available or configured — a self-hosted install with Drive access never set up should degrade to "direct upload only" cleanly, not error.

**Per-tier source availability is a real, wanted future capability — deliberately not built here, and not out of caution, but out of sequencing.** File 03's existing Per-run performance tier decision already establishes the right shape for this: tiers are named config-profile bundles of the same underlying knobs (which OCR engines run, how many preprocessing presets, which inference tier), not special-cased logic per tier — "which ingestion sources this tier can submit through" is just one more knob that belongs in that same bundle, not a second permission system Ingestion invents on its own. But that bundle's actual machinery — Architect's registry owning tier-profile *definitions*, Billing/Execution Core *applying* them to a given run — isn't built yet; building a parallel, Ingestion-specific version of "which tier gets what" now would mean throwing it away (or worse, reconciling two divergent mechanisms) once the real one exists. **Today: `sources_enabled` is a single global list, install-wide, no per-tier variation.** The forward-compatible shape is already in place for the transition, though: `source_registry.py`'s enabled-check takes a `user_id`/`run_id` context (same convention as every OCR/Preprocessing/Inference call already threads through, per file 03's concurrency decisions) rather than reading a bare global flag, so swapping "look up the global list" for "look up this run's resolved tier profile's list" is a resolution-source change inside that one function, not a redesign of how sources report their own availability.

---

## 2. Package layout

```
core/ingestion/
  __init__.py
  contracts.py              # IngestionSource protocol, SourceFile, NormalizedImage, error types
  service.py                  # thin gRPC service implementation, delegates everything
  source_registry.py          # Provider Registry: which sources are configured/enabled
  sources/
    __init__.py
    base.py                    # IngestionSource protocol
    direct_upload.py            # receives from Gateway, simplest source — no push/poll uncertainty
    google_drive/
      __init__.py
      credential_provider.py    # swappable: service_account.py, oauth.py — see §4.1
      service_account.py
      oauth.py                   # implemented now, gated inactive until Google verification clears
      drive_source.py
    scanner/
      __init__.py
      capture_session.py         # server-side session for an in-progress multi-frame scan
      stitcher.py                 # panorama/stitching, server-side — see §4.3
  webhook_manager/              # Sub-API: Webhook Subscription Manager (file 01) — see §4.1.3
    __init__.py
    subscription.py
    circadian.py                 # "Webhook Circadian" — inferred third-party delivery health
  format_normalization/         # Sub-API: Format Normalization — full treatment in v3-deepdive-42-format-normalization.md, see §5
    __init__.py
    raster.py                     # PDF rendering, delegates to Preprocessing's own raster.py for image output shape parity
    codecs.py                     # archival re-encode — single owner-selected codec
    archive_extract.py            # zip handling
  content_security_client.py    # thin client calling the Content Security API — no scanning logic here
  errors.py
  metrics.py
```

Same discipline as the prior three: `contracts.py` is the only file other APIs import from.

```python
# source_registry.py — sketch
class SourceRegistry:
    def enabled_sources(self, user_id: str, run_id: str) -> frozenset[SourceKind]:
        """Today: reads the single global `sources_enabled` config list,
        `user_id`/`run_id` unused but present in the signature. Once the
        tier-profile mechanism (Architect/Billing/Execution Core) exists,
        this becomes 'resolve this run's tier profile, read its sources
        list' instead — a change entirely inside this one method, not a
        redesign of how any source or caller reports/consumes
        availability. See §1."""
```

---

## 3. Data contracts (`contracts.py`)

```python
class SourceKind(str, Enum):
    DIRECT_UPLOAD = "direct_upload"
    GOOGLE_DRIVE = "google_drive"
    SCANNER = "scanner"

@dataclass(frozen=True)
class SourceFile:
    run_id: str
    user_id: str
    source: SourceKind
    raw_blob_ref: BlobRef          # the as-received bytes, pre-normalization, pre-Content-Security-clearance — a TEMPORARY staging blob, not necessarily retained under Persistence's permanent BlobLocation mapping (its deep-dive §3.3) the way archival_blob_ref below is; may be purged on its own short retention window without needing a mapping-table entry at all, since nothing permanent ever references it by logical_id once normalization completes
    original_filename: str
    declared_mime_type: str         # client-supplied, never trusted — Content Security determines the real type

@dataclass(frozen=True)
class NormalizedImage:
    image_ref: BlobRef              # a finished, base image ready for Preprocessing/OCR
    page_index: int = 0              # for multi-page sources (PDF, multi-photo panorama)
    source: SourceKind = SourceKind.DIRECT_UPLOAD
    error: IngestionError | None = None

@dataclass(frozen=True)
class NormalizationResult:
    images: tuple[NormalizedImage, ...]   # one or more — a PDF or a panorama capture yields several
    archival_blob_ref: BlobRef             # the re-encoded archival copy (Format Normalization deep-dive §3), stored independently of images fed to Preprocessing
```

Same "errors are data, not exceptions" convention already established in the prior three deep-dives — a per-file or per-page failure populates `.error` rather than raising across the API boundary.

---

## 4. Sources — Provider Registry entries

### 4.1 Google Drive

#### 4.1.1 Credential strategy — swappable interface, one usable implementation today
```python
# sources/google_drive/credential_provider.py
class DriveCredentialProvider(Protocol):
    def get_service(self) -> Any: ...   # returns an authenticated Drive v3 service object
```
Two implementations behind this interface: `ServiceAccountCredentialProvider` (§4.1.1a) and `OAuthCredentialProvider` (§4.1.1b). **Only the service-account implementation is actually usable right now.** Per-user OAuth for Drive's scopes requires passing Google's OAuth app-verification process before it can be offered to real users at all — that process is what's blocking it, not a design preference, and it's a real, separate piece of work (a CASA audit, a multi-week review) outside this deep-dive's scope to resolve. The OAuth implementation is written and complete behind the interface regardless, gated off by a config flag (`google_drive.credential_strategy: service_account | oauth`, defaulting to and currently locked to `service_account`) — so flipping the default once verification clears is a config change and a flag-flip, not new code, not a rewrite, and definitely not a "revisit this deep-dive" moment.

**4.1.1a Service account (the only active path today)**
- A user shares their receipts folder with a designated service-account email — the same action as sharing a folder with a colleague, no OAuth consent screen involved.
- `pip install google-api-python-client google-auth` (no `google-auth-oauthlib` needed for this path specifically).
- DOMTRI's hosted service and self-hosted installs both use this by default; self-hosted installs can use DOMTRI's shared service account or generate their own via Google Cloud Console in a few minutes (no review process either way).
- Onboarding surfaced in Setup/Ingestion settings: "share your folder with `<service-account-email>`," ideally with a direct deep-link into Drive's own sharing dialog.

**4.1.1b Per-user OAuth (implemented, inactive)**
- `pip install google-auth-oauthlib` additionally.
- Standard `InstalledAppFlow`/web consent flow, token refresh, standard OAuth2 credential storage.
- Held inactive behind the config flag until verification clears — worth a genuine "will this actually get used" check periodically (a Telemetrees-tracked reminder, not a fire-and-forget code path left to bit-rot silently for years) since code that's never exercised in production is exactly the kind of thing that can quietly break (a library API shift, an expired test credential) without anyone noticing until the day it's finally switched on.

#### 4.1.2 Drive as a source, independent of credential strategy
```python
# sources/google_drive/drive_source.py — sketch
class GoogleDriveSource:
    def __init__(self, credentials: DriveCredentialProvider): ...
    async def list_new_files(self) -> list[SourceFile]: ...   # fallback poll path
    async def download(self, file_id: str) -> SourceFile: ...
```
File-type filtering at the Drive API query level (PDF, JPEG/PNG/TIFF/BMP/WebP MIME types) narrows the poll/webhook payload before anything reaches Content Security — a cheap first filter, not a substitute for it (declared MIME type is still never trusted past this point, per §1).

#### 4.1.3 Webhook Subscription Manager (file 01's existing sub-API, detailed here)
**Full treatment in `v3-deepdive-35-webhook-subscription-manager.md`.** Summary below.
Already specified at a high level in file 01 — this section adds the concrete mechanics. Push notifications are the primary trigger (registered via Gateway's Cloudflare Tunnel endpoint), with two real caveats already identified: Google gives an expiration timestamp but no advance warning before lapse, and webhook channels have been reported to occasionally die silently before their stated expiry.

```python
# webhook_manager/subscription.py — sketch
class WebhookSubscription:
    channel_id: str
    resource_id: str
    expires_at: datetime
    provider: SourceKind

async def renew(sub: WebhookSubscription) -> WebhookSubscription:
    """Register-new-then-confirm-active-then-deregister-old — never
    stop-then-start, which would open a real delivery gap between the
    old channel dying and the new one being confirmed live."""
```
- **Renewal**: a Background Worker (idle-time class, file 01 #4) proactively renews ahead of the known expiry — the exact lead time is a bench-tunable config value, not hardcoded, since it trades off unnecessary renewal churn against margin for a slow renewal attempt.
- **"Webhook Circadian"**: since there's no status/ping endpoint for these providers, health is *inferred* from delivery rhythm — proactive renewal against known expiry, plus a much-less-frequent fallback poll (daily default, file 01 already specifies this) whose only job is catching the rare silent-failure case a healthy webhook should have already reported. Distinct from Watchdog (file 01 #18), which proves *this program's own* processes are alive — Circadian is about a third party's delivery health, a genuinely different kind of liveness signal.
- **Provider-agnostic by design**: the same subscription/renewal/circadian machinery handles any future push-capable source (OneDrive/Microsoft Graph, etc.) via a different provider adapter — nothing here is Drive-specific except the actual API calls inside each provider's own adapter module.
- **Drive's empty-body callback quirk**: Drive's webhook POST carries no payload, just a signal that something changed — the handler's job on receipt is exactly one follow-up `changes.list` call to find out what, then emit a "new file available" event per changed item for Execution Core to consume. Execution Core owns batching/coalescing those events into an actual run (file 03's debounce-with-max-wait design) — this sub-API never decides run boundaries, only reports raw change events.

### 4.2 Direct upload
The simplest source mechanically — no push/poll uncertainty, no third-party reliability question. Gateway (file 01 #16) authenticates the browser's POST via session cookie, forwards over internal gRPC to Ingestion, which routes it through Content Security before hashing/storing and emitting a trigger event. The upload arriving *is* the trigger — no debounce window needed for a single direct upload the way Drive's batch-oriented triggering needs one, though a rapid burst of several direct uploads in a short window still benefits from Execution Core's existing coalescing logic to avoid opening a new run per file.

### 4.3 In-browser scanner

#### 4.3.1 Client-side detection and single-photo correction — resolves this API's own boundary with Preprocessing
**The scanner's live corner-detection and perspective-correction step runs entirely client-side, in the browser, via `opencv.js`** (the WASM build of OpenCV) — not server-side, and not deferred to Preprocessing. This is a deliberate, now-resolved answer to a boundary question the earlier deep-dive discussion left open ("does perspective correction belong to Ingestion or Preprocessing, since it affects OCR quality too"): it belongs to Ingestion, and the reasoning is about *when* it happens, not just *what* it does — this step is about producing one well-framed, rectangular base image from a live camera feed *before a file exists at all*, structurally the same role as Format Normalization's PDF rasterization (§5.1) — turning a raw capture into the one finished image Preprocessing will later generate OCR-variants *from*. Preprocessing's own scope (its §1) already starts from "a single already-selected image"; the scanner's job is producing that image in the first place, not enhancing an existing one for OCR.

Concretely, the established current technique (confirmed via real, current tooling, not assumed): `cv.cvtColor` → `cv.GaussianBlur` → `cv.Canny`/adaptive threshold → `cv.findContours`, picking the largest plausible document-shaped quadrilateral, then `cv.warpPerspective` with a computed homography to flatten the detected quad into a rectangular image — entirely in-browser, zero server round-trip for the detection/correction step itself. A lightweight wrapper library (`jscanify`, built directly on `opencv.js`) provides `highlightPaper()`/`extractPaper()` convenience over this same pipeline and is a reasonable starting point rather than hand-rolling the contour math from scratch — worth evaluating directly against a hand-rolled version using the OCR API's Preprocessing findings as a quality bar, not assumed sufficient without checking. The live camera path uses `navigator.mediaDevices.getUserMedia()` streaming frames to a canvas, with `highlightPaper()`-equivalent detection running on an interval to show the user a live boundary overlay before they confirm capture — giving the user a chance to adjust framing or manually correct detected corners before committing, rather than a single blind auto-capture.

#### 4.3.2 Panorama/stitching mode — deliberately server-side, a different reliability profile than single-photo capture
Multi-frame stitching for a long receipt is a heavier, more failure-prone operation than single-frame perspective correction — feature matching and blending across several frames is meaningfully more compute, and WASM performance plus mobile battery/thermal constraints make it a worse fit for the browser than the lightweight single-frame case. **Decision: the client captures and uploads the individual raw frames (each with light client-side edge-preview for capture-time framing feedback, but not final-quality perspective correction per frame), and the actual stitching happens server-side** in Ingestion's own pipeline using native OpenCV's `cv2.Stitcher` — the full desktop/server build, not the WASM one, giving access to more robust feature-matching/blending than a browser build would reasonably carry. This also gives a real retry/fallback story a client-side failure wouldn't: if `cv2.Stitcher` reports a failure (not enough overlap, a bad match), the server can request the client re-capture a specific frame rather than stranding the user in a broken client-side state with no way to recover except starting over.
```python
# sources/scanner/stitcher.py — sketch
def stitch_panorama(frames: list[np.ndarray]) -> StitchResult:
    stitcher = cv2.Stitcher.create(cv2.Stitcher_PANORAMA)
    status, result = stitcher.stitch(frames)
    if status != cv2.Stitcher_OK:
        return StitchResult(image=None, error=StitchError(status))
    return StitchResult(image=result, error=None)
```
`cv2.Stitcher`'s status codes distinguish real failure reasons (`ERR_NEED_MORE_IMGS`, `ERR_HOMOGRAPHY_EST_FAIL`, `ERR_CAMERA_PARAMS_ADJUST_FAIL`) — worth surfacing the specific reason to the client rather than a flat "stitching failed," since "need more images" and "bad match, retake this section" call for different user-facing guidance.

---

## 5. Format Normalization
**Extracted to its own dedicated document, `v3-deepdive-42-format-normalization.md`** — corrected out of this section after a corpus-wide sweep found file 01 had mislabeled it "sub-capability" when it has its own real package path and depth comparable to Historian or Reimport. Covers: PDF rasterization, image format coverage (Pillow's native AVIF, `pillow-heif` for HEIC), the single owner-selected archival codec and hash-on-original-bytes scheme, and zip/bulk-upload handling including the 3.16 selective-remediation capability.

---

## 6. Content Security integration

Every `SourceFile`, regardless of which source produced it, is scanned by the Content Security API before Format Normalization touches it — real file-type verification via magic bytes (never the extension or client-supplied MIME type), malware/exploit scanning, polyglot detection. Ingestion is a caller of this API, not an implementer of any scanning logic — `content_security_client.py` is a thin gRPC client, deliberately with no local fallback/bypass path even under Content Security being briefly unavailable (fail closed, not open, for this specific check — a file that can't be verified safe doesn't get processed just because the verifier was slow to respond). Full design of Content Security's own scanning logic is out of scope for this document — see its own future deep-dive.

---

## 7. Asyncio, free-threading, and profiling

### 7.1 Where asyncio is load-bearing
Every source is fundamentally I/O-bound — Drive API calls, direct-upload stream handling, webhook callback processing — genuinely the "Async I/O" bucket from file 02's concurrency model, not the "Native/GIL-released" bucket OCR's local engines or Preprocessing's OpenCV work fall into. `source_registry.py`'s fan-out across enabled sources and the Webhook Subscription Manager's renewal/circadian logic are both naturally `async`/`await` all the way down — there's no blocking native call anywhere in this API's own hot path needing the `run_in_executor` pattern the prior three deep-dives leaned on repeatedly. The one exception is `cv2.Stitcher.stitch()` (§4.3.2) — a genuinely blocking, CPU-bound native call, dispatched via `run_in_executor` exactly like every other blocking-native-call case in this project's design, the fourth instance of the same pattern.

### 7.2 Free-threading — narrow relevance, same as Preprocessing's own conclusion
Since this API's actual work is I/O-bound, not compute-bound, free-threading's per-op GIL-release story doesn't move the needle here the way it might for a compute-heavy API — there's little pure-Python CPU-bound work in this API's own scope to begin with. The one native-code dependency worth tracking for free-threading compatibility is `PyMuPDF`, plus `pillow-heif` (already confirmed to have declared free-threading support in a recent release — a genuinely different, better starting position than `opencv-python`'s still-unresolved free-threaded-wheel blocker, worth noting as a positive data point rather than assuming every dependency is in the same boat). **Telemetrees ownership, consistent with the prior three deep-dives**: track `pymupdf` and `pillow-heif`'s free-threading status as Dependencies Warden entries (file 02 rule #8), not asserted as a fixed fact here.

### 7.3 Profiling
Given this API's I/O-bound shape, `py-spy`'s GIL-holding diagnostics are less central here than for OCR/Inference/Preprocessing — the more relevant profiling question for Ingestion is request latency and queue depth on the async paths (Drive API round-trip time, webhook processing time), which is Health API's live-diagnostic territory (file 01 #18) more than a bench-suite CPU-profiling concern. `cv2.Stitcher`'s blocking call is the one place `py-spy`/Tachyon's usual role applies the same way it did in the other three deep-dives — confirming the `run_in_executor` dispatch actually keeps the event loop free during a stitch operation.

---

## 8. gRPC surface (`.proto` sketch)

```protobuf
service IngestionService {
  rpc SubmitDirectUpload(DirectUploadRequest) returns (NormalizationResponse);
  rpc StartScanSession(StartScanRequest) returns (ScanSessionResponse);
  rpc SubmitScanFrame(ScanFrameRequest) returns (ScanFrameResponse);       // one per captured frame in panorama mode
  rpc FinalizeScanSession(FinalizeScanRequest) returns (NormalizationResponse);  // triggers stitching if >1 frame
  rpc ListEnabledSources(ListSourcesRequest) returns (ListSourcesResponse); // for Interface API's settings menu — reflects actual owner-enabled state
  rpc HandleDriveWebhook(DriveWebhookPayload) returns (WebhookAck);         // internal, called by Gateway on callback receipt
}

message NormalizationResponse {
  repeated NormalizedImage images = 1;
  string archival_blob_ref = 2;
  string error_code = 3;
  string error_detail = 4;
}

message NormalizedImage {
  string image_blob_ref = 1;
  int32 page_index = 2;
  string source = 3;
  string error_code = 4;
  string error_detail = 5;
}
```
Direct upload and scanner finalization both return a `NormalizationResponse` synchronously (fast enough not to need streaming); scan-session frame submission is its own call per frame since a panorama capture is inherently multi-step and the client needs per-frame confirmation (detected/accepted vs. retake) before moving on, not a single batch call at the end.

---

## 9. Config surface

```
ingestion:
  sources_enabled: [direct_upload, google_drive]     # global, install-wide today — see §1 for the planned per-tier resolution path once Architect/Billing's tier-profile mechanism exists; scanner opt-in
  google_drive:
    credential_strategy: service_account               # service_account | oauth — oauth inactive until Google verification clears
    fallback_poll_interval: daily
    webhook_renewal_lead_time_hours: 24
  scanner:
    stitching_backend: server                           # only option today — see §4.3.2
  format_normalization:
    archival_codec: avif                                 # avif | webp — single owner-level choice, see Format Normalization deep-dive §3
    archival_quality: 75
  content_security:
    fail_mode: closed                                    # never configurable to "open" — see §6
```

---

## 10. Testing hooks

- `tests/unit/core/ingestion/` — each source mocked at its own external-call boundary (Drive API client, Gateway's upload stream, the scanner's frame-submission contract) so the suite runs without live credentials or a real camera.
- **Credential-strategy swap test**: a regression test that stands up `GoogleDriveSource` against both `ServiceAccountCredentialProvider` and `OAuthCredentialProvider` mocked identically, confirming the source genuinely doesn't care which one it's handed — the concrete way to keep the "swappable, not hardcoded" requirement (§4.1.1) honest over time rather than just asserted in prose.
- **Stitching failure-mode bench case**: real test image sets engineered to trigger each of `cv2.Stitcher`'s distinct failure codes, confirming each produces the right specific user-facing guidance (§4.3.2) rather than a flat failure message.
- **Format-decoding fuzz/security regression**: given Format Normalization's own deep-dive §4.2 explicit CVE history in `pillow-heif`, a standing fuzz-test pass (malformed/truncated HEIC, AVIF, PDF inputs) feeding Content Security + Format Normalization together, not just a unit test of the happy path.
- Failure-injection mode: a bench case simulating a Drive webhook silently dying without notice, confirming Webhook Circadian's fallback poll actually catches the resulting missed file within its configured interval — direct validation of §4.1.3's core reliability claim, not just trusting the design reasoning.

---

## 11. Open questions for this deep-dive (logged, not guessed at)

- **`jscanify` vs. a hand-rolled `opencv.js` contour/perspective pipeline** (§4.3.1): `jscanify` ships as the default — reasonable starting point, genuinely not yet confirmed sufficient against unevenly-lit, non-white-background real receipts. A real quality comparison stays a pre-launch bench task, not a design gap; if it underperforms, the swap is cheap given this already sits behind its own module boundary.
- (Live per-frame quality gating during panorama capture — resolved: **not in the initial release.** Real client-side complexity for a UX improvement over an already-working fallback (a full server-side stitch failure with retry) — worth revisiting once real usage data shows retry frequency is actually a problem worth solving, not built speculatively now.)
- (OAuth activation readiness check — resolved, owner assigned: **Telemetrees.** This is exactly the shape of "confirm a currently-gated capability still actually works before the day it's switched on" that Telemetrees' own continuous tracking discipline already exists for — a periodic check added to its own tracked-fact inventory, not a new mechanism.)
- **Whether email-in is ever a real future source** — explicitly deferred, a placeholder for future demand, not a commitment either way; not blocking.
- **Per-tier source availability** (§1, §9): still genuinely blocked on real dependencies, not a design gap — the shape is prepared for (`SourceRegistry.enabled_sources()` already takes a `user_id`/`run_id` context) but needs Architect's own tier-profile-definition registry to exist first. Worth noting Billing's own side of this dependency is now resolved (billing off by default, tiers only meaningful once an owner opts in, `v3-deepdive-22-billing-subscription-api.md` §3.1) — the remaining blocker is specifically Architect's tier-profile registry, not the whole dependency chain.
