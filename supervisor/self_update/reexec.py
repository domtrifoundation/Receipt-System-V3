"""§4.2's own two-phase verified re-exec — "the actual reason Supervisor is kept
deliberately minimal": Supervisor cannot clone-and-cutover itself the way it updates
everything else, because updating Supervisor means replacing the very process that would
normally catch a bad update and roll it back.

1. Stage the new Supervisor build somewhere the current process doesn't touch (the
   caller's own concern — a real Update API `CloneRelease` call, out of this module's
   scope; this module receives the already-staged command to run).
2. Launch the new build as a genuinely separate process with `--smoke-test`: it must
   prove it can read config, locate active releases, and report healthy — **without
   touching any live service's state**.
3. Only if that smoke test passes does the current Supervisor hand off; if it fails, the
   current process keeps running, untouched, and reports the failure — never a blind
   swap.

**"Never silent or fully automatic" (§4.2) is enforced structurally here, not left to
the caller's own discipline** — `update_supervisor()` refuses to even attempt the smoke
test without `owner_confirmed=True`, matching §9's own config: `require_owner_
confirmation: true # never configurable to false`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..contracts import UpdateResult

__all__ = ["DEFAULT_SMOKE_TEST_TIMEOUT_SECONDS", "SMOKE_TEST_FLAG", "update_supervisor"]

SMOKE_TEST_FLAG = "--smoke-test"

DEFAULT_SMOKE_TEST_TIMEOUT_SECONDS = 30.0


async def update_supervisor(
    smoke_test_command: list[str],
    *,
    owner_confirmed: bool,
    handoff: Callable[[], Awaitable[None]] | None = None,
    timeout_seconds: float = DEFAULT_SMOKE_TEST_TIMEOUT_SECONDS,
) -> UpdateResult:
    """`smoke_test_command` is the new build's own real invocation, e.g.
    `[python_bin, "-m", "supervisor.service", "--smoke-test"]` — this module runs it
    exactly as given rather than assuming a binary shape, since the new build is staged
    by the caller (a real Update API clone), not constructed here.

    `handoff`, when the smoke test passes, is the real "hand live arbitration to the new
    process" step (§4.2's own step 3) — injected rather than hardcoded, since what
    "handing off" concretely means (a signal, an IPC message, a config flag) is a real
    deployment decision this module does not make unilaterally. `handoff=None` means the
    caller wants the smoke-test verdict only, without an automatic handoff — a reasonable
    two-step call shape for an interactive confirmation flow.
    """
    if not owner_confirmed:
        return UpdateResult(ok=False, error_detail="Supervisor self-update requires explicit owner confirmation and was not given one")

    if SMOKE_TEST_FLAG not in smoke_test_command:
        smoke_test_command = [*smoke_test_command, SMOKE_TEST_FLAG]

    try:
        process = await asyncio.create_subprocess_exec(
            *smoke_test_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return UpdateResult(ok=False, smoke_test_passed=False, error_detail=f"smoke test timed out after {timeout_seconds}s")
    except OSError as exc:
        return UpdateResult(ok=False, smoke_test_passed=False, error_detail=f"could not launch smoke test: {exc}")

    if process.returncode != 0:
        detail = stdout.decode("utf-8", errors="replace").strip()
        return UpdateResult(ok=False, smoke_test_passed=False, error_detail=detail or f"smoke test exited {process.returncode}")

    if handoff is None:
        return UpdateResult(ok=True, smoke_test_passed=True, handed_off=False)

    await handoff()
    return UpdateResult(ok=True, smoke_test_passed=True, handed_off=True)
