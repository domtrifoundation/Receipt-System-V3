# Adding a New Menu Item / TUI Screen

## When this applies
You're adding something to the TUI's navigation — a new settings toggle, a new action, a new submenu, or (rarely) a genuinely new custom screen.

## The default path: menu data, not code
`docs/PRINCIPLES.md` §1.4 is explicit: any screen that's fundamentally "a list of labeled actions" is expressed as declarative menu data and rendered through the one generic `MenuScreen` — **this covers the overwhelming majority of what gets added here.** A new settings toggle, a new action button, a new submenu is a `MenuItemSpec` entry (label, tooltip, docs reference, target API call, kind) in the relevant `menu_data/` file — never a new screen class.

## When a custom screen is actually justified
Only for genuinely stateful, interactive screens that don't reduce to "a list of labeled actions" — the project's own enumerated exception list (run monitor, OCR corroboration diff viewer, vendor/branch editor, staff audit-review queue, the fleet screen, Boot Sequence, the codename header, the credits screen) is **closed by design**. Adding to it requires the same explicit justification as any other rule exception in this project — state in the PR description specifically why this can't be expressed as menu data, not just that it seemed easier to write as a custom screen.

## What either path requires
1. **Menu data path**: a `MenuItemSpec` entry with a real tooltip and, where relevant, a `docs_ref` pointing at actual documentation — not a placeholder. The target API call must be a real, currently-registered RPC (see `new_grpc_endpoint.md` if it doesn't exist yet).
2. **Custom screen path**: uses Textual's own widget system directly, never ad hoc print/input-style control flow (`docs/PRINCIPLES.md` §1.4's own stated constraint even for the exception list). Justification for the exception stated explicitly in the PR.

## PR checklist
- [ ] Confirmed this reduces to "a list of labeled actions" and used menu data — or explicitly justified why not, referencing the closed exception list
- [ ] `MenuItemSpec`'s target API call is a real, currently-registered RPC
- [ ] Tooltip and `docs_ref` are real, not placeholders
- [ ] If a custom screen: built on Textual's widget system directly, no ad hoc control flow
- [ ] If a custom screen introduces its own new state/contract (not just calling an existing RPC): dict-typed fields use `FrozenDict`, consistent with `docs/PRINCIPLES.md` §2.1

## CI test: `check_menu_data_integrity.yml` (this is also the interface walker)
**What it checks**: iterates the live menu-data structure and confirms every `target` field resolves to a real, currently-registered RPC — a stale menu entry pointing at a removed/renamed endpoint fails the build rather than being discovered by a user clicking a dead button. This is the same interface walker described in `docs/PRINCIPLES.md` §3.2 — it can never go stale itself, since it reads what the app actually renders from.
**Recommended use**: automatic on every PR, since menu data can be touched by changes that don't look menu-related at first glance (renaming an RPC elsewhere silently breaks a menu entry pointing at the old name). Also useful to run manually after any gRPC endpoint rename specifically, before you even open the PR.
