"""Shared fixtures for Inference's unit tests."""

from __future__ import annotations

import asyncio

import pytest

from core.inference.contracts import BlobRef, ContentBlock, ContentBlockType, Message, MessageRole


def run(coro):
    return asyncio.run(coro)


def text_message(role: MessageRole, text: str) -> Message:
    return Message(role=role, content=(ContentBlock(type=ContentBlockType.TEXT, text=text),))


def image_message(role: MessageRole, logical_id: str) -> Message:
    return Message(
        role=role,
        content=(ContentBlock(type=ContentBlockType.IMAGE, image_ref=BlobRef(logical_id=logical_id)),),
    )


class FakeBlobStore:
    def __init__(self, blobs: dict[str, bytes] | None = None) -> None:
        self.blobs = blobs or {}

    async def read_blob(self, ref: BlobRef) -> bytes:
        return self.blobs[ref.logical_id]


@pytest.fixture
def blob_store() -> FakeBlobStore:
    return FakeBlobStore()
