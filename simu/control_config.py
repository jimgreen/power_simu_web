from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Tuple


DEFAULT_CONTROL_CONFIG_PATH = (
    Path(__file__).resolve().parent
    / "config"
    / "renewable_control_defaults.json"
)


def _load_default_control_config() -> Mapping[str, Any]:
    try:
        payload = json.loads(DEFAULT_CONTROL_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"unable to load renewable control defaults: {DEFAULT_CONTROL_CONFIG_PATH}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"renewable control defaults must be an object: {DEFAULT_CONTROL_CONFIG_PATH}"
        )
    return MappingProxyType(payload)


DEFAULT_CONTROL_CONFIG = _load_default_control_config()


def default_number(name: str) -> float:
    if name not in DEFAULT_CONTROL_CONFIG:
        raise RuntimeError(f"missing renewable control default: {name}")
    try:
        return float(DEFAULT_CONTROL_CONFIG[name])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid renewable control default: {name}") from exc


def default_integer(name: str) -> int:
    value = default_number(name)
    if not value.is_integer():
        raise RuntimeError(f"renewable control default must be an integer: {name}")
    return int(value)


def default_derating_curve(name: str) -> Tuple[Tuple[float, float], ...]:
    raw_curve = DEFAULT_CONTROL_CONFIG.get(name)
    if not isinstance(raw_curve, list) or len(raw_curve) < 2:
        raise RuntimeError(f"invalid renewable control derating curve: {name}")
    result = []
    for point in raw_curve:
        if not isinstance(point, Mapping):
            raise RuntimeError(f"invalid renewable control derating point: {name}")
        try:
            soc = float(point["soc"])
            power_ratio = float(point["power_ratio"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"invalid renewable control derating point: {name}"
            ) from exc
        result.append((soc, power_ratio))
    return tuple(result)
