"""Validated per-model WEB runtime parameter definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


@dataclass(frozen=True)
class RuntimeSettingSpec:
    default: float | int
    minimum: float | int
    maximum: float | int
    value_type: str = "number"

    def public_constraint(self) -> Dict[str, Any]:
        return {
            "type": self.value_type,
            "min": self.minimum,
            "max": self.maximum,
        }


COMMON_RUNTIME_SETTING_SPECS: Dict[str, RuntimeSettingSpec] = {
    "frontend_refresh_seconds": RuntimeSettingSpec(1.0, 0.2, 60.0),
    "frontend_request_timeout_seconds": RuntimeSettingSpec(30.0, 1.0, 300.0),
    "runtime_log_page_size": RuntimeSettingSpec(20, 5, 200, "integer"),
    "runtime_log_cache_limit": RuntimeSettingSpec(300, 50, 5000, "integer"),
    "diagram_flow_electric_threshold_kw": RuntimeSettingSpec(0.1, 0.0, 1000000.0),
    "diagram_flow_hydrogen_threshold_nm3_h": RuntimeSettingSpec(0.1, 0.0, 1000000.0),
}

ROLE_RUNTIME_SETTING_SPECS: Dict[str, Dict[str, RuntimeSettingSpec]] = {
    "simulator": {
        "curve_request_timeout_seconds": RuntimeSettingSpec(8.0, 1.0, 300.0),
        "runtime_log_delta_batch_size": RuntimeSettingSpec(200, 20, 500, "integer"),
        "runtime_log_history_batch_size": RuntimeSettingSpec(120, 20, 500, "integer"),
    },
    "trainee": {
        "backend_refresh_seconds": RuntimeSettingSpec(1.0, 0.1, 60.0),
        "backend_request_timeout_seconds": RuntimeSettingSpec(8.0, 1.0, 300.0),
        "frame_age_limit_seconds": RuntimeSettingSpec(15.0, 1.0, 3600.0),
        "same_frame_limit_seconds": RuntimeSettingSpec(30.0, 1.0, 3600.0),
        "receive_state_sync_seconds": RuntimeSettingSpec(5.0, 0.5, 60.0),
        "receive_max_reconnect_attempts": RuntimeSettingSpec(3, 1, 20, "integer"),
        "measurement_delta_history_limit": RuntimeSettingSpec(200, 10, 5000, "integer"),
    },
}


def normalize_runtime_settings_role(role: Any) -> str:
    normalized = str(role or "").strip().lower()
    if normalized not in ROLE_RUNTIME_SETTING_SPECS:
        raise ValueError(f"Unsupported WEB runtime settings role: {role}")
    return normalized


def runtime_setting_specs(role: Any) -> Dict[str, RuntimeSettingSpec]:
    normalized = normalize_runtime_settings_role(role)
    return {
        **COMMON_RUNTIME_SETTING_SPECS,
        **ROLE_RUNTIME_SETTING_SPECS[normalized],
    }


def default_runtime_settings(role: Any) -> Dict[str, float | int]:
    return {name: spec.default for name, spec in runtime_setting_specs(role).items()}


def _normalize_value(name: str, value: Any, spec: RuntimeSettingSpec) -> float | int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a {spec.value_type}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a {spec.value_type}") from exc
    if not spec.minimum <= number <= spec.maximum:
        raise ValueError(f"{name} must be between {spec.minimum} and {spec.maximum}")
    if spec.value_type == "integer":
        integer = int(number)
        if number != integer:
            raise ValueError(f"{name} must be an integer")
        return integer
    return number


def normalize_runtime_settings(
    role: Any,
    values: Mapping[str, Any],
    *,
    base: Mapping[str, Any] | None = None,
) -> Dict[str, float | int]:
    specs = runtime_setting_specs(role)
    unknown = sorted(set(values) - set(specs))
    if unknown:
        raise ValueError(f"Unknown WEB runtime setting: {unknown[0]}")
    normalized = default_runtime_settings(role)
    if base:
        for name, value in base.items():
            if name in specs:
                normalized[name] = _normalize_value(name, value, specs[name])
    for name, value in values.items():
        normalized[name] = _normalize_value(name, value, specs[name])
    return normalized


def stored_runtime_settings(local_settings: Mapping[str, Any], role: Any) -> Dict[str, Any]:
    normalized_role = normalize_runtime_settings_role(role)
    container = local_settings.get("web_runtime_parameters", {})
    role_entry = container.get(normalized_role, {}) if isinstance(container, Mapping) else {}
    if not isinstance(role_entry, Mapping):
        role_entry = {}
    saved = role_entry.get("settings", {})
    if not isinstance(saved, Mapping):
        saved = {}
    try:
        settings = normalize_runtime_settings(normalized_role, saved)
    except ValueError:
        settings = default_runtime_settings(normalized_role)
    return {
        "version": 1,
        "updated_at": str(role_entry.get("updated_at") or ""),
        "settings": settings,
    }


def runtime_settings_payload(
    local_settings: Mapping[str, Any],
    role: Any,
    *,
    model_id: str,
) -> Dict[str, Any]:
    normalized_role = normalize_runtime_settings_role(role)
    specs = runtime_setting_specs(normalized_role)
    stored = stored_runtime_settings(local_settings, normalized_role)
    settings = dict(stored["settings"])
    return {
        "role": normalized_role,
        "modelId": str(model_id),
        "version": int(stored["version"]),
        "settings": settings,
        "effectiveSettings": dict(settings),
        "defaults": default_runtime_settings(normalized_role),
        "constraints": {
            name: spec.public_constraint()
            for name, spec in specs.items()
        },
        "updatedAt": stored["updated_at"],
    }


def updated_runtime_settings_entry(
    local_settings: Mapping[str, Any],
    role: Any,
    payload: Mapping[str, Any],
    *,
    updated_at: str,
) -> Dict[str, Any]:
    normalized_role = normalize_runtime_settings_role(role)
    allowed_top_level = {"settings"}
    unknown_top_level = sorted(set(payload) - allowed_top_level)
    if unknown_top_level:
        raise ValueError(f"Unknown WEB runtime settings payload field: {unknown_top_level[0]}")
    values = payload.get("settings", {})
    if not isinstance(values, Mapping):
        raise ValueError("settings must be an object")
    current = stored_runtime_settings(local_settings, normalized_role)["settings"]
    normalized = normalize_runtime_settings(normalized_role, values, base=current)
    return {
        "version": 1,
        "updated_at": str(updated_at),
        "settings": normalized,
    }
