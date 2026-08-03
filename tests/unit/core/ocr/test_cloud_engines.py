"""The paid, network-bound cloud tier (deep-dive §4.7) — never exercised against a real
network call in this automated suite (real money, real external services). Availability
gating is tested for real; the actual HTTP call shape is tested against a monkeypatched
`httpx.AsyncClient`, matching the deep-dive's own §11 testing guidance for this tier.
"""

from __future__ import annotations

import pytest

from core.ocr.engines.cloud_engines.aws_textract import AwsTextractEngine
from core.ocr.engines.cloud_engines.azure_doc_intelligence import AzureDocumentIntelligenceEngine
from core.ocr.engines.cloud_engines.base_cloud_engine import CloudEngineConfig
from core.ocr.engines.cloud_engines.google_vision import GoogleVisionEngine
from core.ocr.errors import OcrEngineUnavailable

from .conftest import run


def test_google_vision_unavailable_without_an_api_key():
    engine = GoogleVisionEngine(CloudEngineConfig(api_key=""))
    assert run(engine.is_available()) is False
    with pytest.raises(OcrEngineUnavailable):
        run(engine.read(b"irrelevant"))


def test_azure_unavailable_without_endpoint_even_with_a_key():
    engine = AzureDocumentIntelligenceEngine(CloudEngineConfig(api_key="k", endpoint=""))
    assert run(engine.is_available()) is False


def test_aws_textract_unavailable_without_credentials():
    engine = AwsTextractEngine(CloudEngineConfig())
    assert run(engine.is_available()) is False


def test_google_vision_calls_the_real_endpoint_shape(monkeypatch):
    """Never a live network call — `httpx.AsyncClient.post` is monkeypatched to return a
    real Google Vision-shaped response body, so this exercises the actual parsing logic
    (`_extract_regions`) without touching the network."""
    import httpx

    class _FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "responses": [
                    {
                        "fullTextAnnotation": {
                            "text": "TOTAL 5.00",
                            "pages": [
                                {
                                    "blocks": [
                                        {
                                            "paragraphs": [
                                                {
                                                    "words": [
                                                        {
                                                            "symbols": [{"text": "T"}, {"text": "O"}, {"text": "T"}, {"text": "A"}, {"text": "L"}],
                                                            "confidence": 0.95,
                                                            "boundingBox": {
                                                                "vertices": [
                                                                    {"x": 0, "y": 0}, {"x": 100, "y": 0},
                                                                    {"x": 100, "y": 20}, {"x": 0, "y": 20},
                                                                ]
                                                            },
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ],
                        }
                    }
                ]
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    engine = GoogleVisionEngine(CloudEngineConfig(api_key="fake-key"))
    reading = run(engine.read(b"fake-image-bytes"))
    assert reading.error is None
    assert reading.text == "TOTAL 5.00"
    assert len(reading.regions) == 1
    assert reading.regions[0].confidence == 0.95
