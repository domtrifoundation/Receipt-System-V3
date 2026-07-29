"""The `ScheduleTrigger` Provider Registry (`v3-deepdive-39-task-scheduler.md` §5).

Re-exports the Protocol, the registry, and the three concrete providers so a caller wiring up
Task Scheduler writes `from core.task_scheduler.triggers import TriggerRegistry,
SupervisorWakeTrigger` rather than reaching into each submodule individually.
"""

from __future__ import annotations

from .base import ScheduleTrigger, TriggerRegistry
from .in_app_timer import DueCallback, InAppTimerTrigger
from .os_native import CommandRunner, OSNativeSchedulerTrigger
from .supervisor_wake import SupervisorWakeClient, SupervisorWakeTrigger

__all__ = [
    "CommandRunner",
    "DueCallback",
    "InAppTimerTrigger",
    "OSNativeSchedulerTrigger",
    "ScheduleTrigger",
    "SupervisorWakeClient",
    "SupervisorWakeTrigger",
    "TriggerRegistry",
]
