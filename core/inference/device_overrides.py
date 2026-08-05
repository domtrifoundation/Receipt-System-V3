"""Manual, persisted per-preset execution-provider overrides — the real "operator can
still pick the device by hand" control the auto-selected `common/execution_provider.py`
default was never meant to replace (§8.6's own hardware-aware *default*, not a mandate).
`InferenceModelRegistry._device_for()` already lets an explicit `device_by_preset` config
entry win outright over the hardware-derived fallback (Phase D) — this module is the real,
persisted, TUI-settable source for that entry, the same `config/*.json` pattern
`services/setup/hardware/persistence.py` already established for `HardwareProfile`.

**Takes effect on restart, not live** — matching `settings_backend.py`'s own precedent
(`auth.get_tenancy_mode`'s `takes_effect_on_restart` note) rather than inventing a new,
riskier "hot-swap an already-loaded model's device mid-session" mechanism this pass has no
real need to build. `SetPresetDevice` writes the override; `_config_from_env()`/`__main__`
reads it back at the *next* process start, merged on top of `RESIBO_INFERENCE_DEVICE`'s
own uniform-across-presets default (an override for one specific preset should not require
an operator to also know and repeat every other preset's own current device).
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["DEVICE_OVERRIDES_RELPATH", "read_device_overrides", "write_device_override"]

DEVICE_OVERRIDES_RELPATH = Path("config") / "inference_device_overrides.json"


def read_device_overrides(install_root: Path) -> dict[str, str]:
    """`{}` when nothing has been set yet or the file is corrupt — never a crash
    (`docs/PRINCIPLES.md` §4.4), matching `hardware/persistence.py`'s own read posture."""
    target = install_root / DEVICE_OVERRIDES_RELPATH
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def write_device_override(install_root: Path, preset: str, device: str) -> None:
    """Read-modify-write against the whole file — one preset's override must never clobber
    another's, the same shape `bootstrap.write_run_on_startup` already uses against
    `install.json`'s own shared file."""
    target = install_root / DEVICE_OVERRIDES_RELPATH
    data = read_device_overrides(install_root)
    data[preset] = device
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
