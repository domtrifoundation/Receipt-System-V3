"""`VariantRegistry` (`v3-deepdive-03-preprocessing-api.md` §7)."""

from __future__ import annotations

from core.preprocessing.contracts import VariantKind
from core.preprocessing.variant_registry import DEFAULT_VARIANTS_ENABLED, PreprocessingConfig, VariantRegistry


def test_available_kinds_covers_the_full_fixed_set_from_the_deep_dive():
    registry = VariantRegistry()
    assert registry.available_kinds() == frozenset(VariantKind)


def test_default_enabled_kinds_matches_section_7s_own_reasoned_starting_set():
    registry = VariantRegistry()
    assert registry.enabled_kinds() == DEFAULT_VARIANTS_ENABLED


def test_a_kind_not_in_variants_enabled_is_not_returned_even_though_available():
    config = PreprocessingConfig(variants_enabled=frozenset({VariantKind.STANDARD}))
    registry = VariantRegistry(config)
    assert registry.enabled_kinds() == {VariantKind.STANDARD}
    assert VariantKind.HIGH_CONTRAST in registry.available_kinds()


def test_denoise_requires_both_variants_enabled_membership_and_its_own_flag():
    """§4.6/§7: denoise is opt-in on two independent axes — being named in `variants_enabled`
    is not enough on its own, `denoise_enabled` must also be true. This is the one variant kind
    with a second gate, deliberately, since §12 calls its opt-in-only status "itself the
    correct, conservative resolution," not a placeholder."""
    named_but_flag_off = PreprocessingConfig(
        variants_enabled=frozenset({VariantKind.DENOISE}), denoise_enabled=False
    )
    named_and_flag_on = PreprocessingConfig(
        variants_enabled=frozenset({VariantKind.DENOISE}), denoise_enabled=True
    )
    flag_on_but_not_named = PreprocessingConfig(
        variants_enabled=frozenset(), denoise_enabled=True
    )

    assert VariantKind.DENOISE not in VariantRegistry(named_but_flag_off).enabled_kinds()
    assert VariantKind.DENOISE in VariantRegistry(named_and_flag_on).enabled_kinds()
    assert VariantKind.DENOISE not in VariantRegistry(flag_on_but_not_named).enabled_kinds()


def test_get_returns_a_real_callable_generator_for_every_available_kind():
    registry = VariantRegistry()
    for kind in registry.available_kinds():
        generator = registry.get(kind)
        assert callable(generator)


def test_high_contrast_and_low_contrast_and_channel_boost_are_configurable():
    """The whole point of the factory-function approach — config values genuinely reach the
    constructed generator, not just get accepted and ignored."""
    import numpy as np

    config = PreprocessingConfig(
        variants_enabled=frozenset(VariantKind),
        high_contrast_clip_limit=5.0,
        low_contrast_alpha=0.3,
        channel_boost_alpha=2.0,
        denoise_enabled=True,
    )
    registry = VariantRegistry(config)
    image = np.full((32, 32, 3), 100, dtype=np.uint8)

    default_low = VariantRegistry().get(VariantKind.LOW_CONTRAST)(image)
    configured_low = registry.get(VariantKind.LOW_CONTRAST)(image)
    assert not np.array_equal(default_low, configured_low)
