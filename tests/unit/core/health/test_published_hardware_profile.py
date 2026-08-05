"""`PublishedHardwareProfile` — the real adapter §8.6 designed and this codebase never
built until tonight (`resource_ledger.py`'s own module docstring has the full account).
Confirms both real `device_id` conventions already live in this codebase
(`core/inference/model_registry.py`'s compute-API strings, `core/ocr/`'s `"gpuN"` index
strings) resolve correctly against the same underlying GPU list, without either caller
needing to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.health.resource_ledger import PublishedHardwareProfile


@dataclass(frozen=True)
class _Gpu:
    vendor: str
    compute_api: str
    discrete: bool = True
    vram_gb: float | None = None


@dataclass(frozen=True)
class _Profile:
    gpus: tuple = field(default_factory=tuple)


def test_none_profile_rejects_everything():
    reader = PublishedHardwareProfile(None)

    assert reader.total_mb("cuda") is None
    assert reader.total_mb("gpu0") is None


def test_exact_compute_api_match():
    profile = _Profile(gpus=(_Gpu(vendor="nvidia", compute_api="cuda", vram_gb=12.0),))
    reader = PublishedHardwareProfile(profile)

    assert reader.total_mb("cuda") == 12288  # 12.0 * 1024


def test_compute_api_match_with_no_gpu_of_that_api_is_none():
    profile = _Profile(gpus=(_Gpu(vendor="intel", compute_api="sycl", vram_gb=12.0),))
    reader = PublishedHardwareProfile(profile)

    assert reader.total_mb("cuda") is None


def test_gpu_index_convention_matches_ocrs_own_default():
    """`core/ocr/engines/rapidocr_engine.py`'s own default `device_id` is `"gpu0"` --
    this must resolve without OCR ever changing that convention."""
    profile = _Profile(gpus=(
        _Gpu(vendor="intel", compute_api="sycl", vram_gb=12.0),
        _Gpu(vendor="nvidia", compute_api="cuda", vram_gb=24.0),
    ))
    reader = PublishedHardwareProfile(profile)

    assert reader.total_mb("gpu0") == round(12.0 * 1024)
    assert reader.total_mb("gpu1") == round(24.0 * 1024)


def test_gpu_index_out_of_range_is_none():
    profile = _Profile(gpus=(_Gpu(vendor="intel", compute_api="sycl", vram_gb=12.0),))
    reader = PublishedHardwareProfile(profile)

    assert reader.total_mb("gpu5") is None


def test_compute_api_index_disambiguates_multiple_gpus_of_the_same_vendor():
    profile = _Profile(gpus=(
        _Gpu(vendor="nvidia", compute_api="cuda", vram_gb=8.0),
        _Gpu(vendor="nvidia", compute_api="cuda", vram_gb=24.0),
    ))
    reader = PublishedHardwareProfile(profile)

    assert reader.total_mb("cuda:0") == round(8.0 * 1024)
    assert reader.total_mb("cuda:1") == round(24.0 * 1024)


def test_bare_compute_api_match_picks_the_gpu_with_more_vram():
    """When a caller uses the plain compute-API convention (Inference's own
    `device_by_preset`) against a real multi-GPU machine, the most capable device wins
    rather than an arbitrary one."""
    profile = _Profile(gpus=(
        _Gpu(vendor="nvidia", compute_api="cuda", vram_gb=8.0),
        _Gpu(vendor="nvidia", compute_api="cuda", vram_gb=24.0),
    ))
    reader = PublishedHardwareProfile(profile)

    assert reader.total_mb("cuda") == round(24.0 * 1024)


def test_gpu_with_no_reported_vram_reports_none_not_zero():
    profile = _Profile(gpus=(_Gpu(vendor="intel", compute_api="sycl", vram_gb=None),))
    reader = PublishedHardwareProfile(profile)

    assert reader.total_mb("sycl") is None


def test_unrecognized_device_id_shape_is_none():
    profile = _Profile(gpus=(_Gpu(vendor="nvidia", compute_api="cuda", vram_gb=12.0),))
    reader = PublishedHardwareProfile(profile)

    assert reader.total_mb("some totally unknown string") is None
