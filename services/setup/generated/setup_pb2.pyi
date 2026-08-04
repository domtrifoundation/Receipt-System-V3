from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ConfigRequest(_message.Message):
    __slots__ = ("install_root",)
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    def __init__(self, install_root: _Optional[str] = ...) -> None: ...

class DevModeResponse(_message.Message):
    __slots__ = ("dev_mode", "known")
    DEV_MODE_FIELD_NUMBER: _ClassVar[int]
    KNOWN_FIELD_NUMBER: _ClassVar[int]
    dev_mode: bool
    known: bool
    def __init__(self, dev_mode: _Optional[bool] = ..., known: _Optional[bool] = ...) -> None: ...

class RunOnStartupResponse(_message.Message):
    __slots__ = ("run_on_startup", "known")
    RUN_ON_STARTUP_FIELD_NUMBER: _ClassVar[int]
    KNOWN_FIELD_NUMBER: _ClassVar[int]
    run_on_startup: bool
    known: bool
    def __init__(self, run_on_startup: _Optional[bool] = ..., known: _Optional[bool] = ...) -> None: ...

class SetRunOnStartupRequest(_message.Message):
    __slots__ = ("install_root", "run_on_startup")
    INSTALL_ROOT_FIELD_NUMBER: _ClassVar[int]
    RUN_ON_STARTUP_FIELD_NUMBER: _ClassVar[int]
    install_root: str
    run_on_startup: bool
    def __init__(self, install_root: _Optional[str] = ..., run_on_startup: _Optional[bool] = ...) -> None: ...

class DetectHardwareRequest(_message.Message):
    __slots__ = ("extra_report_search_paths",)
    EXTRA_REPORT_SEARCH_PATHS_FIELD_NUMBER: _ClassVar[int]
    extra_report_search_paths: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, extra_report_search_paths: _Optional[_Iterable[str]] = ...) -> None: ...

class GpuInfoMessage(_message.Message):
    __slots__ = ("name", "vendor", "discrete", "vram_gb", "compute_api", "shader_core_count")
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
    def __init__(self, name: _Optional[str] = ..., vendor: _Optional[str] = ..., discrete: _Optional[bool] = ..., vram_gb: _Optional[float] = ..., compute_api: _Optional[str] = ..., shader_core_count: _Optional[int] = ...) -> None: ...

class HardwareProfileResponse(_message.Message):
    __slots__ = ("cpu_name", "cores", "threads", "ram_gb", "gpus", "npus", "detected_at", "source")
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
    def __init__(self, cpu_name: _Optional[str] = ..., cores: _Optional[int] = ..., threads: _Optional[int] = ..., ram_gb: _Optional[int] = ..., gpus: _Optional[_Iterable[_Union[GpuInfoMessage, _Mapping]]] = ..., npus: _Optional[_Iterable[str]] = ..., detected_at: _Optional[str] = ..., source: _Optional[str] = ...) -> None: ...

class WizardAnswerMessage(_message.Message):
    __slots__ = ("step_id", "skipped", "data")
    class DataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    SKIPPED_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    step_id: str
    skipped: bool
    data: _containers.ScalarMap[str, str]
    def __init__(self, step_id: _Optional[str] = ..., skipped: _Optional[bool] = ..., data: _Optional[_Mapping[str, str]] = ...) -> None: ...

class WizardStepMessage(_message.Message):
    __slots__ = ("step_id", "context", "is_final")
    class ContextEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    IS_FINAL_FIELD_NUMBER: _ClassVar[int]
    step_id: str
    context: _containers.ScalarMap[str, str]
    is_final: bool
    def __init__(self, step_id: _Optional[str] = ..., context: _Optional[_Mapping[str, str]] = ..., is_final: _Optional[bool] = ...) -> None: ...

class ProvisionVenvsRequest(_message.Message):
    __slots__ = ("clone_dir", "python_bin")
    CLONE_DIR_FIELD_NUMBER: _ClassVar[int]
    PYTHON_BIN_FIELD_NUMBER: _ClassVar[int]
    clone_dir: str
    python_bin: str
    def __init__(self, clone_dir: _Optional[str] = ..., python_bin: _Optional[str] = ...) -> None: ...

class ProvisionOutcomeMessage(_message.Message):
    __slots__ = ("import_path", "venv_dir", "created", "error_code", "error_detail")
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
    def __init__(self, import_path: _Optional[str] = ..., venv_dir: _Optional[str] = ..., created: _Optional[bool] = ..., error_code: _Optional[str] = ..., error_detail: _Optional[str] = ...) -> None: ...

class ProvisionVenvsResponse(_message.Message):
    __slots__ = ("outcomes", "fully_provisioned")
    OUTCOMES_FIELD_NUMBER: _ClassVar[int]
    FULLY_PROVISIONED_FIELD_NUMBER: _ClassVar[int]
    outcomes: _containers.RepeatedCompositeFieldContainer[ProvisionOutcomeMessage]
    fully_provisioned: bool
    def __init__(self, outcomes: _Optional[_Iterable[_Union[ProvisionOutcomeMessage, _Mapping]]] = ..., fully_provisioned: _Optional[bool] = ...) -> None: ...
