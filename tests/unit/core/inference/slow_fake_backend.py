"""A deliberately slow fake backend — module-level for the same pickling reason
`fakes.py` is (`test_generation.py`'s own module docstring). Used only to make the
`max_concurrent_generations` backpressure cap's real timing effect observable: a fast
fake backend's calls complete before the cap would ever matter."""

from __future__ import annotations

import time

from core.inference.backends.base import BackendGenerationOutput
from core.inference.contracts import FinishReason

#: Deliberately larger than one micro-batch window so concurrent requests beyond the
#: `max_concurrent_generations` cap measurably queue rather than all finishing together.
DELAY_SECONDS = 0.5


class SlowFakeBackend:
    def load(self, model_dir: str, device: str, install_root: str | None = None) -> None:
        pass

    def unload(self) -> None:
        pass

    def generate(
        self, prompt: str, *, grammar_schema, max_tokens: int, temperature: float,
        images: tuple[bytes, ...] = (), reasoning_marker=None, reasoning_token_budget: int = 0,
    ) -> BackendGenerationOutput:
        time.sleep(DELAY_SECONDS)
        return BackendGenerationOutput(text="done", finish_reason=FinishReason.STOP)


def make_slow_backend() -> SlowFakeBackend:
    return SlowFakeBackend()
