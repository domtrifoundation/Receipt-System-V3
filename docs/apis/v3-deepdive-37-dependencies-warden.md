# V3 Deep Dive: Dependencies Warden (Telemetrees API sub-API)

**Parent API:** `v3-deepdive-28-telemetrees-api.md` §3. **Companion files:** `v3-deepdive-36-proving-grounds.md` (the execution consumer of what this API flags).

**Status:** Sub-API deep-dive, full treatment — expanding the tracked-fact-kind design already established in Telemetrees' own document into the actual monitoring mechanism.

---

## 1. Scope & boundary

Dependencies Warden owns **continuous, automated monitoring** of every tracked dependency's release activity and other tracked facts (free-threading support flags, specific upstream issue states, model/preset currency — the full taxonomy Telemetrees' own deep-dive §3 established). It does not:
- **decide whether to adopt what it finds** — surfaces "this exists now" to developers; Proving Grounds actually tests a flagged candidate, a human judgment call decides what's worth testing at all (file 02 rule #8's own explicit statement).
- **poll uniformly** — different tracked-fact kinds need different polling mechanisms (a PyPI release feed vs. a specific GitHub issue's state), already designed as distinct in the parent document.

---

## 2. Package layout

```
core/telemetrees/dependencies_warden/
  __init__.py
  contracts.py             # TrackedDependency, TrackedFact, ReleaseEvent (re-exported from parent)
  pollers/
    __init__.py
    pypi_poller.py             # release_version fact kind
    github_issue_poller.py       # upstream_issue_status fact kind
    free_threading_poller.py       # free_threading_support fact kind — see §3
  surfacing.py                # changelog_surface, see §4
  errors.py
```

---

## 3. Per-fact-kind polling mechanisms
```python
class PyPIPoller:
    async def poll(self, dep_name: str) -> ReleaseEvent | None:
        """Standard PyPI JSON API release-feed check — stable and
        pre-release (beta/alpha/RC) versions both, per file 02's own
        day-0 dependency support rule, not just stable releases."""

class GitHubIssuePoller:
    async def poll(self, issue_ref: str) -> IssueStateEvent | None:
        """Checks one specific issue's open/closed state via GitHub's
        API — e.g. opencv/opencv#27933 (Preprocessing deep-dive §8.2's
        free-threaded-wheel blocker). A version-release poller alone
        would never surface this fact, since it lives on an issue
        thread, not a changelog."""

class FreeThreadingPoller:
    async def poll(self, dep_name: str) -> FreeThreadingStatusEvent | None:
        """Checks a dependency's own declared free-threading support —
        via its PyPI classifiers (a real, standardized signal: the
        'Programming Language :: Python :: Free Threading' trove
        classifier), its own changelog/release notes, or a maintained
        community compatibility tracker as a cross-check — not a single
        source assumed always current or authoritative on its own."""
```

---

## 4. Surfacing — where the point of tracking actually lands
```python
async def update_changelog_surface() -> None:
    """Regenerates a checked-in summary file (Telemetrees' own
    deep-dive §4's reasoned direction) whenever any tracked fact
    changes — the natural integration point for this project's
    LLM-assisted development model specifically, since a Claude Code
    session picks up 'here's what changed since you last worked on
    this' from its own repo context rather than needing a separate
    dashboard a human has to remember to check."""
```
Every fact-kind change (a new release, a flipped free-threading flag, a closed tracked issue) triggers a regeneration — not a periodic full rebuild, so the surface stays current within one poll cycle of an actual change, not just eventually.

---

## 5. Asyncio
Every poller is network I/O against an external API (PyPI, GitHub) — genuinely async, no compute-bound work of its own, consistent with the parent document's own conclusion.

---

## 6. gRPC surface
Doesn't expose its own top-level service — queried through Telemetrees' own `GetTrackedDependencies`/`GetChangelog` RPCs (parent deep-dive §6), consistent with being a sub-API, not a peer with its own client surface.

---

## 7. Config

```
dependencies_warden:
  poll_interval_hours: 24
  # per-dependency fact_kinds config lives in the parent Telemetrees
  # document's own config block (§7 there) — not duplicated here
```

---

## 8. Testing hooks
- **Multi-poller coverage test**: confirms every dependency in Telemetrees' own §3.1 inventory has a poller actually registered for each of its declared `fact_kinds`, not silently falling back to release-version-only monitoring for something that needed a different fact kind — the concrete enforcement mechanism keeping this registry honest over time, same principle as the parent document's own testing hooks.
- **Free-threading classifier detection test**: confirms the `FreeThreadingPoller` correctly reads the PyPI trove classifier where present, not just guessing from changelog text alone.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Community compatibility tracker choice, resolved: `py-free-threading.github.io`.** The real, well-established community tracker as of this writing — confirmed current via direct research, not assumed from memory, cross-referenced by CPython's own official free-threading documentation and multiple independent sources throughout 2026. The right secondary signal to trust for `FreeThreadingPoller`'s own cross-check.
