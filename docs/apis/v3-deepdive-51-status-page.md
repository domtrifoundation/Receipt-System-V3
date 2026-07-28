# V3 Deep Dive: Status Page API

**Companion files:** `v3-deepdive-20-health-api.md` (the diagnostic data this API republishes publicly, in summarized form), `v3-deepdive-14-interface-api.md` §3.3 (the internal Fleet screen this is explicitly *not* — different audience, different data resolution).

**Status:** New Core API (#30), surfaced as a genuine blind spot during a corpus-wide sweep — never mentioned anywhere in this project's prior planning.

---

## 1. Scope & boundary

Status Page owns a public, unauthenticated page showing the hosted service's own uptime and incident history — for DOMTRI's hosted multi-tenant service specifically; a self-hosted install has no public audience to show this to and doesn't run this API at all (the same "doesn't apply to self-hosted, skip it" pattern Gateway itself already established for a different reason, `v3-deepdive-19-gateway-api.md` §1). It does not:
- **expose anything Health API's own live-diagnostic layer wouldn't already share internally** — this is a *public, summarized* republishing of a subset of already-existing health signals, never a second, independent monitoring system with its own opinion about what's healthy.
- **replace the internal Fleet screen** — Fleet (`v3-deepdive-14-interface-api.md` §3.3) is owner/staff-facing, per-service, real-time, and detailed; this is public-facing, aggregated, and deliberately coarse (a customer doesn't need or want to know which of 28 internal services is degraded, only whether *the product* is working).
- **auto-detect and publish incidents** — an incident entry is a deliberate, staff-authored action (§4), never an automatic consequence of a health check flipping red, since a transient blip that self-resolves in ten seconds shouldn't become a public incident record just because it crossed a threshold for a moment.

---

## 2. Package layout

```
services/status_page/
  __init__.py
  app.py                    # a genuinely separate, minimal web app — see §3
  contracts.py                 # Incident, ComponentStatus, error types
  aggregator.py                    # summarizes Health API's own signal into public-facing component groups
  incidents.py                       # staff-authored incident CRUD
  errors.py
```

---

## 3. Why this is its own small app, not a webapp screen or a Gateway route
**Deliberately not part of the main webapp** (`v3-deepdive-44-webapp.md`) — a status page needs to stay reachable *even when the main product is having problems*, which argues for genuine infrastructure independence: its own minimal process, its own (separate, cheap) hosting path, no dependency on the same database/gRPC core being healthy to render at all. Concretely: `aggregator.py` polls Health API's own diagnostic layer on an interval and caches the result locally (`incidents.py`'s own small SQLite table, independent of Persistence's own per-user databases) — if the core gRPC fleet is genuinely down, the status page still renders its own last-known state plus any manually-authored incident, rather than itself becoming unreachable at the exact moment someone most wants to check it.

---

## 4. Incidents — staff-authored, never automatic
```python
@dataclass(frozen=True)
class Incident:
    incident_id: str
    title: str
    status: Literal["investigating", "identified", "monitoring", "resolved"]
    affected_components: tuple[str, ...]      # coarse groups (e.g. "Receipt Processing", "Webapp") — never internal API names
    updates: tuple[IncidentUpdate, ...]
    created_by: str                             # staff user_id
    created_at: datetime

@dataclass(frozen=True)
class IncidentUpdate:
    message: str
    status: Literal["investigating", "identified", "monitoring", "resolved"]
    posted_at: datetime
```
A staff member creates and updates an incident manually (via a small admin surface — a Fleet screen extension, not a separate TUI screen given the low frequency of this action) — never generated automatically from a health-check flip. **`affected_components` uses coarse, customer-meaningful groups, never raw internal API names** — "Receipt Processing" or "Webapp," never "OCR API" or "Preprocessing API" — consistent with this document's own stated boundary against leaking internal architecture to a public audience.

---

## 5. Component status — aggregated, not per-API
```python
@dataclass(frozen=True)
class ComponentStatus:
    component_name: str          # "Receipt Processing", "Webapp", "Email Notifications" — coarse groups
    status: Literal["operational", "degraded", "outage"]
```
`aggregator.py` maps many internal services to few public components — "Receipt Processing" reflects the worst status among OCR/Preprocessing/Inference/Matching/Execution Core combined, not five separate rows a customer has no reason to parse individually.

---

## 6. Asyncio, free-threading, and profiling
A small FastAPI app (the same async-native shape Gateway's own deep-dive already established for this pattern, `v3-deepdive-19-gateway-api.md` §8) polling Health API on an interval and serving a handful of static-ish routes — genuinely I/O-bound, no compute-bound work of any kind. **Forward-compatibility check, explicit rather than assumed**: no new dependency beyond what Gateway's own stack already uses (FastAPI, already-tracked); nothing here needs its own new Telemetrees entry.

---

## 7. gRPC surface
Not applicable in the usual sense — this is a small standalone web app serving public HTTP routes (`/status`, `/api/v1/status.json` for programmatic checks), not a gRPC service other Core APIs call into. It's a *client* of Health API's own gRPC surface (polling `GetStatus`, `v3-deepdive-20-health-api.md` §8), the same client relationship Gateway has with the rest of the fleet.

---

## 8. Config

```
status_page:
  poll_interval_seconds: 60
  component_mapping:
    receipt_processing: [ocr, preprocessing, inference, matching, execution_core]
    webapp: [gateway, tunnel_exposure]
```

---

## 9. Testing hooks
- **Independence-under-outage test**: confirms the status page still renders its own last-known state when the core gRPC fleet is genuinely unreachable — the concrete validation of §3's entire reason for existing as a separate process.
- **No-internal-name-leak test**: a static check confirming no `ComponentStatus`/`Incident` ever surfaces a raw internal API name — direct enforcement of §4/§5's stated boundary.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- **Hosting/infrastructure independence in practice, resolved: a static-site-plus-tiny-API split.** A simple static HTML/CSS page for the actual status display, backed by a small separate API endpoint serving the aggregator's own data — genuinely simple and cheap, achieves real independence from the core fleet without needing a whole separate VM or duplicate infrastructure stack.
- **Historical uptime percentage calculation, resolved: yes, a rolling 90-day percentage.** A standard, expected status-page convention, and low-cost to compute given the aggregator already retains the historical data needed — no reason to omit it.
- **Subscriber notifications, resolved: yes, email on incident updates.** The more commonly-used and expected mechanism compared to RSS, which stays a real but lower-priority future addition rather than launch-blocking scope.
