from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RasterizeRequest(_message.Message):
    __slots__ = ("run_id", "user_id", "source_blob_ref", "page_index", "scale")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    PAGE_INDEX_FIELD_NUMBER: _ClassVar[int]
    SCALE_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    user_id: str
    source_blob_ref: str
    page_index: int
    scale: float
    def __init__(self, run_id: _Optional[str] = ..., user_id: _Optional[str] = ..., source_blob_ref: _Optional[str] = ..., page_index: _Optional[int] = ..., scale: _Optional[float] = ...) -> None: ...

class RasterizeResponse(_message.Message):
    __slots__ = ("image_blob_ref", "width", "height", "duration_ms", "device", "error_code", "error_detail")
    IMAGE_BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    image_blob_ref: str
    width: int
    height: int
    duration_ms: int
    device: str
    error_code: str
    error_detail: str
    def __init__(self, image_blob_ref: _Optional[str] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., duration_ms: _Optional[int] = ..., device: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class GenerateVariantsRequest(_message.Message):
    __slots__ = ("run_id", "user_id", "image_blob_ref", "kinds", "device_preference")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    IMAGE_BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    KINDS_FIELD_NUMBER: _ClassVar[int]
    DEVICE_PREFERENCE_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    user_id: str
    image_blob_ref: str
    kinds: _containers.RepeatedScalarFieldContainer[str]
    device_preference: str
    def __init__(self, run_id: _Optional[str] = ..., user_id: _Optional[str] = ..., image_blob_ref: _Optional[str] = ..., kinds: _Optional[_Iterable[str]] = ..., device_preference: _Optional[str] = ...) -> None: ...

class GenerateVariantsResponse(_message.Message):
    __slots__ = ("variants",)
    VARIANTS_FIELD_NUMBER: _ClassVar[int]
    variants: _containers.RepeatedCompositeFieldContainer[Variant]
    def __init__(self, variants: _Optional[_Iterable[_Union[Variant, _Mapping]]] = ...) -> None: ...

class Variant(_message.Message):
    __slots__ = ("kind", "image_blob_ref", "duration_ms", "device", "error_code", "error_detail")
    KIND_FIELD_NUMBER: _ClassVar[int]
    IMAGE_BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    kind: str
    image_blob_ref: str
    duration_ms: int
    device: str
    error_code: str
    error_detail: str
    def __init__(self, kind: _Optional[str] = ..., image_blob_ref: _Optional[str] = ..., duration_ms: _Optional[int] = ..., device: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ListVariantKindsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListVariantKindsResponse(_message.Message):
    __slots__ = ("available_kinds", "enabled_kinds")
    AVAILABLE_KINDS_FIELD_NUMBER: _ClassVar[int]
    ENABLED_KINDS_FIELD_NUMBER: _ClassVar[int]
    available_kinds: _containers.RepeatedScalarFieldContainer[str]
    enabled_kinds: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, available_kinds: _Optional[_Iterable[str]] = ..., enabled_kinds: _Optional[_Iterable[str]] = ...) -> None: ...
