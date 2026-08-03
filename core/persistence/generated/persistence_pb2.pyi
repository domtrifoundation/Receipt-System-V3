from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class BlobRefMessage(_message.Message):
    __slots__ = ("logical_id",)
    LOGICAL_ID_FIELD_NUMBER: _ClassVar[int]
    logical_id: str
    def __init__(self, logical_id: _Optional[str] = ...) -> None: ...

class ReferenceIdentifierMessage(_message.Message):
    __slots__ = ("kind", "value", "normalized")
    KIND_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    NORMALIZED_FIELD_NUMBER: _ClassVar[int]
    kind: str
    value: str
    normalized: str
    def __init__(self, kind: _Optional[str] = ..., value: _Optional[str] = ..., normalized: _Optional[str] = ...) -> None: ...

class ReceiptMessage(_message.Message):
    __slots__ = ("receipt_id", "user_id", "blob", "group_id", "vendor_id", "vendor_name", "transaction_date", "currency", "total_amount", "vat_amount", "identifiers", "fields_json", "created_at", "updated_at", "schema_version")
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    BLOB_FIELD_NUMBER: _ClassVar[int]
    GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    VENDOR_ID_FIELD_NUMBER: _ClassVar[int]
    VENDOR_NAME_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_DATE_FIELD_NUMBER: _ClassVar[int]
    CURRENCY_FIELD_NUMBER: _ClassVar[int]
    TOTAL_AMOUNT_FIELD_NUMBER: _ClassVar[int]
    VAT_AMOUNT_FIELD_NUMBER: _ClassVar[int]
    IDENTIFIERS_FIELD_NUMBER: _ClassVar[int]
    FIELDS_JSON_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    receipt_id: str
    user_id: str
    blob: BlobRefMessage
    group_id: str
    vendor_id: str
    vendor_name: str
    transaction_date: str
    currency: str
    total_amount: str
    vat_amount: str
    identifiers: _containers.RepeatedCompositeFieldContainer[ReferenceIdentifierMessage]
    fields_json: str
    created_at: str
    updated_at: str
    schema_version: int
    def __init__(self, receipt_id: _Optional[str] = ..., user_id: _Optional[str] = ..., blob: _Optional[_Union[BlobRefMessage, _Mapping]] = ..., group_id: _Optional[str] = ..., vendor_id: _Optional[str] = ..., vendor_name: _Optional[str] = ..., transaction_date: _Optional[str] = ..., currency: _Optional[str] = ..., total_amount: _Optional[str] = ..., vat_amount: _Optional[str] = ..., identifiers: _Optional[_Iterable[_Union[ReferenceIdentifierMessage, _Mapping]]] = ..., fields_json: _Optional[str] = ..., created_at: _Optional[str] = ..., updated_at: _Optional[str] = ..., schema_version: _Optional[int] = ...) -> None: ...

class GetReceiptRequest(_message.Message):
    __slots__ = ("user_id", "receipt_id")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    receipt_id: str
    def __init__(self, user_id: _Optional[str] = ..., receipt_id: _Optional[str] = ...) -> None: ...

class ReceiptResponse(_message.Message):
    __slots__ = ("receipt", "error_code", "error_detail")
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    receipt: ReceiptMessage
    error_code: str
    error_detail: str
    def __init__(self, receipt: _Optional[_Union[ReceiptMessage, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class SaveReceiptRequest(_message.Message):
    __slots__ = ("receipt", "actor")
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    receipt: ReceiptMessage
    actor: str
    def __init__(self, receipt: _Optional[_Union[ReceiptMessage, _Mapping]] = ..., actor: _Optional[str] = ...) -> None: ...

class SaveReceiptResponse(_message.Message):
    __slots__ = ("receipt_id", "historian_event_id", "error_code", "error_detail")
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    HISTORIAN_EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    receipt_id: str
    historian_event_id: str
    error_code: str
    error_detail: str
    def __init__(self, receipt_id: _Optional[str] = ..., historian_event_id: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListReceiptsRequest(_message.Message):
    __slots__ = ("user_id", "after_receipt_id", "limit")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    AFTER_RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    after_receipt_id: str
    limit: int
    def __init__(self, user_id: _Optional[str] = ..., after_receipt_id: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class ListReceiptsResponse(_message.Message):
    __slots__ = ("receipts", "error_code", "error_detail")
    RECEIPTS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    receipts: _containers.RepeatedCompositeFieldContainer[ReceiptMessage]
    error_code: str
    error_detail: str
    def __init__(self, receipts: _Optional[_Iterable[_Union[ReceiptMessage, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class PutBlobRequest(_message.Message):
    __slots__ = ("original_bytes", "stored_bytes", "codec", "user_id")
    ORIGINAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    STORED_BYTES_FIELD_NUMBER: _ClassVar[int]
    CODEC_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    original_bytes: bytes
    stored_bytes: bytes
    codec: str
    user_id: str
    def __init__(self, original_bytes: _Optional[bytes] = ..., stored_bytes: _Optional[bytes] = ..., codec: _Optional[str] = ..., user_id: _Optional[str] = ...) -> None: ...

class PutBlobResponse(_message.Message):
    __slots__ = ("blob", "deduplicated", "durably_backed_up", "fully_synced", "confirmed_targets", "failed_targets", "error_code", "error_detail")
    BLOB_FIELD_NUMBER: _ClassVar[int]
    DEDUPLICATED_FIELD_NUMBER: _ClassVar[int]
    DURABLY_BACKED_UP_FIELD_NUMBER: _ClassVar[int]
    FULLY_SYNCED_FIELD_NUMBER: _ClassVar[int]
    CONFIRMED_TARGETS_FIELD_NUMBER: _ClassVar[int]
    FAILED_TARGETS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    blob: BlobRefMessage
    deduplicated: bool
    durably_backed_up: bool
    fully_synced: bool
    confirmed_targets: _containers.RepeatedScalarFieldContainer[str]
    failed_targets: _containers.RepeatedScalarFieldContainer[str]
    error_code: str
    error_detail: str
    def __init__(self, blob: _Optional[_Union[BlobRefMessage, _Mapping]] = ..., deduplicated: _Optional[bool] = ..., durably_backed_up: _Optional[bool] = ..., fully_synced: _Optional[bool] = ..., confirmed_targets: _Optional[_Iterable[str]] = ..., failed_targets: _Optional[_Iterable[str]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class GetBlobRequest(_message.Message):
    __slots__ = ("logical_id", "verify", "user_id")
    LOGICAL_ID_FIELD_NUMBER: _ClassVar[int]
    VERIFY_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    logical_id: str
    verify: bool
    user_id: str
    def __init__(self, logical_id: _Optional[str] = ..., verify: _Optional[bool] = ..., user_id: _Optional[str] = ...) -> None: ...

class GetBlobResponse(_message.Message):
    __slots__ = ("data", "codec", "byte_size", "error_code", "error_detail")
    DATA_FIELD_NUMBER: _ClassVar[int]
    CODEC_FIELD_NUMBER: _ClassVar[int]
    BYTE_SIZE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    codec: str
    byte_size: int
    error_code: str
    error_detail: str
    def __init__(self, data: _Optional[bytes] = ..., codec: _Optional[str] = ..., byte_size: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class HistoryEntry(_message.Message):
    __slots__ = ("track", "event_id", "occurred_at", "table_name", "row_id", "before_json", "after_json", "actor", "program_version", "receipt_id", "run_id", "stage", "summary", "detail_json", "triggered_by")
    TRACK_FIELD_NUMBER: _ClassVar[int]
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    TABLE_NAME_FIELD_NUMBER: _ClassVar[int]
    ROW_ID_FIELD_NUMBER: _ClassVar[int]
    BEFORE_JSON_FIELD_NUMBER: _ClassVar[int]
    AFTER_JSON_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    PROGRAM_VERSION_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    DETAIL_JSON_FIELD_NUMBER: _ClassVar[int]
    TRIGGERED_BY_FIELD_NUMBER: _ClassVar[int]
    track: str
    event_id: str
    occurred_at: str
    table_name: str
    row_id: str
    before_json: str
    after_json: str
    actor: str
    program_version: str
    receipt_id: str
    run_id: str
    stage: str
    summary: str
    detail_json: str
    triggered_by: str
    def __init__(self, track: _Optional[str] = ..., event_id: _Optional[str] = ..., occurred_at: _Optional[str] = ..., table_name: _Optional[str] = ..., row_id: _Optional[str] = ..., before_json: _Optional[str] = ..., after_json: _Optional[str] = ..., actor: _Optional[str] = ..., program_version: _Optional[str] = ..., receipt_id: _Optional[str] = ..., run_id: _Optional[str] = ..., stage: _Optional[str] = ..., summary: _Optional[str] = ..., detail_json: _Optional[str] = ..., triggered_by: _Optional[str] = ...) -> None: ...

class ReceiptHistoryRequest(_message.Message):
    __slots__ = ("user_id", "receipt_id")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    receipt_id: str
    def __init__(self, user_id: _Optional[str] = ..., receipt_id: _Optional[str] = ...) -> None: ...

class ReceiptHistoryResponse(_message.Message):
    __slots__ = ("entries", "error_code", "error_detail")
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[HistoryEntry]
    error_code: str
    error_detail: str
    def __init__(self, entries: _Optional[_Iterable[_Union[HistoryEntry, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListExportProvidersRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListExportProvidersResponse(_message.Message):
    __slots__ = ("provider_names",)
    PROVIDER_NAMES_FIELD_NUMBER: _ClassVar[int]
    provider_names: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, provider_names: _Optional[_Iterable[str]] = ...) -> None: ...

class GenerateExportRequest(_message.Message):
    __slots__ = ("user_id", "provider_name", "params_json")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_NAME_FIELD_NUMBER: _ClassVar[int]
    PARAMS_JSON_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    provider_name: str
    params_json: str
    def __init__(self, user_id: _Optional[str] = ..., provider_name: _Optional[str] = ..., params_json: _Optional[str] = ...) -> None: ...

class GenerateExportResponse(_message.Message):
    __slots__ = ("export_blob", "format", "generated_at", "export_id", "extra_artifacts_json", "error_code", "error_detail")
    EXPORT_BLOB_FIELD_NUMBER: _ClassVar[int]
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    GENERATED_AT_FIELD_NUMBER: _ClassVar[int]
    EXPORT_ID_FIELD_NUMBER: _ClassVar[int]
    EXTRA_ARTIFACTS_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    export_blob: BlobRefMessage
    format: str
    generated_at: str
    export_id: str
    extra_artifacts_json: str
    error_code: str
    error_detail: str
    def __init__(self, export_blob: _Optional[_Union[BlobRefMessage, _Mapping]] = ..., format: _Optional[str] = ..., generated_at: _Optional[str] = ..., export_id: _Optional[str] = ..., extra_artifacts_json: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class FieldConflictMessage(_message.Message):
    __slots__ = ("receipt_id", "field", "original_value", "canonical_value", "reimported_value")
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    FIELD_FIELD_NUMBER: _ClassVar[int]
    ORIGINAL_VALUE_FIELD_NUMBER: _ClassVar[int]
    CANONICAL_VALUE_FIELD_NUMBER: _ClassVar[int]
    REIMPORTED_VALUE_FIELD_NUMBER: _ClassVar[int]
    receipt_id: str
    field: str
    original_value: str
    canonical_value: str
    reimported_value: str
    def __init__(self, receipt_id: _Optional[str] = ..., field: _Optional[str] = ..., original_value: _Optional[str] = ..., canonical_value: _Optional[str] = ..., reimported_value: _Optional[str] = ...) -> None: ...

class ReimportUpload(_message.Message):
    __slots__ = ("user_id", "file_path", "actor_user_id", "content_scan_passed")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    FILE_PATH_FIELD_NUMBER: _ClassVar[int]
    ACTOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_SCAN_PASSED_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    file_path: str
    actor_user_id: str
    content_scan_passed: bool
    def __init__(self, user_id: _Optional[str] = ..., file_path: _Optional[str] = ..., actor_user_id: _Optional[str] = ..., content_scan_passed: _Optional[bool] = ...) -> None: ...

class ReimportResultMessage(_message.Message):
    __slots__ = ("fields_applied", "conflicts", "flag_id", "receipts_touched", "error_code", "error_detail", "rejected_fields")
    FIELDS_APPLIED_FIELD_NUMBER: _ClassVar[int]
    CONFLICTS_FIELD_NUMBER: _ClassVar[int]
    FLAG_ID_FIELD_NUMBER: _ClassVar[int]
    RECEIPTS_TOUCHED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    REJECTED_FIELDS_FIELD_NUMBER: _ClassVar[int]
    fields_applied: int
    conflicts: _containers.RepeatedCompositeFieldContainer[FieldConflictMessage]
    flag_id: str
    receipts_touched: _containers.RepeatedScalarFieldContainer[str]
    error_code: str
    error_detail: str
    rejected_fields: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, fields_applied: _Optional[int] = ..., conflicts: _Optional[_Iterable[_Union[FieldConflictMessage, _Mapping]]] = ..., flag_id: _Optional[str] = ..., receipts_touched: _Optional[_Iterable[str]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ..., rejected_fields: _Optional[_Iterable[str]] = ...) -> None: ...

class EnableSyncRequest(_message.Message):
    __slots__ = ("user_id", "provider_name", "target_path", "enabled")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_NAME_FIELD_NUMBER: _ClassVar[int]
    TARGET_PATH_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    provider_name: str
    target_path: str
    enabled: bool
    def __init__(self, user_id: _Optional[str] = ..., provider_name: _Optional[str] = ..., target_path: _Optional[str] = ..., enabled: _Optional[bool] = ...) -> None: ...

class SyncStatusRequest(_message.Message):
    __slots__ = ("user_id", "provider_name")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_NAME_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    provider_name: str
    def __init__(self, user_id: _Optional[str] = ..., provider_name: _Optional[str] = ...) -> None: ...

class SyncStatusResponse(_message.Message):
    __slots__ = ("state", "last_receipt_id", "last_synced_at", "paused_reason", "mirrored", "error_code", "error_detail")
    STATE_FIELD_NUMBER: _ClassVar[int]
    LAST_RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    LAST_SYNCED_AT_FIELD_NUMBER: _ClassVar[int]
    PAUSED_REASON_FIELD_NUMBER: _ClassVar[int]
    MIRRORED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    state: str
    last_receipt_id: str
    last_synced_at: str
    paused_reason: str
    mirrored: int
    error_code: str
    error_detail: str
    def __init__(self, state: _Optional[str] = ..., last_receipt_id: _Optional[str] = ..., last_synced_at: _Optional[str] = ..., paused_reason: _Optional[str] = ..., mirrored: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class RestoreRequest(_message.Message):
    __slots__ = ("snapshot_id", "target_dir", "snapshot_source", "scope", "user_id")
    SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_DIR_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_SOURCE_FIELD_NUMBER: _ClassVar[int]
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    snapshot_id: str
    target_dir: str
    snapshot_source: str
    scope: str
    user_id: str
    def __init__(self, snapshot_id: _Optional[str] = ..., target_dir: _Optional[str] = ..., snapshot_source: _Optional[str] = ..., scope: _Optional[str] = ..., user_id: _Optional[str] = ...) -> None: ...

class RestoreStatusRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class RestoreJobResponse(_message.Message):
    __slots__ = ("job_id", "snapshot_id", "scope", "stage", "started_at", "blobs_restored", "report", "error_code", "error_detail")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    BLOBS_RESTORED_FIELD_NUMBER: _ClassVar[int]
    REPORT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    snapshot_id: str
    scope: str
    stage: str
    started_at: str
    blobs_restored: int
    report: VerificationReportResponse
    error_code: str
    error_detail: str
    def __init__(self, job_id: _Optional[str] = ..., snapshot_id: _Optional[str] = ..., scope: _Optional[str] = ..., stage: _Optional[str] = ..., started_at: _Optional[str] = ..., blobs_restored: _Optional[int] = ..., report: _Optional[_Union[VerificationReportResponse, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class VerifyRequest(_message.Message):
    __slots__ = ("target_dir", "require_blobs_present")
    TARGET_DIR_FIELD_NUMBER: _ClassVar[int]
    REQUIRE_BLOBS_PRESENT_FIELD_NUMBER: _ClassVar[int]
    target_dir: str
    require_blobs_present: bool
    def __init__(self, target_dir: _Optional[str] = ..., require_blobs_present: _Optional[bool] = ...) -> None: ...

class VerificationReportResponse(_message.Message):
    __slots__ = ("total_refs_checked", "orphaned_logical_ids", "orphaned_physical_files", "hash_mismatches", "clean", "error_code", "error_detail")
    TOTAL_REFS_CHECKED_FIELD_NUMBER: _ClassVar[int]
    ORPHANED_LOGICAL_IDS_FIELD_NUMBER: _ClassVar[int]
    ORPHANED_PHYSICAL_FILES_FIELD_NUMBER: _ClassVar[int]
    HASH_MISMATCHES_FIELD_NUMBER: _ClassVar[int]
    CLEAN_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    total_refs_checked: int
    orphaned_logical_ids: _containers.RepeatedScalarFieldContainer[str]
    orphaned_physical_files: _containers.RepeatedScalarFieldContainer[str]
    hash_mismatches: _containers.RepeatedScalarFieldContainer[str]
    clean: bool
    error_code: str
    error_detail: str
    def __init__(self, total_refs_checked: _Optional[int] = ..., orphaned_logical_ids: _Optional[_Iterable[str]] = ..., orphaned_physical_files: _Optional[_Iterable[str]] = ..., hash_mismatches: _Optional[_Iterable[str]] = ..., clean: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
