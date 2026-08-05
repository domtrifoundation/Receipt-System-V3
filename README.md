# DOMTRI / Resibo (V3)

A receipt-processing system for Philippine businesses: take a photo or upload a receipt,
and it reads it with multiple OCR engines in parallel, cross-checks the reading against
itself and a learned vendor directory, and turns it into clean, BIR-relevant records —
without you typing anything in by hand.

**Status: pre-release, in active development.** This is the third generation of the
program (V1 was a Claude skill driving Excel, V2 a single-process Python program). There
is no tagged public release yet — the first one will be `x03.00.00` ("Zircon"). Until
then, this repository is a real, working codebase under construction, not a finished
product.

---

## Getting started

**Cloning this repository will not give you a working install.** `git clone` gets you the
source code, not a runnable installation — there's no top-level config, database, or
first-run setup produced by a bare clone. Once `x03.00.00` ships, this repo's GitHub
Releases page will carry a real installer for each supported OS; run that, not `git
clone`, to get a working instance.

**Right now, before that first release, the only way to run this is the developer path:**
see [`docs/MAINTENANCE.md` §5](docs/MAINTENANCE.md#5-developer-mode) for the exact,
step-by-step setup — download a release archive, run the developer-mode setup script, and
it builds a real working top-level install (config, database, first-run wizard, hardware
detection) around a proper clone. An AI developer operating unattended, with no human in
the loop, follows the same steps — see `docs/MAINTENANCE.md`'s "AI-developer installs"
note for how that path gets MCP access automatically.

---

## What this actually does, today

This project is organized as one small, independent process per capability ("Core API"),
talking to each other only over internal gRPC — never one big monolith. Here's what's
real and implemented as of this snapshot, not the full long-term plan:

**The processing pipeline**: Ingestion (pulling receipts in from upload, camera capture,
or a watched Google Drive folder) → Content Security (scanning untrusted files before
anything touches them) → Preprocessing (image cleanup) → OCR (several engines running in
parallel, corroborated against each other) → Matching (fuzzy vendor/address/TIN lookups
against a learned directory) → Inference (an LLM pass that parses and corroborates the
result) → Reconciliation (propagating corrections back through the record) →
Persistence (the one place that actually touches disk — SQLite plus a blob store).

**Everything around that pipeline**: Auth & Tenancy (SSO/OIDC, sessions, roles,
single-user or multi-tenant), Groups (pooling receipts under a team), Accounting Sync
(pushing clean records straight into QuickBooks/Xero), Billing (subscription tiers over a
swappable payment processor), Notifications, Support Ticketing, Task Scheduler,
Review/Flagging (a real human-review queue for anything uncertain), Search/Query,
Geo/Address (address geocoding and cross-checking), Architect (the taxonomy/vendor
directory itself, with temporal learning), Migration (schema versioning), Audit and Logs
(a tamper-evident trail and a separate operational trace), Health (live diagnostics and
resource tracking), Telemetrees (dependency-update monitoring), Account Guardian (a real
privacy/security center for end users), and Agent Control (a genuine MCP server and
headless interface, so an AI agent can operate a running instance the same way a human
would through the TUI).

**Deployment infrastructure**: Update API (no-downtime, health-gated release channels —
LTSC/Stable/Beta/Alpha/Latest-Commit can all run concurrently), Proving Grounds (real
candidate-build testing before a version gets promoted), and Supervisor (the process that
actually boots the whole fleet in dependency order, health-gates it, and can roll back,
sleep idle services, and restart individual ones).

**The TUI** (Textual, an admin/status console — not a web page): the menu system, the
real boot-sequence loading screen, the credits/license screen, and a full working
first-run setup wizard screen are built and tested. Several planned screens (Fleet &
Updates, Run Monitor, the vendor/branch editor, Groups management, the staff audit queue)
are named but not yet built — selecting one in the running TUI says so plainly rather
than pretending. The end-user webapp hasn't been started yet.

For the complete, current, evolving state of what's built versus not — package by
package — see each API's own `CLAUDE.md` (e.g. [`core/ocr/CLAUDE.md`](core/ocr/CLAUDE.md),
[`supervisor/CLAUDE.md`](supervisor/CLAUDE.md)) rather than this file, which describes a
snapshot and will drift.

---

## License

Proprietary and confidential to DOMTRI Foundation — see [`LICENSE`](LICENSE). Not open
source.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a PR — it links to the right
template for whatever you're adding and the full design-principles document.

## Documentation

The full documentation set starts at [`docs/index.md`](docs/index.md).
