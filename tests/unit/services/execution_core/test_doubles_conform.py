"""The fakes in `_doubles.py` must actually match the Protocols in `contracts.py`.

Its own module because it is not a test of Execution Core at all — it is a test of this suite.
A fake whose method signature has drifted from the `Protocol` it stands in for makes every
other module here pass against an interface no production caller uses, which is the most
expensive kind of green suite because it looks exactly like coverage.
"""

from __future__ import annotations

import pytest

from services.execution_core.contracts import (
    AttemptCounter,
    CheckpointStore,
    HistorianNarrator,
    ReviewFlagger,
)

from ._doubles import (
    FakeAttemptCounter,
    FakeCheckpointStore,
    RecordingFlagger,
    RecordingNarrator,
)


# --------------------------------------------------------------------------------------------
# The fakes must actually match the Protocols they stand in for
# --------------------------------------------------------------------------------------------



@pytest.mark.parametrize(
    "fake, protocol",
    [
        (FakeCheckpointStore(), CheckpointStore),
        (FakeAttemptCounter(), AttemptCounter),
        (RecordingFlagger(), ReviewFlagger),
        (RecordingNarrator(), HistorianNarrator),
    ],
)
def test_every_fake_in_this_suite_satisfies_the_protocol_it_stands_in_for(fake, protocol):
    """A fake that has drifted from its Protocol makes this whole suite meaningless.

    It would keep passing while testing an interface no production caller uses — the most
    expensive kind of green suite, because it looks like coverage. `runtime_checkable`
    Protocols only check method *names*, which is a weak check, but it catches the case that
    actually happens: a method renamed or dropped on one side of the seam.
    """
    assert isinstance(fake, protocol)
