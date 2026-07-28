# V3 Deep Dive: Content Security API

**Companion files:** `v3-deepdive-04-ingestion-api.md` §6 (the primary caller), `v3-deepdive-13-persistence-api.md` §6 (Reimport's own uploads share this same scanning), `v3-deepdive-08-audit-event-log-api.md` (staff-confirmed malicious verdicts get audit-logged there).

**Status:** Twenty-seventh deep-dive session. Genuinely central to this project's security posture — every untrusted file entering the system passes through here exactly once, in one shared place, regardless of which channel it arrived through.

---

## 1. Scope & boundary

Content Security owns **scanning every untrusted incoming file** — real file-type verification (magic bytes, never trusting an extension or client-supplied MIME type), malware/exploit scanning, polyglot detection, and container-level bomb checks for archives. It does not:
- **decide what happens after a rejection** — flagging, notifying, and any staff review of a rejected file are Review/Flagging's and Notifications' own jobs; this API's contract is a pass/fail verdict plus detail, not a downstream workflow.
- **get bypassed or reimplemented per-caller** — Ingestion calls it (its deep-dive §6, explicitly fail-closed with no local bypass path), and Persistence's Reimport calls the exact same shared logic for its own uploads (file 01) rather than either API rolling its own scanning.

---

## 2. Package layout

```
core/content_security/
  __init__.py
  contracts.py            # ScanRequest, ScanVerdict, error types
  scanning/
    __init__.py
    magic_bytes.py             # real file-type detection
    polyglot_detection.py        # a file valid as two different formats simultaneously
    bomb_check.py                  # container-level (zip) — see §3
  providers/
    __init__.py
    base.py                          # MalwareScanProvider protocol — Provider Registry, docs/PRINCIPLES.md §1.2
    clamav_provider.py                  # local subprocess scanner, the default
    virustotal_provider.py                # cloud multi-engine alternative, §9's own resolution
  errors.py
  metrics.py
```
**Corrected during a principles-compliance audit**: an earlier version of this layout had malware scanning as a single `malware_scan.py` module, despite §5.1 and §9 both describing ClamAV and a cloud scanner as genuinely swappable alternatives — a real `docs/PRINCIPLES.md` §1.2/§1.3 violation (the Provider Registry pattern is mandatory for any swappable capability, "at every granularity"), not a stylistic preference. Now a real provider folder with a real Protocol:
```python
class MalwareScanProvider(Protocol):
    async def scan(self, blob_ref: str) -> ScanVerdict: ...
    async def is_available(self) -> bool: ...      # graceful degradation, §4.4 — a missing ClamAV binary or an unreachable cloud API degrades cleanly rather than failing the whole pipeline
```
Multiple providers can run simultaneously and be cross-checked, exactly as OCR's own engines do — which is what makes §9's own "auto-reject only on unanimous agreement, disagreement routes to staff review" resolution structurally possible rather than aspirational.

---

## 3. Two-pass scanning for containers — a bomb-free container can still hold one bad file
Already specified in the Ingestion deep-dive's own Format Normalization section (§5.4 there) and restated here as the authoritative owner: zip/archive inputs get a **container-level check first** (`infolist()` metadata — compression ratio, cumulative uncompressed total, entry count, nesting depth — before any extraction happens at all), then **every individual file extracted from a cleared container gets its own full scan** — the container passing its own bomb check says nothing about whether an individual extracted file is safe.

### 3.1 Selective remediation via Python 3.16's `zipfile.remove()`/`repack()` — feature-detected, not version-gated
File 02's own Forward-Compatibility Pattern applies directly here: Python 3.16 (currently alpha) adds `zipfile.ZipFile.remove()` and `.repack()`, letting a clean archive containing one bomb-prone or malicious member have *just that member* stripped and the rest safely extracted, rather than rejecting the whole container over one bad entry. Implemented now, gated by `hasattr(zipfile.ZipFile, 'remove')` — not a `sys.version_info` check, since a still-alpha API can shift shape before its stable release, and a hard version check would need updating if that happens where a feature-detection check just naturally stops matching and falls through. **Safe to build against today specifically because the fallback path is already correct, not a placeholder**: where the capability isn't available, the existing safe default applies — reject the whole archive, exactly as if this feature didn't exist yet.
```python
def remediate_or_reject(zf: zipfile.ZipFile, bad_members: list[str]) -> RemediationResult:
    if hasattr(zipfile.ZipFile, "remove"):
        for name in bad_members:
            zf.remove(name)
        zf.repack()
        return RemediationResult(action="stripped_and_extracted", removed=bad_members)
    return RemediationResult(action="rejected_whole_archive", removed=[])
```

---

## 4. Fail-closed, always — the one hard rule every caller inherits
```python
async def scan(request: ScanRequest) -> ScanVerdict:
    """If this call fails, times out, or this service is briefly
    unavailable, the correct behavior for EVERY caller is to treat the
    file as unscanned and therefore unsafe — never a silent bypass.
    Ingestion's own deep-dive already states this explicitly for its
    own call site; stated here as this API's own contract guarantee,
    not just a caller-side convention that could be forgotten by a
    future integration."""
```
Worth being precise about why this belongs here as a contract-level guarantee rather than trusted to every caller independently: a security check that *can* be silently skipped under some failure condition is, for practical purposes, not really a security check — the guarantee needs to live where it can't be accidentally weakened by a caller's own error-handling choices.

---

## 5. Malicious-content resolution — surfaced through Review/Flagging, audited through Audit
A confirmed-malicious verdict (either automated or staff-confirmed after review) surfaces as a Review/Flagging flag (the `malicious/unsafe content detected` type, already named in file 01's flag taxonomy) and, once staff confirm it, an Audit event (`CONTENT_CONFIRMED_MALICIOUS`, Audit deep-dive §4) — this API produces the verdict, it doesn't own either downstream mechanism.

### 5.1 Malware-scanning backend — ClamAV as the local default, already named in file 02's own concurrency classification
File 02's Concurrency Model table already gives this API's concrete shape rather than leaving it a blank slate: **local scanning via a ClamAV subprocess call (native/GIL-released) as the default**, with a cloud-scanner API as a swappable alternative (async, network-bound) behind the same `PaymentProvider`-style adapter pattern used throughout this project — file-signature checking itself is fast pure-Python, the actual malware scan is either a native subprocess call or a network call depending on which provider is configured, never both at once for a single scan. `pip install pyclamd` (or shelling out to `clamscan` directly) is the concrete integration point for the local path; `clamd`'s own daemon process needs to be running and its virus-definition database kept current — worth a Telemetrees-tracked freshness check on the definitions themselves, not just the package version, since a stale ClamAV database is a real, silent security gap distinct from the package being outdated.

---

## 6. Asyncio and profiling
Scanning is a mix of CPU-bound work (magic-byte/polyglot detection on file bytes already in memory) and potentially I/O if any scan step calls out to an external malware-detection service — worth classifying per actual scan step rather than assuming one shape for the whole API, the same per-worker classification principle Background Workers' own deep-dive establishes generically (§3 there), applied here to this API's own internal scan pipeline stages.

---

## 7. gRPC surface

```protobuf
service ContentSecurityService {
  rpc ScanFile(ScanRequest) returns (ScanVerdict);
  rpc ScanContainer(ContainerScanRequest) returns (ContainerScanVerdict);
}

message ScanVerdict {
  bool safe = 1;
  string detected_type = 2;     // the REAL file type, from magic bytes — may differ from what the client claimed
  string rejection_reason = 3;
  bool requires_staff_review = 4;
}
```

---

## 8. Testing hooks
- **Fail-closed test**: a simulated Content Security outage during an Ingestion upload attempt confirms the file is rejected/held, never silently passed through — direct validation of §4's core guarantee.
- **Polyglot detection test**: a file crafted to be valid as two different formats simultaneously (a classic real attack technique) is correctly flagged, not passed based on only checking the first plausible format match.
- **Container two-pass test**: a zip containing one malicious file among otherwise-clean ones is caught by the per-file pass even though the container itself passes its own bomb check.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Cloud-scanner alternative provider, resolved: VirusTotal.** A well-established, genuinely multi-engine scanning API with a real free tier, the same "widely-used, well-documented, low-risk implementation choice" reasoning behind other similar picks in this project (`py_webauthn`, `mediagis/nominatim`) — a defensible default, not a coin flip.
- **Staff-review threshold, resolved with a concrete rule.** Auto-reject outright only when every enabled scanner agrees on a malicious verdict; any disagreement between scanners, or a single scanner's own low-confidence/borderline result, routes to `requires_staff_review` rather than either extreme (auto-rejecting on ambiguous signal, or auto-accepting anything short of full consensus) — the same "surface a discrepancy, don't unilaterally resolve it" discipline every other corroboration-shaped check in this project follows.
- (ClamAV definition-freshness monitoring — resolved, no longer open. Already a real, connected Telemetrees tracked-fact entry, `v3-deepdive-28-telemetrees-api.md` §3.1 — this wasn't actually missing, just needed this cross-reference confirmed rather than left flagged as a follow-up.)
