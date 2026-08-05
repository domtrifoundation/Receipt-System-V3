from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GeocodeRequest(_message.Message):
    __slots__ = ("candidate_strings", "providers", "country_code", "vendor_name_hint")
    CANDIDATE_STRINGS_FIELD_NUMBER: _ClassVar[int]
    PROVIDERS_FIELD_NUMBER: _ClassVar[int]
    COUNTRY_CODE_FIELD_NUMBER: _ClassVar[int]
    VENDOR_NAME_HINT_FIELD_NUMBER: _ClassVar[int]
    candidate_strings: _containers.RepeatedScalarFieldContainer[str]
    providers: _containers.RepeatedScalarFieldContainer[str]
    country_code: str
    vendor_name_hint: str
    def __init__(self, candidate_strings: _Optional[_Iterable[str]] = ..., providers: _Optional[_Iterable[str]] = ..., country_code: _Optional[str] = ..., vendor_name_hint: _Optional[str] = ...) -> None: ...

class GeoAddressProto(_message.Message):
    __slots__ = ("formatted", "line1", "barangay", "city", "province", "region", "postal_code", "country_code", "latitude", "longitude")
    FORMATTED_FIELD_NUMBER: _ClassVar[int]
    LINE1_FIELD_NUMBER: _ClassVar[int]
    BARANGAY_FIELD_NUMBER: _ClassVar[int]
    CITY_FIELD_NUMBER: _ClassVar[int]
    PROVINCE_FIELD_NUMBER: _ClassVar[int]
    REGION_FIELD_NUMBER: _ClassVar[int]
    POSTAL_CODE_FIELD_NUMBER: _ClassVar[int]
    COUNTRY_CODE_FIELD_NUMBER: _ClassVar[int]
    LATITUDE_FIELD_NUMBER: _ClassVar[int]
    LONGITUDE_FIELD_NUMBER: _ClassVar[int]
    formatted: str
    line1: str
    barangay: str
    city: str
    province: str
    region: str
    postal_code: str
    country_code: str
    latitude: float
    longitude: float
    def __init__(self, formatted: _Optional[str] = ..., line1: _Optional[str] = ..., barangay: _Optional[str] = ..., city: _Optional[str] = ..., province: _Optional[str] = ..., region: _Optional[str] = ..., postal_code: _Optional[str] = ..., country_code: _Optional[str] = ..., latitude: _Optional[float] = ..., longitude: _Optional[float] = ...) -> None: ...

class ProviderCandidateResultProto(_message.Message):
    __slots__ = ("provider", "candidate_string", "address", "confidence", "matched_business_name", "error_code", "error_detail")
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    CANDIDATE_STRING_FIELD_NUMBER: _ClassVar[int]
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    MATCHED_BUSINESS_NAME_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    provider: str
    candidate_string: str
    address: GeoAddressProto
    confidence: float
    matched_business_name: str
    error_code: str
    error_detail: str
    def __init__(self, provider: _Optional[str] = ..., candidate_string: _Optional[str] = ..., address: _Optional[_Union[GeoAddressProto, _Mapping]] = ..., confidence: _Optional[float] = ..., matched_business_name: _Optional[str] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class GeoResultProto(_message.Message):
    __slots__ = ("normalized_address", "confidence", "agreement", "matched_candidate_string", "provider_results", "vendor_name_at_address", "vendor_name_discrepancy", "conflict", "conflict_detail", "degraded_providers", "from_cache", "cache_stale")
    NORMALIZED_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    AGREEMENT_FIELD_NUMBER: _ClassVar[int]
    MATCHED_CANDIDATE_STRING_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_RESULTS_FIELD_NUMBER: _ClassVar[int]
    VENDOR_NAME_AT_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    VENDOR_NAME_DISCREPANCY_FIELD_NUMBER: _ClassVar[int]
    CONFLICT_FIELD_NUMBER: _ClassVar[int]
    CONFLICT_DETAIL_FIELD_NUMBER: _ClassVar[int]
    DEGRADED_PROVIDERS_FIELD_NUMBER: _ClassVar[int]
    FROM_CACHE_FIELD_NUMBER: _ClassVar[int]
    CACHE_STALE_FIELD_NUMBER: _ClassVar[int]
    normalized_address: GeoAddressProto
    confidence: float
    agreement: str
    matched_candidate_string: str
    provider_results: _containers.RepeatedCompositeFieldContainer[ProviderCandidateResultProto]
    vendor_name_at_address: str
    vendor_name_discrepancy: bool
    conflict: bool
    conflict_detail: str
    degraded_providers: _containers.RepeatedScalarFieldContainer[str]
    from_cache: bool
    cache_stale: bool
    def __init__(self, normalized_address: _Optional[_Union[GeoAddressProto, _Mapping]] = ..., confidence: _Optional[float] = ..., agreement: _Optional[str] = ..., matched_candidate_string: _Optional[str] = ..., provider_results: _Optional[_Iterable[_Union[ProviderCandidateResultProto, _Mapping]]] = ..., vendor_name_at_address: _Optional[str] = ..., vendor_name_discrepancy: _Optional[bool] = ..., conflict: _Optional[bool] = ..., conflict_detail: _Optional[str] = ..., degraded_providers: _Optional[_Iterable[str]] = ..., from_cache: _Optional[bool] = ..., cache_stale: _Optional[bool] = ...) -> None: ...

class GeocodeResponse(_message.Message):
    __slots__ = ("result", "error_code", "error_detail")
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    result: GeoResultProto
    error_code: str
    error_detail: str
    def __init__(self, result: _Optional[_Union[GeoResultProto, _Mapping]] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...
