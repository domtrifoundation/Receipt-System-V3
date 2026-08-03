"""The real, runnable first-run wizard entrypoint (`v3-deepdive-11-setup-api.md` §7, §7.4).

**Why this is a separate module invoked as a subprocess, not a function `bootstrap.py`
calls directly.** `bootstrap.py`'s own CLI runs under the bare pinned interpreter, before
any per-service venv exists — it cannot import `textual` itself. `services/interface/
requirements.txt` is what gets `textual` installed, into `.venvs/services.interface/`,
as part of `venv_provisioning.provision_clone()` (itself one step inside
`finalize_clone()`). This module is what `bootstrap.py` re-execs, using that now-
provisioned venv's own interpreter, once finalize has completed — the wizard genuinely
needs the interface venv's own dependencies, not the bootstrap script's bare ones.

Every wizard collaborator (`AccountEnrollmentGateway`, `TunnelSetupGateway`, etc.) is
`None` at this point in the system's lifecycle — no Core API service is running yet, this
runs *before* Supervisor's own Boot Sequence (§7.4's own stated order). Each affected
step degrades to "not configured" per `docs/PRINCIPLES.md` §4.4, exactly as
`services/setup/wizard.py`'s own docstring already states for an unimplemented
collaborator; this is not a shortcut specific to first-run, it is the same designed
degrade path every later real caller gets too.
"""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App

from services.interface.tui.custom_screens.wizard_screen import WizardScreen
from services.setup.contracts import WizardState
from services.setup.wizard import WizardEngine

#: Relative to the install root — a real, small, useful artifact even though nothing yet
#: consumes it downstream (Auth doesn't exist as a running service at this point in the
#: lifecycle to hand tenancy_mode to directly). The same "write it down, even before every
#: consumer exists" posture `bootstrap.py`'s own `write_install_config` already takes.
WIZARD_STATE_RELPATH = Path("config") / "wizard_state.json"


class _WizardHostApp(App):
    """The minimal Textual `App` that hosts `WizardScreen` for a real, standalone run —
    not a test harness; this is the actual program a user sees during first-run setup."""

    def __init__(self, engine: WizardEngine) -> None:
        super().__init__()
        self._engine = engine
        self.final_state: WizardState | None = None

    async def on_mount(self) -> None:
        async def on_complete(state: WizardState) -> None:
            self.final_state = state
            self.exit()

        await self.push_screen(WizardScreen(self._engine, on_complete=on_complete))


async def run_first_run_wizard(launcher_path: Path) -> WizardState | None:
    """Runs the wizard interactively against the real terminal. Returns `None` if the
    user quit before completing it (e.g. Ctrl+C/Ctrl+Q) — a genuinely different outcome
    from a real `WizardState`, and the caller's own concern to handle, not this
    function's to paper over."""
    engine = WizardEngine(launcher_path=launcher_path)
    app = _WizardHostApp(engine)
    await app.run_async()
    return app.final_state


def write_wizard_state(install_root: Path, state: WizardState) -> Path:
    target = install_root / WIZARD_STATE_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tenancy_mode": state.tenancy_mode,
        "owner_created": state.owner_created,
        "initial_tier": state.initial_tier,
        "drive_restore_offered": state.drive_restore_offered,
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


__all__ = ["WIZARD_STATE_RELPATH", "run_first_run_wizard", "write_wizard_state"]


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    def _parse_args() -> tuple[Path, Path]:
        if len(sys.argv) != 3:
            print("usage: python -m services.interface.tui.wizard_entrypoint <launcher_path> <install_root>", file=sys.stderr)
            raise SystemExit(2)
        return Path(sys.argv[1]), Path(sys.argv[2])

    async def _main() -> int:
        launcher_path, install_root = _parse_args()
        state = await run_first_run_wizard(launcher_path)
        if state is None:
            print("Wizard exited before completion — no state saved.", file=sys.stderr)
            return 1
        target = write_wizard_state(install_root, state)
        print(f"Wizard complete. State written to {target}.")
        return 0

    sys.exit(asyncio.run(_main()))
