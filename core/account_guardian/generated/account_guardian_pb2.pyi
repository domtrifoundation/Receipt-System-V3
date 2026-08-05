from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ListSessionsRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class DeviceSessionMessage(_message.Message):
    __slots__ = ("session_id", "created_at", "last_seen_at", "user_agent_summary", "is_current")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_SEEN_AT_FIELD_NUMBER: _ClassVar[int]
    USER_AGENT_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    IS_CURRENT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    created_at: str
    last_seen_at: str
    user_agent_summary: str
    is_current: bool
    def __init__(self, session_id: _Optional[str] = ..., created_at: _Optional[str] = ..., last_seen_at: _Optional[str] = ..., user_agent_summary: _Optional[str] = ..., is_current: _Optional[bool] = ...) -> None: ...

class ListSessionsResponse(_message.Message):
    __slots__ = ("devices", "error_code", "error_detail")
    DEVICES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    devices: _containers.RepeatedCompositeFieldContainer[DeviceSessionMessage]
    error_code: str
    error_detail: str
    def __init__(self, devices: _Optional[_Iterable[_Union[DeviceSessionMessage, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class RevokeSessionRequest(_message.Message):
    __slots__ = ("session_id", "target_session_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    target_session_id: str
    def __init__(self, session_id: _Optional[str] = ..., target_session_id: _Optional[str] = ...) -> None: ...

class RevokeAllSessionsRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class RevokeResponse(_message.Message):
    __slots__ = ("revoked", "sessions_revoked", "error_code", "error_detail", "audit_recorded", "audit_error")
    REVOKED_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_REVOKED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    AUDIT_RECORDED_FIELD_NUMBER: _ClassVar[int]
    AUDIT_ERROR_FIELD_NUMBER: _ClassVar[int]
    revoked: bool
    sessions_revoked: int
    error_code: str
    error_detail: str
    audit_recorded: bool
    audit_error: str
    def __init__(self, revoked: _Optional[bool] = ..., sessions_revoked: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ..., audit_recorded: _Optional[bool] = ..., audit_error: _Optional[str] = ...) -> None: ...

class RequestRecoveryRequest(_message.Message):
    __slots__ = ("user_id", "lost_method")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LOST_METHOD_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    lost_method: str
    def __init__(self, user_id: _Optional[str] = ..., lost_method: _Optional[str] = ...) -> None: ...

class UpdateChecklistRequest(_message.Message):
    __slots__ = ("request_id", "session_id", "knowledge_check_passed", "knowledge_check_note", "recovery_contact_state", "vouched_by_user_id")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_CHECK_PASSED_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_CHECK_NOTE_FIELD_NUMBER: _ClassVar[int]
    RECOVERY_CONTACT_STATE_FIELD_NUMBER: _ClassVar[int]
    VOUCHED_BY_USER_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    session_id: str
    knowledge_check_passed: bool
    knowledge_check_note: str
    recovery_contact_state: int
    vouched_by_user_id: str
    def __init__(self, request_id: _Optional[str] = ..., session_id: _Optional[str] = ..., knowledge_check_passed: _Optional[bool] = ..., knowledge_check_note: _Optional[str] = ..., recovery_contact_state: _Optional[int] = ..., vouched_by_user_id: _Optional[str] = ...) -> None: ...

class ResolveRecoveryRequest(_message.Message):
    __slots__ = ("request_id", "session_id", "reason")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    session_id: str
    reason: str
    def __init__(self, request_id: _Optional[str] = ..., session_id: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class CompleteRecoveryRequest(_message.Message):
    __slots__ = ("request_id", "session_id", "notes")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    NOTES_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    session_id: str
    notes: str
    def __init__(self, request_id: _Optional[str] = ..., session_id: _Optional[str] = ..., notes: _Optional[str] = ...) -> None: ...

class CancelCaseRequest(_message.Message):
    __slots__ = ("request_id", "acting_user_id")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    ACTING_USER_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    acting_user_id: str
    def __init__(self, request_id: _Optional[str] = ..., acting_user_id: _Optional[str] = ...) -> None: ...

class GetCaseRequest(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    def __init__(self, request_id: _Optional[str] = ...) -> None: ...

class ListForUserRequest(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class RecoveryResponse(_message.Message):
    __slots__ = ("request_id", "user_id", "requested_at", "stage", "lost_method", "knowledge_check_passed", "knowledge_check_note", "recovery_contact_state", "vouched_by_user_id", "reviewed_by", "resolved_at", "notes", "error_code", "error_detail", "audit_recorded", "audit_error")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_AT_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    LOST_METHOD_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_CHECK_PASSED_FIELD_NUMBER: _ClassVar[int]
    KNOWLEDGE_CHECK_NOTE_FIELD_NUMBER: _ClassVar[int]
    RECOVERY_CONTACT_STATE_FIELD_NUMBER: _ClassVar[int]
    VOUCHED_BY_USER_ID_FIELD_NUMBER: _ClassVar[int]
    REVIEWED_BY_FIELD_NUMBER: _ClassVar[int]
    RESOLVED_AT_FIELD_NUMBER: _ClassVar[int]
    NOTES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    AUDIT_RECORDED_FIELD_NUMBER: _ClassVar[int]
    AUDIT_ERROR_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    user_id: str
    requested_at: str
    stage: str
    lost_method: str
    knowledge_check_passed: bool
    knowledge_check_note: str
    recovery_contact_state: int
    vouched_by_user_id: str
    reviewed_by: str
    resolved_at: str
    notes: str
    error_code: str
    error_detail: str
    audit_recorded: bool
    audit_error: str
    def __init__(self, request_id: _Optional[str] = ..., user_id: _Optional[str] = ..., requested_at: _Optional[str] = ..., stage: _Optional[str] = ..., lost_method: _Optional[str] = ..., knowledge_check_passed: _Optional[bool] = ..., knowledge_check_note: _Optional[str] = ..., recovery_contact_state: _Optional[int] = ..., vouched_by_user_id: _Optional[str] = ..., reviewed_by: _Optional[str] = ..., resolved_at: _Optional[str] = ..., notes: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ..., audit_recorded: _Optional[bool] = ..., audit_error: _Optional[str] = ...) -> None: ...

class ListRecoveryResponse(_message.Message):
    __slots__ = ("requests",)
    REQUESTS_FIELD_NUMBER: _ClassVar[int]
    requests: _containers.RepeatedCompositeFieldContainer[RecoveryResponse]
    def __init__(self, requests: _Optional[_Iterable[_Union[RecoveryResponse, _Mapping]]] = ...) -> None: ...

class RequestSsoLinkRequest(_message.Message):
    __slots__ = ("session_id", "provider", "step_up_confirmed")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    STEP_UP_CONFIRMED_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    provider: str
    step_up_confirmed: bool
    def __init__(self, session_id: _Optional[str] = ..., provider: _Optional[str] = ..., step_up_confirmed: _Optional[bool] = ...) -> None: ...

class SsoLinkResponse(_message.Message):
    __slots__ = ("request_id", "user_id", "provider", "requested_at", "stage", "completed_at", "error_code", "error_detail", "audit_recorded", "audit_error")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_AT_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    AUDIT_RECORDED_FIELD_NUMBER: _ClassVar[int]
    AUDIT_ERROR_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    user_id: str
    provider: str
    requested_at: str
    stage: str
    completed_at: str
    error_code: str
    error_detail: str
    audit_recorded: bool
    audit_error: str
    def __init__(self, request_id: _Optional[str] = ..., user_id: _Optional[str] = ..., provider: _Optional[str] = ..., requested_at: _Optional[str] = ..., stage: _Optional[str] = ..., completed_at: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ..., audit_recorded: _Optional[bool] = ..., audit_error: _Optional[str] = ...) -> None: ...

class RequestExportRequest(_message.Message):
    __slots__ = ("session_id", "provider_name")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_NAME_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    provider_name: str
    def __init__(self, session_id: _Optional[str] = ..., provider_name: _Optional[str] = ...) -> None: ...

class ExportResponse(_message.Message):
    __slots__ = ("request_id", "user_id", "requested_at", "status", "export_logical_id", "error_code", "error_detail", "audit_recorded", "audit_error")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_AT_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    EXPORT_LOGICAL_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    AUDIT_RECORDED_FIELD_NUMBER: _ClassVar[int]
    AUDIT_ERROR_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    user_id: str
    requested_at: str
    status: str
    export_logical_id: str
    error_code: str
    error_detail: str
    audit_recorded: bool
    audit_error: str
    def __init__(self, request_id: _Optional[str] = ..., user_id: _Optional[str] = ..., requested_at: _Optional[str] = ..., status: _Optional[str] = ..., export_logical_id: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ..., audit_recorded: _Optional[bool] = ..., audit_error: _Optional[str] = ...) -> None: ...

class RequestDeletionRequest(_message.Message):
    __slots__ = ("session_id", "grace_period_days")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    GRACE_PERIOD_DAYS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    grace_period_days: int
    def __init__(self, session_id: _Optional[str] = ..., grace_period_days: _Optional[int] = ...) -> None: ...

class DeletionResponse(_message.Message):
    __slots__ = ("request_id", "user_id", "requested_at", "stage", "grace_period_ends_at_unix", "completed_at_unix", "error_code", "error_detail", "audit_recorded", "audit_error")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_AT_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    GRACE_PERIOD_ENDS_AT_UNIX_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_UNIX_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    AUDIT_RECORDED_FIELD_NUMBER: _ClassVar[int]
    AUDIT_ERROR_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    user_id: str
    requested_at: str
    stage: str
    grace_period_ends_at_unix: int
    completed_at_unix: int
    error_code: str
    error_detail: str
    audit_recorded: bool
    audit_error: str
    def __init__(self, request_id: _Optional[str] = ..., user_id: _Optional[str] = ..., requested_at: _Optional[str] = ..., stage: _Optional[str] = ..., grace_period_ends_at_unix: _Optional[int] = ..., completed_at_unix: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ..., audit_recorded: _Optional[bool] = ..., audit_error: _Optional[str] = ...) -> None: ...

class PolicyVersionRequest(_message.Message):
    __slots__ = ("document_type",)
    DOCUMENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    document_type: str
    def __init__(self, document_type: _Optional[str] = ...) -> None: ...

class PolicyVersionResponse(_message.Message):
    __slots__ = ("document_type", "version", "published_at", "text_ref", "requires_reconsent", "published")
    DOCUMENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_AT_FIELD_NUMBER: _ClassVar[int]
    TEXT_REF_FIELD_NUMBER: _ClassVar[int]
    REQUIRES_RECONSENT_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_FIELD_NUMBER: _ClassVar[int]
    document_type: str
    version: str
    published_at: str
    text_ref: str
    requires_reconsent: bool
    published: bool
    def __init__(self, document_type: _Optional[str] = ..., version: _Optional[str] = ..., published_at: _Optional[str] = ..., text_ref: _Optional[str] = ..., requires_reconsent: _Optional[bool] = ..., published: _Optional[bool] = ...) -> None: ...

class RecordConsentRequest(_message.Message):
    __slots__ = ("user_id", "document_type", "document_version", "ip_address")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    IP_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    document_type: str
    document_version: str
    ip_address: str
    def __init__(self, user_id: _Optional[str] = ..., document_type: _Optional[str] = ..., document_version: _Optional[str] = ..., ip_address: _Optional[str] = ...) -> None: ...

class ConsentResponse(_message.Message):
    __slots__ = ("has_valid_consent", "current_version", "error_code", "error_detail")
    HAS_VALID_CONSENT_FIELD_NUMBER: _ClassVar[int]
    CURRENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    has_valid_consent: bool
    current_version: str
    error_code: str
    error_detail: str
    def __init__(self, has_valid_consent: _Optional[bool] = ..., current_version: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
