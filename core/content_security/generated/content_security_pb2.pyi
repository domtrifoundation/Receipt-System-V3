from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ScanRequest(_message.Message):
    __slots__ = ("content", "claimed_mime_type", "claimed_filename", "blob_ref", "requesting_user_id", "run_id")
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    CLAIMED_MIME_TYPE_FIELD_NUMBER: _ClassVar[int]
    CLAIMED_FILENAME_FIELD_NUMBER: _ClassVar[int]
    BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    REQUESTING_USER_ID_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    content: bytes
    claimed_mime_type: str
    claimed_filename: str
    blob_ref: str
    requesting_user_id: str
    run_id: str
    def __init__(self, content: _Optional[bytes] = ..., claimed_mime_type: _Optional[str] = ..., claimed_filename: _Optional[str] = ..., blob_ref: _Optional[str] = ..., requesting_user_id: _Optional[str] = ..., run_id: _Optional[str] = ...) -> None: ...

class ScanVerdict(_message.Message):
    __slots__ = ("safe", "detected_type", "rejection_reason", "requires_staff_review", "error_code", "provider_verdicts")
    class ProviderVerdictsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    SAFE_FIELD_NUMBER: _ClassVar[int]
    DETECTED_TYPE_FIELD_NUMBER: _ClassVar[int]
    REJECTION_REASON_FIELD_NUMBER: _ClassVar[int]
    REQUIRES_STAFF_REVIEW_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_VERDICTS_FIELD_NUMBER: _ClassVar[int]
    safe: bool
    detected_type: str
    rejection_reason: str
    requires_staff_review: bool
    error_code: str
    provider_verdicts: _containers.ScalarMap[str, str]
    def __init__(self, safe: _Optional[bool] = ..., detected_type: _Optional[str] = ..., rejection_reason: _Optional[str] = ..., requires_staff_review: _Optional[bool] = ..., error_code: _Optional[str] = ..., provider_verdicts: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ContainerScanRequest(_message.Message):
    __slots__ = ("content", "claimed_filename", "blob_ref", "requesting_user_id", "run_id")
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    CLAIMED_FILENAME_FIELD_NUMBER: _ClassVar[int]
    BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    REQUESTING_USER_ID_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    content: bytes
    claimed_filename: str
    blob_ref: str
    requesting_user_id: str
    run_id: str
    def __init__(self, content: _Optional[bytes] = ..., claimed_filename: _Optional[str] = ..., blob_ref: _Optional[str] = ..., requesting_user_id: _Optional[str] = ..., run_id: _Optional[str] = ...) -> None: ...

class BombCheckResult(_message.Message):
    __slots__ = ("safe", "reason", "compression_ratio", "uncompressed_total_bytes", "entry_count", "nesting_depth", "bad_entries")
    SAFE_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    COMPRESSION_RATIO_FIELD_NUMBER: _ClassVar[int]
    UNCOMPRESSED_TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    ENTRY_COUNT_FIELD_NUMBER: _ClassVar[int]
    NESTING_DEPTH_FIELD_NUMBER: _ClassVar[int]
    BAD_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    safe: bool
    reason: str
    compression_ratio: float
    uncompressed_total_bytes: int
    entry_count: int
    nesting_depth: int
    bad_entries: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, safe: _Optional[bool] = ..., reason: _Optional[str] = ..., compression_ratio: _Optional[float] = ..., uncompressed_total_bytes: _Optional[int] = ..., entry_count: _Optional[int] = ..., nesting_depth: _Optional[int] = ..., bad_entries: _Optional[_Iterable[str]] = ...) -> None: ...

class RemediationResult(_message.Message):
    __slots__ = ("action", "removed")
    ACTION_FIELD_NUMBER: _ClassVar[int]
    REMOVED_FIELD_NUMBER: _ClassVar[int]
    action: str
    removed: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, action: _Optional[str] = ..., removed: _Optional[_Iterable[str]] = ...) -> None: ...

class ContainerScanVerdict(_message.Message):
    __slots__ = ("safe", "bomb_check", "member_verdicts", "remediation", "requires_staff_review", "rejection_reason", "error_code")
    class MemberVerdictsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: ScanVerdict
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[ScanVerdict, _Mapping]] = ...) -> None: ...
    SAFE_FIELD_NUMBER: _ClassVar[int]
    BOMB_CHECK_FIELD_NUMBER: _ClassVar[int]
    MEMBER_VERDICTS_FIELD_NUMBER: _ClassVar[int]
    REMEDIATION_FIELD_NUMBER: _ClassVar[int]
    REQUIRES_STAFF_REVIEW_FIELD_NUMBER: _ClassVar[int]
    REJECTION_REASON_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    safe: bool
    bomb_check: BombCheckResult
    member_verdicts: _containers.MessageMap[str, ScanVerdict]
    remediation: RemediationResult
    requires_staff_review: bool
    rejection_reason: str
    error_code: str
    def __init__(self, safe: _Optional[bool] = ..., bomb_check: _Optional[_Union[BombCheckResult, _Mapping]] = ..., member_verdicts: _Optional[_Mapping[str, ScanVerdict]] = ..., remediation: _Optional[_Union[RemediationResult, _Mapping]] = ..., requires_staff_review: _Optional[bool] = ..., rejection_reason: _Optional[str] = ..., error_code: _Optional[str] = ...) -> None: ...
