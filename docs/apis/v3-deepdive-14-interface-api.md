# V3 Deep Dive: Interface API / Control Panel

**Companion files:** all prior deep-dives — this is the API every other one's gRPC contract ultimately surfaces through, for a human.

**Status:** Fourteenth deep-dive session. Real V2 lineage for the menu-data pattern and the `find_setting` fuzzy-search tool (both genuinely good V2 designs, worth carrying forward as techniques); the webapp framework choice was explicitly left open in file 01 — resolved here.

---

## 1. Scope & boundary

Interface API is two distinct surfaces sharing one gRPC-client relationship with the core: the **TUI** (Textual, admin/status console for the always-on server — config, health, run monitoring, owner/staff use) and the **webapp** (end-user surface — upload, view/manage own receipts, reachable via Cloudflare Tunnel through Gateway). Both are genuinely detachable clients, not part of the main process — a concrete instance of `docs/PRINCIPLES.md` §1.7's process-separation-via-gRPC principle, worth keeping in mind for every section below: nothing this API owns should ever become something a Core API's own correct functioning depends on. It does not:
- **contain business logic** — every screen/action is a thin renderer over a gRPC call to the actual owning API; a settings screen doesn't validate a setting's own business rules, it just calls whatever API owns that config and displays the result.
- **own theming/i18n as separate sub-APIs** — both are cross-cutting concerns structured within this API itself (file 01), not their own package elsewhere.

---

## 2. Package layout

```
services/interface/
  __init__.py
  tui/
    __init__.py
    menu_data/                  # declarative menu trees — see §3
      __init__.py
      root.py
      settings.py
      geo_tools.py
    menu_screen.py                # the single generic MenuScreen renderer
    custom_screens/                # the enumerated exception list — see §3.2
      run_monitor.py
      ocr_diff_viewer.py
      vendor_branch_editor.py
      staff_audit_queue.py
      fleet_screen.py
      boot_sequence.py
      credits.py
    theme.py
    i18n.py
  webapp/                       # React + TypeScript, see §4 — built as part of normal release-clone prep, not a separate deploy process
    src/
    package.json
  contracts.py                 # MenuItemSpec, ThemeConfig — shared between TUI and any future webapp menu-data reuse
  errors.py
```

---

## 3. Menu-data-driven architecture — a binding rule, not a preference

File 02's Repo Hygiene Rules state this as enforced, not aspirational: **any screen that's fundamentally "a list of labeled actions" must be expressed as declarative menu data (label, target API call, tooltip, docs reference) and rendered through one generic `MenuScreen`** — never a bespoke screen class. Adding a new simple menu item is an edit to the data, never new screen code; if adding an item seems to require a new screen class, that's a signal the item either belongs in the data-driven layer (fix the schema) or is a genuine custom-screen case, added to the exception list explicitly with a reason, not smuggled in as a one-off.

```python
@dataclass(frozen=True)
class MenuItemSpec:
    label: str
    tooltip: str
    docs_ref: str | None
    target: str                  # dotted API-call reference, e.g. "auth.revoke_session"
    kind: str                     # "action" | "bool" | "number" | "text" | "submenu"
```

### 3.1 `find_setting` — V2's real fuzzy-search technique, carries forward directly
V2 built the menu tree against a throwaway config (never touching real config), walked it into a flat searchable list, and used `rapidfuzz.fuzz.partial_ratio` for natural-language lookup with a plain-substring fallback if `rapidfuzz` isn't available. Genuinely good design, worth keeping essentially as-is — this is exactly the mechanism Tool Call API's `settings_tools.py` (its own deep-dive §4.2) needs behind its `MUTATING_STAGED` settings-proposal tool: a way to resolve "the user/model described a setting in natural language" to an actual dotted config key, without needing the exact key memorized.

**"Jump to a moved setting" — a real V2 behavior, resolved here.** V2's menu system kept a relocated setting findable from its old reference point after a menu reorganization; this document carried forward `find_setting`'s fuzzy-search but never designed the relocation-tracking piece specifically. Fixed with one added field on `MenuItemSpec`:
```python
@dataclass(frozen=True)
class MenuItemSpec:
    path: str                    # the current dotted path
    former_paths: tuple[str, ...] = ()   # any prior dotted path(s) this setting used to live at, before a reorganization moved it
    # ... label, tooltip, docs_ref, target, kind — unchanged
```
When a menu reorganization moves a setting, its old path gets appended to the new entry's `former_paths` rather than simply vanishing — `find_setting`'s own resolution checks `former_paths` as a fallback whenever a direct/fuzzy match against current paths comes up empty, so a saved deep-link, a stale doc reference, or plain muscle memory still resolves to the setting's new home instead of silently failing. Never pruned automatically — a `former_paths` entry only gets removed by a deliberate follow-up edit once enough time has passed that the redirect is no longer pulling its weight, the same "don't silently drop old references" instinct behind Reimport's own three-way diff.

### 3.2 The enumerated exception list — genuinely stateful screens, not an escape hatch
Run monitor, OCR corroboration diff viewer, the vendor/corporation/branch/franchiser editor, **the Groups management screen**, staff audit-review queue, the fleet/Active-Services screen, the Boot Sequence loading screen, the persistent codename header, and the credits screen are the explicitly enumerated exceptions (file 02) — even these use Textual's own widget system directly, never ad hoc print/input-style control flow. The list is closed by design; adding to it requires the same explicit justification as any other rule exception in this project. **The vendor/branch editor's own naming predates temporal_learning's Corporation/Branch/Franchiser redesign** (`v3-deepdive-40-temporal-learning.md` §4) — resolving the last open question this document carried: the TUI-side screen was never actually undesigned, it was already on this exception list under its older, simpler name, and now correctly reflects the current three-entity model plus the sharing-gate/staff-direct-write mechanics that document's own §8 already specifies as the requirement this screen needs to satisfy.

### 3.2.1 The Groups management screen — a real addition to the exception list, with the justification this list's own rule demands
**Added deliberately, not assumed in.** `v3-deepdive-41-groups.md` §11 flagged the TUI-side surface as genuinely undesigned (unlike the vendor editor, which turned out to already be on this list under an older name — a real distinction worth keeping straight rather than conflating). The justification for it being a custom screen rather than declarative menu-data: **group membership is a two-level relational structure** (a group, then its members, each with an independent `is_group_manager` toggle) that the flat `MenuItemSpec` pattern genuinely cannot express — the same reason the vendor/corporation/branch/franchiser editor earned its own exception, applied to the identical structural problem one entity-type over.

Functional parity with the webapp's own equivalent (`v3-deepdive-44-webapp.md` §5.4), not a reduced subset: create/rename/delete groups, add/remove members, toggle `is_group_manager` per membership, and view the group export. **Permission-gated identically** — `staff`/`owner`/group-manager only, enforced server-side by Groups' own `ListGroupMembers` RPC regardless of which client is asking (§4.1 there), with the TUI's own gating being UX, never the security boundary — the same discipline `v3-deepdive-47-frontend-auth-session.md` §4 already states for the webapp's own route guards.

**Two real behaviors this screen needs that the webapp's own description doesn't have to state explicitly:**
- **Toggling `is_group_manager` is an Audit-logged privileged action** (`v3-deepdive-41-groups.md` §11's own resolution) — the TUI surfaces a confirmation before applying it, consistent with every other privileged action in this interface, not a silent toggle.
- **The multi-group "active group" selector** (Groups §5, resolved) lives here too — a member of more than one group needs a real place to see and change which group their new receipts get tagged with, and this screen is that place rather than a separate settings entry disconnected from the group list it refers to.

### 3.3 The Fleet screen, expanded into Fleet & Updates — a real, previously-underspecified design, correcting a V2 mistake
**Unlike V2, update functionality gets its own dedicated area, never buried inside Settings** — a deliberate correction, not a stylistic preference: version/update management is an operational concern (closer in kind to health monitoring than to a user preference), and V2's own choice to bury it in Settings made it genuinely hard to find when it actually mattered. Rather than inventing a *second* new custom-screen exception for this, it lives as a real expansion of the Fleet screen already on the enumerated list (§3.2) — the same screen that already shows which services are running is also where an owner manages what version each one is running, since the two are naturally the same information, not two unrelated concerns that happen to share a name.

**Two genuinely different controls on this one screen, matching Supervisor's own two-shape design** (`v3-deepdive-38-supervisor.md` §5.1):
- **For the 24 multi-version-capable services**: a per-service, per-channel status view, plus `PinServiceVersion` (Supervisor's own deep-dive §5.2) exposed as an explicit "pin this service to a specific version on this channel" action — a real, surgical override distinct from a full channel rollback, gated to owner/staff.
- **For the TUI and Inference specifically** (the two single-instance services, Supervisor's own deep-dive §5.3): a version dropdown plus a **"Confirm Update (will restart the process, not the whole program)"** button — worded exactly that plainly, since "restart" is ambiguous enough in this context (does it mean the whole install? just this one service?) that the confirmation text itself needs to resolve the ambiguity, not just the design intent behind it.

**The TUI's own restart is fullscreen; Inference's is not — a real, deliberate asymmetry, not an inconsistency.** Restarting the TUI necessarily takes over the same terminal the operator is already looking at, so it reuses the Boot Sequence's own loading screen (already on the exception list, §3.2) rather than leaving a blank terminal or inventing a second full-screen loading experience for the same underlying purpose — with a clearly-secondary **"skip animation"** control for development/testing iteration, visually subordinate to the primary action, not gated behind `dev_mode` specifically since a normal owner mid-update might reasonably want it too. Restarting Inference happens entirely out of band from the TUI's own process — the TUI stays fully interactive throughout, showing the transition as a small, non-blocking status panel fed by Health API's own live-diagnostic layer (`v3-deepdive-20-health-api.md` §3), never a full-screen takeover for a restart that doesn't actually touch the process the operator is looking at.

---

## 4. Webapp framework — resolved: React + TypeScript, Zustand + TanStack Query for state
File 01 left this genuinely open. Resolved here rather than deferred again: **React, with TypeScript, not Vue or Svelte.** Reasoning specific to this project's actual constraints, not a generic "React is popular" argument: this is an LLM-assisted solo-dev project where a huge fraction of the webapp's code will be written and maintained through Claude Code sessions — React's ecosystem depth and training-data representation directly translates to higher-quality, more reliable AI-assisted output than a smaller ecosystem would, a genuinely relevant factor for *this* project's development model that wouldn't matter the same way for a team with deep framework-specific expertise already in-house. Secondary reasons that would matter regardless of dev model: the largest component-library ecosystem (relevant given this project needs a real "My Files" browsing UI, forms, tables — not a marketing site), and the most mature server-streaming/gRPC-Web client tooling, matching Gateway's own transport choice (file 01 #16).

**State management, previously left open, resolved here: Zustand for client/UI state, TanStack Query for server state — never one library trying to do both.** This is the current, broadly-converged 2026 pattern for exactly this app shape (a scoped set of gRPC-Web/REST data sources, real-time streaming updates, no deeply nested enterprise state graph) — Zustand crossed 50% adoption in the State of React 2025 survey specifically because it fits this shape without Redux's boilerplate, and the same LLM-assisted-development reasoning that drove the React choice applies again here: a minimal, widely-documented, low-ceremony library produces more reliable AI-generated code than a heavier, more opinionated one. Concretely: **TanStack Query owns everything that originates from Gateway** (receipt lists, run status, the streaming live-log tail) — its own caching, refetch, and polling machinery is a direct fit for data that's fundamentally "fetched from a server and needs to stay in sync," which is most of what this webapp actually displays. **Zustand owns genuinely local UI/client state** — which modal is open, in-progress form values, the current My Files filter selection — state that has no server-side source of truth at all. Full architectural detail (component structure, routing, the actual page/screen breakdown) lives in the webapp's own dedicated deep-dive documents, not duplicated here.

---

## 5. Version codenames, credits, and the real legal obligation hiding in a fun feature
Already well-specified in file 02: ASCII-art codename banners live in-repo (not the shared-assets folder, since they're tiny text files versioned alongside code), keyed to major version, retained indefinitely (not pruned) since LTSC channels can genuinely still be running an old codename in production concurrently with newer channels elsewhere in the fleet — a "Version History" screen becomes a free bonus once that retention already exists for functional reasons. **The credits screen is genuinely fun but has a real second purpose worth taking seriously**: many of this project's dependencies (Pillow, ONNX Runtime, Textual, FastAPI, Authlib, and others across every prior deep-dive) ship under licenses (MIT/BSD/Apache 2.0) that require their notices be included in redistributed software — once this is sold rather than just self-used, that's a genuine legal obligation, and the credits screen is the natural, already-planned place to satisfy it rather than needing a separate compliance mechanism invented later.

---

## 6. Localization/i18n — a cross-cutting concern, not a sub-API

**Scope resolved with real direction: English and Tagalog ship at launch, and the underlying architecture is built for genuinely open-ended localization, not just these two.** File 01's own original framing (string externalization + locale-aware formatting, structured here rather than spun out) was already correctly cautious about not hardcoding strings — this confirms the scope that mechanism needs to actually support from day one.

### 6.1 What "infinite localization" means concretely, not just as an aspiration
Every user-facing string routes through a translation-key lookup (`t("files.upload.button")`, never a raw hardcoded string anywhere in a screen component or menu-data entry) — the same discipline `docs/PRINCIPLES.md` §1.4 already requires for menu-data-driven screens, applied here to their *text* specifically. A new language is a new translation file mapping the same key set, never a code change to any screen — the architecture doesn't distinguish "the two launch languages" from "a hypothetical future one" at the mechanism level, only at the *content* level (which languages currently have a complete, reviewed translation file checked in). This is what makes "design for infinite localization" a real, testable property rather than a slogan: adding language #3 should be exactly as much work as language #2 was, never progressively harder because earlier work assumed only two languages would ever exist.

### 6.2 Tagalog specifically — not just "add a translation file"
Tagalog carries real considerations English-only design wouldn't surface: number/date formatting conventions, and — given this project's own BIR/financial domain — whether certain terms (VAT, TIN, Official Receipt) are better left in their original English/Filipino-business-context form even within an otherwise-Tagalog UI, since these are the terms an actual Filipino business owner already uses daily in exactly that form, not translated equivalents that would read as unfamiliar. This is a real, deliberate localization judgment call for whoever authors the Tagalog translation file, not something this document resolves — flagged as guidance for that work, not a decision made here.

---

## 7. Asyncio and concurrency
Textual is `asyncio`-native by construction (file 02's own table) — no additional design needed here beyond what Textual already provides. The webapp's own async model is standard React/browser-native (fetch/streaming for gRPC-Web calls), not a Python concurrency question at all.

---

## 8. gRPC surface and config
Interface API itself doesn't define new business-domain RPCs — every screen/action calls into the API that actually owns the relevant capability (Auth's `RevokeSession`, Execution Core's `GetRunStatus` streaming, etc.). The one Interface-owned contract is menu-data delivery for any server-driven menu content (e.g. Tool Call's `settings_tools.py` needing the current menu tree for its fuzzy-search resolution):
```protobuf
service InterfaceService {
  rpc GetMenuTree(MenuTreeRequest) returns (MenuTreeResponse);
}
```
```
interface:
  theme: default
  locale: en-PH
```

---

## 9. Testing hooks
- **Menu-data completeness check**: every `MenuItemSpec.target` resolves to a real, currently-registered API call — a stale menu entry pointing at a removed/renamed RPC should fail CI, not be discovered by a user clicking a dead button.
- **`find_setting` accuracy regression**: a fixed set of natural-language queries against known settings, confirming the fuzzy-search resolution still finds the right dotted key as the menu tree grows over time.
- **Fleet & Updates asymmetry test**: confirms a TUI restart genuinely takes over the terminal fullscreen while an Inference restart genuinely stays non-blocking and interactive — direct validation of §3.3's whole stated asymmetry, not just trusted from the design reasoning.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- (Full translation scope beyond English — resolved, no longer open. English and Tagalog ship at launch; the underlying architecture supports genuinely open-ended future languages as new translation files, never a code change — full design in §6.)
- (Manual vendor/corporation/branch/franchiser management screens — resolved, no longer open. The TUI side was never actually undesigned — it was already on §3.2's own enumerated exception list under an older name, now updated to reflect temporal_learning's current data model. The webapp side has its own real design at `v3-deepdive-44-webapp.md` §5.5.)
