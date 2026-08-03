from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers

DESCRIPTOR: _descriptor.FileDescriptor

class DetectHardwareRequest(_message.Message):
    __slots__ = ("extra_report_search_paths",)
    EXTRA_REPORT_SEARCH_PATHS_FIELD_NUMBER: _ClassVar[int]
    extra_report_search_paths: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, extra_report_search_paths: _Iterable[str] | None = ...) -> None: ...

class GpuInfoMessage(_message.Message):
    __slots__ = ("compute_api", "discrete", "name", "shader_core_count", "vendor", "vram_gb")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    DISCRETE_FIELD_NUMBER: _ClassVar[int]
    VRAM_GB_FIELD_NUMBER: _ClassVar[int]
    COMPUTE_API_FIELD_NUMBER: _ClassVar[int]
    SHADER_CORE_COUNT_FIELD_NUMBER: _ClassVar[int]
    name: str
    vendor: str
    discrete: bool
    vram_gb: float
    compute_api: str
    shader_core_count: int
    def __init__(self, name: str | None = ..., vendor: str | None = ..., discrete: bool | None = ..., vram_gb: float | None = ..., compute_api: str | None = ..., shader_core_count: int | None = ...) -> None: ...

class HardwareProfileResponse(_message.Message):
    __slots__ = ("cores", "cpu_name", "detected_at", "gpus", "npus", "ram_gb", "source", "threads")
    CPU_NAME_FIELD_NUMBER: _ClassVar[int]
    CORES_FIELD_NUMBER: _ClassVar[int]
    THREADS_FIELD_NUMBER: _ClassVar[int]
    RAM_GB_FIELD_NUMBER: _ClassVar[int]
    GPUS_FIELD_NUMBER: _ClassVar[int]
    NPUS_FIELD_NUMBER: _ClassVar[int]
    DETECTED_AT_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    cpu_name: str
    cores: int
    threads: int
    ram_gb: int
    gpus: _containers.RepeatedCompositeFieldContainer[GpuInfoMessage]
    npus: _containers.RepeatedScalarFieldContainer[str]
    detected_at: str
    source: str
    def __init__(self, cpu_name: str | None = ..., cores: int | None = ..., threads: int | None = ..., ram_gb: int | None = ..., gpus: _Iterable[GpuInfoMessage | _Mapping] | None = ..., npus: _Iterable[str] | None = ..., detected_at: str | None = ..., source: str | None = ...) -> None: ...

class WizardAnswerMessage(_message.Message):
    __slots__ = ("data", "skipped", "step_id")
    class DataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: str | None = ..., value: str | None = ...) -> None: ...
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    SKIPPED_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    step_id: str
    skipped: bool
    data: _containers.ScalarMap[str, str]
    def __init__(self, step_id: str | None = ..., skipped: bool | None = ..., data: _Mapping[str, str] | None = ...) -> None: ...

class WizardStepMessage(_message.Message):
    __slots__ = ("context", "is_final", "step_id")
    class ContextEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: str | None = ..., value: str | None = ...) -> None: ...
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    IS_FINAL_FIELD_NUMBER: _ClassVar[int]
    step_id: str
    context: _containers.ScalarMap[str, str]
    is_final: bool
    def __init__(self, step_id: str | None = ..., context: _Mapping[str, str] | None = ..., is_final: bool | None = ...) -> None: ...

class ProvisionVenvsRequest(_message.Message):
    __slots__ = ("clone_dir", "python_bin")
    CLONE_DIR_FIELD_NUMBER: _ClassVar[int]
    PYTHON_BIN_FIELD_NUMBER: _ClassVar[int]
    clone_dir: str
    python_bin: str
    def __init__(self, clone_dir: str | None = ..., python_bin: str | None = ...) -> None: ...

class ProvisionOutcomeMessage(_message.Message):
    __slots__ = ("created", "error_code", "error_detail", "import_path", "venv_dir")
    IMPORT_PATH_FIELD_NUMBER: _ClassVar[int]
    VENV_DIR_FIELD_NUMBER: _ClassVar[int]
    CREATED_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAIL_FIELD_NUMBER: _ClassVar[int]
    import_path: str
    venv_dir: str
    created: bool
    error_code: str
    error_detail: str
    def __init__(self, import_path: str | None = ..., venv_dir: str | None = ..., created: bool | None = ..., error_code: str | None = ..., error_detail: str | None = ...) -> None: ...

class ProvisionVenvsResponse(_message.Message):
    __slots__ = ("fully_provisioned", "outcomes")
    OUTCOMES_FIELD_NUMBER: _ClassVar[int]
    FULLY_PROVISIONED_FIELD_NUMBER: _ClassVar[int]
    outcomes: _containers.RepeatedCompositeFieldContainer[ProvisionOutcomeMessage]
    fully_provisioned: bool
    def __init__(self, outcomes: _Iterable[ProvisionOutcomeMessage | _Mapping] | None = ..., fully_provisioned: bool | None = ...) -> None: ...
