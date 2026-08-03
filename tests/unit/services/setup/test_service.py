"""The `SetupServicer` gRPC surface (`setup.proto`).

`nox -s forward_compat` deliberately installs a narrow dependency set that excludes grpcio,
because grpcio has no prebuilt wheel for 3.15 yet (`docs/MAINTENANCE.md` §8.1). A bare
module-level `import grpc` here would break *collection* under that session on 3.15, not just
skip these tests — the same guard `core/auth/`'s, `core/audit/`'s and
`core/account_guardian/`'s own servicer tests already carry.

Most tests below call `SetupServicer`'s methods directly against a fake async answer-iterator
and `context=None`, the same "prove the real behaviour without a live server" approach
`core/geo_address/`'s own service tests use — proving the servicer's own wire-conversion logic
(`_encode_map`/`_decode_map`, the bidirectional streaming loop) without needing a real port.

One test (`test_a_real_client_can_drive_the_whole_wizard_over_an_actual_grpc_connection`) is a
genuine end-to-end run against a live `grpc.aio` server on a real socket — this project's stated
discipline is never stubbing the thing under test, and the thing under test here is specifically
"does this work as a real gRPC service," which only a real server can prove.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from services.setup.service import (  # noqa: E402
    SetupServicer,
    _decode_map,
    _encode_map,
    serve,
)
from services.setup.wizard import WizardEngine  # noqa: E402


# --- _encode_map / _decode_map ---------------------------------------------------------------


def test_plain_strings_round_trip_unencoded_and_human_readable():
    """The common case — `"personal"`, `"sso"` — must stay a readable string on the wire, not
    become the JSON-quoted `'"personal"'`."""
    wire = _encode_map({"use_case": "personal"})
    assert wire == {"use_case": "personal"}
    assert _decode_map(wire) == {"use_case": "personal"}


def test_non_string_values_round_trip_through_json():
    original = {"enable": True, "count": 3, "credentials": {"key": "value"}}
    wire = _encode_map(original)
    assert all(isinstance(v, str) for v in wire.values())
    assert _decode_map(wire) == original


def test_a_bare_word_that_is_not_valid_json_decodes_as_the_raw_string():
    """A wire value written by a client that did not JSON-encode a plain string (or one written
    by `_encode_map`'s own unencoded-string path) must not fail to decode."""
    assert _decode_map({"method": "sso"}) == {"method": "sso"}


# --- DetectHardware -----------------------------------------------------------------------


@pytest.mark.slow
def test_detect_hardware_returns_a_real_profile_through_the_servicer():
    """A real subprocess call (Windows WMI via PowerShell, or /proc reads on Linux) — the same
    live-hardware guarantee `test_hardware_detect.py` establishes, exercised through the
    servicer's own wire-conversion layer this time.
    """
    from services.setup.generated import setup_pb2

    async def go():
        servicer = SetupServicer()
        response = await servicer.DetectHardware(setup_pb2.DetectHardwareRequest())
        return response

    response = asyncio.run(go())
    assert response.cpu_name
    assert response.cores > 0
    assert response.source in ("os_probe", "os_probe+external_report")


# --- RunWizard, in-process (no real network) ------------------------------------------------


def test_run_wizard_drives_a_full_personal_branch_through_the_servicer():
    """Drives `SetupServicer.RunWizard` directly (no real network) via the queue-based helper
    below — a queue is what lets the client-side answer generator react to each server-yielded
    step in turn, which a plain fixed sequence of pre-built answers cannot do for a genuinely
    bidirectional, request-reactive protocol.
    """
    steps_seen = asyncio.run(_drive_personal_branch())

    assert steps_seen[0] == "welcome"
    assert steps_seen[-1] == "finalize"
    assert "tunnel_exposure" not in steps_seen
    assert "groups" not in steps_seen


async def _drive_personal_branch():
    from services.setup.generated import setup_pb2 as pb

    servicer = SetupServicer(wizard_engine_factory=lambda: WizardEngine(launcher_path=Path("start.sh")))
    queue: asyncio.Queue = asyncio.Queue()

    async def answers():
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item

    steps_seen = []
    call = servicer.RunWizard(answers(), context=None)
    first = True
    async for step_msg in call:
        steps_seen.append(step_msg.step_id)
        if step_msg.is_final:
            break
        if first:
            await queue.put(pb.WizardAnswerMessage(step_id="welcome", skipped=False, data={"use_case": json.dumps("personal")}))
            first = False
        elif step_msg.step_id == "account":
            await queue.put(pb.WizardAnswerMessage(step_id="account", skipped=False, data={"method": json.dumps("sso")}))
        elif step_msg.step_id == "terms_of_service":
            await queue.put(pb.WizardAnswerMessage(step_id="terms_of_service", skipped=False, data={"accepted": json.dumps(True)}))
        else:
            await queue.put(pb.WizardAnswerMessage(step_id=step_msg.step_id, skipped=True))
    await queue.put(None)
    return steps_seen


def test_run_wizard_rejects_an_out_of_order_answer():
    """The servicer's own wire-level dispatch reaches `WizardEngine._validate_answer` — an
    answer for the wrong step must surface as a real error over the RPC, not be silently
    accepted or hang the stream.
    """
    from services.setup.generated import setup_pb2 as pb

    async def go():
        servicer = SetupServicer(wizard_engine_factory=lambda: WizardEngine(launcher_path=Path("start.sh")))

        async def bad_answers():
            yield pb.WizardAnswerMessage(step_id="welcome", skipped=False, data={"use_case": json.dumps("personal")})
            yield pb.WizardAnswerMessage(step_id="billing", skipped=True)  # wrong step

        call = servicer.RunWizard(bad_answers(), context=None)
        async for _ in call:
            pass

    with pytest.raises(ValueError, match="expected an answer"):
        asyncio.run(go())


# --- ProvisionVenvs -------------------------------------------------------------------------


@pytest.mark.slow
def test_provision_venvs_dispatches_off_the_event_loop_and_returns_a_real_report(tmp_path):
    """`provision_clone` is synchronous and runs real `pip`/`venv` subprocesses — this proves
    the servicer's `run_in_executor` dispatch actually works end to end against a real clone,
    not just that the call doesn't raise.
    """
    from services.setup.generated import setup_pb2
    from services.setup.venv_provisioning import BASE_REQUIREMENTS_RELPATH

    clone = tmp_path / "clone"
    base = clone / BASE_REQUIREMENTS_RELPATH
    base.parent.mkdir(parents=True)
    base.write_text("", encoding="utf-8")
    pkg = clone / "core" / "tiny"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    async def go():
        servicer = SetupServicer()
        request = setup_pb2.ProvisionVenvsRequest(clone_dir=str(clone))
        return await servicer.ProvisionVenvs(request)

    response = asyncio.run(go())
    assert response.fully_provisioned, [(o.import_path, o.error_detail) for o in response.outcomes]
    assert len(response.outcomes) == 1
    assert response.outcomes[0].import_path == "core.tiny"


# --- real end-to-end over an actual socket ---------------------------------------------------


@pytest.mark.slow
def test_a_real_client_can_drive_the_whole_wizard_over_an_actual_grpc_connection():
    """No stub of the thing under test: a real `grpc.aio` server on a real loopback socket, a
    real client stub, a real bidirectional stream. This is the scenario manually verified while
    building this module (a full `team`-branch run correctly included `groups`, correctly
    excluded nothing it should have kept) — pinned here as a permanent regression check.
    """
    from services.setup.generated import setup_pb2, setup_pb2_grpc

    async def go():
        address = "127.0.0.1:19700"
        server = await serve(address)
        try:
            channel = grpc.aio.insecure_channel(address)
            stub = setup_pb2_grpc.SetupServiceStub(channel)

            hw = await stub.DetectHardware(setup_pb2.DetectHardwareRequest())
            assert hw.cpu_name

            queue: asyncio.Queue = asyncio.Queue()

            async def answers():
                while True:
                    item = await queue.get()
                    if item is None:
                        return
                    yield item

            call = stub.RunWizard(answers())
            steps_seen = []
            first = True
            async for step_msg in call:
                steps_seen.append(step_msg.step_id)
                if step_msg.is_final:
                    break
                if first:
                    await queue.put(setup_pb2.WizardAnswerMessage(step_id="welcome", skipped=False, data={"use_case": json.dumps("team")}))
                    first = False
                elif step_msg.step_id == "account":
                    await queue.put(setup_pb2.WizardAnswerMessage(step_id="account", skipped=False, data={"method": json.dumps("sso")}))
                elif step_msg.step_id == "terms_of_service":
                    await queue.put(setup_pb2.WizardAnswerMessage(step_id="terms_of_service", skipped=False, data={"accepted": json.dumps(True)}))
                else:
                    await queue.put(setup_pb2.WizardAnswerMessage(step_id=step_msg.step_id, skipped=True))
            await queue.put(None)
            await channel.close()
            return steps_seen
        finally:
            await server.stop(None)

    steps_seen = asyncio.run(go())
    assert steps_seen == [
        "welcome", "account", "run_on_startup", "tunnel_exposure", "groups", "billing",
        "sms_notifications", "receipt_ingestion", "address_checking", "hardware_tier",
        "terms_of_service", "finalize",
    ]
