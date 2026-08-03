from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FlagInfo(_message.Message):
    __slots__ = ("flag_id", "flag_type", "user_id", "receipt_id", "status", "created_by", "created_at", "assigned_to", "resolved_at", "resolved_by", "resolution_note", "payload")
    class PayloadEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    FLAG_ID_FIELD_NUMBER: _ClassVar[int]
    FLAG_TYPE_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_TO_FIELD_NUMBER: _ClassVar[int]
    RESOLVED_AT_FIELD_NUMBER: _ClassVar[int]
    RESOLVED_BY_FIELD_NUMBER: _ClassVar[int]
    RESOLUTION_NOTE_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    flag_id: str
    flag_type: str
    user_id: str
    receipt_id: str
    status: str
    created_by: str
    created_at: str
    assigned_to: str
    resolved_at: str
    resolved_by: str
    resolution_note: str
    payload: _containers.ScalarMap[str, str]
    def __init__(self, flag_id: _Optional[str] = ..., flag_type: _Optional[str] = ..., user_id: _Optional[str] = ..., receipt_id: _Optional[str] = ..., status: _Optional[str] = ..., created_by: _Optional[str] = ..., created_at: _Optional[str] = ..., assigned_to: _Optional[str] = ..., resolved_at: _Optional[str] = ..., resolved_by: _Optional[str] = ..., resolution_note: _Optional[str] = ..., payload: _Optional[_Mapping[str, str]] = ...) -> None: ...

class CreateFlagRequest(_message.Message):
    __slots__ = ("flag_type", "user_id", "receipt_id", "created_by", "payload")
    class PayloadEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    FLAG_TYPE_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    flag_type: str
    user_id: str
    receipt_id: str
    created_by: str
    payload: _containers.ScalarMap[str, str]
    def __init__(self, flag_type: _Optional[str] = ..., user_id: _Optional[str] = ..., receipt_id: _Optional[str] = ..., created_by: _Optional[str] = ..., payload: _Optional[_Mapping[str, str]] = ...) -> None: ...

class AssignFlagRequest(_message.Message):
    __slots__ = ("flag_id", "assignee_user_id", "session_id")
    FLAG_ID_FIELD_NUMBER: _ClassVar[int]
    ASSIGNEE_USER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    flag_id: str
    assignee_user_id: str
    session_id: str
    def __init__(self, flag_id: _Optional[str] = ..., assignee_user_id: _Optional[str] = ..., session_id: _Optional[str] = ...) -> None: ...

class ResolveFlagRequest(_message.Message):
    __slots__ = ("flag_id", "resolution_note", "edit_field", "edit_new_value", "session_id")
    FLAG_ID_FIELD_NUMBER: _ClassVar[int]
    RESOLUTION_NOTE_FIELD_NUMBER: _ClassVar[int]
    EDIT_FIELD_FIELD_NUMBER: _ClassVar[int]
    EDIT_NEW_VALUE_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    flag_id: str
    resolution_note: str
    edit_field: str
    edit_new_value: str
    session_id: str
    def __init__(self, flag_id: _Optional[str] = ..., resolution_note: _Optional[str] = ..., edit_field: _Optional[str] = ..., edit_new_value: _Optional[str] = ..., session_id: _Optional[str] = ...) -> None: ...

class DismissFlagRequest(_message.Message):
    __slots__ = ("flag_id", "reason", "session_id")
    FLAG_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    flag_id: str
    reason: str
    session_id: str
    def __init__(self, flag_id: _Optional[str] = ..., reason: _Optional[str] = ..., session_id: _Optional[str] = ...) -> None: ...

class FlagResponse(_message.Message):
    __slots__ = ("flag", "error_code", "error_detail")
    FLAG_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    flag: FlagInfo
    error_code: str
    error_detail: str
    def __init__(self, flag: _Optional[_Union[FlagInfo, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class AuditViewRequest(_message.Message):
    __slots__ = ("receipt_id",)
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    receipt_id: str
    def __init__(self, receipt_id: _Optional[str] = ...) -> None: ...

class AuditTraceEntryInfo(_message.Message):
    __slots__ = ("timestamp", "service", "level", "message", "detail")
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    timestamp: str
    service: str
    level: str
    message: str
    detail: str
    def __init__(self, timestamp: _Optional[str] = ..., service: _Optional[str] = ..., level: _Optional[str] = ..., message: _Optional[str] = ..., detail: _Optional[str] = ...) -> None: ...

class AuditViewResponse(_message.Message):
    __slots__ = ("receipt_id", "trace", "flags", "trace_available", "error_code", "error_detail")
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    TRACE_FIELD_NUMBER: _ClassVar[int]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    TRACE_AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    receipt_id: str
    trace: _containers.RepeatedCompositeFieldContainer[AuditTraceEntryInfo]
    flags: _containers.RepeatedCompositeFieldContainer[FlagInfo]
    trace_available: bool
    error_code: str
    error_detail: str
    def __init__(self, receipt_id: _Optional[str] = ..., trace: _Optional[_Iterable[_Union[AuditTraceEntryInfo, _Mapping]]] = ..., flags: _Optional[_Iterable[_Union[FlagInfo, _Mapping]]] = ..., trace_available: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListFlagsRequest(_message.Message):
    __slots__ = ("statuses", "flag_type", "receipt_id", "assigned_to", "limit", "offset")
    STATUSES_FIELD_NUMBER: _ClassVar[int]
    FLAG_TYPE_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_ID_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_TO_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    statuses: _containers.RepeatedScalarFieldContainer[str]
    flag_type: str
    receipt_id: str
    assigned_to: str
    limit: int
    offset: int
    def __init__(self, statuses: _Optional[_Iterable[str]] = ..., flag_type: _Optional[str] = ..., receipt_id: _Optional[str] = ..., assigned_to: _Optional[str] = ..., limit: _Optional[int] = ..., offset: _Optional[int] = ...) -> None: ...

class ListFlagsResponse(_message.Message):
    __slots__ = ("flags", "total_matching", "error_code", "error_detail")
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_MATCHING_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    flags: _containers.RepeatedCompositeFieldContainer[FlagInfo]
    total_matching: int
    error_code: str
    error_detail: str
    def __init__(self, flags: _Optional[_Iterable[_Union[FlagInfo, _Mapping]]] = ..., total_matching: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
