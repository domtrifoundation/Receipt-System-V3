"""The interim `HeuristicHardwareScorer` (`v3-deepdive-11-setup-api.md` §5.4).

`reasoned=False` on every result is the load-bearing property here — it is the flag that stops
a future session mistaking this heuristic for the bench-calibrated function §5.4 actually asks
for. Every test below checks that flag as carefully as it checks the tier itself.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.setup.contracts import GpuInfo, HardwareProfile, TierProfile
from services.setup.hardware.scoring import HeuristicHardwareScorer


def _profile(threads, ram_gb, gpus=()):
    return HardwareProfile(
        cpu_name="Test CPU",
        cores=threads // 2 or 1,
        threads=threads,
        ram_gb=ram_gb,
        gpus=tuple(gpus),
        npus=(),
        detected_at=datetime.now(timezone.utc),
        source="os_probe",
    )


def test_every_recommendation_is_flagged_unreasoned():
    """The central guarantee: nothing this module produces should ever be mistaken for
    bench-calibrated output, regardless of which tier it lands on.
    """
    scorer = HeuristicHardwareScorer()
    for profile in (_profile(2, 4), _profile(8, 16), _profile(24, 96, [GpuInfo("x", "nvidia", True, 24.0, "cuda")])):
        assert scorer.recommend(profile).reasoned is False


def test_a_low_thread_low_ram_machine_gets_lightweight():
    scorer = HeuristicHardwareScorer()
    result = scorer.recommend(_profile(threads=4, ram_gb=8))
    assert result.tier is TierProfile.LIGHTWEIGHT


def test_a_capable_machine_with_no_strong_gpu_gets_balanced_not_maximum():
    """Balanced is the honest middle default — a machine with real cores and RAM but no
    substantial discrete GPU should not be pointed at the heaviest local engines.
    """
    scorer = HeuristicHardwareScorer()
    result = scorer.recommend(_profile(threads=16, ram_gb=16, gpus=()))
    assert result.tier is TierProfile.BALANCED


def test_high_ram_plus_strong_discrete_gpu_gets_maximum_accuracy():
    """This machine's own real, live-detected profile during development: a Core Ultra 9 285K
    (24 threads), 95GB RAM, and an Arc B580 correctly resolved to 11.9GB VRAM
    (`test_hardware_detect.py`'s own regression case) — this is exactly the shape that should
    receive the most capable recommendation, not an accident of arbitrary thresholds.
    """
    scorer = HeuristicHardwareScorer()
    gpu = GpuInfo(name="Intel(R) Arc(TM) B580 Graphics", vendor="intel", discrete=True, vram_gb=11.9, compute_api="sycl")
    result = scorer.recommend(_profile(threads=24, ram_gb=95, gpus=[gpu]))
    assert result.tier is TierProfile.MAXIMUM_ACCURACY


def test_a_weak_integrated_gpu_does_not_push_a_capable_machine_to_maximum():
    """A discrete-in-name-only or low-VRAM adapter must not count toward the Maximum Accuracy
    threshold just because `gpus` is non-empty.
    """
    scorer = HeuristicHardwareScorer()
    weak_gpu = GpuInfo(name="Intel(R) Graphics", vendor="intel", discrete=False, vram_gb=2.0, compute_api="sycl")
    result = scorer.recommend(_profile(threads=16, ram_gb=32, gpus=[weak_gpu]))
    assert result.tier is TierProfile.BALANCED


def test_missing_ram_or_vram_data_degrades_to_a_conservative_tier_not_a_crash():
    """`ram_gb` and `vram_gb` are both legitimately `None` (§5.2's own never-guess-a-number
    rule) — the scorer must treat that as "unknown, so don't assume generous," not raise.
    """
    scorer = HeuristicHardwareScorer()
    gpu = GpuInfo(name="Unknown GPU", vendor="unknown", discrete=True, vram_gb=None, compute_api="unknown")
    result = scorer.recommend(_profile(threads=8, ram_gb=None, gpus=[gpu]))
    assert result.tier is TierProfile.LIGHTWEIGHT
