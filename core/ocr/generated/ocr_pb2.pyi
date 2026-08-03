from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class OcrReadRequest(_message.Message):
    __slots__ = ("run_id", "user_id", "blob_ref", "engines", "timeout_ms")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    ENGINES_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_MS_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    user_id: str
    blob_ref: str
    engines: _containers.RepeatedScalarFieldContainer[str]
    timeout_ms: int
    def __init__(self, run_id: _Optional[str] = ..., user_id: _Optional[str] = ..., blob_ref: _Optional[str] = ..., engines: _Optional[_Iterable[str]] = ..., timeout_ms: _Optional[int] = ...) -> None: ...

class OcrReadResponse(_message.Message):
    __slots__ = ("readings", "merged_text", "agreement", "confidence")
    READINGS_FIELD_NUMBER: _ClassVar[int]
    MERGED_TEXT_FIELD_NUMBER: _ClassVar[int]
    AGREEMENT_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    readings: _containers.RepeatedCompositeFieldContainer[EngineReading]
    merged_text: str
    agreement: str
    confidence: float
    def __init__(self, readings: _Optional[_Iterable[_Union[EngineReading, _Mapping]]] = ..., merged_text: _Optional[str] = ..., agreement: _Optional[str] = ..., confidence: _Optional[float] = ...) -> None: ...

class EngineReading(_message.Message):
    __slots__ = ("engine", "text", "duration_ms", "error_code", "error_detail", "regions", "device", "has_mean_confidence", "mean_confidence")
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    REGIONS_FIELD_NUMBER: _ClassVar[int]
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    HAS_MEAN_CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    MEAN_CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    engine: str
    text: str
    duration_ms: int
    error_code: str
    error_detail: str
    regions: _containers.RepeatedCompositeFieldContainer[TextRegion]
    device: str
    has_mean_confidence: bool
    mean_confidence: float
    def __init__(self, engine: _Optional[str] = ..., text: _Optional[str] = ..., duration_ms: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ..., regions: _Optional[_Iterable[_Union[TextRegion, _Mapping]]] = ..., device: _Optional[str] = ..., has_mean_confidence: _Optional[bool] = ..., mean_confidence: _Optional[float] = ...) -> None: ...

class TextRegion(_message.Message):
    __slots__ = ("text", "confidence", "box_x", "box_y", "box_w", "box_h")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    BOX_X_FIELD_NUMBER: _ClassVar[int]
    BOX_Y_FIELD_NUMBER: _ClassVar[int]
    BOX_W_FIELD_NUMBER: _ClassVar[int]
    BOX_H_FIELD_NUMBER: _ClassVar[int]
    text: str
    confidence: float
    box_x: float
    box_y: float
    box_w: float
    box_h: float
    def __init__(self, text: _Optional[str] = ..., confidence: _Optional[float] = ..., box_x: _Optional[float] = ..., box_y: _Optional[float] = ..., box_w: _Optional[float] = ..., box_h: _Optional[float] = ...) -> None: ...

class ListEnginesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListEnginesResponse(_message.Message):
    __slots__ = ("available_engines", "enabled_engines")
    AVAILABLE_ENGINES_FIELD_NUMBER: _ClassVar[int]
    ENABLED_ENGINES_FIELD_NUMBER: _ClassVar[int]
    available_engines: _containers.RepeatedScalarFieldContainer[str]
    enabled_engines: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, available_engines: _Optional[_Iterable[str]] = ..., enabled_engines: _Optional[_Iterable[str]] = ...) -> None: ...
