from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Definition(_message.Message):
    __slots__ = ("code", "label", "kind", "description", "deprecated", "attributes", "parent_code", "value_pattern", "example", "multi_valued", "default_severity", "raised_by")
    class AttributesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    CODE_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    DEPRECATED_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    PARENT_CODE_FIELD_NUMBER: _ClassVar[int]
    VALUE_PATTERN_FIELD_NUMBER: _ClassVar[int]
    EXAMPLE_FIELD_NUMBER: _ClassVar[int]
    MULTI_VALUED_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_SEVERITY_FIELD_NUMBER: _ClassVar[int]
    RAISED_BY_FIELD_NUMBER: _ClassVar[int]
    code: str
    label: str
    kind: str
    description: str
    deprecated: bool
    attributes: _containers.ScalarMap[str, str]
    parent_code: str
    value_pattern: str
    example: str
    multi_valued: bool
    default_severity: str
    raised_by: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, code: _Optional[str] = ..., label: _Optional[str] = ..., kind: _Optional[str] = ..., description: _Optional[str] = ..., deprecated: _Optional[bool] = ..., attributes: _Optional[_Mapping[str, str]] = ..., parent_code: _Optional[str] = ..., value_pattern: _Optional[str] = ..., example: _Optional[str] = ..., multi_valued: _Optional[bool] = ..., default_severity: _Optional[str] = ..., raised_by: _Optional[_Iterable[str]] = ...) -> None: ...

class TaxonomyRequest(_message.Message):
    __slots__ = ("kind", "include_deprecated", "parent_code")
    KIND_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_DEPRECATED_FIELD_NUMBER: _ClassVar[int]
    PARENT_CODE_FIELD_NUMBER: _ClassVar[int]
    kind: str
    include_deprecated: bool
    parent_code: str
    def __init__(self, kind: _Optional[str] = ..., include_deprecated: _Optional[bool] = ..., parent_code: _Optional[str] = ...) -> None: ...

class TaxonomyResponse(_message.Message):
    __slots__ = ("definitions", "error_code", "error_detail")
    DEFINITIONS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    definitions: _containers.RepeatedCompositeFieldContainer[Definition]
    error_code: str
    error_detail: str
    def __init__(self, definitions: _Optional[_Iterable[_Union[Definition, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ContributionRequest(_message.Message):
    __slots__ = ("contributor", "target_entity_type", "target_entity_id", "proposed_change", "staff_authored")
    class ProposedChangeEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    CONTRIBUTOR_FIELD_NUMBER: _ClassVar[int]
    TARGET_ENTITY_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ENTITY_ID_FIELD_NUMBER: _ClassVar[int]
    PROPOSED_CHANGE_FIELD_NUMBER: _ClassVar[int]
    STAFF_AUTHORED_FIELD_NUMBER: _ClassVar[int]
    contributor: str
    target_entity_type: str
    target_entity_id: str
    proposed_change: _containers.ScalarMap[str, str]
    staff_authored: bool
    def __init__(self, contributor: _Optional[str] = ..., target_entity_type: _Optional[str] = ..., target_entity_id: _Optional[str] = ..., proposed_change: _Optional[_Mapping[str, str]] = ..., staff_authored: _Optional[bool] = ...) -> None: ...

class ContributionInfo(_message.Message):
    __slots__ = ("contribution_id", "contributor", "target_entity_type", "target_entity_id", "proposed_change", "target_layer", "llm_prescreen_verdict", "staff_review_status", "merged", "submitted_at", "curation_type")
    class ProposedChangeEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    CONTRIBUTION_ID_FIELD_NUMBER: _ClassVar[int]
    CONTRIBUTOR_FIELD_NUMBER: _ClassVar[int]
    TARGET_ENTITY_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ENTITY_ID_FIELD_NUMBER: _ClassVar[int]
    PROPOSED_CHANGE_FIELD_NUMBER: _ClassVar[int]
    TARGET_LAYER_FIELD_NUMBER: _ClassVar[int]
    LLM_PRESCREEN_VERDICT_FIELD_NUMBER: _ClassVar[int]
    STAFF_REVIEW_STATUS_FIELD_NUMBER: _ClassVar[int]
    MERGED_FIELD_NUMBER: _ClassVar[int]
    SUBMITTED_AT_FIELD_NUMBER: _ClassVar[int]
    CURATION_TYPE_FIELD_NUMBER: _ClassVar[int]
    contribution_id: str
    contributor: str
    target_entity_type: str
    target_entity_id: str
    proposed_change: _containers.ScalarMap[str, str]
    target_layer: str
    llm_prescreen_verdict: str
    staff_review_status: str
    merged: bool
    submitted_at: str
    curation_type: str
    def __init__(self, contribution_id: _Optional[str] = ..., contributor: _Optional[str] = ..., target_entity_type: _Optional[str] = ..., target_entity_id: _Optional[str] = ..., proposed_change: _Optional[_Mapping[str, str]] = ..., target_layer: _Optional[str] = ..., llm_prescreen_verdict: _Optional[str] = ..., staff_review_status: _Optional[str] = ..., merged: _Optional[bool] = ..., submitted_at: _Optional[str] = ..., curation_type: _Optional[str] = ...) -> None: ...

class ContributionResponse(_message.Message):
    __slots__ = ("contribution", "error_code", "error_detail")
    CONTRIBUTION_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    contribution: ContributionInfo
    error_code: str
    error_detail: str
    def __init__(self, contribution: _Optional[_Union[ContributionInfo, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ReviewRequest(_message.Message):
    __slots__ = ("contribution_id", "reviewer", "approved", "reason")
    CONTRIBUTION_ID_FIELD_NUMBER: _ClassVar[int]
    REVIEWER_FIELD_NUMBER: _ClassVar[int]
    APPROVED_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    contribution_id: str
    reviewer: str
    approved: bool
    reason: str
    def __init__(self, contribution_id: _Optional[str] = ..., reviewer: _Optional[str] = ..., approved: _Optional[bool] = ..., reason: _Optional[str] = ...) -> None: ...

class VendorSearchRequest(_message.Message):
    __slots__ = ("query", "user_id", "limit")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    query: str
    user_id: str
    limit: int
    def __init__(self, query: _Optional[str] = ..., user_id: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class VendorRecordInfo(_message.Message):
    __slots__ = ("corporation_id", "name", "corporate_tin", "layer", "category_code", "aliases", "branch_count")
    CORPORATION_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    CORPORATE_TIN_FIELD_NUMBER: _ClassVar[int]
    LAYER_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_CODE_FIELD_NUMBER: _ClassVar[int]
    ALIASES_FIELD_NUMBER: _ClassVar[int]
    BRANCH_COUNT_FIELD_NUMBER: _ClassVar[int]
    corporation_id: str
    name: str
    corporate_tin: str
    layer: str
    category_code: str
    aliases: _containers.RepeatedScalarFieldContainer[str]
    branch_count: int
    def __init__(self, corporation_id: _Optional[str] = ..., name: _Optional[str] = ..., corporate_tin: _Optional[str] = ..., layer: _Optional[str] = ..., category_code: _Optional[str] = ..., aliases: _Optional[_Iterable[str]] = ..., branch_count: _Optional[int] = ...) -> None: ...

class VendorSearchResponse(_message.Message):
    __slots__ = ("records", "error_code", "error_detail")
    RECORDS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    records: _containers.RepeatedCompositeFieldContainer[VendorRecordInfo]
    error_code: str
    error_detail: str
    def __init__(self, records: _Optional[_Iterable[_Union[VendorRecordInfo, _Mapping]]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
