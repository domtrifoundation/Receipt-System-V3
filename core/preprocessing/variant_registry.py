"""`VariantRegistry` — the Provider Registry mapping `VariantKind` -> `VariantGenerator`
(deep-dive §2, §7). Every variant kind is independently enableable, matching every other
Provider Registry in this project (`docs/PRINCIPLES.md` §1.2) — `variants_enabled` is a real
config list, not a single value swapped one-at-a-time.

`DENOISE`'s own `enabled` flag is a second, narrower on/off switch nested inside
`variants_enabled` membership itself (§4.6, §7's own config sketch: `denoise: {enabled: false,
h: 10}`) — it can appear in `variants_enabled` and still not run unless its own flag is also
true, since an operator turning on the *fixed set* generally (§4.7) should not accidentally
also opt into the one variant this API's own deep-dive explicitly keeps default-off due to its
real cost (§4.6, §12: "this is itself the correct, conservative resolution").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import VariantKind
from .variants.base import VariantGenerator
from .variants.channel_variants import channel_boost_factory
from .variants.denoise_variants import denoise_factory
from .variants.geometry_variants import deskew
from .variants.tonal_variants import bw_threshold, color, high_contrast_factory, low_contrast_factory, standard

__all__ = ["PreprocessingConfig", "VariantRegistry"]

#: §7's own reasoned starting set — the sensible default guess that document's own §12 already
#: reasoned through, not arbitrary. Bench sweeps can refine this later (§11); nothing here
#: blocks shipping with the current membership in the meantime.
DEFAULT_VARIANTS_ENABLED: frozenset[VariantKind] = frozenset(
    {VariantKind.STANDARD, VariantKind.BW_THRESHOLD}
)


@dataclass(frozen=True)
class PreprocessingConfig:
    """§7's config surface, as a real typed object rather than a loosely-shaped dict."""

    variants_enabled: frozenset[VariantKind] = field(default_factory=lambda: DEFAULT_VARIANTS_ENABLED)
    high_contrast_clip_limit: float = 2.0
    high_contrast_tile_grid_size: tuple[int, int] = (8, 8)
    low_contrast_alpha: float = 0.6
    channel_boost_alpha: float = 1.6
    denoise_enabled: bool = False
    denoise_h: float = 10.0


class VariantRegistry:
    """Built once from a `PreprocessingConfig`. `available_kinds()` is every kind this registry
    knows how to generate at all (the full fixed set, §4.7); `enabled_kinds()` is the subset
    config actually turns on — the same `available ∩ enabled` shape `OcrEngineRegistry` uses
    (OCR deep-dive §6), applied here to variant kinds instead of engines.
    """

    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        self._config = config or PreprocessingConfig()
        self._generators: dict[VariantKind, VariantGenerator] = {
            VariantKind.STANDARD: standard,
            VariantKind.BW_THRESHOLD: bw_threshold,
            VariantKind.LOW_CONTRAST: low_contrast_factory(alpha=self._config.low_contrast_alpha),
            VariantKind.HIGH_CONTRAST: high_contrast_factory(
                clip_limit=self._config.high_contrast_clip_limit,
                tile_grid_size=self._config.high_contrast_tile_grid_size,
            ),
            VariantKind.CHANNEL_BOOST_RED: channel_boost_factory("red", alpha=self._config.channel_boost_alpha),
            VariantKind.CHANNEL_BOOST_GREEN: channel_boost_factory("green", alpha=self._config.channel_boost_alpha),
            VariantKind.CHANNEL_BOOST_BLUE: channel_boost_factory("blue", alpha=self._config.channel_boost_alpha),
            VariantKind.COLOR: color,
            VariantKind.DESKEW: deskew,
            VariantKind.DENOISE: denoise_factory(h=self._config.denoise_h),
        }

    def available_kinds(self) -> frozenset[VariantKind]:
        return frozenset(self._generators)

    def enabled_kinds(self) -> frozenset[VariantKind]:
        enabled = self.available_kinds() & self._config.variants_enabled
        if VariantKind.DENOISE in enabled and not self._config.denoise_enabled:
            enabled = enabled - {VariantKind.DENOISE}
        return enabled

    def get(self, kind: VariantKind) -> VariantGenerator:
        """Raises `KeyError` for a kind this registry has no generator for at all — a
        programming error (an unrecognized `VariantKind`), not a runtime degradation case;
        `enabled_kinds()`/`available_kinds()` are what a caller checks before calling this."""
        return self._generators[kind]
