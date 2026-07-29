from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class VendorCandidateProto(_message.Message):
    __slots__ = ("entity_id", "name", "entity_kind", "tin", "category_code", "aliases")
    ENTITY_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ENTITY_KIND_FIELD_NUMBER: _ClassVar[int]
    TIN_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_CODE_FIELD_NUMBER: _ClassVar[int]
    ALIASES_FIELD_NUMBER: _ClassVar[int]
    entity_id: str
    name: str
    entity_kind: str
    tin: str
    category_code: str
    aliases: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, entity_id: _Optional[str] = ..., name: _Optional[str] = ..., entity_kind: _Optional[str] = ..., tin: _Optional[str] = ..., category_code: _Optional[str] = ..., aliases: _Optional[_Iterable[str]] = ...) -> None: ...

class MatchRequest(_message.Message):
    __slots__ = ("extracted_text", "raw_ocr_text", "candidates", "limit", "plausibility_window")
    EXTRACTED_TEXT_FIELD_NUMBER: _ClassVar[int]
    RAW_OCR_TEXT_FIELD_NUMBER: _ClassVar[int]
    CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    PLAUSIBILITY_WINDOW_FIELD_NUMBER: _ClassVar[int]
    extracted_text: str
    raw_ocr_text: str
    candidates: _containers.RepeatedCompositeFieldContainer[VendorCandidateProto]
    limit: int
    plausibility_window: int
    def __init__(self, extracted_text: _Optional[str] = ..., raw_ocr_text: _Optional[str] = ..., candidates: _Optional[_Iterable[_Union[VendorCandidateProto, _Mapping]]] = ..., limit: _Optional[int] = ..., plausibility_window: _Optional[int] = ...) -> None: ...

class GazetteerScanRequest(_message.Message):
    __slots__ = ("raw_ocr_text", "candidates", "plausibility_window", "limit")
    RAW_OCR_TEXT_FIELD_NUMBER: _ClassVar[int]
    CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    PLAUSIBILITY_WINDOW_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    raw_ocr_text: str
    candidates: _containers.RepeatedCompositeFieldContainer[VendorCandidateProto]
    plausibility_window: int
    limit: int
    def __init__(self, raw_ocr_text: _Optional[str] = ..., candidates: _Optional[_Iterable[_Union[VendorCandidateProto, _Mapping]]] = ..., plausibility_window: _Optional[int] = ..., limit: _Optional[int] = ...) -> None: ...

class MatchCandidateProto(_message.Message):
    __slots__ = ("canonical_name", "score", "source", "entity_id", "entity_kind", "tin", "category_code", "matched_alias")
    CANONICAL_NAME_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    ENTITY_ID_FIELD_NUMBER: _ClassVar[int]
    ENTITY_KIND_FIELD_NUMBER: _ClassVar[int]
    TIN_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_CODE_FIELD_NUMBER: _ClassVar[int]
    MATCHED_ALIAS_FIELD_NUMBER: _ClassVar[int]
    canonical_name: str
    score: float
    source: str
    entity_id: str
    entity_kind: str
    tin: str
    category_code: str
    matched_alias: str
    def __init__(self, canonical_name: _Optional[str] = ..., score: _Optional[float] = ..., source: _Optional[str] = ..., entity_id: _Optional[str] = ..., entity_kind: _Optional[str] = ..., tin: _Optional[str] = ..., category_code: _Optional[str] = ..., matched_alias: _Optional[str] = ...) -> None: ...

class MatchResponse(_message.Message):
    __slots__ = ("candidates", "error_code", "error_detail")
    CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    candidates: _containers.RepeatedCompositeFieldContainer[MatchCandidateProto]
    error_code: str
    error_detail: str
    def __init__(self, candidates: _Optional[_Iterable[_Union[MatchCandidateProto, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class VendorMatchContextRequest(_message.Message):
    __slots__ = ("match_request", "policy", "threshold")
    MATCH_REQUEST_FIELD_NUMBER: _ClassVar[int]
    POLICY_FIELD_NUMBER: _ClassVar[int]
    THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    match_request: MatchRequest
    policy: str
    threshold: float
    def __init__(self, match_request: _Optional[_Union[MatchRequest, _Mapping]] = ..., policy: _Optional[str] = ..., threshold: _Optional[float] = ...) -> None: ...

class MatchContextResponse(_message.Message):
    __slots__ = ("candidates", "included", "policy", "top_score", "error_code", "error_detail")
    CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    INCLUDED_FIELD_NUMBER: _ClassVar[int]
    POLICY_FIELD_NUMBER: _ClassVar[int]
    TOP_SCORE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    candidates: _containers.RepeatedCompositeFieldContainer[MatchCandidateProto]
    included: bool
    policy: str
    top_score: float
    error_code: str
    error_detail: str
    def __init__(self, candidates: _Optional[_Iterable[_Union[MatchCandidateProto, _Mapping]]] = ..., included: _Optional[bool] = ..., policy: _Optional[str] = ..., top_score: _Optional[float] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
