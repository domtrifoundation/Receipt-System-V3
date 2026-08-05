"""Declarative settings menu data (`v3-deepdive-14-interface-api.md` §3).

**Every entry below is a setting the planning corpus already resolved**, each carrying a
`docs_ref` to where it was decided. Nothing here is an invented product decision — this is a
transcription of settled config keys into the declarative form §1.4 requires, seeded in
Phase 1 so Agent Control's `find_setting` resolves against real data.

It is deliberately partial. Phase 2 owns completing the tree as each API's own config
surface is built. `targets` point at RPCs that do not exist yet; the menu-data integrity
check (§9's testing hooks) will fail on them until Phase 2 registers those calls, which is
the correct behaviour — a stale or premature target should surface in CI, not to a user.
"""

from __future__ import annotations

from services.interface.contracts import MenuItemSpec

SETTINGS_MENU: tuple[MenuItemSpec, ...] = (
    MenuItemSpec(
        path="settings.general.tenancy_mode",
        label="Tenancy mode",
        tooltip=(
            "Single-user or multi-tenant. Single mode makes Auth & Tenancy effectively a "
            "no-op via the implicit-owner path; multi mode enables real accounts, roles, "
            "and per-user data isolation. Set once during first-run setup."
        ),
        target="auth.get_tenancy_mode",
        kind="choice",
        docs_ref="v3-deepdive-05-auth-tenancy-api.md",
    ),
    MenuItemSpec(
        path="settings.general.dev_mode",
        label="Developer mode",
        tooltip=(
            "Recorded once at first clone. A developer-mode install keeps docs/, the test "
            "tree, and CI scaffolding in every release clone; a normal install strips them. "
            "Not convertible on a live install — switching means a fresh setup run."
        ),
        target="setup.get_dev_mode",
        kind="bool",
        docs_ref="v3-deepdive-11-setup-api.md",
    ),
    MenuItemSpec(
        path="settings.general.run_on_startup",
        label="Run on startup",
        tooltip="Launch the service cluster when the machine boots. Offered as a genuinely "
                "skippable step during first-run setup.",
        target="setup.set_run_on_startup",
        kind="bool",
        docs_ref="v3-deepdive-11-setup-api.md",
    ),
    MenuItemSpec(
        path="settings.updates.update_channel",
        label="Update channel",
        tooltip=(
            "LTSC, Stable, Beta, or Alpha. Each user picks their own; several channels "
            "running at once is a standing state in hosted multi-tenant mode, not just a "
            "rollout window. Inference API is the one service that never follows this."
        ),
        target="update.set_channel",
        kind="choice",
        docs_ref="docs/MAINTENANCE.md",
    ),
    MenuItemSpec(
        path="settings.updates.dependency_testing_opt_in",
        label="Join dependency-bump testing",
        tooltip=(
            "Opt in to having candidate dependency updates tested against this install's "
            "real bench workload via Proving Grounds. Independent of the update channel — "
            "never applied to real customer runs without consent."
        ),
        target="update.set_dependency_testing_opt_in",
        kind="bool",
        docs_ref="v3-deepdive-36-proving-grounds.md",
    ),
    MenuItemSpec(
        path="settings.logging.log_verbosity",
        label="Log verbosity",
        tooltip=(
            "normal, verbose, or debug. Gates per-receipt matching and inference detail "
            "independently of the log level, so the live log window stays readable by "
            "default without losing detail when debugging."
        ),
        target="logs.set_verbosity",
        kind="choice",
        docs_ref="v3-deepdive-18-logs-api.md",
    ),
    MenuItemSpec(
        path="settings.ingestion.google_drive_enabled",
        label="Google Drive ingestion",
        tooltip=(
            "Enable the watched-Drive-folder source. Each ingestion source is an "
            "independently enableable Provider Registry entry — turning this off degrades "
            "cleanly to the remaining sources, it never errors."
        ),
        target="ingestion.set_source_enabled",
        kind="bool",
        docs_ref="v3-deepdive-04-ingestion-api.md",
    ),
    MenuItemSpec(
        path="settings.ingestion.archival_codec",
        label="Archival codec",
        tooltip=(
            "WebP or AVIF, one choice for the whole install, owner-selected. Deliberately "
            "system-wide and never a per-user or per-tier lever. The content-address hash "
            "is computed over the original upload, before this re-encode."
        ),
        target="ingestion.set_archival_codec",
        kind="choice",
        docs_ref="v3-deepdive-42-format-normalization.md",
    ),
    MenuItemSpec(
        path="settings.network.tunnel_exposure_enabled",
        label="Tunnel exposure",
        tooltip=(
            "Expose Gateway to the public internet without opening inbound firewall ports. "
            "Self-hosted installs only; offered as a skippable first-run step. Does not "
            "replace Gateway's own rate limiting and request validation."
        ),
        target="gateway.set_tunnel_enabled",
        kind="bool",
        docs_ref="v3-deepdive-43-tunnel-exposure.md",
    ),
    MenuItemSpec(
        path="settings.diagnostics.telemetrees_opt_in",
        label="Send diagnostics to developers",
        tooltip=(
            "Let Telemetrees compile diagnosed errors and degradation signals into tracked "
            "issues. Off unless explicitly enabled outside DOMTRI's own instances; any data "
            "leaving the install is scrubbed of receipt and financial content first."
        ),
        target="telemetrees.set_opt_in",
        kind="bool",
        docs_ref="v3-deepdive-28-telemetrees-api.md",
    ),
    MenuItemSpec(
        path="settings.diagnostics.filed_issues",
        label="Reported issues",
        tooltip=(
            "Every issue this install has filed with the developers, and its real, live "
            "GitHub status — open/closed, and any pull request already linked to it. Empty "
            "until the diagnosed-error detector that files these actually exists; the "
            "ledger and live status lookup are real, that detector is not yet built."
        ),
        target="interface.open_screen.filed_issues",
        kind="action",
        docs_ref="v3-deepdive-28-telemetrees-api.md",
    ),
    MenuItemSpec(
        path="settings.agents.agent_tokens",
        label="Agent access tokens",
        tooltip=(
            "Issue, review, and revoke tokens for AI agents and automation. A token is "
            "always issued deliberately by a human and is capped at staff-equivalent "
            "permissions — never owner, regardless of who issues it."
        ),
        target="agent_control.list_agent_tokens",
        kind="submenu",
        docs_ref="v3-deepdive-55-agent-control-api.md",
    ),
)
