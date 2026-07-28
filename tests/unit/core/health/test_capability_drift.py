"""Version capability drift checking (`v3-deepdive-20-health-api.md` §4).

§10's fourth testing hook asks for **both directions** explicitly: a stale-lockfile simulation
where the PyPI `frozendict` is still active on a 3.15+ interpreter must be flagged, *and* a
genuinely clean 3.15+ environment must report `drifted: false` rather than a false positive.
"Both directions matter equally here, since a check that cries wolf gets ignored just as fast
as one that never fires."

The probes read `sys.version_info` directly, so these tests drive them through the registry's
own injection point — a fake probe — rather than monkeypatching the interpreter's version
tuple. Faking `sys.version_info` would test the fake; driving the aggregation logic through
`probes=` tests what the aggregation actually does with each answer, which is the part §4's
consumers depend on.
"""

from __future__ import annotations

import sys

from core.health.capability_drift import (
    BUILTIN_FROZENDICT_VERSION,
    EXPECTED_PROFILER_ON_NEW_PYTHON,
    NoConfig,
    any_drifted,
    check_capability_drift,
)
from core.health.contracts import CapabilityDriftFinding
from core.health.metrics import HealthMetricsCollector


class StaticConfig:
    """A config reader over a fixed map — the injection point Setup API will replace."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, key: str) -> str | None:
        return self._values.get(key)


def finding(capability: str, *, drifted: bool, actual: str = "") -> CapabilityDriftFinding:
    return CapabilityDriftFinding(
        capability=capability,
        python_version="3.15.0",
        expected_path="builtin (PEP 814)",
        actual_path=actual or ("builtin" if not drifted else "PyPI package (unexpected)"),
        drifted=drifted,
    )


def test_stale_lockfile_simulation_is_flagged():
    """§10: the PyPI package still active on an interpreter that has the builtin.

    Nothing breaks when this happens — which is exactly why it needs a detector. The install
    keeps running the older path forever with no symptom.
    """
    probes = [lambda _v, _c: finding("frozendict", drifted=True)]

    findings = check_capability_drift(probes=probes)

    assert any_drifted(findings)
    assert findings[0].actual_path == "PyPI package (unexpected)"


def test_clean_environment_reports_not_drifted_rather_than_a_false_positive():
    """§10's other direction, which matters equally."""
    probes = [lambda _v, _c: finding("frozendict", drifted=False)]

    findings = check_capability_drift(probes=probes)

    assert len(findings) == 1
    assert not findings[0].drifted
    assert not any_drifted(findings)


def test_clean_findings_are_returned_not_swallowed():
    """§4.1: "a clean bill of health is itself a useful, loggable fact".

    Returning nothing when everything is fine would leave an operator unable to distinguish a
    healthy install from a check that silently stopped running.
    """
    probes = [
        lambda _v, _c: finding("frozendict", drifted=False),
        lambda _v, _c: finding("profiling_tool_preference", drifted=False, actual="tachyon"),
    ]

    findings = check_capability_drift(probes=probes)

    assert [f.capability for f in findings] == ["frozendict", "profiling_tool_preference"]


def test_a_probe_that_cannot_run_reports_nothing_for_that_capability():
    """Never `drifted=False` for a check that did not execute.

    §4.1's whole argument is that these findings can be trusted; a clean claim from an unrun
    probe is worse than silence because it is indistinguishable from a real one.
    """
    probes = [lambda _v, _c: None, lambda _v, _c: finding("frozendict", drifted=False)]

    findings = check_capability_drift(probes=probes)

    assert [f.capability for f in findings] == ["frozendict"]


def test_one_raising_probe_does_not_take_down_the_others():
    """`docs/PRINCIPLES.md` §4.4 — one unrunnable probe must not cost the other findings."""

    def explodes(_version, _config):
        raise RuntimeError("probe blew up")

    findings = check_capability_drift(
        probes=[explodes, lambda _v, _c: finding("frozendict", drifted=True)]
    )

    assert [f.capability for f in findings] == ["frozendict"]
    assert any_drifted(findings)


def test_default_config_reader_cannot_produce_a_clean_profiler_claim():
    """Setup API does not exist yet, so `NoConfig` is what a real process gets today."""
    assert NoConfig().get("telemetrees.preferred_profiler") is None


def test_real_probes_are_silent_below_the_pivot_version():
    """Below 3.15 there is nothing to have drifted from — the PyPI package is correct there.

    This asserts against the interpreter actually running the suite rather than a fake, so it
    stays honest whichever side of the pivot CI is on.
    """
    findings = check_capability_drift(
        config=StaticConfig({"telemetrees.preferred_profiler": "py-spy"})
    )

    if sys.version_info < BUILTIN_FROZENDICT_VERSION:
        assert findings == ()
    else:
        capabilities = {f.capability for f in findings}
        assert "frozendict" in capabilities
        assert "profiling_tool_preference" in capabilities
        profiler = next(f for f in findings if f.capability == "profiling_tool_preference")
        assert profiler.drifted
        assert profiler.expected_path == EXPECTED_PROFILER_ON_NEW_PYTHON


def test_drift_checks_and_findings_are_counted():
    metrics = HealthMetricsCollector()

    check_capability_drift(
        metrics=metrics,
        probes=[
            lambda _v, _c: finding("frozendict", drifted=True),
            lambda _v, _c: finding("profiling_tool_preference", drifted=True),
        ],
    )

    snapshot = metrics.snapshot()
    assert snapshot.drift_checks_run == 1
    assert snapshot.drift_findings_flagged == 2
