from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AuditEventMessage(_message.Message):
    __slots__ = ("event_id", "action_type", "actor_user_id", "target_user_id", "reason", "details_json", "occurred_at", "corrects_event_id")
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_TYPE_FIELD_NUMBER: _ClassVar[int]
    ACTOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_USER_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    DETAILS_JSON_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    CORRECTS_EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    event_id: str
    action_type: str
    actor_user_id: str
    target_user_id: str
    reason: str
    details_json: str
    occurred_at: str
    corrects_event_id: str
    def __init__(self, event_id: _Optional[str] = ..., action_type: _Optional[str] = ..., actor_user_id: _Optional[str] = ..., target_user_id: _Optional[str] = ..., reason: _Optional[str] = ..., details_json: _Optional[str] = ..., occurred_at: _Optional[str] = ..., corrects_event_id: _Optional[str] = ...) -> None: ...

class RecordActionRequest(_message.Message):
    __slots__ = ("operation", "actor_user_id", "target_user_id", "reason", "details_json", "corrects_event_id", "occurred_at")
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    ACTOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_USER_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    DETAILS_JSON_FIELD_NUMBER: _ClassVar[int]
    CORRECTS_EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    operation: str
    actor_user_id: str
    target_user_id: str
    reason: str
    details_json: str
    corrects_event_id: str
    occurred_at: str
    def __init__(self, operation: _Optional[str] = ..., actor_user_id: _Optional[str] = ..., target_user_id: _Optional[str] = ..., reason: _Optional[str] = ..., details_json: _Optional[str] = ..., corrects_event_id: _Optional[str] = ..., occurred_at: _Optional[str] = ...) -> None: ...

class RecordActionResponse(_message.Message):
    __slots__ = ("recorded", "event_id", "degraded_sinks", "error_code", "error_detail")
    RECORDED_FIELD_NUMBER: _ClassVar[int]
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    DEGRADED_SINKS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    recorded: bool
    event_id: str
    degraded_sinks: _containers.RepeatedScalarFieldContainer[str]
    error_code: str
    error_detail: str
    def __init__(self, recorded: _Optional[bool] = ..., event_id: _Optional[str] = ..., degraded_sinks: _Optional[_Iterable[str]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class QueryEventsRequest(_message.Message):
    __slots__ = ("action_types", "actor_user_id", "target_user_id", "occurred_after", "occurred_before", "limit", "offset")
    ACTION_TYPES_FIELD_NUMBER: _ClassVar[int]
    ACTOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_USER_ID_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AFTER_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_BEFORE_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    action_types: _containers.RepeatedScalarFieldContainer[str]
    actor_user_id: str
    target_user_id: str
    occurred_after: str
    occurred_before: str
    limit: int
    offset: int
    def __init__(self, action_types: _Optional[_Iterable[str]] = ..., actor_user_id: _Optional[str] = ..., target_user_id: _Optional[str] = ..., occurred_after: _Optional[str] = ..., occurred_before: _Optional[str] = ..., limit: _Optional[int] = ..., offset: _Optional[int] = ...) -> None: ...

class QueryEventsResponse(_message.Message):
    __slots__ = ("events", "total_matching", "error_code", "error_detail")
    EVENTS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_MATCHING_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    events: _containers.RepeatedCompositeFieldContainer[AuditEventMessage]
    total_matching: int
    error_code: str
    error_detail: str
    def __init__(self, events: _Optional[_Iterable[_Union[AuditEventMessage, _Mapping]]] = ..., total_matching: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class GetEventRequest(_message.Message):
    __slots__ = ("event_id",)
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    event_id: str
    def __init__(self, event_id: _Optional[str] = ...) -> None: ...

class ResolveRetentionPolicyRequest(_message.Message):
    __slots__ = ("retention_days", "retention_mode", "shorten_override", "shorten_override_reason")
    RETENTION_DAYS_FIELD_NUMBER: _ClassVar[int]
    RETENTION_MODE_FIELD_NUMBER: _ClassVar[int]
    SHORTEN_OVERRIDE_FIELD_NUMBER: _ClassVar[int]
    SHORTEN_OVERRIDE_REASON_FIELD_NUMBER: _ClassVar[int]
    retention_days: int
    retention_mode: str
    shorten_override: bool
    shorten_override_reason: str
    def __init__(self, retention_days: _Optional[int] = ..., retention_mode: _Optional[str] = ..., shorten_override: _Optional[bool] = ..., shorten_override_reason: _Optional[str] = ...) -> None: ...

class RetentionPolicyResponse(_message.Message):
    __slots__ = ("retention_days", "retention_mode", "shorten_override", "shorten_override_reason", "baseline_citation", "error_code", "error_detail")
    RETENTION_DAYS_FIELD_NUMBER: _ClassVar[int]
    RETENTION_MODE_FIELD_NUMBER: _ClassVar[int]
    SHORTEN_OVERRIDE_FIELD_NUMBER: _ClassVar[int]
    SHORTEN_OVERRIDE_REASON_FIELD_NUMBER: _ClassVar[int]
    BASELINE_CITATION_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    retention_days: int
    retention_mode: str
    shorten_override: bool
    shorten_override_reason: str
    baseline_citation: str
    error_code: str
    error_detail: str
    def __init__(self, retention_days: _Optional[int] = ..., retention_mode: _Optional[str] = ..., shorten_override: _Optional[bool] = ..., shorten_override_reason: _Optional[str] = ..., baseline_citation: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ApplyRetentionPolicyRequest(_message.Message):
    __slots__ = ("retention_days", "retention_mode", "shorten_override", "shorten_override_reason", "actor_user_id")
    RETENTION_DAYS_FIELD_NUMBER: _ClassVar[int]
    RETENTION_MODE_FIELD_NUMBER: _ClassVar[int]
    SHORTEN_OVERRIDE_FIELD_NUMBER: _ClassVar[int]
    SHORTEN_OVERRIDE_REASON_FIELD_NUMBER: _ClassVar[int]
    ACTOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    retention_days: int
    retention_mode: str
    shorten_override: bool
    shorten_override_reason: str
    actor_user_id: str
    def __init__(self, retention_days: _Optional[int] = ..., retention_mode: _Optional[str] = ..., shorten_override: _Optional[bool] = ..., shorten_override_reason: _Optional[str] = ..., actor_user_id: _Optional[str] = ...) -> None: ...

class ApplyRetentionPolicyResponse(_message.Message):
    __slots__ = ("purged", "horizon", "error_code", "error_detail")
    PURGED_FIELD_NUMBER: _ClassVar[int]
    HORIZON_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    purged: int
    horizon: str
    error_code: str
    error_detail: str
    def __init__(self, purged: _Optional[int] = ..., horizon: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class GetMetricsRequest(_message.Message):
    __slots__ = ("retention_days", "retention_mode")
    RETENTION_DAYS_FIELD_NUMBER: _ClassVar[int]
    RETENTION_MODE_FIELD_NUMBER: _ClassVar[int]
    retention_days: int
    retention_mode: str
    def __init__(self, retention_days: _Optional[int] = ..., retention_mode: _Optional[str] = ...) -> None: ...

class MetricsResponse(_message.Message):
    __slots__ = ("total_events", "events_by_action", "oldest_occurred_at", "newest_occurred_at", "events_past_horizon", "database_bytes", "error_code", "error_detail")
    class EventsByActionEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    TOTAL_EVENTS_FIELD_NUMBER: _ClassVar[int]
    EVENTS_BY_ACTION_FIELD_NUMBER: _ClassVar[int]
    OLDEST_OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    NEWEST_OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    EVENTS_PAST_HORIZON_FIELD_NUMBER: _ClassVar[int]
    DATABASE_BYTES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    total_events: int
    events_by_action: _containers.ScalarMap[str, int]
    oldest_occurred_at: str
    newest_occurred_at: str
    events_past_horizon: int
    database_bytes: int
    error_code: str
    error_detail: str
    def __init__(self, total_events: _Optional[int] = ..., events_by_action: _Optional[_Mapping[str, int]] = ..., oldest_occurred_at: _Optional[str] = ..., newest_occurred_at: _Optional[str] = ..., events_past_horizon: _Optional[int] = ..., database_bytes: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
