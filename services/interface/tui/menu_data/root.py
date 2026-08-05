"""The top-level menu tree (`v3-deepdive-14-interface-api.md` §3, §3.2).

`settings` is genuine menu-data (a plain submenu). Every other root entry names one of
§3.2's enumerated custom screens — the root menu itself is still "a list of labeled
actions," so it is still expressed as data and rendered through `MenuScreen`; only what
happens *after* selection (pushing a bespoke screen instead of calling a leaf RPC) is
custom, via the `interface.open_screen.<name>` target convention `app.py`'s resolver
interprets. This keeps the closed exception list (§3.2) about screens, not about whether
the root menu itself is data-driven.

**Build-status honesty, not a design gap**: only `boot_sequence` (the loading screen every
launch already goes through) and `credits` are real screens as of this pass. The other
five exception-list screens (`fleet_updates`, `run_monitor`, `staff_audit_queue`,
`vendor_branch_editor`, `groups`) are named here — a real, sourced item each — but their
own screen classes are not yet built; selecting one reports that plainly rather than
crashing or rendering blank. See `services/interface/CLAUDE.md` for the tracked list.
"""

from __future__ import annotations

from services.interface.contracts import MenuItemSpec

ROOT_MENU: tuple[MenuItemSpec, ...] = (
    MenuItemSpec(
        path="settings",
        label="Settings",
        tooltip="Configure this install — general, updates, logging, ingestion, network, "
                "diagnostics, and agent access.",
        target="interface.open_submenu.settings",
        kind="submenu",
    ),
    MenuItemSpec(
        path="fleet_updates",
        label="Fleet & Updates",
        tooltip="Which services are running, their versions per channel, version pinning, "
                "and the TUI/Inference restart controls (v3-deepdive-14-interface-api.md §3.3).",
        target="interface.open_screen.fleet_updates",
        kind="action",
        docs_ref="v3-deepdive-38-supervisor.md",
    ),
    MenuItemSpec(
        path="run_monitor",
        label="Run Monitor",
        tooltip="Live status of in-progress and recent ingestion/processing runs.",
        target="interface.open_screen.run_monitor",
        kind="action",
        docs_ref="v3-deepdive-06-execution-core-api.md",
    ),
    MenuItemSpec(
        path="staff_audit_queue",
        label="Staff Audit Queue",
        tooltip="Flagged items awaiting staff review and correction.",
        target="interface.open_screen.staff_audit_queue",
        kind="action",
        docs_ref="v3-deepdive-23-review-flagging-api.md",
    ),
    MenuItemSpec(
        path="vendor_branch_editor",
        label="Vendors, Corporations & Branches",
        tooltip="Manage the learned vendor directory: corporations, branches, franchisers.",
        target="interface.open_screen.vendor_branch_editor",
        kind="action",
        docs_ref="v3-deepdive-40-temporal-learning.md",
    ),
    MenuItemSpec(
        path="groups",
        label="Groups",
        tooltip="Create/rename/delete groups, manage members, and set your active group.",
        target="interface.open_screen.groups",
        kind="action",
        docs_ref="v3-deepdive-41-groups.md",
    ),
    MenuItemSpec(
        path="find_a_setting",
        label="Find a Setting...",
        tooltip="Fuzzy-search every setting by name or description (V2's find_setting, "
                "carried forward — v3-deepdive-14-interface-api.md §3.1).",
        target="interface.open_screen.find_setting",
        kind="action",
    ),
    MenuItemSpec(
        path="credits",
        label="Credits",
        tooltip="Version history, codenames, and third-party license notices.",
        target="interface.open_screen.credits",
        kind="action",
    ),
)
