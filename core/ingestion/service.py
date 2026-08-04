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

from .content_security_client import ContentSecurityClient
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
    ) -> None:
        self._blob_store = blob_store
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
        from .generated import ingestion_pb2 as pb

        source_file = await self._direct_upload.receive(
            request.run_id, request.user_id, request.filename, request.declared_mime_type, request.content,
        )
        result = await normalize_source_file(
            source_file, self._blob_store, self._content_security,
            archival_codec=self._archival_codec, archival_quality=self._archival_quality,
        )
        self._record_metrics(result)
        return _normalization_response(pb, result)

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
        real backstop here, not a design gap in this RPC."""
        from .generated import ingestion_pb2 as pb

        try:
            await self._webhook_manager.handle_callback(request.channel_id, self._drive_credentials)
            return pb.WebhookAck(accepted=True)
        except UnknownSubscription:
            return pb.WebhookAck(accepted=False)
        except Exception:  # noqa: BLE001 - any Drive API failure still acks False, never raises to Gateway
            return pb.WebhookAck(accepted=False)

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


async def serve(address: str = DEFAULT_ADDRESS, *, blob_store: BlobStoreGateway):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import ingestion_pb2_grpc

    server = grpc.aio.server()
    ingestion_pb2_grpc.add_IngestionServiceServicer_to_server(
        IngestionServicer(blob_store), server
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
        from common.blob_client import GrpcBlobStoreClient
        from pathlib import Path as _Path
        client = GrpcBlobStoreClient(PERSISTENCE_ADDRESS, install_root=_Path.cwd().parent.parent)
        srv = await serve(addr, blob_store=client)
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('ingestion')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())
