"""`recommended_settings()` — tier calibration (deep-dive §5.4).

**This is the interim heuristic, not the calibrated function §5.4 actually asks for.** §5.4's
own words: "this scoring function's actual coefficients should come from the bench suite's real
measurements... once they exist, not invented here." §9 repeats it: "explicitly deferred to real
bench data per those APIs' own testing sections, not invented here." No bench suite exists yet
in this repo (`tests/bench/` is 0-byte scaffolding), so there is nothing to calibrate against.

What is built here instead is the real seam (`HardwareScorer`, `RecommendedTier.reasoned`) plus
a defensible, clearly-labelled interim heuristic — the same posture OCR's own deep-dive takes
toward Tesseract's PSM default (§9 there: ship a reasoned default now, let real measurement
override it once it exists, never leave the wizard with nothing to show). `reasoned=False` on
every result this module produces is the honest signal that a future bench-calibrated
`HardwareScorer` implementation should replace it, not extend it.
"""

from __future__ import annotations

from ..contracts import HardwareProfile, RecommendedTier, TierProfile

__all__ = ["HeuristicHardwareScorer"]

#: Below this many logical threads OR this much RAM, recommend Lightweight regardless of GPU —
#: a machine this constrained genuinely cannot run the heavier local OCR/Inference engines
#: alongside everything else without becoming unusable for its own primary purpose.
_LIGHTWEIGHT_MAX_THREADS = 4
_LIGHTWEIGHT_MAX_RAM_GB = 8

#: At or above this RAM, plus a discrete GPU with real VRAM, Maximum Accuracy is a defensible
#: recommendation rather than an optimistic one — PaddleOCR and a larger Inference preset both
#: have real memory footprints this threshold is sized to actually clear, not just exceed
#: nominally.
_MAX_ACCURACY_MIN_RAM_GB = 16
_MAX_ACCURACY_MIN_VRAM_GB = 6.0


class HeuristicHardwareScorer:
    """`HardwareScorer` — cores/RAM/GPU-presence tiering, not bench-calibrated coefficients.

    Deliberately simple rather than an elaborate weighted formula: a formula with more knobs
    than the interim heuristic needs would just be more surface area to silently mistake for
    calibrated later. Three plain rules, matching the three plain labels
    `docs/SETUP_WIZARD_SCRIPT.md` Step 9 actually shows an owner.
    """

    def recommend(self, profile: HardwareProfile) -> RecommendedTier:
        ram_gb = profile.ram_gb or 0
        best_gpu = max(profile.gpus, key=lambda g: g.vram_gb or 0, default=None)
        best_vram = (best_gpu.vram_gb if best_gpu else None) or 0

        if profile.threads <= _LIGHTWEIGHT_MAX_THREADS or ram_gb <= _LIGHTWEIGHT_MAX_RAM_GB:
            tier = TierProfile.LIGHTWEIGHT
        elif ram_gb >= _MAX_ACCURACY_MIN_RAM_GB and best_vram >= _MAX_ACCURACY_MIN_VRAM_GB:
            tier = TierProfile.MAXIMUM_ACCURACY
        else:
            tier = TierProfile.BALANCED

        return RecommendedTier(tier=tier, reasoned=False)
