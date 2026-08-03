from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ToolSpecInfo(_message.Message):
    __slots__ = ("name", "description", "parameters_schema_json", "category")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_SCHEMA_JSON_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    parameters_schema_json: str
    category: str
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., parameters_schema_json: _Optional[str] = ..., category: _Optional[str] = ...) -> None: ...

class ToolCallContext(_message.Message):
    __slots__ = ("run_id", "user_id", "calling_api", "session_id")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    CALLING_API_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    user_id: str
    calling_api: str
    session_id: str
    def __init__(self, run_id: _Optional[str] = ..., user_id: _Optional[str] = ..., calling_api: _Optional[str] = ..., session_id: _Optional[str] = ...) -> None: ...

class ListToolsRequest(_message.Message):
    __slots__ = ("context",)
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    context: ToolCallContext
    def __init__(self, context: _Optional[_Union[ToolCallContext, _Mapping]] = ...) -> None: ...

class ListToolsResponse(_message.Message):
    __slots__ = ("tools",)
    TOOLS_FIELD_NUMBER: _ClassVar[int]
    tools: _containers.RepeatedCompositeFieldContainer[ToolSpecInfo]
    def __init__(self, tools: _Optional[_Iterable[_Union[ToolSpecInfo, _Mapping]]] = ...) -> None: ...

class DispatchToolRequest(_message.Message):
    __slots__ = ("context", "tool_name", "arguments_json")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_JSON_FIELD_NUMBER: _ClassVar[int]
    context: ToolCallContext
    tool_name: str
    arguments_json: str
    def __init__(self, context: _Optional[_Union[ToolCallContext, _Mapping]] = ..., tool_name: _Optional[str] = ..., arguments_json: _Optional[str] = ...) -> None: ...

class DispatchToolResponse(_message.Message):
    __slots__ = ("tool_name", "result_json", "error", "error_code")
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    tool_name: str
    result_json: str
    error: str
    error_code: str
    def __init__(self, tool_name: _Optional[str] = ..., result_json: _Optional[str] = ..., error: _Optional[str] = ..., error_code: _Optional[str] = ...) -> None: ...
