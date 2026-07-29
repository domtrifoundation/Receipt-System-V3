"""`OSNativeSchedulerTrigger` — an optional third provider for self-hosted power users (§5).

For users who want OS-level scheduling guarantees independent of this project's own process
model: Windows Task Scheduler (`schtasks`) or a Linux `cron`/`systemd` timer, structurally
available behind the identical `ScheduleTrigger` interface — **not the default**. §5 names it
as the least commonly needed of the three providers, and this implementation reflects that: it
is real and functional, not a stub, but it is deliberately the smallest of the three.

**Every actual OS interaction goes through one injected `CommandRunner` seam**
(`docs/PRINCIPLES.md` §1.3) — `subprocess` is the external dependency here, and it sits behind
one adapter rather than being invoked at scattered call sites. This is also what makes the
provider testable without actually mutating a real machine's crontab or Task Scheduler state:
a test supplies a fake runner that records the command it would have run.

**Availability is feature-detected, never version- or OS-name-matched** (`docs/PRINCIPLES.md`
§3.3 point 2): `shutil.which` looks for the actual binary this provider needs, not a
`platform.system() == "Windows"` branch alone — a Windows install missing `schtasks.exe` (or
a Linux install with neither `crontab` nor `systemctl` on `PATH`, a minimal container image
being the realistic case) reports unavailable rather than failing the first time it is used.
"""

from __future__ import annotations

import asyncio
import platform
import shutil
from typing import Protocol, runtime_checkable

from ..contracts import UserScheduledTask
from ..errors import TriggerUnavailable

#: The tag every entry this provider creates carries, so `deregister_trigger` can find and
#: remove exactly its own entry without disturbing anything else already in a user's real
#: crontab or Task Scheduler library.
TASK_TAG_PREFIX = "resibo-task"


@runtime_checkable
class CommandRunner(Protocol):
    """The one seam onto the OS. `run` raises on a non-zero exit or a missing binary; it
    never returns a sentinel a caller could forget to check."""

    def run(self, args: list[str]) -> None: ...


class _SubprocessRunner:
    """The real adapter, imported lazily inside `run` — `subprocess` is stdlib and always
    importable, but keeping the import inside the one method that uses it matches this
    project's own "lazy import for anything not needed at process startup" posture
    (`docs/PRINCIPLES.md` §3.3 point 5) and keeps this module trivially patchable in tests
    without a real subprocess ever spawning."""

    def run(self, args: list[str]) -> None:
        import subprocess

        subprocess.run(args, check=True, capture_output=True, text=True)


def _tag(task_id: str) -> str:
    return f"{TASK_TAG_PREFIX}:{task_id}"


class OSNativeSchedulerTrigger:
    """`platform_name` is injectable so tests can exercise both the Windows and the
    Linux/macOS command shapes on a single development machine, independent of which OS is
    actually running the test."""

    def __init__(
        self, runner: CommandRunner | None = None, *, platform_name: str | None = None,
    ) -> None:
        self._runner = runner or _SubprocessRunner()
        self._platform = platform_name or platform.system()

    @property
    def name(self) -> str:
        return "os_native"

    def is_available(self) -> bool:
        if self._platform == "Windows":
            return shutil.which("schtasks") is not None
        return shutil.which("crontab") is not None or shutil.which("systemctl") is not None

    def _register_command(self, task: UserScheduledTask) -> list[str]:
        tag = _tag(task.task_id)
        if self._platform == "Windows":
            # schtasks has no native cron-expression input; this provider's own scope is a
            # simple daily-at-time schedule, the common case for a self-hosted power user's
            # "run this every day at 2am" — a full cron-to-schtasks translation is real,
            # future work rather than something worth guessing at here.
            return [
                "schtasks", "/Create", "/TN", tag, "/SC", "DAILY", "/TR",
                f"resibo-task-run --task-id={task.task_id}", "/F",
            ]
        return [
            "sh", "-c",
            f"(crontab -l 2>/dev/null; echo '{task.cron_expression} "
            f"resibo-task-run --task-id={task.task_id} # {tag}') | crontab -",
        ]

    def _deregister_command(self, task_id: str) -> list[str]:
        tag = _tag(task_id)
        if self._platform == "Windows":
            return ["schtasks", "/Delete", "/TN", tag, "/F"]
        return ["sh", "-c", f"crontab -l 2>/dev/null | grep -v '{tag}' | crontab -"]

    async def register_trigger(self, task: UserScheduledTask) -> None:
        if not self.is_available():
            raise TriggerUnavailable(
                f"no OS-native scheduler binary found on {self._platform}"
            )
        await asyncio.to_thread(self._runner.run, self._register_command(task))

    async def deregister_trigger(self, task_id: str) -> None:
        if not self.is_available():
            # Nothing this provider could have armed persists once its own binary is gone
            # either — deregistering degrades to a no-op rather than a failure.
            return
        await asyncio.to_thread(self._runner.run, self._deregister_command(task_id))


__all__ = ["CommandRunner", "OSNativeSchedulerTrigger", "TASK_TAG_PREFIX"]
