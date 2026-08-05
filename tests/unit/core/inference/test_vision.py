"""`vision.py` — resolving a request's image content blocks (deep-dive §7)."""

from __future__ import annotations

import pytest

from core.inference.contracts import MessageRole
from core.inference.presets import PresetSpec
from core.inference.vision import requires_vision, resolve_images

from .conftest import image_message, run, text_message, FakeBlobStore


def test_requires_vision_false_for_text_only_messages():
    assert requires_vision((text_message(MessageRole.USER, "hi"),)) is False


def test_requires_vision_true_when_any_image_block_present():
    assert requires_vision((image_message(MessageRole.USER, "img1"),)) is True


def test_resolve_images_returns_empty_for_a_text_only_request(blob_store):
    from core.inference.contracts import GenerationRequest

    request = GenerationRequest(
        run_id="r1", user_id="u1", preset="phi4-vision",
        messages=(text_message(MessageRole.USER, "hi"),),
    )
    spec = PresetSpec("phi4-vision")
    result = run(resolve_images(request, spec, blob_store))
    assert result == ()


def test_resolve_images_reads_real_bytes_through_the_blob_store():
    from core.inference.contracts import GenerationRequest

    store = FakeBlobStore({"img1": b"fake-jpeg-bytes"})
    request = GenerationRequest(
        run_id="r1", user_id="u1", preset="phi4-vision",
        messages=(image_message(MessageRole.USER, "img1"),),
    )
    spec = PresetSpec("phi4-vision")
    result = run(resolve_images(request, spec, store))
    assert len(result) == 1
    assert result[0].data == b"fake-jpeg-bytes"


def test_resolve_images_raises_when_preset_does_not_support_vision():
    from core.inference.contracts import GenerationRequest

    store = FakeBlobStore({"img1": b"fake-jpeg-bytes"})
    request = GenerationRequest(
        run_id="r1", user_id="u1", preset="phi4-mini",
        messages=(image_message(MessageRole.USER, "img1"),),
    )
    spec = PresetSpec("phi4-mini")  # supports_tools, not supports_vision
    with pytest.raises(ValueError):
        run(resolve_images(request, spec, store))
