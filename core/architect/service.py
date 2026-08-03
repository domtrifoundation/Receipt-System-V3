"""The `ArchitectServicer` gRPC servicer (`architect.proto`) — the real assembly point
tying the read registry (`registry/read.py`), temporal_learning's moderation pipeline
(`temporal_learning/moderation_queue.py`), and the vendor directory
(`vendor_directory/directory.py`) to the wire surface every other API actually calls.

**This was a real, complete gap, not a documented placeholder**: every module this
servicer calls already existed and was independently tested, but nothing in this package
ever constructed one of each and answered a single RPC — `architect.proto` defined a
contract that Persistence, Matching, Review/Flagging, Billing, and Execution Core were
all meant to call, and there was no server on the other end of it at all. The same shape
of gap this session found repeatedly elsewhere (Ingestion's `GoogleDriveSource`/
`webhook_manager`, Preprocessing's metrics collector, Accounting Sync's own
`sync_engine.py`).

**`ContributionRequest.staff_authored` is a real, named, NOT-enforced gap.** The proto's
own comment is explicit: "Set only by a caller the server has already resolved as staff.
Never trusted from a claim the caller makes about itself — the server checks the
session's own role." This servicer does not check anything today — no Auth API client
exists anywhere in this codebase's `service.py` files to check a session's role against
(confirmed: no other API's `service.py` does this either), so `staff_authored` is
currently trusted verbatim from the request. This is flagged here rather than silently
built as if it were real enforcement; a real deployment MUST NOT expose this RPC to an
untrusted caller until a Gateway-level or Auth-backed check is wired in front of it.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from .contracts import DefinitionKind, RegistryDefinition, TaxonomyResult, TaxonomyType, VendorRecord, VendorSearchResult
from .registry.read import DefinitionRegistry
from .temporal_learning.contracts import Contribution, ContributionResult
from .temporal_learning.contribution import contribution_for_correction
from .temporal_learning.entities import EntityManager
from .temporal_learning.moderation_queue import ModerationQueue
from .vendor_directory.directory import DEFAULT_SEARCH_LIMIT, VendorDirectory

DEFAULT_ADDRESS = "127.0.0.1:50060"

__all__ = ["ArchitectServicer", "DEFAULT_ADDRESS", "serve"]


def _definition_to_pb(pb, d: RegistryDefinition):
    msg = pb.Definition(
        code=d.code, label=d.label, kind=d.kind.value, description=d.description,
        deprecated=d.deprecated,
    )
    msg.attributes.update({k: str(v) for k, v in d.attributes.items()})
    parent_code = getattr(d, "parent_code", None)
    if parent_code is not None:
        msg.parent_code = parent_code
    value_pattern = getattr(d, "value_pattern", None)
    if value_pattern:
        msg.value_pattern = value_pattern
        msg.example = getattr(d, "example", "")
        msg.multi_valued = getattr(d, "multi_valued", False)
    default_severity = getattr(d, "default_severity", None)
    if default_severity is not None:
        msg.default_severity = default_severity
        msg.raised_by.extend(getattr(d, "raised_by", ()))
    return msg


def _taxonomy_response(pb, result: TaxonomyResult):
    response = pb.TaxonomyResponse()
    for d in result.definitions:
        response.definitions.append(_definition_to_pb(pb, d))
    if result.error is not None:
        response.error_code = result.error.code
        response.error_detail = result.error.detail
    return response


def _contribution_to_pb(pb, c: Contribution):
    msg = pb.ContributionInfo(
        contribution_id=c.contribution_id, contributor=c.contributor,
        target_entity_type=c.target_entity_type, target_entity_id=c.target_entity_id or "",
        target_layer=c.target_layer.value, llm_prescreen_verdict=c.llm_prescreen_verdict or "",
        staff_review_status=c.staff_review_status, merged=c.merged,
        submitted_at=c.submitted_at.isoformat(), curation_type=c.curation_type or "",
    )
    msg.proposed_change.update({k: str(v) for k, v in c.proposed_change.items()})
    return msg


def _contribution_response(pb, result: ContributionResult):
    response = pb.ContributionResponse()
    if result.contribution is not None:
        response.contribution.CopyFrom(_contribution_to_pb(pb, result.contribution))
    if result.error is not None:
        response.error_code = result.error.code
        response.error_detail = result.error.detail
    return response


def _vendor_record_to_pb(pb, r: VendorRecord):
    return pb.VendorRecordInfo(
        corporation_id=r.corporation_id, name=r.name, corporate_tin=r.corporate_tin,
        layer=r.layer.value, category_code=r.category_code or "", aliases=list(r.aliases),
        branch_count=r.branch_count,
    )


def _vendor_search_response(pb, result: VendorSearchResult):
    response = pb.VendorSearchResponse()
    for r in result.records:
        response.records.append(_vendor_record_to_pb(pb, r))
    if result.error is not None:
        response.error_code = result.error.code
        response.error_detail = result.error.detail
    return response


class ArchitectServicer:
    """Implements `ArchitectService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        registry: DefinitionRegistry | None = None,
        entities: EntityManager | None = None,
        queue: ModerationQueue | None = None,
        directory: VendorDirectory | None = None,
    ) -> None:
        self._registry = registry if registry is not None else DefinitionRegistry()
        self._entities = entities if entities is not None else EntityManager()
        self._queue = queue if queue is not None else ModerationQueue(self._entities)
        self._directory = directory if directory is not None else VendorDirectory(self._entities)

    async def GetTaxonomy(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import architect_pb2 as pb

        try:
            kind = DefinitionKind(request.kind)
        except ValueError:
            from .errors import ErrorCode, message_for

            response = pb.TaxonomyResponse()
            response.error_code = ErrorCode.UNKNOWN_KIND
            response.error_detail = message_for(ErrorCode.UNKNOWN_KIND)
            return response

        if request.parent_code:
            result = self._registry.children(request.parent_code)
        else:
            result = self._registry.list(kind, include_deprecated=request.include_deprecated)
        return _taxonomy_response(pb, result)

    async def SubmitContribution(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import architect_pb2 as pb

        built = contribution_for_correction(
            entity_type=request.target_entity_type,
            entity_id=request.target_entity_id or None,
            change=dict(request.proposed_change),
            contributor=request.contributor,
            staff_authored=request.staff_authored,
        )
        if built.error is not None:
            return _contribution_response(pb, built)

        submitted = self._queue.submit(built.contribution)
        processed = await self._queue.process(submitted.contribution.contribution_id)
        return _contribution_response(pb, processed)

    async def ReviewContribution(self, request, context=None):  # noqa: N802 - gRPC naming
        """A staff decision. On approval, merges immediately — the proto exposes no
        separate merge RPC, and there is no reason for a caller to hold an approved,
        eligible contribution unmerged."""
        from .generated import architect_pb2 as pb

        reviewed = self._queue.review(
            request.contribution_id, request.reviewer, request.approved, request.reason,
        )
        if reviewed.error is not None or not request.approved:
            return _contribution_response(pb, reviewed)

        merged = self._queue.merge(request.contribution_id)
        return _contribution_response(pb, merged)

    async def SearchVendorDirectory(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import architect_pb2 as pb

        result = self._directory.search(
            request.query, user_id=request.user_id or None,
            limit=request.limit if request.limit > 0 else DEFAULT_SEARCH_LIMIT,
        )
        return _vendor_search_response(pb, result)


async def serve(address: str = DEFAULT_ADDRESS):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import architect_pb2_grpc

    server = grpc.aio.server()
    architect_pb2_grpc.add_ArchitectServiceServicer_to_server(ArchitectServicer(), server)
    server.add_insecure_port(address)
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr)
        print(f"listening on {addr}", file=sys.stderr)
        await srv.wait_for_termination()

    asyncio.run(_main())
