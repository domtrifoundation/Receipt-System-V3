from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PollDriveFallbackRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DirectUploadRequest(_message.Message):
    __slots__ = ("run_id", "user_id", "filename", "declared_mime_type", "content")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    DECLARED_MIME_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    user_id: str
    filename: str
    declared_mime_type: str
    content: bytes
    def __init__(self, run_id: _Optional[str] = ..., user_id: _Optional[str] = ..., filename: _Optional[str] = ..., declared_mime_type: _Optional[str] = ..., content: _Optional[bytes] = ...) -> None: ...

class NormalizationResponse(_message.Message):
    __slots__ = ("images", "archival_blob_ref", "error_code", "error_detail")
    IMAGES_FIELD_NUMBER: _ClassVar[int]
    ARCHIVAL_BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    images: _containers.RepeatedCompositeFieldContainer[NormalizedImage]
    archival_blob_ref: str
    error_code: str
    error_detail: str
    def __init__(self, images: _Optional[_Iterable[_Union[NormalizedImage, _Mapping]]] = ..., archival_blob_ref: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class NormalizedImage(_message.Message):
    __slots__ = ("image_blob_ref", "page_index", "source", "error_code", "error_detail")
    IMAGE_BLOB_REF_FIELD_NUMBER: _ClassVar[int]
    PAGE_INDEX_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    image_blob_ref: str
    page_index: int
    source: str
    error_code: str
    error_detail: str
    def __init__(self, image_blob_ref: _Optional[str] = ..., page_index: _Optional[int] = ..., source: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class StartScanRequest(_message.Message):
    __slots__ = ("run_id", "user_id")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    user_id: str
    def __init__(self, run_id: _Optional[str] = ..., user_id: _Optional[str] = ...) -> None: ...

class ScanSessionResponse(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class ScanFrameRequest(_message.Message):
    __slots__ = ("session_id", "frame")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    FRAME_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    frame: bytes
    def __init__(self, session_id: _Optional[str] = ..., frame: _Optional[bytes] = ...) -> None: ...

class ScanFrameResponse(_message.Message):
    __slots__ = ("frame_index", "error_code", "error_detail")
    FRAME_INDEX_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    frame_index: int
    error_code: str
    error_detail: str
    def __init__(self, frame_index: _Optional[int] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class FinalizeScanRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class ListSourcesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListSourcesResponse(_message.Message):
    __slots__ = ("available_sources", "enabled_sources")
    AVAILABLE_SOURCES_FIELD_NUMBER: _ClassVar[int]
    ENABLED_SOURCES_FIELD_NUMBER: _ClassVar[int]
    available_sources: _containers.RepeatedScalarFieldContainer[str]
    enabled_sources: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, available_sources: _Optional[_Iterable[str]] = ..., enabled_sources: _Optional[_Iterable[str]] = ...) -> None: ...

class DriveWebhookPayload(_message.Message):
    __slots__ = ("channel_id", "resource_id")
    CHANNEL_ID_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    channel_id: str
    resource_id: str
    def __init__(self, channel_id: _Optional[str] = ..., resource_id: _Optional[str] = ...) -> None: ...

class WebhookAck(_message.Message):
    __slots__ = ("accepted",)
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    def __init__(self, accepted: _Optional[bool] = ...) -> None: ...
