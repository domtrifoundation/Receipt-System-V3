"""The `IngestionServicer` gRPC servicer (`ingestion.proto`) and the normalization
pipeline every source's output goes through identically (deep-dive §6, Format
Normalization deep-dive §3).

**The pipeline, in order, for every `SourceFile` regardless of which source produced
it**: Content Security scan (fail-closed, `content_security_client.py`) -> archival
re-encode (`format_normalization/codecs.py` for a plain raster image; the original bytes
themselves for a PDF, since re-encoding a multi-page container into a single-image codec
makes no sense) -> base-image rasterization (`format_normalization/raster.py`, one or more
pages). The archival branch and the base-image branch both start from the same original
bytes independently — neither depends on the other's output (Format Normalization
deep-dive §3's own "branches two ways from one common source, not sequentially").

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from .content_security_client import DEFAULT_CONTENT_SECURITY_ADDRESS, ContentSecurityClient
from .contracts import (
    BlobStoreGateway,
    IngestionError,
    IngestionErrorCode,
    NormalizedImage,
    NormalizationResult,
    SourceFile,
    SourceKind,
)
from .drive_assembly import GoogleDriveConfig, build_credential_provider, build_google_drive_source
from .errors import ContentSecurityUnavailable
from .format_normalization import errors as fn_errors
from .metrics import IngestionMetricsCollector
from .source_registry import SourceRegistry, SourceRegistryConfig
from .sources.direct_upload import DirectUploadSource
from .sources.scanner.capture_session import CaptureSessionStore
from .webhook_manager.errors import UnknownSubscription
from .webhook_manager.manager import WebhookManager
from .webhook_manager.subscription import DriveWebhookAdapter

DEFAULT_ADDRESS = "127.0.0.1:50074"

#: Owner-level, system-wide archival codec choice (Format Normalization deep-dive §3,
#: §9's config sketch) — never a per-user/tier lever.
DEFAULT_ARCHIVAL_CODEC = "avif"
DEFAULT_ARCHIVAL_QUALITY = 75


async def normalize_source_file(
    source_file: SourceFile,
    blob_store: BlobStoreGateway,
    content_security: ContentSecurityClient,
    *,
    archival_codec: str = DEFAULT_ARCHIVAL_CODEC,
    archival_quality: int = DEFAULT_ARCHIVAL_QUALITY,
) -> NormalizationResult:
    from .format_normalization.codecs import encode_archival
    from .format_normalization.raster import rasterize_all_pages

    raw_bytes = await blob_store.read_blob(source_file.raw_blob_ref)

    try:
        verdict = await content_security.scan(
            raw_bytes,
            claimed_mime_type=source_file.declared_mime_type,
            claimed_filename=source_file.original_filename,
            blob_ref=source_file.raw_blob_ref.logical_id,
            requesting_user_id=source_file.user_id,
            run_id=source_file.run_id,
        )
    except ContentSecurityUnavailable as exc:
        # Fail closed (deep-dive §6, errors.py's own docstring) — unreachable/timed-out
        # verification is treated the same as a failed scan, never as permission.
        return NormalizationResult(
            images=(), archival_blob_ref=None,
            error=IngestionError(IngestionErrorCode.CONTENT_SECURITY_UNAVAILABLE, str(exc)),
        )
    if not verdict.safe:
        return NormalizationResult(
            images=(), archival_blob_ref=None,
            error=IngestionError(IngestionErrorCode.CONTENT_SECURITY_REJECTED, verdict.rejection_reason),
        )

    from core.preprocessing.raster import sniff_format

    try:
        fmt = sniff_format(raw_bytes)
    except Exception as exc:  # noqa: BLE001 - an unrecognized format is a data error, not a crash
        return NormalizationResult(
            images=(), archival_blob_ref=None,
            error=IngestionError(IngestionErrorCode.UNSUPPORTED_FORMAT, str(exc)),
        )

    # Archival branch: re-encode for a plain image; store the original bytes as-is for a
    # PDF (a multi-page container has no meaningful single-image codec re-encode).
    try:
        if fmt == "pdf":
            archival_bytes = raw_bytes
        else:
            archival_bytes = await encode_archival(raw_bytes, codec=archival_codec, quality=archival_quality)
        archival_ref = await blob_store.write_blob(archival_bytes)
    except fn_errors.CodecEncodeFailed as exc:
        return NormalizationResult(
            images=(), archival_blob_ref=None,
            error=IngestionError(IngestionErrorCode.NORMALIZATION_FAILED, str(exc)),
        )

    # Base-image branch: rasterize every page independently of the archival branch above.
    try:
        pages = await rasterize_all_pages(raw_bytes)
    except (fn_errors.RasterFailed, fn_errors.UnsupportedFormat) as exc:
        return NormalizationResult(
            images=(), archival_blob_ref=archival_ref,
            error=IngestionError(IngestionErrorCode.NORMALIZATION_FAILED, str(exc)),
        )

    images = []
    for page_index, page_bytes in enumerate(pages):
        image_ref = await blob_store.write_blob(page_bytes)
        images.append(
            NormalizedImage(image_ref=image_ref, page_index=page_index, source=source_file.source)
        )
    return NormalizationResult(images=tuple(images), archival_blob_ref=archival_ref)


class IngestionServicer:
    """Implements `IngestionService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        blob_store: BlobStoreGateway,
        *,
        registry: SourceRegistry | None = None,
        content_security: ContentSecurityClient | None = None,
        archival_codec: str = DEFAULT_ARCHIVAL_CODEC,
        archival_quality: int = DEFAULT_ARCHIVAL_QUALITY,
        google_drive: GoogleDriveConfig | None = None,
        source_registry_config: SourceRegistryConfig | None = None,
        execution_core_address: str | None = None,
        log_writer=None,
    ) -> None:
        self._blob_store = blob_store
        #: Real trigger wiring, added post-launch: `None` degrades to "normalize only,
        #: don't submit for processing" (matches a caller with no Execution Core to talk
        #: to, e.g. an isolated unit test of normalization alone) rather than raising.
        #: `"127.0.0.1:50068"` (Execution Core's own `DEFAULT_ADDRESS`) is the real
        #: default for an actual running install.
        self._execution_core_address = execution_core_address
        #: Real, previously-missing observability: every one of this file's own
        #: best-effort `except Exception` catches used to genuinely vanish -- confirmed
        #: live, `core/logs/writer.py`'s `LogWriter` (the real write path every API is
        #: meant to log through, per `v3-deepdive-18-logs-api.md`'s own "every API in
        #: this batch writes through this one") had zero callers anywhere outside
        #: `core/logs/` itself. One shared instance per process, matching that module's
        #: own "one instance per process" convention -- never one per call. Injectable so
        #: a test never writes real files to this machine's own default log root
        #: (`core/logs/paths.py`'s own `~/.resibo/logs` fallback).
        from core.logs.writer import LogWriter

        self._log_writer = log_writer if log_writer is not None else LogWriter()
        self._content_security = content_security or ContentSecurityClient()
        self._archival_codec = archival_codec
        self._archival_quality = archival_quality
        self._metrics = IngestionMetricsCollector()
        self._direct_upload = DirectUploadSource(blob_store)
        google_drive = google_drive or GoogleDriveConfig()
        # One credential provider instance, shared between the download path
        # (`GoogleDriveSource`) and the webhook path (`DriveWebhookAdapter`) — resolving
        # `credential_strategy` twice independently could let the two paths disagree
        # about which strategy is active.
        drive_credentials = build_credential_provider(google_drive)
        if registry is not None:
            self._registry = registry
        else:
            # `GoogleDriveSource` was built and independently tested but never actually
            # constructed/registered anywhere — the real gap this assembly closes
            # (`drive_assembly.py`'s own module docstring). A self-hosted install with
            # no Drive folder configured still degrades cleanly: `GoogleDriveSource.
            # is_available()` reports `False` without a `folder_id`, so registering it
            # unconditionally is safe (deep-dive §1's own "direct-upload-only" guarantee).
            drive_source = build_google_drive_source(drive_credentials, google_drive, blob_store, self._metrics)
            self._registry = SourceRegistry(
                {SourceKind.DIRECT_UPLOAD: self._direct_upload, SourceKind.GOOGLE_DRIVE: drive_source},
                source_registry_config or SourceRegistryConfig(),
            )
        self._scan_sessions = CaptureSessionStore()

        # `webhook_manager`'s own subscription/circadian/callback-handling logic existed
        # and was independently tested but nothing ever constructed or held one of these
        # — `HandleDriveWebhook` used to acknowledge every callback unconditionally
        # without doing anything at all. Real now, still unverified against a real Drive
        # webhook delivery (no real credentials/channel exist in this environment).
        webhook_adapter = (
            DriveWebhookAdapter(drive_credentials, google_drive.webhook_callback_url)
            if google_drive.webhook_callback_url else None
        )
        self._webhook_manager = WebhookManager(
            webhook_adapter,
            renewal_lead_time_hours=google_drive.webhook_renewal_lead_time_hours,
            fallback_poll_interval_hours=google_drive.fallback_poll_interval_hours,
        )
        self._drive_credentials = drive_credentials

    async def SubmitDirectUpload(self, request, context=None):  # noqa: N802 - gRPC naming
        """Real webapp/direct-upload trigger, closing a genuine, previously-confirmed
        gap: this method used to normalize a file and stop — nothing anywhere told
        Execution Core a receipt existed to process. Now calls `StartRun` then
        `SubmitReceipt` per normalized page once normalization succeeds. Errors from
        that call are logged-and-swallowed rather than failing the upload response — the
        file is genuinely, safely normalized and stored either way; a receipt that never
        got processed is a real gap the run-monitoring surface should show, not a reason
        to tell the uploader their upload failed when it plainly did not.
        """
        from .generated import ingestion_pb2 as pb

        source_file = await self._direct_upload.receive(
            request.run_id, request.user_id, request.filename, request.declared_mime_type, request.content,
        )
        result = await normalize_source_file(
            source_file, self._blob_store, self._content_security,
            archival_codec=self._archival_codec, archival_quality=self._archival_quality,
        )
        self._record_metrics(result)
        if result.error is None:
            await self._submit_for_processing(request.run_id, request.user_id, result)
        return _normalization_response(pb, result)

    async def _submit_for_processing(self, run_id: str, user_id: str, result: NormalizationResult) -> None:
        if self._execution_core_address is None:
            return
        try:
            import grpc

            from services.execution_core.generated import execution_core_pb2 as ec_pb
            from services.execution_core.generated import execution_core_pb2_grpc as ec_pb_grpc

            async with grpc.aio.insecure_channel(self._execution_core_address) as channel:
                stub = ec_pb_grpc.ExecutionCoreServiceStub(channel)
                start_response = await stub.StartRun(ec_pb.StartRunRequest(user_id=user_id, file_count=len(result.images)))
                if start_response.error_code:
                    return
                for image in result.images:
                    if image.image_ref is None:
                        continue
                    # A real, live-found bug: `run_id:page_index` collides across two
                    # different uploads that the debounce coalescer merges into the same
                    # run (both start at page_index 0) -- the second SubmitReceipt
                    # silently overwrote the first's Persistence row under the same
                    # receipt_id. The blob's own content hash is unique per real file
                    # regardless of coalescing, so it's what receipt_id is keyed on now.
                    await stub.SubmitReceipt(ec_pb.SubmitReceiptRequest(
                        run_id=start_response.run.run_id, user_id=user_id,
                        receipt_id=f"{image.image_ref.logical_id}:{image.page_index}",
                        source_blob_ref=image.image_ref.logical_id, content_hash=image.image_ref.logical_id,
                    ))
        except Exception as exc:  # noqa: BLE001 - best-effort, see this method's own caller's docstring
            from core.logs.contracts import LogLevel

            await self._log_writer.log_exception(
                "ingestion", f"failed to submit run {run_id!r} for processing", exc,
                run_id=run_id, user_id=user_id, level=LogLevel.ERROR,
            )

    async def StartScanSession(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import ingestion_pb2 as pb

        session = self._scan_sessions.start(request.run_id, request.user_id)
        self._metrics.increment("scan_sessions_started")
        return pb.ScanSessionResponse(session_id=session.session_id)

    async def SubmitScanFrame(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import ingestion_pb2 as pb

        response = pb.ScanFrameResponse()
        try:
            frame_index = self._scan_sessions.submit_frame(request.session_id, request.frame)
            response.frame_index = frame_index
        except KeyError:
            response.error_code = IngestionErrorCode.SOURCE_NOT_CONFIGURED.value
            response.error_detail = f"unknown or expired scan session {request.session_id!r}"
        return response

    async def FinalizeScanSession(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import ingestion_pb2 as pb
        from .errors import StitchFailed

        try:
            source_file = await self._scan_sessions.finalize(request.session_id, self._blob_store)
        except KeyError:
            response = pb.NormalizationResponse()
            response.error_code = IngestionErrorCode.SOURCE_NOT_CONFIGURED.value
            response.error_detail = f"unknown or expired scan session {request.session_id!r}"
            return response
        except StitchFailed as exc:
            response = pb.NormalizationResponse()
            response.error_code = IngestionErrorCode.STITCH_FAILED.value
            response.error_detail = str(exc)
            self._metrics.increment("stitch_failed_count")
            return response

        result = await normalize_source_file(
            source_file, self._blob_store, self._content_security,
            archival_codec=self._archival_codec, archival_quality=self._archival_quality,
        )
        self._record_metrics(result)
        self._metrics.increment("scan_sessions_finalized")
        return _normalization_response(pb, result)

    async def ListEnabledSources(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import ingestion_pb2 as pb

        response = pb.ListSourcesResponse()
        response.available_sources.extend(sorted(s.value for s in await self._registry.available_sources()))
        response.enabled_sources.extend(sorted(s.value for s in await self._registry.enabled_sources()))
        return response

    async def HandleDriveWebhook(self, request, context=None):  # noqa: N802 - gRPC naming
        """Delegates to `WebhookManager.handle_callback()` for real — this RPC used to
        acknowledge every callback unconditionally without doing anything at all
        (`webhook_manager`'s entire sub-API was disconnected from the running service).
        `accepted=False` for an unknown/unregistered channel or a Drive API failure —
        Drive's own retry behavior for a webhook that returns an error response is the
        real backstop here, not a design gap in this RPC.

        **Now also processes the real events it receives, closing another genuine gap**:
        `pending_events` used to be a real queue nothing ever drained — `WebhookManager`'s
        own docstring calls it "a stand-in for Execution Core's own not-yet-built debounce
        consumer." This downloads, normalizes, and submits each new/modified file for
        real processing immediately, the same real path `SubmitDirectUpload` uses.
        """
        from .generated import ingestion_pb2 as pb

        try:
            events = await self._webhook_manager.handle_callback(request.channel_id, self._drive_credentials)
        except UnknownSubscription:
            return pb.WebhookAck(accepted=False)
        except Exception as exc:  # noqa: BLE001 - any Drive API failure still acks False, never raises to Gateway
            from core.logs.contracts import LogLevel

            await self._log_writer.log_exception(
                "ingestion", f"Drive webhook callback failed for channel {request.channel_id!r}", exc, level=LogLevel.ERROR,
            )
            return pb.WebhookAck(accepted=False)

        await self._process_drive_events(events)
        return pb.WebhookAck(accepted=True)

    async def PollDriveFallback(self, request, context=None):  # noqa: N802 - gRPC naming
        """The real "every 24h by default" safety net (`settings.updates`-adjacent
        config, `GoogleDriveConfig.fallback_poll_interval_hours`) — real and callable,
        not yet invoked on a timer by anything (that requires a periodic caller, e.g.
        Task Scheduler API, which is real, separate wiring not yet done). Lists every
        file currently in the configured Drive folder and processes any this install
        hasn't already ingested (`already_written`-equivalent dedup happens naturally at
        Execution Core's own content-hash checkpoint, so a re-poll of an already-processed
        file is safe, not a duplicate).
        """
        from .generated import ingestion_pb2 as pb
        from .contracts import SourceKind
        from .sources.google_drive.drive_source import SourceUnavailable

        drive_source = self._registry._sources.get(SourceKind.GOOGLE_DRIVE)
        if drive_source is None:
            return pb.WebhookAck(accepted=False)
        try:
            files = await drive_source.list_new_files()
        except SourceUnavailable:
            return pb.WebhookAck(accepted=False)
        except Exception as exc:  # noqa: BLE001 - any Drive API failure acks False, never raises
            from core.logs.contracts import LogLevel

            await self._log_writer.log_exception("ingestion", "Drive fallback poll failed", exc, level=LogLevel.ERROR)
            return pb.WebhookAck(accepted=False)

        from .webhook_manager.contracts import ChangeEvent
        from .webhook_manager.contracts import WebhookProvider

        events = tuple(
            ChangeEvent(provider=WebhookProvider.GOOGLE_DRIVE, file_id=f["id"], change_type="added")
            for f in files
        )
        await self._process_drive_events(events)
        return pb.WebhookAck(accepted=True)

    async def _process_drive_events(self, events) -> None:
        """Shared by the real-time webhook path and the fallback poll — downloads,
        normalizes, and submits each event's own file for real processing. Single shared
        Drive folder, single effective user (`"local"`, matching this project's own
        single-tenant-mode convention, `common/blob_client.py`'s own default) — Drive
        ingestion has no real per-user mapping today; a per-user Drive connection is real,
        separate follow-up work."""
        from .contracts import SourceKind

        drive_source = self._registry._sources.get(SourceKind.GOOGLE_DRIVE)
        if drive_source is None:
            return
        for event in events:
            if event.change_type == "removed":
                continue
            try:
                source_file = await drive_source.download(
                    run_id=f"drive-{event.file_id}", user_id="local", file_id=event.file_id,
                    filename=event.file_id, mime_type="application/octet-stream",
                )
                result = await normalize_source_file(
                    source_file, self._blob_store, self._content_security,
                    archival_codec=self._archival_codec, archival_quality=self._archival_quality,
                )
                self._record_metrics(result)
                if result.error is None:
                    await self._submit_for_processing(source_file.run_id, source_file.user_id, result)
            except Exception as exc:  # noqa: BLE001 - one bad file must never stop the rest of the batch
                from core.logs.contracts import LogLevel

                await self._log_writer.log_exception(
                    "ingestion", f"Drive file {event.file_id!r} failed to process", exc, level=LogLevel.ERROR,
                )
                continue

    def _record_metrics(self, result: NormalizationResult) -> None:
        if result.error is None:
            self._metrics.increment("files_ingested")
        elif result.error.code == IngestionErrorCode.CONTENT_SECURITY_REJECTED:
            self._metrics.increment("files_rejected_by_content_security")
        elif result.error.code == IngestionErrorCode.NORMALIZATION_FAILED:
            self._metrics.increment("normalization_failed_count")


def _normalization_response(pb, result: NormalizationResult):
    response = pb.NormalizationResponse()
    if result.archival_blob_ref is not None:
        response.archival_blob_ref = result.archival_blob_ref.logical_id
    if result.error is not None:
        response.error_code = result.error.code.value
        response.error_detail = result.error.detail
    for image in result.images:
        msg = response.images.add()
        if image.image_ref is not None:
            msg.image_blob_ref = image.image_ref.logical_id
        msg.page_index = image.page_index
        msg.source = image.source.value
        if image.error is not None:
            msg.error_code = image.error.code.value
            msg.error_detail = image.error.detail
    return response


async def serve(
    address: str = DEFAULT_ADDRESS, *, blob_store: BlobStoreGateway,
    execution_core_address: str | None = None, content_security: ContentSecurityClient | None = None,
):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import ingestion_pb2_grpc

    server = grpc.aio.server()
    ingestion_pb2_grpc.add_IngestionServiceServicer_to_server(
        IngestionServicer(
            blob_store, execution_core_address=execution_core_address, content_security=content_security,
        ),
        server,
    )
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


PERSISTENCE_ADDRESS = "127.0.0.1:50076"

if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        from common.blob_client import GrpcBlobStoreClient, resolve_service_address
        from common.install_paths import resolve_install_root
        from pathlib import Path as _Path

        install_root = resolve_install_root(_Path(__file__))
        # Real, live-found gap: every one of these three peer addresses was either a
        # hardcoded fixed default or (for content_security) never resolved/passed at
        # all — confirmed live, a real install's SubmitDirectUpload failed every single
        # call with content_security_unavailable because ContentSecurityClient()'s own
        # hardcoded 127.0.0.1:50062 default is never where the real, dynamically-bound
        # (:0) Content Security service actually is. All three now resolve the same way
        # execution_core_address already did.
        persistence_address = (
            PERSISTENCE_ADDRESS if install_root is None
            else resolve_service_address(install_root, "persistence", PERSISTENCE_ADDRESS)
        )
        client = GrpcBlobStoreClient(persistence_address, install_root=_Path.cwd().parent.parent)
        execution_core_address = (
            "127.0.0.1:50068" if install_root is None
            else resolve_service_address(install_root, "execution_core", "127.0.0.1:50068")
        )
        content_security_address = (
            DEFAULT_CONTENT_SECURITY_ADDRESS if install_root is None
            else resolve_service_address(install_root, "content_security", DEFAULT_CONTENT_SECURITY_ADDRESS)
        )
        content_security = ContentSecurityClient(content_security_address)
        srv = await serve(
            addr, blob_store=client, execution_core_address=execution_core_address,
            content_security=content_security,
        )
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('ingestion')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())
