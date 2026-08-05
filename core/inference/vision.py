"""Vision/multimodal request handling (deep-dive §7) — genuinely new for V3.

**No separate sharing mechanism to build.** Per the deep-dive's own clarification: most
current vision-language ONNX GenAI exports are one unified model handling both text-only
and text+image requests through the same loaded weights, so "don't double-load" falls
naturally out of `model_registry.py` treating a vision-capable preset as a single
`PresetWorker` — this module's whole job is resolving a request's own image content
blocks into bytes before they cross to that worker, nothing more.
"""

from __future__ import annotations

from .contracts import BlobStoreGateway, ContentBlockType, GenerationRequest, Message
from .presets import PresetSpec

__all__ = ["ResolvedImage", "requires_vision", "resolve_images"]


class ResolvedImage:
    """A `ContentBlock`'s `image_ref` resolved to real bytes — plain, picklable data safe
    to hand across a `PresetWorker`'s own queue, the same reasoning
    `core/preprocessing/generation.py`'s own worker jobs carry only plain data."""

    __slots__ = ("logical_id", "data")

    def __init__(self, logical_id: str, data: bytes) -> None:
        self.logical_id = logical_id
        self.data = data


def requires_vision(messages: tuple[Message, ...]) -> bool:
    return any(
        block.type == ContentBlockType.IMAGE
        for message in messages
        for block in message.content
    )


async def resolve_images(
    request: GenerationRequest, preset: PresetSpec, blob_store: BlobStoreGateway
) -> tuple[ResolvedImage, ...]:
    """Reads every image block's bytes via the blob store — raises `ValueError` if the
    request carries image content but the chosen preset doesn't support vision (a caller
    error, discovered before any worker dispatch, not a per-generation failure)."""
    if not requires_vision(request.messages):
        return ()
    if not preset.supports_vision:
        raise ValueError(
            f"preset {preset.name!r} does not support vision, but the request carries image content"
        )

    resolved: list[ResolvedImage] = []
    for message in request.messages:
        for block in message.content:
            if block.type == ContentBlockType.IMAGE and block.image_ref is not None:
                data = await blob_store.read_blob(block.image_ref)
                resolved.append(ResolvedImage(block.image_ref.logical_id, data))
    return tuple(resolved)
