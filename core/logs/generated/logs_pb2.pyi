from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class LogQueryRequest(_message.Message):
    __slots__ = ("run_id", "user_id", "min_level", "service", "since", "until", "limit", "requesting_user_id")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    MIN_LEVEL_FIELD_NUMBER: _ClassVar[int]
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    SINCE_FIELD_NUMBER: _ClassVar[int]
    UNTIL_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    REQUESTING_USER_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    user_id: str
    min_level: str
    service: str
    since: str
    until: str
    limit: int
    requesting_user_id: str
    def __init__(self, run_id: _Optional[str] = ..., user_id: _Optional[str] = ..., min_level: _Optional[str] = ..., service: _Optional[str] = ..., since: _Optional[str] = ..., until: _Optional[str] = ..., limit: _Optional[int] = ..., requesting_user_id: _Optional[str] = ...) -> None: ...

class LogRecord(_message.Message):
    __slots__ = ("entry", "error")
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    entry: LogEntry
    error: LogQueryError
    def __init__(self, entry: _Optional[_Union[LogEntry, _Mapping]] = ..., error: _Optional[_Union[LogQueryError, _Mapping]] = ...) -> None: ...

class LogEntry(_message.Message):
    __slots__ = ("timestamp", "run_id", "user_id", "service", "level", "message", "traceback", "suggested_style", "context_json")
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    TRACEBACK_FIELD_NUMBER: _ClassVar[int]
    SUGGESTED_STYLE_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_JSON_FIELD_NUMBER: _ClassVar[int]
    timestamp: str
    run_id: str
    user_id: str
    service: str
    level: str
    message: str
    traceback: str
    suggested_style: str
    context_json: str
    def __init__(self, timestamp: _Optional[str] = ..., run_id: _Optional[str] = ..., user_id: _Optional[str] = ..., service: _Optional[str] = ..., level: _Optional[str] = ..., message: _Optional[str] = ..., traceback: _Optional[str] = ..., suggested_style: _Optional[str] = ..., context_json: _Optional[str] = ...) -> None: ...

class LogQueryError(_message.Message):
    __slots__ = ("error_code", "error_detail")
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    error_code: str
    error_detail: str
    def __init__(self, error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
