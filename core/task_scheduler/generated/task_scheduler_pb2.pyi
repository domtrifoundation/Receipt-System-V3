from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ScheduledTaskInfo(_message.Message):
    __slots__ = ("task_id", "created_by", "action", "action_params", "cron_expression", "enabled", "created_at", "updated_at")
    class ActionParamsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    ACTION_PARAMS_FIELD_NUMBER: _ClassVar[int]
    CRON_EXPRESSION_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    created_by: str
    action: str
    action_params: _containers.ScalarMap[str, str]
    cron_expression: str
    enabled: bool
    created_at: str
    updated_at: str
    def __init__(self, task_id: _Optional[str] = ..., created_by: _Optional[str] = ..., action: _Optional[str] = ..., action_params: _Optional[_Mapping[str, str]] = ..., cron_expression: _Optional[str] = ..., enabled: _Optional[bool] = ..., created_at: _Optional[str] = ..., updated_at: _Optional[str] = ...) -> None: ...

class SchedulableActionInfo(_message.Message):
    __slots__ = ("name", "description", "param_keys")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    PARAM_KEYS_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    param_keys: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., param_keys: _Optional[_Iterable[str]] = ...) -> None: ...

class CreateTaskRequest(_message.Message):
    __slots__ = ("session_id", "action", "action_params", "cron_expression", "enabled")
    class ActionParamsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    ACTION_PARAMS_FIELD_NUMBER: _ClassVar[int]
    CRON_EXPRESSION_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    action: str
    action_params: _containers.ScalarMap[str, str]
    cron_expression: str
    enabled: bool
    def __init__(self, session_id: _Optional[str] = ..., action: _Optional[str] = ..., action_params: _Optional[_Mapping[str, str]] = ..., cron_expression: _Optional[str] = ..., enabled: _Optional[bool] = ...) -> None: ...

class UpdateTaskRequest(_message.Message):
    __slots__ = ("session_id", "task_id", "action", "action_params", "action_params_set", "cron_expression", "enabled", "enabled_set")
    class ActionParamsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    ACTION_PARAMS_FIELD_NUMBER: _ClassVar[int]
    ACTION_PARAMS_SET_FIELD_NUMBER: _ClassVar[int]
    CRON_EXPRESSION_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    ENABLED_SET_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    task_id: str
    action: str
    action_params: _containers.ScalarMap[str, str]
    action_params_set: bool
    cron_expression: str
    enabled: bool
    enabled_set: bool
    def __init__(self, session_id: _Optional[str] = ..., task_id: _Optional[str] = ..., action: _Optional[str] = ..., action_params: _Optional[_Mapping[str, str]] = ..., action_params_set: _Optional[bool] = ..., cron_expression: _Optional[str] = ..., enabled: _Optional[bool] = ..., enabled_set: _Optional[bool] = ...) -> None: ...

class DeleteTaskRequest(_message.Message):
    __slots__ = ("session_id", "task_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    task_id: str
    def __init__(self, session_id: _Optional[str] = ..., task_id: _Optional[str] = ...) -> None: ...

class ListTasksRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class ListActionsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class TaskResponse(_message.Message):
    __slots__ = ("task", "error_code", "error_detail")
    TASK_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    task: ScheduledTaskInfo
    error_code: str
    error_detail: str
    def __init__(self, task: _Optional[_Union[ScheduledTaskInfo, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class DeleteTaskResponse(_message.Message):
    __slots__ = ("ok", "error_code", "error_detail")
    OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    error_code: str
    error_detail: str
    def __init__(self, ok: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListTasksResponse(_message.Message):
    __slots__ = ("tasks", "error_code", "error_detail")
    TASKS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    tasks: _containers.RepeatedCompositeFieldContainer[ScheduledTaskInfo]
    error_code: str
    error_detail: str
    def __init__(self, tasks: _Optional[_Iterable[_Union[ScheduledTaskInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListActionsResponse(_message.Message):
    __slots__ = ("actions", "error_code", "error_detail")
    ACTIONS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    actions: _containers.RepeatedCompositeFieldContainer[SchedulableActionInfo]
    error_code: str
    error_detail: str
    def __init__(self, actions: _Optional[_Iterable[_Union[SchedulableActionInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
