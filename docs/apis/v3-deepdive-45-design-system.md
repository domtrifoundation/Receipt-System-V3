# V3 Deep Dive: Design System / Component Library (Webapp sub-API)

**Parent:** `v3-deepdive-44-webapp.md` §7 (the section this document expands and replaces the brief version of).

**Companion files:** `v3-deepdive-49-reimport-diff-ui.md` and the staff review queues (`v3-deepdive-44-webapp.md` §5.6) both depend on the shared diff-viewer component this document owns; every data-table screen (My Files, Groups' member list, the staff queues) depends on the shared table component.

**Status:** New dedicated document, extracted per `docs/PRINCIPLES.md` §1.8's threshold — used across every screen in the application, has real component contracts (props/behavior), and a genuine theming/swappability question of its own.

---

## 1. Scope & boundary

The Design System owns every reusable visual building block the webapp's screens are composed from — form controls, data tables, the diff viewer, layout primitives, theming. It does not:
- **own screen-level composition or business logic** — a component here renders what it's given and emits events for what a user does; deciding what data to fetch or what an action means belongs to the screen that uses it, never to the component itself.
- **own routing or data fetching** — components receive data as props (or, for data-aware components, a typed query hook from the Client Data Layer, `v3-deepdive-46-client-data-layer.md`); they don't reach out and fetch their own data.

---

## 2. Package layout

```
webapp/src/components/
  primitives/                  # Button, Input, Select, Checkbox, Dialog, Toast — the actual base layer
  layout/                        # PageShell, Sidebar, Header
  data-table/                      # DataTable<T> — see §3
  diff-viewer/                       # DiffViewer — see §4
  theme/
    tokens.ts                          # design tokens — see §5
    ThemeProvider.tsx
```

---

## 3. `DataTable<T>` — one shared, configurable table, not a bespoke implementation per screen
Every screen that's fundamentally "rows of data with row-level actions" (My Files, Groups' member list, both staff review queues, the vendor/branch/franchiser browser) uses this one generic, type-parameterized component — the frontend's direct equivalent of `docs/PRINCIPLES.md` §1.4's "no hardcoded TUI" principle, applied to its actual web counterpart. Configured via column definitions, row-action definitions, and a data source (a Client Data Layer query hook) — never a copy-pasted table implementation per screen. Sorting, filtering, and pagination are the table's own concern, implemented once; a screen that needs a table describes its columns and gets all three for free.

```typescript
interface DataTableProps<T> {
  columns: ColumnDef<T>[];
  data: T[];
  rowActions?: RowAction<T>[];
  onRowClick?: (row: T) => void;
}
```

---

## 4. `DiffViewer` — the shared component behind both Reimport and moderation review
Reimport's own diff UI (`v3-deepdive-49-reimport-diff-ui.md`) and the staff moderation-review queues (`v3-deepdive-44-webapp.md` §5.6) are, underneath their different data shapes, the same fundamental interaction: **show a proposed change, let a human accept/reject/edit it, field by field.** One shared component, not two independently-built diff UIs that could drift apart in behavior or accessibility. Takes a generic `{field, oldValue, newValue}[]` shape and a set of per-field action callbacks — Reimport's own three-way-diff conflicts and temporal_learning's own `Contribution.proposed_change` both normalize into this same shape before reaching the component, each in their own consuming screen, never inside this component itself.

---

## 5. Theming — tokens, not hardcoded values, and a real swappability question
Design tokens (`theme/tokens.ts` — color, spacing, typography scale) rather than hardcoded values scattered through component styles — the same swappable-never-hardcoded discipline `docs/PRINCIPLES.md` §1.3 already requires everywhere else, applied to the frontend's own visual layer. **A real, previously-unconsidered question**: given a self-hosted operator might reasonably want their own branding (their own logo, their own accent color) rather than DOMTRI's default look, theming needs to be a genuine per-deployment configuration, not a build-time constant — consistent with Gateway's own runtime-config-injection design (`v3-deepdive-19-gateway-api.md` §4.3), the same injected `window.__RESIBO_CONFIG__` object that carries the API base path and feature flags also carries a theme-override object, read by `ThemeProvider` at boot before anything renders.

---

## 6. Accessibility — a real requirement, not an afterthought
Every primitive component (`primitives/`) is built on top of accessible-by-default underlying implementations (native HTML form elements, ARIA-compliant patterns for anything custom like the `DataTable`'s own sort controls) — worth stating as a real requirement here rather than left implicit, since it's exactly the kind of thing that's easy to silently drop when a screen is built quickly against a shared library that doesn't itself enforce it.

---

## 7. Asyncio/concurrency — not applicable in the Python sense, stated explicitly rather than silently skipped
This is a TypeScript/React component library — no Python concurrency model applies to it at all. Stated explicitly because the standing hygiene rule (`docs/PRINCIPLES.md` §5) requires every document to address this rather than omit it, and "not applicable" is a valid answer only when it's actually written down. **Forward-Compatibility Hygiene** similarly: no `FrozenDict` surface (no Python contracts here), no Python-version-sensitive dependencies, and free-threading is irrelevant to a browser-side library — all four points genuinely not applicable, stated rather than skipped.

---

## 8. Testing hooks
- **Theming override test**: confirms a deployment-supplied theme override actually takes effect before first paint, not a flash-of-default-theme.
- **`DiffViewer` shared-usage test**: confirms both Reimport's own consuming screen and the moderation-review queue render through the same component instance type, not two independent implementations that happen to look similar — the concrete enforcement of §4's whole reason for existing.
- **`DataTable` accessibility regression**: keyboard navigation and screen-reader labeling checked as a standing test, not a one-time manual check.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Starting component library, resolved: shadcn/ui.** Already named as available tooling elsewhere in this project's own environment — the same "don't reinvent what already exists well" discipline behind picking established libraries throughout this corpus (Motion, `py_webauthn`), not a bespoke primitive set built from scratch.
- **Dark mode, resolved: yes.** A genuinely low-cost addition given the runtime theme-injection mechanism already designed (§5) — light/dark is just another token set delivered the same way a deployment's own branding override already is, not a separate mechanism needing its own design.
