from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GenerateRequest(_message.Message):
    __slots__ = ("run_id", "user_id", "preset", "messages", "tools", "response_schema_json", "max_tokens", "temperature", "timeout_ms")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PRESET_FIELD_NUMBER: _ClassVar[int]
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    TOOLS_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_SCHEMA_JSON_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_MS_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    user_id: str
    preset: str
    messages: _containers.RepeatedCompositeFieldContainer[Message]
    tools: _containers.RepeatedCompositeFieldContainer[ToolSpec]
    response_schema_json: str
    max_tokens: int
    temperature: float
    timeout_ms: int
    def __init__(self, run_id: _Optional[str] = ..., user_id: _Optional[str] = ..., preset: _Optional[str] = ..., messages: _Optional[_Iterable[_Union[Message, _Mapping]]] = ..., tools: _Optional[_Iterable[_Union[ToolSpec, _Mapping]]] = ..., response_schema_json: _Optional[str] = ..., max_tokens: _Optional[int] = ..., temperature: _Optional[float] = ..., timeout_ms: _Optional[int] = ...) -> None: ...

class Message(_message.Message):
    __slots__ = ("role", "content")
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    role: str
    content: _containers.RepeatedCompositeFieldContainer[ContentBlock]
    def __init__(self, role: _Optional[str] = ..., content: _Optional[_Iterable[_Union[ContentBlock, _Mapping]]] = ...) -> None: ...

class ContentBlock(_message.Message):
    __slots__ = ("type", "text", "image_blob_ref")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    IMAGE_BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    type: str
    text: str
    image_blob_ref: str
    def __init__(self, type: _Optional[str] = ..., text: _Optional[str] = ..., image_blob_ref: _Optional[str] = ...) -> None: ...

class ToolSpec(_message.Message):
    __slots__ = ("name", "description", "parameters_schema_json")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_SCHEMA_JSON_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    parameters_schema_json: str
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., parameters_schema_json: _Optional[str] = ...) -> None: ...

class GenerateResponse(_message.Message):
    __slots__ = ("text", "tool_call", "finish_reason", "schema_valid", "device", "duration_ms", "error_code", "error_detail")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_FIELD_NUMBER: _ClassVar[int]
    FINISH_REASON_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_VALID_FIELD_NUMBER: _ClassVar[int]
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    text: str
    tool_call: ToolCall
    finish_reason: str
    schema_valid: bool
    device: str
    duration_ms: int
    error_code: str
    error_detail: str
    def __init__(self, text: _Optional[str] = ..., tool_call: _Optional[_Union[ToolCall, _Mapping]] = ..., finish_reason: _Optional[str] = ..., schema_valid: _Optional[bool] = ..., device: _Optional[str] = ..., duration_ms: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ToolCall(_message.Message):
    __slots__ = ("name", "arguments_json")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_JSON_FIELD_NUMBER: _ClassVar[int]
    name: str
    arguments_json: str
    def __init__(self, name: _Optional[str] = ..., arguments_json: _Optional[str] = ...) -> None: ...

class ListPresetsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListPresetsResponse(_message.Message):
    __slots__ = ("available_presets", "enabled_presets", "preset_statuses")
    AVAILABLE_PRESETS_FIELD_NUMBER: _ClassVar[int]
    ENABLED_PRESETS_FIELD_NUMBER: _ClassVar[int]
    PRESET_STATUSES_FIELD_NUMBER: _ClassVar[int]
    available_presets: _containers.RepeatedScalarFieldContainer[str]
    enabled_presets: _containers.RepeatedScalarFieldContainer[str]
    preset_statuses: _containers.RepeatedCompositeFieldContainer[PresetStatusMessage]
    def __init__(self, available_presets: _Optional[_Iterable[str]] = ..., enabled_presets: _Optional[_Iterable[str]] = ..., preset_statuses: _Optional[_Iterable[_Union[PresetStatusMessage, _Mapping]]] = ...) -> None: ...

class PresetStatusMessage(_message.Message):
    __slots__ = ("name", "status", "device")
    NAME_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    name: str
    status: str
    device: str
    def __init__(self, name: _Optional[str] = ..., status: _Optional[str] = ..., device: _Optional[str] = ...) -> None: ...

class ProvisionPresetRequest(_message.Message):
    __slots__ = ("preset", "device_family")
    PRESET_FIELD_NUMBER: _ClassVar[int]
    DEVICE_FAMILY_FIELD_NUMBER: _ClassVar[int]
    preset: str
    device_family: str
    def __init__(self, preset: _Optional[str] = ..., device_family: _Optional[str] = ...) -> None: ...

class ProvisionProgressMessage(_message.Message):
    __slots__ = ("preset", "current_file", "bytes_downloaded", "total_bytes", "files_completed", "files_total", "complete", "ok", "error_code", "error_detail")
    PRESET_FIELD_NUMBER: _ClassVar[int]
    CURRENT_FILE_FIELD_NUMBER: _ClassVar[int]
    BYTES_DOWNLOADED_FIELD_NUMBER: _ClassVar[int]
    TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    FILES_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    FILES_TOTAL_FIELD_NUMBER: _ClassVar[int]
    COMPLETE_FIELD_NUMBER: _ClassVar[int]
    OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    preset: str
    current_file: str
    bytes_downloaded: int
    total_bytes: int
    files_completed: int
    files_total: int
    complete: bool
    ok: bool
    error_code: str
    error_detail: str
    def __init__(self, preset: _Optional[str] = ..., current_file: _Optional[str] = ..., bytes_downloaded: _Optional[int] = ..., total_bytes: _Optional[int] = ..., files_completed: _Optional[int] = ..., files_total: _Optional[int] = ..., complete: _Optional[bool] = ..., ok: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
