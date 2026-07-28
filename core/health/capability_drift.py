"""Version capability drift checking (`v3-deepdive-20-health-api.md` §4).

`docs/PRINCIPLES.md` §3.3's Forward-Compatibility Pattern is built entirely around *not
breaking* on an older Python — feature detection, environment-marker installs, graceful
degradation to the existing safe behaviour. **Nothing in that pattern checks the opposite
direction.** Once an install actually is running on a newer interpreter, is this process
genuinely using what that unlocks, or silently still on the fallback path because nothing ever
re-evaluated the branch? A shim that degrades gracefully is, by construction, also capable of
staying degraded forever after the interpreter is upgraded.

That is a distinct failure mode from anything Telemetrees' Dependencies Warden covers.
Dependencies Warden watches for *external* releases becoming available; this checks whether
*this specific running process* is using what it already has.

**Every future shimmed capability registers its own check here, in the same PR that introduces
the shim** (§4.1). `docs/templates/new_dependency.md`'s Forward-Compatibility Hygiene checkbox
is the enforcement that makes that real rather than remembered.

Two rules this module holds to:

* **A clean result is reported, not omitted** (§4.1's closing line). Findings with
  `drifted=False` are returned so an operator can tell "checked, fine" from "never checked".
* **A check that could not run reports nothing for that capability, never `drifted=False`.**
  Claiming a clean bill of health for a probe that did not execute is worse than silence,
  because §4.1's whole argument is that these findings can be trusted.

This file is not in the deep-dive's §2 package layout; the reason is recorded in this
package's `CLAUDE.md`. §4's design is a genuine third responsibility alongside `status.py` and
`live_diagnostic.py`, and folding it into either would have meant one of them owning a concern
that is not its own.
"""

from __future__ import annotations

import importlib
import platform
import sys
from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from .contracts import CapabilityDriftFinding
from .metrics import HealthMetricsCollector

#: The interpreter version at which `frozendict` became a builtin (PEP 814) and Tachyon
#: (`profiling.sampling`) superseded `py-spy`. Both shims in §4.1 pivot on this one number, so
#: it is named once here rather than repeated as a literal in each probe.
BUILTIN_FROZENDICT_VERSION: tuple[int, int] = (3, 15)

#: What `telemetrees.preferred_profiler` should read on an interpreter that has Tachyon —
#: OCR's own deep-dive §10.3 states that intent, and this is the value that check compares to.
EXPECTED_PROFILER_ON_NEW_PYTHON: str = "tachyon"


@runtime_checkable
class ConfigReader(Protocol):
    """The one adapter between this module and whatever holds configuration.

    Setup API owns config and does not exist yet, so this is injected rather than imported
    (`docs/PRINCIPLES.md` §1.3). When Setup lands, wiring it in means passing a real reader —
    not editing this module.
    """

    def get(self, key: str) -> str | None:
        """The configured value for a dotted key, or `None` if it is not set or unreadable."""


class NoConfig:
    """The default reader: nothing is configured, so the profiler probe cannot run.

    It reports *no finding* for that capability rather than a clean one. A drift check that
    quietly passed because it could not read the config would be exactly the silent-fallback
    failure this whole section exists to detect, reproduced inside the detector.
    """

    def get(self, key: str) -> str | None:
        return None


def _frozendict_finding(python_version: str) -> CapabilityDriftFinding | None:
    """Is the resolved `FrozenDict` genuinely the builtin, or did the PyPI package win? (§4.1)

    The drift this catches is real and mundane: a stale lockfile, or a transitive dependency
    pulling `frozendict` in despite the environment-marker scoping that should have excluded
    it. Nothing breaks — which is the problem. The install keeps running the older path
    forever with no symptom.

    Returns `None` below 3.15: there is nothing to have drifted from on an interpreter where
    the PyPI package is the correct answer.
    """
    if sys.version_info < BUILTIN_FROZENDICT_VERSION:
        return None
    try:
        module = importlib.import_module("common.frozen_dict")
        resolved = module.FrozenDict
    except Exception as exc:  # pragma: no cover - import of a first-party module
        return CapabilityDriftFinding(
            capability="frozendict",
            python_version=python_version,
            expected_path="builtin (PEP 814)",
            actual_path="unresolvable",
            drifted=True,
            detail=f"common.frozen_dict could not be imported: {exc}",
        )
    is_builtin = getattr(resolved, "__module__", "") == "builtins"
    return CapabilityDriftFinding(
        capability="frozendict",
        python_version=python_version,
        expected_path="builtin (PEP 814)",
        actual_path="builtin" if is_builtin else "PyPI package (unexpected)",
        drifted=not is_builtin,
        detail=(
            ""
            if is_builtin
            else "the PyPI frozendict is active on an interpreter that has the builtin — "
            "check the lockfile and any transitive dependency pulling it in"
        ),
    )


def _profiler_finding(python_version: str, config: ConfigReader) -> CapabilityDriftFinding | None:
    """Does config still name `py-spy` on an interpreter that has Tachyon? (§4.1)

    Returns `None` below 3.15, and also when config is unreadable — an unread setting is an
    unrun check, and the module docstring's second rule forbids reporting that as clean.
    """
    if sys.version_info < BUILTIN_FROZENDICT_VERSION:
        return None
    configured = config.get("telemetrees.preferred_profiler")
    if configured is None:
        return None
    return CapabilityDriftFinding(
        capability="profiling_tool_preference",
        python_version=python_version,
        expected_path=EXPECTED_PROFILER_ON_NEW_PYTHON,
        actual_path=configured,
        drifted=configured != EXPECTED_PROFILER_ON_NEW_PYTHON,
        detail=(
            ""
            if configured == EXPECTED_PROFILER_ON_NEW_PYTHON
            else "py-spy is not even installed on this interpreter under the environment-marker "
            "scoping, so this preference resolves to a provider that cannot run"
        ),
    )


#: The registry of probes. §4.1 is explicit that this list is deliberately small and specific
#: right now — exactly the two Forward-Compatibility-shimmed capabilities the corpus currently
#: has — and that every future shimmed capability appends its own probe here.
Probe = Callable[[str, ConfigReader], "CapabilityDriftFinding | None"]

PROBES: tuple[Probe, ...] = (
    lambda version, _config: _frozendict_finding(version),
    _profiler_finding,
)


def check_capability_drift(
    *,
    config: ConfigReader | None = None,
    metrics: HealthMetricsCollector | None = None,
    probes: Sequence[Probe] = PROBES,
) -> tuple[CapabilityDriftFinding, ...]:
    """Run every registered probe and return all findings, drifted or not (§4.1).

    Triggered by the Boot Sequence as part of cold-start health gating, and again as a
    Background Workers idle-time job on an interval (§4.2) — a config change between restarts
    is exactly the kind of thing that introduces drift without a restart to catch it.

    A probe that raises is skipped rather than allowed to take the whole check down: one
    unrunnable probe must not cost an operator the findings from the others (§4.4).
    """
    collector = metrics or HealthMetricsCollector()
    reader = config or NoConfig()
    version = platform.python_version()

    findings: list[CapabilityDriftFinding] = []
    for probe in probes:
        try:
            finding = probe(version, reader)
        except Exception:
            continue
        if finding is not None:
            findings.append(finding)

    collector.increment("drift_checks_run")
    drifted = sum(1 for f in findings if f.drifted)
    if drifted:
        collector.increment("drift_findings_flagged", drifted)
    return tuple(findings)


def any_drifted(findings: Sequence[CapabilityDriftFinding]) -> bool:
    """§8's `DriftResponse.any_drifted`, derived rather than tracked separately."""
    return any(f.drifted for f in findings)


__all__ = [
    "BUILTIN_FROZENDICT_VERSION",
    "EXPECTED_PROFILER_ON_NEW_PYTHON",
    "PROBES",
    "ConfigReader",
    "NoConfig",
    "Probe",
    "any_drifted",
    "check_capability_drift",
]
