from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StartRunRequest(_message.Message):
    __slots__ = ("user_id", "file_count")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    FILE_COUNT_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    file_count: int
    def __init__(self, user_id: _Optional[str] = ..., file_count: _Optional[int] = ...) -> None: ...

class RunStatusRequest(_message.Message):
    __slots__ = ("run_id",)
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    def __init__(self, run_id: _Optional[str] = ...) -> None: ...

class CancelRunRequest(_message.Message):
    __slots__ = ("run_id",)
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    def __init__(self, run_id: _Optional[str] = ...) -> None: ...

class PauseRunRequest(_message.Message):
    __slots__ = ("run_id",)
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    def __init__(self, run_id: _Optional[str] = ...) -> None: ...

class Run(_message.Message):
    __slots__ = ("run_id", "user_id", "state", "opened_at", "closing_started_at", "receipt_count")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    OPENED_AT_FIELD_NUMBER: _ClassVar[int]
    CLOSING_STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_COUNT_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    user_id: str
    state: str
    opened_at: str
    closing_started_at: str
    receipt_count: int
    def __init__(self, run_id: _Optional[str] = ..., user_id: _Optional[str] = ..., state: _Optional[str] = ..., opened_at: _Optional[str] = ..., closing_started_at: _Optional[str] = ..., receipt_count: _Optional[int] = ...) -> None: ...

class RunResponse(_message.Message):
    __slots__ = ("run", "started_new_run", "error_code", "error_detail")
    RUN_FIELD_NUMBER: _ClassVar[int]
    STARTED_NEW_RUN_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    run: Run
    started_new_run: bool
    error_code: str
    error_detail: str
    def __init__(self, run: _Optional[_Union[Run, _Mapping]] = ..., started_new_run: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class RunProgress(_message.Message):
    __slots__ = ("run_id", "state", "receipts_total", "receipts_completed", "current_stage_summary", "error_code", "error_detail")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    RECEIPTS_TOTAL_FIELD_NUMBER: _ClassVar[int]
    RECEIPTS_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STAGE_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    state: str
    receipts_total: int
    receipts_completed: int
    current_stage_summary: str
    error_code: str
    error_detail: str
    def __init__(self, run_id: _Optional[str] = ..., state: _Optional[str] = ..., receipts_total: _Optional[int] = ..., receipts_completed: _Optional[int] = ..., current_stage_summary: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
