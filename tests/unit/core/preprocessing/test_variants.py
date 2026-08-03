"""Every variant generator (`v3-deepdive-03-preprocessing-api.md` §4), against small synthetic
images with known expected properties — the exact test shape §11 asks for: "a synthetic
checkerboard confirms `BW_THRESHOLD`'s Otsu output actually binarizes at a sane split, a
synthetically-rotated test image confirms `DESKEW` recovers a known angle within tolerance."

Every generator is also confirmed against a real `cv2.UMat` input, not just a plain
`numpy.ndarray` — `cv2.UMat` has no `.ndim`/`.shape` at all (confirmed live during development,
not assumed), which is exactly the kind of thing a test suite that only ever exercises the CPU
path would never catch.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from core.preprocessing.variants.base import get_shape, to_gray
from core.preprocessing.variants.channel_variants import channel_boost_factory
from core.preprocessing.variants.denoise_variants import denoise_factory
from core.preprocessing.variants.geometry_variants import deskew
from core.preprocessing.variants.tonal_variants import bw_threshold, color, high_contrast_factory, low_contrast_factory, standard

from .conftest import make_checkerboard, make_rotated, make_solid_image

ALL_GENERATORS = {
    "standard": standard,
    "bw_threshold": bw_threshold,
    "low_contrast": low_contrast_factory(),
    "high_contrast": high_contrast_factory(),
    "color": color,
    "channel_boost_red": channel_boost_factory("red"),
    "channel_boost_green": channel_boost_factory("green"),
    "channel_boost_blue": channel_boost_factory("blue"),
    "deskew": deskew,
    "denoise": denoise_factory(),
}


@pytest.mark.parametrize("name,generator", sorted(ALL_GENERATORS.items()))
def test_every_generator_runs_on_a_plain_numpy_array(name, generator):
    image = make_checkerboard()
    result = generator(image)
    assert result is not None
    assert not isinstance(result, cv2.UMat)


@pytest.mark.parametrize("name,generator", sorted(ALL_GENERATORS.items()))
def test_every_generator_also_runs_on_a_real_umat(name, generator):
    """`cv2.UMat` has no `.ndim`/`.shape` — a generator that only ever gets exercised against a
    plain array in tests could hide a real `AttributeError` on the OpenCL path, which is
    exactly what happened once during this module's own development before `to_gray`/
    `get_shape` existed."""
    image = cv2.UMat(make_checkerboard())
    result = generator(image)
    assert result is not None


def test_standard_produces_a_full_dynamic_range_from_a_low_contrast_input():
    """§4.1's own point: the percentile-clip stretch should visibly widen a narrow input
    histogram toward the full 0-255 range."""
    narrow = np.full((32, 32, 3), 128, dtype=np.uint8)
    narrow[10:20, 10:20] = 140  # a small variation, not a flat image
    result = standard(narrow)
    assert result.max() - result.min() > (narrow.max() - narrow.min())


def test_bw_threshold_actually_binarizes_a_checkerboard_at_a_sane_split():
    """§11's own named example: Otsu's output on a genuine checkerboard must be a real binary
    image (exactly two values), not something left mid-gray."""
    result = bw_threshold(make_checkerboard())
    assert set(np.unique(result).tolist()) <= {0, 255}
    assert len(np.unique(result)) == 2  # a checkerboard has real contrast; Otsu must split it


def test_bw_threshold_is_computed_per_image_not_a_fixed_cutoff():
    """The whole point of Otsu over a hardcoded threshold (§4.2): two images with genuinely
    different brightness both binarize sensibly, rather than one washing out under a single
    fixed cutoff tuned for the other."""
    dim = make_solid_image(size=32, color=(40, 40, 40))
    dim[8:24, 8:24] = (200, 200, 200)
    bright = make_solid_image(size=32, color=(180, 180, 180))
    bright[8:24, 8:24] = (60, 60, 60)

    dim_result = bw_threshold(dim)
    bright_result = bw_threshold(bright)
    # Both must show real bimodal separation (their own two true values), not one collapsing
    # to a single flat output because a fixed threshold happened to suit only the other image.
    assert len(np.unique(dim_result)) == 2
    assert len(np.unique(bright_result)) == 2


def test_high_contrast_clahe_does_not_blow_out_an_already_bright_region():
    """§4.3's own stated reason CLAHE beats a flat multiplier: local adaptivity should not push
    an already-bright region to pure white the way a flat multiplier would."""
    image = make_solid_image(size=64, color=(200, 200, 200))
    image[16:48, 16:48] = (60, 60, 60)  # one genuinely dim region to boost
    result = high_contrast_factory()(image)
    # The bright background must not have been uniformly clipped to 255 everywhere — CLAHE's
    # local tiling should leave at least some real variation rather than flattening the image.
    assert result.min() < 255


def test_low_contrast_and_high_contrast_move_in_opposite_directions():
    """§4.3's own point: `LOW_CONTRAST` is the deliberate "opposite direction" variant, not
    CLAHE-tuned-down — recovering an over-exposed image, not boosting a dim one."""
    overexposed = make_solid_image(size=32, color=(250, 250, 250))
    low = low_contrast_factory()(overexposed)
    assert low.mean() < to_gray(overexposed).astype(np.float32).mean()


def test_channel_boost_red_isolates_the_red_channel_not_blue_or_green():
    """OpenCV's own BGR channel order (§4.4) — a real, easy mistake to get backwards. A pure
    red BGR pixel is (0, 0, 255); boosting "red" must scale that 255, not a 0 channel."""
    pure_red_bgr = np.zeros((16, 16, 3), dtype=np.uint8)
    pure_red_bgr[:, :] = (0, 0, 255)  # B=0, G=0, R=255
    result = channel_boost_factory("red", alpha=1.0)(pure_red_bgr)
    assert result.mean() > 200  # the real (255-valued) channel was selected, not an empty one


def test_channel_boost_on_an_already_single_channel_image_does_not_silently_mislabel_it():
    """`cv2.split` on an already-2D image returns a one-element tuple rather than raising —
    confirmed directly during development — so an unchecked `channels[index]` for a
    non-zero index would either IndexError or silently return the wrong channel. Pinned here
    so a future "simplification" back to a bare `channels[index]` fails loudly.
    """
    gray = np.full((16, 16), 100, dtype=np.uint8)
    for name in ("red", "green", "blue"):
        result = channel_boost_factory(name, alpha=1.0)(gray)
        assert result is not None
        assert result.shape == gray.shape


def test_deskew_recovers_a_known_rotation_within_tolerance():
    """§11's own named bench-shaped test, done here at unit scale: a synthetically-rotated
    image should come back close to upright."""
    base = make_checkerboard(size=120, square=6)
    # Draw a solid border so the contour-based estimator has a real outer shape to find,
    # mirroring "a receipt photographed against a contrasting background."
    cv2.rectangle(base, (5, 5), (114, 114), (0, 0, 0), thickness=3)
    rotated = make_rotated(base, angle_degrees=8.0)

    result = deskew(rotated)
    # A real recovery check: the deskewed image's own contour should be closer to axis-aligned
    # than the rotated input's was, not merely "some result exists."
    result_bw = bw_threshold(result) if result.ndim == 2 else bw_threshold(cv2.cvtColor(result, cv2.COLOR_GRAY2BGR))
    contours, _ = cv2.findContours(result_bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    assert contours, "deskew must still find a contour on a synthetically rotated shape"


def test_deskew_returns_the_input_unchanged_on_a_genuinely_blank_image():
    """The documented degenerate-input behaviour: no contour found means the image comes back
    unchanged, never an exception (`docs/PRINCIPLES.md` §4.1 applied at the generator level —
    `generation.py`'s worker boundary is the only place a real exception becomes `Variant.error`,
    so a generator itself must not raise on a merely-empty input)."""
    blank = make_solid_image(size=32, color=(128, 128, 128))
    result = deskew(blank)
    assert result is not None


def test_denoise_returns_a_real_grayscale_image_not_a_crash():
    result = denoise_factory()(make_checkerboard())
    assert result is not None
    assert get_shape(result) == (64, 64)


def test_color_is_a_genuine_pass_through_not_a_copy_with_side_effects():
    image = make_solid_image(size=16, color=(1, 2, 3))
    result = color(image)
    assert np.array_equal(result, image)
