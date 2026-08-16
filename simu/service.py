"""Service layer for the polar microgrid time-series simulation system.

The service deliberately keeps the web/API layer thin.  It owns the runtime
copies of the E files, projects curve/settings/trainee-command overlays into
those files, calls the existing load-flow kernel, and exposes JSON snapshots
that both the simulator console and trainee console can poll.
"""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from bisect import bisect_left
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from hybrid_power_system_analysis.efile_read import EBlock, EBook
except ImportError:  # The migrated web repo can run outside the original package tree.
    import sys

    ROOT_DIR = Path(__file__).resolve().parents[1]
    LEGACY_PACKAGE_DIR = (
        ROOT_DIR.parent
        / "elec_power_flow"
        / "hybrid_power_system_analysis"
        / "src"
        / "hybrid_power_system_analysis"
    )
    for package_dir in (ROOT_DIR / "src" / "hybrid_power_system_analysis", LEGACY_PACKAGE_DIR):
        if (package_dir / "efile_read.py").exists() and str(package_dir) not in sys.path:
            sys.path.insert(0, str(package_dir))
    from efile_read import EBlock, EBook

try:
    import simu_loop  # type: ignore
except ImportError:  # pragma: no cover - legacy package compatibility.
    from hybrid_power_system_analysis.simu import simu_loop

from simu.definition_editing import (
    clamp_setpoint_safety_bounds,
    DefinitionSnapshot,
    MEASUREMENT_STATUS_TOKENS,
    MEASUREMENT_STATUS_VALIDITY,
    SafetyBoundaryError,
    atomic_write_text,
    normalize_device_changes,
    normalize_measurement_changes,
    ratio_parameter_number,
    require_definition_revision,
)
from simu.device_roles import (
    AC_TO_DC,
    converter_control_mode,
    converter_power_in_dc_to_ac_convention,
    converter_power_setpoint_fields,
)
from simu.device_runtime_frame import compact_device_runtime_frame
from simu.model_semantics import (
    HYDROGEN_CONVERSION_BLOCKS,
    device_family_from_block,
    energy_coupling_control_bindings,
    grid_converter_keys,
    resolve_resource_reference,
    resource_keys_by_alias,
    resources_by_device_key,
    structured_resources,
    normalize_hydrogen_conversion_control_mode,
    resource_aliases,
    terminal_domains_from_block,
    validate_hydrogen_power_setpoint_safety,
)
from simu.measurement_delta import (
    compact_measurement_delta,
    measurement_definition_signature,
    measurement_rows_by_definition_index,
)
from simu.measurement_history import MeasurementHistoryStore
from simu.point_names import automatic_point_name
from simu.power_flow_worker import PowerFlowExecution, PowerFlowTimeoutError
from simu.renewable_capability import renewable_weather_available_kw
from simu.source_curves import (
    load_curve_catalog,
    load_curve_identity,
    source_curve_catalog,
    source_curve_catalog_by_identity,
    source_curve_catalog_by_key,
    source_curve_identity,
)
from simu.web_runtime_settings import runtime_settings_payload, updated_runtime_settings_entry


WEATHER_HEADER = (
    "time",
    "wind_speed_mps",
    "air_temp_c",
    "air_pressure_hpa",
    "solar_irradiance_w_m2",
    "humidity_pct",
    "load_kw",
)

RUNTIME_LOAD_POWER_HEADER = ("dev_type", "dev_name", "p_kw")

MEAS_HEADER = ("idx", "name", "dev_type", "dev_name", "meas_type", "weight", "valid", "value")

DEFAULT_WEATHER: Dict[str, Optional[float]] = {
    "wind_speed_mps": None,
    "air_temp_c": -18.0,
    "air_pressure_hpa": 960.0,
    "solar_irradiance_w_m2": None,
    "humidity_pct": 72.0,
    "load_kw": 100.0,
}
UNKNOWN_WEATHER_VALUE = "NA"


class ServiceInstanceRetiredError(RuntimeError):
    """Raised when a request targets a service lifecycle that has been retired."""

WEATHER_MEASUREMENTS = (
    ("wind_speed_mps", "wind_speed", "WIND_SPEED"),
    ("air_temp_c", "air_temp", "AIR_TEMP"),
    ("humidity_pct", "humidity", "HUMIDITY"),
    ("air_pressure_hpa", "air_pressure", "AIR_PRESSURE"),
    ("solar_irradiance_w_m2", "solar_irradiance", "SOLAR_IRRADIANCE"),
)

WEATHER_MEASUREMENT_TYPE_SET = {item[2] for item in WEATHER_MEASUREMENTS}
SIGNAL_MEASUREMENT_TYPES = {"RUN_STAT", "STATUS"}
SIGNAL_MEASUREMENTS = (
    ("RunStat", "run_stat", "RUN_STAT", "run_stat"),
    ("CbOpenStat", "status", "STATUS", "status"),
)
SNAPSHOT_STATIC_FIELDS = (
    "files",
    "source_files",
    "work_files",
    "definitions",
    "curves",
    "settings",
    "device_parameters",
    "diagram",
)

STAT_HEADERS = {
    "RunStat": ("dev_type", "dev_name", "run_stat"),
    "CbOpenStat": ("dev_type", "dev_name", "status"),
    "SetValue": ("dev_type", "dev_name", "set_type", "set_value"),
    "StorageSoc": ("dev_type", "idx", "name", "soc_curr"),
    "HydroStorageState": (
        "dev_type",
        "idx",
        "name",
        "pressure",
        "flow",
        "gas_quantity",
        "soc",
    ),
}
RUNTIME_CONTROL_STATUS_FIELDS = frozenset(("run_stat", "status"))
RUNTIME_CONTROL_SETPOINT_FIELDS = frozenset(
    (
        "p_set",
        "q_set",
        "v_set",
        "i_set",
        "p_ac_set",
        "q_ac_set",
        "v_ac_set",
        "v_dc_set",
        "p_dc_set",
        "q_dc_set",
        "p_from_set",
        "q_from_set",
        "v_from_set",
        "p_to_set",
        "q_to_set",
        "v_to_set",
        "flow_set",
        "heat_power",
    )
)

EXTERNAL_REALTIME_WEATHER_FIELDS = (
    ("wind_speed_mps", "m/s"),
    ("solar_irradiance_w_m2", "W/m2"),
    ("air_temp_c", "degC"),
    ("air_pressure_hpa", "hPa"),
    ("humidity_pct", "%"),
)
EXTERNAL_REALTIME_WEATHER_FIELD_SET = {item[0] for item in EXTERNAL_REALTIME_WEATHER_FIELDS}
EXTERNAL_CURVE_ENVIRONMENT_SPECS = {
    "wind_speed_mps": "m/s",
    "solar_irradiance_w_m2": "W/m2",
    "air_temp_c": "℃",
}
RUNTIME_CONTROL_SETPOINT_ALIASES = {
    ("ACLoad", "pv0"): "p_set",
    ("ACLoad", "qv0"): "q_set",
    ("DCLoad", "pv0"): "p_set",
    ("DCLoad", "qv0"): "q_set",
}
DEFINITION_DEFAULTS_FILE = "definition_defaults.json"
SOURCE_DEFINITION_FILES = (
    "model.e",
    "meas.e",
    "stat.e",
    "control.e",
    "weather.e",
    "curves.e",
    DEFINITION_DEFAULTS_FILE,
)
LEGACY_RUNTIME_DEFINITION_FILES = SOURCE_DEFINITION_FILES + ("device.e",)
DIAGRAM_FILE_NAME = "diagram.svg"
MANUAL_DEFINITION_CHANGES_FILE = "manual_overrides.json"
CONTROL_DEFINITION_BLOCKS = ("RunStat", "CbOpenStat", "SetValue", "StorageSoc")
CLOCK_SPEED_LEVELS = (1.0, 5.0, 15.0, 30.0, 60.0, 300.0, 900.0, 1800.0, 3600.0)
SIMULATION_MODE_CONFIGS: Dict[str, Dict[str, float | int | str]] = {
    "hour": {
        "label": "时仿真",
        "duration_minutes": 60.0,
        "time_step_minutes": 1.0 / 60.0,
        "point_count": 3600,
        "default_clock_speed": 1.0,
        "day_count": 1,
    },
    "day": {
        "label": "日仿真",
        "duration_minutes": 24.0 * 60.0,
        "time_step_minutes": 1.0,
        "point_count": 1440,
        "default_clock_speed": 60.0,
        "day_count": 1,
    },
    "week": {
        "label": "周仿真",
        "duration_minutes": 7.0 * 24.0 * 60.0,
        "time_step_minutes": 1.0,
        "point_count": 7 * 1440,
        "default_clock_speed": 60.0,
        "day_count": 7,
    },
    "month": {
        "label": "月仿真",
        "duration_minutes": 30.0 * 24.0 * 60.0,
        "time_step_minutes": 60.0,
        "point_count": 30 * 24,
        "default_clock_speed": 3600.0,
        "day_count": 30,
    },
    "year": {
        "label": "年仿真",
        "duration_minutes": 365.0 * 24.0 * 60.0,
        "time_step_minutes": 60.0,
        "point_count": 365 * 24,
        "default_clock_speed": 3600.0,
        "day_count": 365,
    },
}
DEFAULT_CONTROL_VALID_MINUTES = 120.0
COMMAND_HISTORY_RECENT_LIMIT = 200
RUNTIME_LOG_HISTORY_LIMIT = 500
RUNTIME_LOG_JOURNAL_ENTRY_LIMIT = 64
RUNTIME_LOG_JOURNAL_BYTE_LIMIT = 256 * 1024
DEFAULT_COMPUTE_INTERVAL_SECONDS = 1.0
DEFAULT_STORAGE_INITIAL_SOC = 0.5
DEFAULT_REMOTE_ADJUSTMENT_RESPONSE_RATIO = 0.7
LOG_DECIMAL_PATTERN = re.compile(r"(?<![\w:])[-+]?\d+\.\d+(?:e[-+]?\d+)?(?![\w:])", re.IGNORECASE)


@dataclass
class ClockState:
    state: str = "stopped"
    minute: float = 0.0
    absolute_minute: float = 0.0
    speed: float = 1.0
    step_minutes: float = 1.0 / 60.0
    run_id: int = 0
    step_count: int = 0
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        def clock_number(value: int | float) -> int | float:
            rounded = round(float(value), 9)
            return int(rounded) if rounded.is_integer() else rounded

        effective_step_minutes = _effective_clock_step(self.step_minutes, self.speed)
        return {
            "state": self.state,
            "minute": clock_number(self.minute),
            "absolute_minute": clock_number(self.absolute_minute),
            "second": clock_number(self.minute * 60.0),
            "absolute_second": clock_number(self.absolute_minute * 60.0),
            "speed": self.speed,
            "step_minutes": clock_number(self.step_minutes),
            "step_seconds": clock_number(self.step_minutes * 60.0),
            "effective_step_minutes": clock_number(effective_step_minutes),
            "effective_step_seconds": clock_number(effective_step_minutes * 60.0),
            "run_id": self.run_id,
            "step_count": self.step_count,
            "time": minute_to_time(self.minute),
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SimulationModelSpec:
    """Input model definition for one independent simulation instance."""

    model_id: str
    sim_dir: str | Path
    name: str = ""

    def normalized(self) -> "SimulationModelSpec":
        model_id = _safe_model_id(self.model_id)
        return SimulationModelSpec(model_id=model_id, sim_dir=Path(self.sim_dir).resolve(), name=self.name or model_id)


def minute_to_time(minute: int | float) -> str:
    total_seconds = int(round((float(minute) % 1440.0) * 60.0))
    hour = (total_seconds // 3600) % 24
    minute_part = (total_seconds // 60) % 60
    second = total_seconds % 60
    return f"{hour:02d}:{minute_part:02d}:{second:02d}"


def _align_minute_to_step(minute: int | float, step_minutes: int | float) -> float:
    step = max(1e-9, float(step_minutes))
    value = max(0.0, float(minute))
    quotient = math.ceil((value - 1e-9) / step)
    return round(max(0.0, quotient * step), 9)


def _effective_clock_step(step_minutes: int | float, speed: int | float) -> float:
    return max(1e-9, float(step_minutes) * float(speed))


def _normalize_simulation_mode(value: Any, fallback: str = "day") -> str:
    mode = str(value or fallback).strip().lower()
    if mode in SIMULATION_MODE_CONFIGS:
        return mode
    return fallback if fallback in SIMULATION_MODE_CONFIGS else "day"


def _simulation_mode_config(value: Any) -> Mapping[str, float | int | str]:
    return SIMULATION_MODE_CONFIGS[_normalize_simulation_mode(value)]


def _simulation_mode_duration_minutes(value: Any) -> float:
    return float(_simulation_mode_config(value)["duration_minutes"])


def _simulation_mode_curve_step_minutes(value: Any) -> float:
    return float(_simulation_mode_config(value)["time_step_minutes"])


def _simulation_mode_point_count(value: Any) -> int:
    return int(_simulation_mode_config(value)["point_count"])


def _simulation_mode_default_clock_speed(value: Any) -> float:
    return float(_simulation_mode_config(value)["default_clock_speed"])


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_scalar(value: Any) -> Any:
    if value in (None, ""):
        return value
    if isinstance(value, (int, float, bool)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return number


def _nearest_clock_speed(value: Any) -> float:
    speed = _to_float(value, CLOCK_SPEED_LEVELS[0])
    if speed is None:
        return CLOCK_SPEED_LEVELS[0]
    return min(CLOCK_SPEED_LEVELS, key=lambda level: (abs(level - speed), level))


def _compute_interval_seconds(value: Any, default: float = DEFAULT_COMPUTE_INTERVAL_SECONDS) -> float:
    interval = _to_float(value, default)
    if interval is None or not math.isfinite(interval):
        interval = default
    return min(3600.0, max(0.1, float(interval)))


def _storage_initial_soc(value: Any, default: float = DEFAULT_STORAGE_INITIAL_SOC) -> float:
    try:
        soc = ratio_parameter_number(
            "state_of_charge",
            value,
            legacy_percent_points=True,
        )
    except (TypeError, ValueError):
        soc = default
    if not math.isfinite(soc):
        soc = default
    return min(1.0, max(0.0, float(soc)))


def _remote_adjustment_response_ratio(
    value: Any,
    default: float = DEFAULT_REMOTE_ADJUSTMENT_RESPONSE_RATIO,
) -> float:
    ratio = _to_float(value, default)
    if ratio is None or not math.isfinite(ratio):
        ratio = default
    return min(1.0, max(0.01, float(ratio)))


def _next_clock_speed(value: Any) -> float:
    speed = _to_float(value, CLOCK_SPEED_LEVELS[0]) or CLOCK_SPEED_LEVELS[0]
    for level in CLOCK_SPEED_LEVELS:
        if level > speed:
            return level
    return CLOCK_SPEED_LEVELS[-1]


def _previous_clock_speed(value: Any) -> float:
    speed = _to_float(value, CLOCK_SPEED_LEVELS[0]) or CLOCK_SPEED_LEVELS[0]
    for level in reversed(CLOCK_SPEED_LEVELS):
        if level < speed:
            return level
    return CLOCK_SPEED_LEVELS[0]


def _number_text(value: Any) -> str:
    number = _to_float(value, None)
    if number is None:
        return "" if value is None else str(value)
    return format_number(number)


def _value_with_unit(value: Any, unit: str) -> str:
    text = _number_text(value)
    return f"{text} {unit}" if text else "未知"


def format_number(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        return str(number)
    if abs(number) < 5e-13:
        number = 0.0
    text = f"{number:.10g}"
    return "0" if text == "-0" else text


def _format_log_number(value: Any, *, scientific: bool = False) -> str:
    number = _to_float(value, None)
    if number is None or not math.isfinite(number):
        return "" if value is None else str(value)
    if scientific:
        return re.sub(r"e([+-])0+(\d+)$", r"e\1\2", f"{number:.2e}")
    if abs(number) < 0.005:
        number = 0.0
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _format_log_text_numbers(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return _format_log_number(token, scientific="e" in token.casefold())

    return LOG_DECIMAL_PATTERN.sub(repl, text)


def _format_log_detail(detail: Any) -> Any:
    if isinstance(detail, str):
        return _format_log_text_numbers(detail)
    if isinstance(detail, bool) or detail is None:
        return detail
    if isinstance(detail, (int, float)):
        return _format_log_number(detail)
    if isinstance(detail, list):
        return [_format_log_detail(item) for item in detail]
    if isinstance(detail, tuple):
        return [_format_log_detail(item) for item in detail]
    if isinstance(detail, Mapping):
        return {key: _format_log_detail(value) for key, value in detail.items()}
    return detail


def parse_measurement_rows(meas_file: Path) -> Tuple[List[str], List[List[str]], List[str]]:
    before: List[str] = []
    rows: List[List[str]] = []
    after: List[str] = []
    in_measurement = False
    seen_measurement = False
    with meas_file.open("rt", encoding="utf-8") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if line == "<Measurement>":
                in_measurement = True
                seen_measurement = True
                continue
            if line == "</Measurement>":
                in_measurement = False
                continue
            if not in_measurement:
                if not seen_measurement:
                    before.append(raw_line.rstrip("\n"))
                elif line:
                    after.append(raw_line.rstrip("\n"))
                continue
            if not line or line.startswith("@"):
                continue
            if line.startswith("#"):
                parts = line[1:].split()
                if len(parts) != len(MEAS_HEADER):
                    raise RuntimeError(f"Invalid measurement row in {meas_file}: {line}")
                rows.append(parts)
    if not seen_measurement:
        raise RuntimeError(f"{meas_file} does not contain a <Measurement> block")
    return before, rows, after


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":") if compact else None,
            indent=None if compact else 2,
        ),
        encoding="utf-8",
    )


def _safe_model_id(value: Any) -> str:
    text = str(value or "default").strip()
    cleaned = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in text)
    return cleaned.strip("_") or "default"


def _model_key(value: Any) -> str:
    return _safe_model_id(value).casefold()


def _clear_directory_contents(directory: Path) -> int:
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    removed = 0
    for path in list(root.iterdir()):
        if path.is_symlink():
            path.unlink()
            removed += 1
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Refusing to clear path outside runtime directory: {path}") from exc
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed += 1
    return removed


def _make_book(blocks: Mapping[str, Tuple[Sequence[str], Sequence[Mapping[str, Any]]]]) -> EBook:
    book = EBook({})
    for name, (headers, rows) in blocks.items():
        block = EBlock(name)
        block.header_list = list(headers)
        block.data = [{key: row.get(key, "") for key in headers} for row in rows]
        book.data[name] = block
    return book


def _ensure_block(book: EBook, name: str, headers: Sequence[str]) -> EBlock:
    block = book.data.get(name)
    if block is None:
        block = EBlock(name)
        block.header_list = list(headers)
        block.data = []
        book.data[name] = block
        return block
    for header in headers:
        if header not in block.header_list:
            block.header_list.append(header)
            for row in block.data:
                row[header] = ""
    return block


def _dev_name(row: Mapping[str, Any]) -> str:
    return str(row.get("dev_name", row.get("name", "")))


def _find_dev_row(block: EBlock, dev_type: str, dev_name: str) -> Optional[dict]:
    for row in block.data:
        if str(row.get("dev_type", "")) == str(dev_type) and _dev_name(row) == str(dev_name):
            return row
    return None


def _find_set_row(block: EBlock, dev_type: str, dev_name: str, set_type: str) -> Optional[dict]:
    for row in block.data:
        if (
            str(row.get("dev_type", "")) == str(dev_type)
            and _dev_name(row) == str(dev_name)
            and str(row.get("set_type", "")) == str(set_type)
        ):
            return row
    return None


def _load_book(path: Path) -> EBook:
    return EBook(path) if path.exists() else EBook({})


def ensure_dcac_dcp_control_rows(model_book: EBook, control_book: EBook) -> int:
    converter_block = model_book.data.get("DCACConverter")
    if converter_block is None or "p_dc_set" not in getattr(converter_block, "header_list", []):
        return 0
    set_block = _ensure_block(control_book, "SetValue", STAT_HEADERS["SetValue"])
    added = 0
    for converter in getattr(converter_block, "data", []):
        name = str(converter.get("name", converter.get("dev_name", ""))).strip()
        if not name or "p_dc_set" not in converter:
            continue
        if _find_set_row(set_block, "DCACConverter", name, "p_dc_set") is not None:
            continue
        set_block.data.append(
            {
                "dev_type": "DCACConverter",
                "dev_name": name,
                "set_type": "p_dc_set",
                "set_value": converter.get("p_dc_set", 0),
            }
        )
        added += 1
    return added


def _reconcile_hydrogen_inline_flow_measurements(
    model_book: EBook,
    measurement_rows: Sequence[Sequence[Any]],
) -> Tuple[List[List[str]], int]:
    return simu_loop.reconcile_hydrogen_inline_flow_measurements(
        model_book,
        measurement_rows,
    )


def _active_window(
    item: Mapping[str, Any],
    minute: int | float,
    absolute_minute: Optional[int | float] = None,
    curve_mode: str = "day",
) -> bool:
    mode = _normalize_simulation_mode(curve_mode)
    day_count = int(_simulation_mode_config(mode)["day_count"])
    if mode in ("week", "month", "year"):
        absolute = float(minute if absolute_minute is None else absolute_minute)
        current_day = int(absolute // 1440) % day_count + 1
        start = min(day_count, max(1, int(_to_float(item.get("start_day", 1), 1) or 1)))
        clear_value = item.get("clear_day", item.get("end_day"))
        if clear_value in (None, ""):
            return current_day >= start
        clear = min(day_count, max(1, int(_to_float(clear_value, day_count) or day_count)))
        if start < clear:
            return start <= current_day <= clear
        if start > clear:
            return current_day >= start or current_day <= clear
        return current_day == start

    start = int(_to_float(item.get("start_minute", item.get("start", 0)), 0) or 0) % 1440
    clear_value = item.get("clear_minute", item.get("end_minute", item.get("clear")))
    if clear_value in (None, ""):
        return minute >= start
    clear = int(_to_float(clear_value, 1440) or 1440) % 1440
    if start < clear:
        return start <= minute < clear
    if start > clear:
        return minute >= start or minute < clear
    return True


def _is_trainee_command_source(source: Any) -> bool:
    text = str(source or "").strip().casefold()
    if not text:
        return False
    if "学员" in text:
        return True
    return text in {"student", "trainee"} or text.startswith("student-") or text.startswith("trainee-")


def _is_simulator_command_source(source: Any) -> bool:
    text = str(source or "").strip().casefold()
    if not text:
        return False
    if "模拟台" in text:
        return True
    return text in {"simulator", "teacher"} or text.startswith("simulator-") or text.startswith("teacher-")


def _has_cancel_command_payload(payload: Mapping[str, Any]) -> bool:
    for key in ("cancel_commands", "cancelCommands", "cancel_items", "cancelItems", "cancel_names", "cancelNames"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) > 0:
            return True
    action = str(payload.get("action", payload.get("operation", "")) or "").strip().casefold()
    if action in {
        "cancel_strategy_generation",
        "cancel-strategy-generation",
        "revoke_strategy_generation",
        "revoke-strategy-generation",
    }:
        return True
    if action in {"cancel", "cancel_command", "cancel_commands", "取消", "取消指令"}:
        return True
    return bool(payload.get("cancel") is True and any(key in payload for key in ("name", "names", "commands", "items", "controls")))


def _strategy_generation_metadata(payload: Mapping[str, Any]) -> Tuple[str, Any, bool]:
    strategy = payload.get("strategy")
    strategy_payload = strategy if isinstance(strategy, Mapping) else {}
    strategy_id = str(
        payload.get(
            "strategy_id",
            payload.get(
                "strategyId",
                strategy_payload.get("strategy_id", strategy_payload.get("strategyId", "")),
            ),
        )
        or ""
    ).strip()
    generation = payload.get(
        "generation",
        payload.get(
            "strategy_generation",
            payload.get(
                "strategyGeneration",
                strategy_payload.get(
                    "generation",
                    strategy_payload.get("strategy_generation", strategy_payload.get("strategyGeneration")),
                ),
            ),
        ),
    )
    if generation is not None and not isinstance(generation, (str, int, float)):
        generation = str(generation)
    if isinstance(generation, str):
        generation = generation.strip()
    replace_generation = bool(
        payload.get(
            "replace_strategy_generation",
            payload.get(
                "replaceStrategyGeneration",
                strategy_payload.get(
                    "replace_strategy_generation",
                    strategy_payload.get("replaceStrategyGeneration", False),
                ),
            ),
        )
    )
    return strategy_id, generation, replace_generation


def _strategy_generation_matches(left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return False
    left_number = _to_float(left, None)
    right_number = _to_float(right, None)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return str(left).strip() == str(right).strip()


def _explicit_command_origin(entry_or_payload: Mapping[str, Any]) -> str:
    payload = entry_or_payload.get("payload") if isinstance(entry_or_payload.get("payload"), Mapping) else entry_or_payload
    for candidate in (entry_or_payload, payload):
        if not isinstance(candidate, Mapping):
            continue
        value = str(
            candidate.get(
                "command_origin",
                candidate.get("commandOrigin", candidate.get("origin", candidate.get("priority", ""))),
            )
            or ""
        ).strip().casefold()
        if value in {"manual", "human", "operator", "人工"}:
            return "manual"
        if value in {"automatic", "auto", "strategy", "自动"}:
            return "automatic"
    return ""


def _manual_command_holds_across_clock_lifecycle(entry_or_payload: Mapping[str, Any], source: Any = "") -> bool:
    payload = entry_or_payload.get("payload") if isinstance(entry_or_payload.get("payload"), Mapping) else entry_or_payload
    text = str(
        source
        or entry_or_payload.get("source", "")
        or (payload.get("source", "") if isinstance(payload, Mapping) else "")
        or ""
    ).strip().casefold()
    if (isinstance(payload, Mapping) and isinstance(payload.get("strategy"), Mapping)) or "renewable" in text or "strategy" in text:
        return False
    explicit_origin = _explicit_command_origin(entry_or_payload)
    if explicit_origin:
        return explicit_origin == "manual"
    for candidate in (entry_or_payload, payload):
        if not isinstance(candidate, Mapping):
            continue
        if "manual_hold" in candidate:
            return bool(candidate.get("manual_hold"))
        if "hold_until_cancelled" in candidate:
            return bool(candidate.get("hold_until_cancelled"))
    return text in {"trainee-ui", "student-ui"} or text.startswith("trainee-ui-") or text.startswith("student-ui-") or "人工" in text


def _command_origin(entry_or_payload: Mapping[str, Any], source: Any = "") -> str:
    return "manual" if _manual_command_holds_across_clock_lifecycle(entry_or_payload, source) else "automatic"


def _cancel_command_origin_filter(payload: Mapping[str, Any]) -> str:
    value = str(
        payload.get(
            "command_origin",
            payload.get("commandOrigin", payload.get("origin", payload.get("priority", "all"))),
        )
        or "all"
    ).strip().casefold()
    if value in {"manual", "human", "operator", "人工"}:
        return "manual"
    if value in {"automatic", "auto", "strategy", "自动"}:
        return "automatic"
    return "all"


def _first_number(source: Mapping[str, Any], keys: Sequence[str]) -> Optional[float]:
    for key in keys:
        if key not in source:
            continue
        value = _to_float(source.get(key), None)
        if value is not None:
            return value
    return None


def _command_valid_minutes(payload: Mapping[str, Any], item: Optional[Mapping[str, Any]] = None) -> float:
    minute_keys = (
        "valid_for_minutes",
        "valid_minutes",
        "validity_minutes",
        "duration_minutes",
        "ttl_minutes",
    )
    second_keys = ("valid_for_seconds", "valid_seconds", "ttl_seconds", "duration_seconds")
    minute_value = _first_number(item or {}, minute_keys)
    if minute_value is None:
        minute_value = _first_number(payload, minute_keys)
    if minute_value is not None:
        return max(1e-6, minute_value)
    second_value = _first_number(item or {}, second_keys)
    if second_value is None:
        second_value = _first_number(payload, second_keys)
    if second_value is not None:
        return max(1e-6, second_value / 60.0)
    return DEFAULT_CONTROL_VALID_MINUTES


def _command_expires_at(payload: Mapping[str, Any], item: Optional[Mapping[str, Any]], issued_absolute_minute: float) -> float:
    absolute_keys = (
        "expires_at_absolute_minute",
        "expire_absolute_minute",
        "valid_until_absolute_minute",
        "end_absolute_minute",
    )
    day_minute_keys = ("expires_at_minute", "expire_minute", "valid_until_minute", "end_minute")
    absolute = _first_number(item or {}, absolute_keys)
    if absolute is None:
        absolute = _first_number(payload, absolute_keys)
    if absolute is not None and absolute > issued_absolute_minute:
        return absolute
    day_minute = _first_number(item or {}, day_minute_keys)
    if day_minute is None:
        day_minute = _first_number(payload, day_minute_keys)
    if day_minute is not None:
        current_day = issued_absolute_minute % 1440.0
        delta = (day_minute - current_day) % 1440.0
        if delta <= 1e-9:
            delta = 1440.0
        return issued_absolute_minute + delta
    return issued_absolute_minute + _command_valid_minutes(payload, item)


def _has_relative_command_validity(payload: Mapping[str, Any], item: Optional[Mapping[str, Any]] = None) -> bool:
    minute_keys = (
        "valid_for_minutes",
        "valid_minutes",
        "validity_minutes",
        "duration_minutes",
        "ttl_minutes",
    )
    second_keys = ("valid_for_seconds", "valid_seconds", "ttl_seconds", "duration_seconds")
    return (
        _first_number(item or {}, minute_keys) is not None
        or _first_number(payload, minute_keys) is not None
        or _first_number(item or {}, second_keys) is not None
        or _first_number(payload, second_keys) is not None
    )


def _has_stale_absolute_command_expiry(
    payload: Mapping[str, Any],
    issued_absolute_minute: float,
    item: Optional[Mapping[str, Any]] = None,
) -> bool:
    absolute_keys = (
        "expires_at_absolute_minute",
        "expire_absolute_minute",
        "valid_until_absolute_minute",
        "end_absolute_minute",
    )
    absolute = _first_number(item or {}, absolute_keys)
    if absolute is None:
        absolute = _first_number(payload, absolute_keys)
    return absolute is not None and absolute <= issued_absolute_minute


def _sender_command_valid_minutes(payload: Mapping[str, Any], item: Optional[Mapping[str, Any]] = None) -> Optional[float]:
    absolute_keys = (
        "expires_at_absolute_minute",
        "expire_absolute_minute",
        "valid_until_absolute_minute",
        "end_absolute_minute",
    )
    sent_keys = (
        "sent_absolute_minute",
        "trainee_sent_absolute_minute",
        "command_absolute_minute",
        "sender_absolute_minute",
    )
    absolute = _first_number(item or {}, absolute_keys)
    if absolute is None:
        absolute = _first_number(payload, absolute_keys)
    sent = _first_number(item or {}, sent_keys)
    if sent is None:
        sent = _first_number(payload, sent_keys)
    if absolute is None or sent is None:
        return None
    duration = absolute - sent
    return duration if duration > 0 else None


def _normalize_points(points: Any, value_aliases: Sequence[str]) -> List[Dict[str, Any]]:
    if points is None:
        return []
    if isinstance(points, Mapping):
        minutes = points.get("minute", points.get("minutes", []))
        if not isinstance(minutes, Sequence) or isinstance(minutes, (str, bytes)):
            minutes = []
        normalized: List[Dict[str, Any]] = []
        for idx, minute in enumerate(minutes):
            row: Dict[str, Any] = {"minute": _to_float(minute, 0.0) or 0.0}
            for key, values in points.items():
                if key in ("minute", "minutes"):
                    continue
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and idx < len(values):
                    row[key] = values[idx]
            normalized.append(row)
        if normalized:
            return normalized
        row = {"minute": _to_float(points.get("minute", 0), 0.0) or 0.0}
        for key in value_aliases:
            if key in points:
                row[key] = points[key]
        return [row] if len(row) > 1 else []
    if isinstance(points, Sequence) and not isinstance(points, (str, bytes)):
        normalized = []
        for idx, item in enumerate(points):
            if isinstance(item, Mapping):
                row = dict(item)
                row["minute"] = _to_float(row.get("minute", idx), float(idx)) or 0.0
                normalized.append(row)
            else:
                normalized.append({"minute": float(idx), value_aliases[0]: item})
        return normalized
    return []


def _interpolate(
    points: Sequence[Mapping[str, Any]],
    minute: int | float,
    key: str,
    default: Optional[float],
    *,
    period_minutes: float = 1440.0,
) -> Optional[float]:
    series = _compile_interpolation_series(points, key, period_minutes)
    return _interpolate_compiled_series(
        series,
        minute,
        default,
        period_minutes=period_minutes,
    )


def _compile_interpolation_series(
    points: Sequence[Mapping[str, Any]],
    key: str,
    period_minutes: float,
) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    pairs: List[Tuple[float, float]] = []
    for point in points:
        value = _to_float(point.get(key), None)
        if value is None:
            continue
        pairs.append((float(point.get("minute", 0)) % period_minutes, value))
    pairs.sort(key=lambda item: item[0])
    return (
        tuple(item[0] for item in pairs),
        tuple(item[1] for item in pairs),
    )


def _interpolate_compiled_series(
    series: Tuple[Sequence[float], Sequence[float]],
    minute: int | float,
    default: Optional[float],
    *,
    period_minutes: float = 1440.0,
) -> Optional[float]:
    minutes, values = series
    if not minutes:
        return default
    m = float(minute % period_minutes)
    if len(minutes) == 1:
        return values[0]
    # Match the legacy linear scan: an exact timestamp, including duplicate
    # timestamps, uses the first point at that timestamp.
    position = bisect_left(minutes, m)
    if position == 0:
        prev_m, prev_v = minutes[-1] - period_minutes, values[-1]
        next_m, next_v = minutes[0], values[0]
    elif position >= len(minutes):
        prev_m, prev_v = minutes[-1], values[-1]
        next_m, next_v = minutes[0] + period_minutes, values[0]
    else:
        prev_m, prev_v = minutes[position - 1], values[position - 1]
        next_m, next_v = minutes[position], values[position]
    span = next_m - prev_m
    if span <= 1e-9:
        return prev_v
    ratio = (m - prev_m) / span
    return prev_v + ratio * (next_v - prev_v)


def _measurement_row_to_dict(row: Sequence[str]) -> Dict[str, Any]:
    item = dict(zip(MEAS_HEADER, row))
    item["idx"] = int(_to_float(item.get("idx"), 0) or 0)
    item["weight"] = _to_float(item.get("weight"), 0.0)
    item["valid"] = int(_to_float(item.get("valid"), 0) or 0)
    item["value"] = _to_float(item.get("value"), 0.0)
    return item


def _normalized_measurement_median_deviation_pairs(
    values: Mapping[str, Any] | Sequence[Sequence[Any]] | None,
) -> Tuple[Tuple[str, float], ...]:
    items = values.items() if isinstance(values, Mapping) else (values or ())
    normalized: Dict[str, float] = {}
    for raw_name, raw_value in items:
        name = str(raw_name).strip()
        number = _to_float(raw_value, None)
        if not name or number is None or not math.isfinite(number):
            continue
        if number == 0.0:
            normalized.pop(name, None)
        else:
            normalized[name] = float(number)
    return tuple(sorted(normalized.items()))


def _measurement_median_deviation_map(snapshot: DefinitionSnapshot) -> Dict[str, float]:
    return dict(snapshot.measurement_median_deviations)


def _measurement_definition_row_to_dict(
    row: Sequence[str],
    median_deviations: Mapping[str, float],
) -> Dict[str, Any]:
    item = _measurement_row_to_dict(row)
    item["median_deviation"] = float(median_deviations.get(str(item.get("name", "")), 0.0))
    return item


def _measurement_dict_to_row(item: Mapping[str, Any]) -> List[str]:
    return [str(item.get(key, "")) for key in MEAS_HEADER]


def _measurement_status_from_valid(value: Any) -> str:
    try:
        return "valid" if int(_to_float(value, 0) or 0) == 1 else "invalid"
    except (TypeError, ValueError):
        return "invalid"


class PolarMicrogridSimulator:
    """Runtime service for simulator and trainee web consoles."""

    def __init__(
        self,
        sim_dir: str | Path,
        runtime_dir: str | Path,
        kernel: Optional[Callable[[simu_loop.SimulationConfig], Optional[simu_loop.SimulationResult]]] = None,
        *,
        kernel_runner: Optional[Any] = None,
        period_seconds: float = 60.0,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        compute_interval_seconds: float = DEFAULT_COMPUTE_INTERVAL_SECONDS,
        model_id: str = "default",
        model_name: str = "",
        clear_commands_on_start_and_reset: bool = False,
        enforce_runtime_setpoint_bounds: bool = True,
    ) -> None:
        self.sim_dir = Path(sim_dir).resolve()
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.model_id = _safe_model_id(model_id)
        self.model_name = model_name or self.model_id
        self.clear_commands_on_start_and_reset = bool(clear_commands_on_start_and_reset)
        self.enforce_runtime_setpoint_bounds = bool(enforce_runtime_setpoint_bounds)
        self.service_instance_id = uuid.uuid4().hex
        self.kernel = kernel or simu_loop.run_once
        self.kernel_runner = kernel_runner
        self.period_seconds = float(period_seconds)
        self._initial_compute_interval_seconds = _compute_interval_seconds(compute_interval_seconds)
        self.compute_interval_seconds = self._initial_compute_interval_seconds
        self.storage_initial_soc = DEFAULT_STORAGE_INITIAL_SOC
        self.remote_adjustment_response_ratio = DEFAULT_REMOTE_ADJUSTMENT_RESPONSE_RATIO
        self._remote_adjustment_execution: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._remote_adjustment_cycle_seq = 0
        self.noise_std = noise_std
        self.random_seed = random_seed
        self.clock = ClockState()
        self.lock = threading.RLock()
        self._step_lock = threading.Lock()
        self._service_instance_lifecycle_lock = threading.RLock()
        self._service_instance_retired = False
        # Definition/control transactions always acquire this lock before
        # ``self.lock``. Reentrancy lets model-import helpers compose safely.
        self.definition_update_lock = threading.RLock()
        # Curve definitions change only through explicit editing APIs. Keep their
        # short read lock separate from the long-running power-flow calculation lock.
        self.curves_lock = threading.RLock()
        self._curve_revision = 0
        self._curve_boundary_cache_key: Optional[Tuple[Any, ...]] = None
        self._curve_boundary_cache_value: Optional[Dict[str, Any]] = None
        self._compiled_curve_revision = -1
        self._compiled_curve_series_cache: Dict[
            Tuple[int, str, float],
            Tuple[Tuple[float, ...], Tuple[float, ...]],
        ] = {}
        self._load_curve_target_cache_key: Optional[Tuple[int, int]] = None
        self._load_curve_target_cache_value: Dict[
            str,
            Tuple[int, Tuple[Tuple[str, str], ...]],
        ] = {}
        self._source_curve_catalog_cache_key = -1
        self._source_curve_catalog_cache_value: Tuple[Dict[str, Any], ...] = ()
        self._measurement_bindings_cache_revision = -1
        self._measurement_bindings_cache: Tuple[simu_loop.MeasurementBinding, ...] = ()
        self._latest_power_summary_cache_key: Optional[Tuple[Any, ...]] = None
        self._latest_power_summary_cache_value: Optional[Dict[str, Any]] = None
        self._device_runtime_frame_cache_key: Optional[Tuple[Any, ...]] = None
        self._device_runtime_frame_cache_value: Optional[Dict[str, Any]] = None
        self.command_history: List[Dict[str, Any]] = []
        self._command_history_persisted_signature: Optional[str] = None
        self._strategy_generation_entries: Dict[str, List[Dict[str, Any]]] = {}
        self._strategy_generation_index_token: Optional[Tuple[int, int, int]] = None
        self.runtime_logs: List[Dict[str, Any]] = []
        self._runtime_log_seq = 0
        self._runtime_log_persistence_lock = threading.RLock()
        self._runtime_log_journal_entry_count = 0
        self.runtime_log_journal_entry_limit = RUNTIME_LOG_JOURNAL_ENTRY_LIMIT
        self.runtime_log_journal_byte_limit = RUNTIME_LOG_JOURNAL_BYTE_LIMIT
        self._measurement_delta_seq = 0
        self._measurement_delta_state: Dict[str, Dict[str, Any]] = {}
        self._measurement_delta_history: List[Dict[str, Any]] = []
        self._measurement_delta_step_count: Optional[int] = None
        self._measurement_delta_runtime_marker: Optional[Tuple[Any, ...]] = None
        self._measurement_delta_definition_signature = ""
        self._measurement_delta_definition_count = 0
        self._measurement_delta_definition_revision = 0
        self._measurement_history = MeasurementHistoryStore()
        self._last_command_response_index = 0
        self.latest_result: Dict[str, Any] = {}
        self.latest_measurements: Dict[str, Any] = {}
        self.latest_measurement_clock: Dict[str, Any] = {}
        self._automatic_runtime_state_invalidated = False
        self.latest_model_book: Optional[EBook] = None
        self.latest_device_states: List[Dict[str, Any]] = []
        self.latest_compute: Dict[str, Any] = {
            "mode": "process" if kernel_runner is not None else "embedded",
            "http_pid": os.getpid(),
            "worker_pid": 0 if kernel_runner is not None else os.getpid(),
            "compute_ms": 0.0,
            "round_trip_ms": 0.0,
            "status": "idle",
            "resident_model": kernel_runner is None,
        }
        self.source_model_book = EBook({})
        self.source_stat_book = EBook({})
        self.control_book = EBook({})
        self.weather_book = EBook({})
        self.dev_define_book = EBook({})
        self._definition_snapshot = DefinitionSnapshot(
            revision=0,
            model_book=self.source_model_book,
            dev_define_book=self.dev_define_book,
            measurement_before=(),
            measurement_rows=(),
            measurement_after=(),
        )
        self.runtime_stat_book = EBook({})
        self.yt_ctrl_book = EBook({})
        self.mode_book: Optional[EBook] = None
        self.measurement_before: List[str] = []
        self.measurement_rows: List[List[str]] = []
        self.measurement_after: List[str] = []
        self._definition_publish_epoch = 0
        self._definition_snapshot_sync_lock = threading.Lock()
        self._definition_mirror_refs = (
            self.source_model_book,
            self.dev_define_book,
            self.measurement_before,
            self.measurement_rows,
            self.measurement_after,
        )
        self.latest_real_rows: List[List[str]] = []
        self.latest_scada_rows: List[List[str]] = []
        self._fault_restore: Dict[Tuple[str, str, str], str] = {}
        self._last_scada_values: Dict[str, float] = {}
        self._internal_power_converter_keys_cache: Optional[
            Tuple[int, set[Tuple[str, str]]]
        ] = None
        self._power_flow_connection_sides_cache: Optional[
            Tuple[int, Tuple[Tuple[str, str, str], ...], Dict[Tuple[str, str], str]]
        ] = None

        self.work_dir = self.runtime_dir / ".simu_loop_work"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.source_files = {
            "model": self.sim_dir / "model.e",
            "meas": self.sim_dir / "meas.e",
            "stat": self.sim_dir / "stat.e",
            "control": self.sim_dir / "control.e",
            "weather": self.sim_dir / "weather.e",
            "curves": self.sim_dir / "curves.json",
            "curves_e": self.sim_dir / "curves.e",
            "diagram": self.sim_dir / DIAGRAM_FILE_NAME,
            "definition_defaults": self.sim_dir / DEFINITION_DEFAULTS_FILE,
        }
        self.work_files = {
            "stat": self.work_dir / "stat.e",
            "weather": self.work_dir / "weather.e",
            "mode": self.work_dir / "mode.e",
        }
        self.files = {
            "model": self.source_files["model"],
            "meas": self.source_files["meas"],
            "stat": self.work_files["stat"],
            "control": self.source_files["control"],
            "weather": self.work_files["weather"],
            "yt_ctrl": self.runtime_dir / "yt_ctrl.e",
            "real": self.runtime_dir / "real.e",
            "scada": self.runtime_dir / "scada.e",
            "diagram": self.source_files["diagram"],
        }
        self.curves_file = self.runtime_dir / "curves.json"
        self.source_curves_file = self.source_files["curves"]
        self.settings_file = self.runtime_dir / "local_settings.json"
        self.commands_file = self.runtime_dir / "commands.json"
        self.runtime_logs_file = self.runtime_dir / "runtime_logs.json"
        self.runtime_logs_journal_file = self.runtime_dir / "runtime_logs.jsonl"
        self.trainee_receive_file = self.runtime_dir / "trainee_receive.json"
        self._trainee_receive_cache_lock = threading.RLock()
        self._trainee_receive_cache_signature: Optional[Tuple[int, int, int]] = None
        self._trainee_receive_cache_value: Optional[Dict[str, Any]] = None
        self._trainee_receive_cache_next_stat_monotonic = 0.0
        # SVG definition edits are runtime overrides.  The source E files stay
        # immutable so an operator can always restore the model defaults.
        self.manual_definition_changes_file = self.runtime_dir / MANUAL_DEFINITION_CHANGES_FILE
        self._manual_definition_changes: Dict[str, Dict[str, Any]] = {}
        self._source_measurement_statuses: Dict[str, Dict[str, Any]] = {}

        self._load_runtime_state_from_disk()

    def _service_instance_active_locked(self) -> bool:
        return not self._service_instance_retired

    def service_instance_active(self) -> bool:
        with self._service_instance_lifecycle_lock:
            return self._service_instance_active_locked()

    def _retire_service_instance_locked(self) -> None:
        with self._service_instance_lifecycle_lock:
            self._service_instance_retired = True

    @contextmanager
    def _active_definition_update_guard(self):
        # Definition edits must not wait for a running kernel that owns service.lock.
        # The lifecycle lock still makes retirement versus memory/WAL/E publication atomic.
        with self.definition_update_lock:
            with self._service_instance_lifecycle_lock:
                if not self._service_instance_active_locked():
                    raise ServiceInstanceRetiredError("定义修改请求所属模型生命周期已失效或已退休。")
                yield

    def _load_runtime_state_from_disk(self) -> None:
        self._copy_runtime_inputs()
        self.weather_defaults = self._read_weather_defaults()
        self.reload_definition_state()
        self.ensure_weather_measurements_in_definition_files()
        self.reload_definition_state()
        with self.curves_lock:
            self.curves = self._read_curves()
            self._curve_revision += 1
            curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        self.clock.speed = _simulation_mode_default_clock_speed(curve_mode)
        self.local_settings = self._read_local_settings()
        self._source_measurement_statuses = self._read_source_measurement_statuses()
        self._apply_stored_system_parameters()
        self.command_history = self._read_command_history()
        self._rebuild_strategy_generation_index()
        if self.clear_commands_on_start_and_reset:
            self._remove_automatic_command_history_for_restart()
        self._last_command_response_index = len(self.command_history)
        self.runtime_logs = self._read_runtime_logs()
        self._runtime_log_seq = max((int(_to_float(item.get("seq"), 0) or 0) for item in self.runtime_logs), default=0)
        self.reload_definition_state()
        self._load_manual_definition_changes()
        self._reset_hydrogen_storage_state_to_initial()
        self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)

    def reset_runtime_for_model_change(self) -> Dict[str, int]:
        """Discard runtime artifacts and rebuild a clean in-memory state from source definitions."""
        with self.definition_update_lock:
            with self.lock:
                if self.clock.state != "stopped":
                    raise ValueError(f"模型运行中或暂停中，无法清理运行数据: {self.model_id}")
                removed = _clear_directory_contents(self.runtime_dir)
                self.runtime_dir.mkdir(parents=True, exist_ok=True)
                self.work_dir.mkdir(parents=True, exist_ok=True)

                self.compute_interval_seconds = self._initial_compute_interval_seconds
                self.storage_initial_soc = DEFAULT_STORAGE_INITIAL_SOC
                self.remote_adjustment_response_ratio = DEFAULT_REMOTE_ADJUSTMENT_RESPONSE_RATIO
                self._remote_adjustment_execution = {}
                self._remote_adjustment_cycle_seq = 0
                self.clock = ClockState()
                self.command_history = []
                self._command_history_persisted_signature = None
                self._strategy_generation_entries = {}
                self._strategy_generation_index_token = None
                self.runtime_logs = []
                self._runtime_log_seq = 0
                self._runtime_log_journal_entry_count = 0
                self._measurement_delta_seq = 0
                self._measurement_delta_state = {}
                self._measurement_delta_history = []
                self._measurement_delta_step_count = None
                self._measurement_delta_runtime_marker = None
                self._measurement_delta_definition_signature = ""
                self._measurement_delta_definition_count = 0
                self._measurement_delta_definition_revision = 0
                self._measurement_history.clear(preserve_definition=False)
                self._last_command_response_index = 0
                self.latest_result = {}
                self.latest_measurements = {}
                self.latest_measurement_clock = {}
                self.latest_model_book = None
                self.latest_device_states = []
                self.latest_real_rows = []
                self.latest_scada_rows = []
                self._fault_restore = {}
                self._last_scada_values = {}
                self._clear_manual_definition_changes_unlocked()
                with self._trainee_receive_cache_lock:
                    self._trainee_receive_cache_signature = None
                    self._trainee_receive_cache_value = None
                    self._trainee_receive_cache_next_stat_monotonic = 0.0

                self._load_runtime_state_from_disk()
                return {"removed": removed}

    @property
    def definition_snapshot(self) -> DefinitionSnapshot:
        epoch_before = self._definition_publish_epoch
        snapshot = self._definition_snapshot
        if epoch_before & 1:
            return snapshot
        mirror_refs = (
            self.source_model_book,
            self.dev_define_book,
            self.measurement_before,
            self.measurement_rows,
            self.measurement_after,
        )
        epoch_after = self._definition_publish_epoch
        if epoch_before != epoch_after or epoch_after & 1:
            return self._definition_snapshot
        if all(
            current is published
            for current, published in zip(mirror_refs, self._definition_mirror_refs)
        ):
            return snapshot

        # A few legacy tests and integrations replace mirror objects directly.
        # Copy those objects before the short snapshot commit window.
        measurement_before = tuple(mirror_refs[2])
        measurement_rows = tuple(tuple(row) for row in mirror_refs[3])
        measurement_after = tuple(mirror_refs[4])
        with self._definition_snapshot_sync_lock:
            if (
                self._definition_publish_epoch != epoch_after
                or self._definition_publish_epoch & 1
                or self._definition_snapshot is not snapshot
            ):
                return self._definition_snapshot
            live_refs = (
                self.source_model_book,
                self.dev_define_book,
                self.measurement_before,
                self.measurement_rows,
                self.measurement_after,
            )
            if not all(current is captured for current, captured in zip(live_refs, mirror_refs)):
                return self._definition_snapshot
            candidate = DefinitionSnapshot(
                revision=snapshot.revision + 1,
                model_book=mirror_refs[0],
                dev_define_book=mirror_refs[1],
                measurement_before=measurement_before,
                measurement_rows=measurement_rows,
                measurement_after=measurement_after,
                measurement_median_deviations=snapshot.measurement_median_deviations,
            )
            self._definition_publish_epoch = epoch_after + 1
            self._definition_mirror_refs = mirror_refs
            self._definition_snapshot = candidate
            self._definition_publish_epoch = epoch_after + 2
            self._internal_power_converter_keys_cache = None
            self._power_flow_connection_sides_cache = None
            self._measurement_delta_step_count = None
            return candidate

    def _publish_definition_snapshot(self, snapshot: DefinitionSnapshot) -> None:
        normalized = DefinitionSnapshot(
            revision=int(snapshot.revision),
            model_book=snapshot.model_book,
            dev_define_book=snapshot.dev_define_book,
            measurement_before=tuple(snapshot.measurement_before),
            measurement_rows=tuple(tuple(row) for row in snapshot.measurement_rows),
            measurement_after=tuple(snapshot.measurement_after),
            measurement_median_deviations=_normalized_measurement_median_deviation_pairs(
                snapshot.measurement_median_deviations
            ),
        )
        measurement_before = list(normalized.measurement_before)
        measurement_rows = [list(row) for row in normalized.measurement_rows]
        measurement_after = list(normalized.measurement_after)
        with self._definition_snapshot_sync_lock:
            epoch = self._definition_publish_epoch
            if epoch & 1:  # pragma: no cover - publishers are serialized by the lock.
                raise RuntimeError("定义快照发布序列处于无效状态")
            old_snapshot = self._definition_snapshot
            old_mirrors = (
                self.source_model_book,
                self.dev_define_book,
                self.measurement_before,
                self.measurement_rows,
                self.measurement_after,
            )
            old_refs = self._definition_mirror_refs
            self._definition_publish_epoch = epoch + 1
            try:
                self.source_model_book = normalized.model_book
                self.dev_define_book = normalized.dev_define_book
                self.measurement_before = measurement_before
                self.measurement_rows = measurement_rows
                self.measurement_after = measurement_after
                self._definition_mirror_refs = (
                    self.source_model_book,
                    self.dev_define_book,
                    self.measurement_before,
                    self.measurement_rows,
                    self.measurement_after,
                )
                # The immutable pointer is committed last; readers seeing an odd
                # epoch return the previously committed old or this complete new value.
                self._definition_snapshot = normalized
            except Exception:
                (
                    self.source_model_book,
                    self.dev_define_book,
                    self.measurement_before,
                    self.measurement_rows,
                    self.measurement_after,
                ) = old_mirrors
                self._definition_mirror_refs = old_refs
                self._definition_snapshot = old_snapshot
                raise
            finally:
                self._definition_publish_epoch = epoch + 2
            self._internal_power_converter_keys_cache = None
            self._power_flow_connection_sides_cache = None
            self._measurement_delta_step_count = None

    def _reconcile_source_dcp_controls_unlocked(
        self,
        model_book: EBook,
        source_stat_book: EBook,
        control_book: EBook,
    ) -> Tuple[EBook, EBook]:
        stat_path = Path(self.source_files["stat"])
        control_path = Path(
            self.source_files["control"]
            if self.source_files["control"].exists()
            else self.source_files["stat"]
        )
        same_file = stat_path.resolve() == control_path.resolve()
        stat_added = ensure_dcac_dcp_control_rows(model_book, source_stat_book)
        if same_file:
            if stat_added:
                simu_loop.write_ebook_aligned(source_stat_book, stat_path)
            return source_stat_book, simu_loop._clone_ebook(source_stat_book)

        control_added = ensure_dcac_dcp_control_rows(model_book, control_book)
        if stat_added:
            simu_loop.write_ebook_aligned(source_stat_book, stat_path)
        if control_added:
            simu_loop.write_ebook_aligned(control_book, control_path)
        return source_stat_book, control_book

    def reload_definition_state(self) -> None:
        """Load source definition E files into the live calculation state."""
        model_book = _load_book(self.source_files["model"])
        self.source_stat_book = _load_book(self.source_files["stat"])
        self.control_book = _load_book(
            self.source_files["control"] if self.source_files["control"].exists() else self.source_files["stat"]
        )
        self.source_stat_book, self.control_book = self._reconcile_source_dcp_controls_unlocked(
            model_book,
            self.source_stat_book,
            self.control_book,
        )
        self.weather_book = _load_book(
            self.source_files["weather"] if self.source_files["weather"].exists() else self.work_files["weather"]
        )
        dev_define_book = simu_loop._capability_define_book(
            model_book,
            self._legacy_dev_define_file(),
        )
        try:
            measurement_before, measurement_rows, measurement_after = parse_measurement_rows(
                self.source_files["meas"]
            )
        except Exception:
            measurement_before, measurement_rows, measurement_after = [], [], []
        measurement_rows, _added_measurements = _reconcile_hydrogen_inline_flow_measurements(
            model_book,
            measurement_rows,
        )
        self._publish_definition_snapshot(
            DefinitionSnapshot(
                revision=self._definition_snapshot.revision + 1,
                model_book=model_book,
                dev_define_book=dev_define_book,
                measurement_before=tuple(measurement_before),
                measurement_rows=tuple(tuple(row) for row in measurement_rows),
                measurement_after=tuple(measurement_after),
                measurement_median_deviations=self._read_source_measurement_median_deviations(
                    measurement_rows
                ),
            )
        )
        self.runtime_stat_book = self._base_stat_book_for_controls()
        self._ensure_runtime_stat_book()
        self.yt_ctrl_book = _make_book({"SetValue": (STAT_HEADERS["SetValue"], [])})
        self.mode_book = None
        self.latest_model_book = None
        self.latest_device_states = []
        self.latest_real_rows = []
        self.latest_scada_rows = []
        median_deviations = _measurement_median_deviation_map(self.definition_snapshot)
        self.latest_measurements = {
            "definitions": [
                _measurement_definition_row_to_dict(row, median_deviations)
                for row in measurement_rows
            ],
            "real": [],
            "scada": [],
        }
        self.latest_measurement_clock = {}
        self._measurement_delta_seq = 0
        self._measurement_delta_state = {}
        self._measurement_delta_history = []
        self._measurement_delta_step_count = None
        self._measurement_delta_definition_signature = ""
        self._measurement_delta_definition_count = 0
        self._measurement_delta_definition_revision = 0
        self._measurement_history.clear(preserve_definition=False)

    def _copy_runtime_inputs(self) -> None:
        self._cleanup_legacy_runtime_definition_files()
        self._cleanup_legacy_working_model_files()
        self._materialize_working_stat()
        self._materialize_working_weather()

    def _cleanup_legacy_runtime_definition_files(self) -> None:
        for file_name in LEGACY_RUNTIME_DEFINITION_FILES:
            legacy_path = self.runtime_dir / file_name
            if not legacy_path.exists() or legacy_path.is_dir():
                continue
            if file_name == "stat.e" and not self.work_files["stat"].exists():
                shutil.copy2(legacy_path, self.work_files["stat"])
            elif file_name == "weather.e" and not self.work_files["weather"].exists():
                shutil.copy2(legacy_path, self.work_files["weather"])
            legacy_path.unlink()

    def _cleanup_legacy_working_model_files(self) -> None:
        for path in (self.work_dir / "model.e", self.work_dir / "merged_model.e"):
            if path.exists() and path.is_file():
                path.unlink()

    def _materialize_working_stat(self) -> None:
        source = self.source_files["stat"]
        target = self.work_files["stat"]
        if not target.exists() and source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _materialize_working_weather(self) -> None:
        source = self.source_files["weather"]
        target = self.work_files["weather"]
        if not target.exists() and source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if not target.exists():
            self._write_weather_row(DEFAULT_WEATHER | {"time": minute_to_time(0)})

    def _read_curves(self) -> Dict[str, Any]:
        default = {"mode": "day", "time_step_minutes": 1, "weather": [], "loads": {}, "sources": []}
        source_curves = _read_json(self.source_curves_file, default) if self.source_curves_file.exists() else default
        payload = _read_json(self.curves_file, source_curves)
        return self._normalized_curves_with_source_defaults(payload)

    def _source_curve_catalog(self) -> Tuple[Dict[str, Any], ...]:
        revision = self.definition_snapshot.revision
        if revision != self._source_curve_catalog_cache_key:
            self._source_curve_catalog_cache_key = revision
            self._source_curve_catalog_cache_value = tuple(
                dict(item) for item in source_curve_catalog(self.definition_snapshot.model_book)
            )
        return self._source_curve_catalog_cache_value

    def _normalized_source_curves(
        self,
        raw_sources: Any,
        point_count: int,
        step_minutes: float,
    ) -> List[Dict[str, Any]]:
        catalog = self._source_curve_catalog()
        catalog_by_identity = {source_curve_identity(item): item for item in catalog}
        incoming: Dict[Tuple[str, str, str], Mapping[str, Any]] = {}
        if isinstance(raw_sources, Mapping):
            candidates = raw_sources.values()
        elif isinstance(raw_sources, Sequence) and not isinstance(raw_sources, (str, bytes)):
            candidates = raw_sources
        else:
            candidates = ()
        for item in candidates:
            if not isinstance(item, Mapping):
                continue
            identity = source_curve_identity(item)
            if identity in catalog_by_identity:
                incoming[identity] = item

        normalized: List[Dict[str, Any]] = []
        for catalog_item in catalog:
            identity = source_curve_identity(catalog_item)
            raw_item = incoming.get(identity, {})
            points = _normalize_points(raw_item.get("points"), ("value", "set_value", "p_kw", "flow_set"))
            default_value = float(catalog_item.get("default_value", 0.0) or 0.0)
            normalized_points: List[Dict[str, Any]] = []
            for index, raw_point in enumerate(points):
                value = next(
                    (
                        raw_point.get(alias)
                        for alias in ("value", "set_value", "p_kw", "flow_set")
                        if raw_point.get(alias) not in (None, "")
                    ),
                    default_value,
                )
                normalized_points.append(
                    {
                        "minute": _to_float(raw_point.get("minute"), index * step_minutes)
                        if raw_point
                        else index * step_minutes,
                        "value": _to_float(value, default_value) or 0.0,
                    }
                )
            if not normalized_points:
                normalized_points.append({"minute": 0.0, "value": default_value})
            normalized.append({**dict(catalog_item), "points": normalized_points})
        return normalized

    def _normalized_curves_with_source_defaults(self, payload: Any) -> Dict[str, Any]:
        raw = dict(payload) if isinstance(payload, Mapping) else {}
        mode = _normalize_simulation_mode(raw.get("mode", "day"))
        default_step = _simulation_mode_curve_step_minutes(mode)
        step_minutes = float(_to_float(raw.get("time_step_minutes"), default_step) or default_step)
        if step_minutes <= 0:
            step_minutes = default_step
        weather = raw.get("weather", [])
        loads = raw.get("loads", {})
        point_count = int(_to_float(raw.get("point_count"), 0) or 0)
        if point_count <= 0:
            point_count = len(weather) if isinstance(weather, Sequence) and not isinstance(weather, (str, bytes)) else 0
        if point_count <= 0 and isinstance(loads, Mapping):
            point_count = max(
                (
                    len(points)
                    for points in loads.values()
                    if isinstance(points, Sequence) and not isinstance(points, (str, bytes))
                ),
                default=0,
            )
        point_count = point_count or _simulation_mode_point_count(mode)
        raw.update(
            {
                "mode": mode,
                "time_step_minutes": step_minutes,
                "point_count": point_count,
                "weather": weather if isinstance(weather, list) else [],
                "loads": loads,
                "sources": self._normalized_source_curves(raw.get("sources"), point_count, step_minutes),
            }
        )
        return raw

    def _read_local_settings(self) -> Dict[str, Any]:
        default = {
            "device_faults": [],
            "measurement_faults": [],
            "measurement_statuses": {},
            "modes": [],
            "system_parameters": {},
        }
        if self.settings_file.exists():
            settings = _read_json(self.settings_file, default)
        else:
            source_settings_file = self.sim_dir / "local_settings.json"
            settings = _read_json(source_settings_file, default) if source_settings_file.exists() else default
        normalized = dict(settings) if isinstance(settings, Mapping) else dict(default)
        for key, fallback in default.items():
            normalized.setdefault(key, fallback.copy() if isinstance(fallback, dict) else list(fallback))
        if not isinstance(normalized.get("measurement_statuses"), Mapping):
            normalized["measurement_statuses"] = {}
        return normalized

    def _read_source_measurement_statuses(self) -> Dict[str, Dict[str, Any]]:
        payload = _read_json(self.source_files["definition_defaults"], {})
        raw_statuses = payload.get("measurement_statuses", {}) if isinstance(payload, Mapping) else {}
        if not isinstance(raw_statuses, Mapping):
            return {}
        statuses: Dict[str, Dict[str, Any]] = {}
        for raw_name, raw_value in raw_statuses.items():
            if not isinstance(raw_value, Mapping):
                continue
            name = str(raw_name).strip()
            status = str(raw_value.get("status", "")).strip().casefold()
            if not name or status not in MEASUREMENT_STATUS_TOKENS:
                continue
            fixed_value = _to_float(raw_value.get("fixed_value"), None)
            statuses[name] = {
                "status": status,
                "fixed_value": fixed_value if status == "fixed" else None,
            }
        return statuses

    def _read_source_measurement_median_deviations(
        self,
        measurement_rows: Sequence[Sequence[Any]],
    ) -> Tuple[Tuple[str, float], ...]:
        payload = _read_json(self.source_files["definition_defaults"], {})
        raw_values = (
            payload.get("measurement_median_deviations", {})
            if isinstance(payload, Mapping)
            else {}
        )
        if not isinstance(raw_values, Mapping):
            return ()
        measurement_names = {
            str(row[1]).strip()
            for row in measurement_rows
            if len(row) > 1 and str(row[1]).strip()
        }
        return _normalized_measurement_median_deviation_pairs(
            {
                str(name): value
                for name, value in raw_values.items()
                if str(name).strip() in measurement_names
            }
        )

    def _read_runtime_logs(self) -> List[Dict[str, Any]]:
        snapshot = _read_json(self.runtime_logs_file, [])
        snapshot_rows = snapshot if isinstance(snapshot, list) else []
        journal_rows: List[Dict[str, Any]] = []
        if self.runtime_logs_journal_file.exists():
            try:
                journal_lines = self.runtime_logs_journal_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                journal_lines = []
            for line in journal_lines:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    journal_rows.append(item)
        self._runtime_log_journal_entry_count = len(journal_rows)

        legacy_rows: List[Dict[str, Any]] = []
        sequenced_rows: Dict[int, Dict[str, Any]] = {}
        for item in [*snapshot_rows, *journal_rows]:
            if not isinstance(item, dict):
                continue
            seq = int(_to_float(item.get("seq"), 0) or 0)
            if seq > 0:
                sequenced_rows[seq] = item
            else:
                legacy_rows.append(item)
        merged = [*legacy_rows, *(sequenced_rows[seq] for seq in sorted(sequenced_rows))]
        return merged[-RUNTIME_LOG_HISTORY_LIMIT:]

    def _write_runtime_logs(self) -> None:
        with self._runtime_log_persistence_lock:
            _write_json(self.runtime_logs_file, self.runtime_logs[-RUNTIME_LOG_HISTORY_LIMIT:])
            if self.runtime_logs_journal_file.exists():
                self.runtime_logs_journal_file.unlink()
            self._runtime_log_journal_entry_count = 0

    def _append_runtime_log_journal(self, entry: Mapping[str, Any]) -> None:
        with self._runtime_log_persistence_lock:
            if not self.runtime_logs_file.exists():
                _write_json(self.runtime_logs_file, [])
            self.runtime_logs_journal_file.parent.mkdir(parents=True, exist_ok=True)
            with self.runtime_logs_journal_file.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(dict(entry), ensure_ascii=False, separators=(",", ":")))
                stream.write("\n")
            self._runtime_log_journal_entry_count += 1
            journal_size = self.runtime_logs_journal_file.stat().st_size
            if (
                self._runtime_log_journal_entry_count >= self.runtime_log_journal_entry_limit
                or journal_size >= self.runtime_log_journal_byte_limit
            ):
                self._write_runtime_logs()

    def _default_trainee_receive_state(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "initialized": False,
            "initialized_at": "",
            "active": False,
            "frozen": False,
            "interaction_link": "",
            "teacher_api_base": "",
            "teacher_model_id": "",
            "teacher_model_name": "",
            "snapshot_path": "",
            "command_path": "",
            "measurement_delta_path": "",
            "definition_archive_path": "",
            "last_receive_at": "",
            "updated_at": "",
        }

    def _normalize_trainee_receive_state(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        current = self._default_trainee_receive_state()
        current.update(
            {
                key: payload.get(key, current[key])
                for key in current
                if key in payload and key not in {"model_id", "model_name"}
            }
        )
        aliases = {
            "initialized": ("initialized", "model_initialized", "modelInitialized"),
            "initialized_at": ("initialized_at", "initializedAt", "model_initialized_at"),
            "active": ("active", "receive_mode", "receiveMode"),
            "frozen": ("frozen",),
            "interaction_link": ("interaction_link", "interactionLink", "link"),
            "teacher_api_base": ("teacher_api_base", "teacherApiBase"),
            "teacher_model_id": ("teacher_model_id", "teacherModelId", "model_id"),
            "teacher_model_name": ("teacher_model_name", "teacherModelName", "model_name"),
            "snapshot_path": ("snapshot_path", "snapshotPath"),
            "command_path": ("command_path", "commandPath"),
            "measurement_delta_path": ("measurement_delta_path", "measurementDeltaPath"),
            "definition_archive_path": ("definition_archive_path", "definitionArchivePath"),
            "last_receive_at": ("last_receive_at", "lastReceiveAt"),
            "updated_at": ("updated_at", "updatedAt"),
        }
        normalized: Dict[str, Any] = {
            "model_id": self.model_id,
            "model_name": self.model_name,
        }
        for key, names in aliases.items():
            value = current.get(key, "")
            for name in names:
                if name in payload:
                    value = payload.get(name)
                    break
            if key in {"initialized", "active", "frozen"}:
                normalized[key] = bool(value)
                continue
            normalized[key] = str(value or "").strip()
        normalized["teacher_api_base"] = normalized["teacher_api_base"].rstrip("/")
        has_explicit_initialized = any(name in payload for name in aliases["initialized"])
        has_saved_connection = bool(
            normalized["interaction_link"]
            or (
                normalized["teacher_api_base"]
                and (normalized["snapshot_path"] or normalized["command_path"])
            )
        )
        if not has_explicit_initialized and has_saved_connection:
            normalized["initialized"] = True
        if not normalized["teacher_model_id"] and normalized["active"]:
            normalized["teacher_model_id"] = self.model_id
        if not normalized["teacher_model_name"] and normalized["teacher_model_id"]:
            normalized["teacher_model_name"] = normalized["teacher_model_id"]
        return normalized

    def trainee_receive_state(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._trainee_receive_cache_lock:
            if (
                self._trainee_receive_cache_value is not None
                and now < self._trainee_receive_cache_next_stat_monotonic
            ):
                return dict(self._trainee_receive_cache_value)
            try:
                stat = self.trainee_receive_file.stat()
                signature: Optional[Tuple[int, int, int]] = (
                    int(stat.st_mtime_ns),
                    int(stat.st_ctime_ns),
                    int(stat.st_size),
                )
            except OSError:
                signature = None
            self._trainee_receive_cache_next_stat_monotonic = now + 0.25
            if (
                self._trainee_receive_cache_value is not None
                and self._trainee_receive_cache_signature == signature
            ):
                return dict(self._trainee_receive_cache_value)
            raw = _read_json(self.trainee_receive_file, {})
            if not isinstance(raw, Mapping):
                raw = {}
            normalized = self._normalize_trainee_receive_state(raw)
            self._trainee_receive_cache_signature = signature
            self._trainee_receive_cache_value = normalized
            return dict(normalized)

    def set_trainee_receive_state(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            if not self._service_instance_active_locked():
                raise RuntimeError("学员台接收请求所属模型生命周期已失效或已退休。")
            existing = self.trainee_receive_state()
            merged = {**existing, **dict(payload)}
            if "updated_at" not in payload and "updatedAt" not in payload:
                merged["updated_at"] = _now_text()
            normalized = self._normalize_trainee_receive_state(merged)
            _write_json(self.trainee_receive_file, normalized)
            try:
                stat = self.trainee_receive_file.stat()
                signature: Optional[Tuple[int, int, int]] = (
                    int(stat.st_mtime_ns),
                    int(stat.st_ctime_ns),
                    int(stat.st_size),
                )
            except OSError:
                signature = None
            with self._trainee_receive_cache_lock:
                self._trainee_receive_cache_signature = signature
                self._trainee_receive_cache_value = normalized
                self._trainee_receive_cache_next_stat_monotonic = time.monotonic() + 0.25
            return dict(normalized)

    def _ensure_weather_measurements_in_file(self, meas_file: Path) -> bool:
        meas_file = Path(meas_file)
        if not meas_file.exists():
            before: List[str] = []
            rows: List[List[str]] = []
            after: List[str] = []
        else:
            try:
                before, rows, after = parse_measurement_rows(meas_file)
            except Exception:
                return False
        kept_rows = [
            row
            for row in rows
            if not self._is_weather_measurement_row(_measurement_row_to_dict(row))
            and not self._is_signal_measurement_row(_measurement_row_to_dict(row))
        ]
        max_idx = -1
        for row in kept_rows:
            max_idx = max(max_idx, int(_to_float(row[0], -1) or -1))
        weather_rows = [
            _measurement_dict_to_row(row)
            for row in self._weather_measurement_rows(max_idx + 1)
        ]
        signal_rows = [
            _measurement_dict_to_row(row)
            for row in self._signal_measurement_rows(max_idx + 1 + len(weather_rows))
        ]
        new_rows = [*kept_rows, *weather_rows, *signal_rows]
        if rows == new_rows:
            return False
        simu_loop.write_measurement_snapshot(meas_file, before, new_rows, after)
        return True

    def ensure_weather_measurements_in_definition_files(self) -> None:
        self._ensure_weather_measurements_in_file(self.source_files["meas"])

    @staticmethod
    def _command_item_sequence(container: Mapping[str, Any], keys: Sequence[str]) -> List[Any]:
        for key in keys:
            value = container.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return list(value)
        return []

    def _filter_loaded_command_history_to_definitions(
        self,
        history: Sequence[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], bool]:
        filtered_history: List[Dict[str, Any]] = []
        changed = False
        run_keys = ("run_status", "runStatus")
        set_keys = ("set_values", "setValues", "setpoints")

        for item in history:
            normalized = item.get("normalized", {})
            normalized_map = normalized if isinstance(normalized, Mapping) else {}
            payload = item.get("payload", {})
            payload_map = payload if isinstance(payload, Mapping) else {}
            accepted = item.get("accepted", {})
            accepted_map = accepted if isinstance(accepted, Mapping) else {}
            accepted_count = (
                int(_to_float(accepted_map.get("run_status"), 0) or 0)
                + int(_to_float(accepted_map.get("set_values"), 0) or 0)
            )

            normalized_has_control_keys = any(key in normalized_map for key in (*run_keys, *set_keys))
            normalized_run = self._command_item_sequence(normalized_map, run_keys)
            normalized_set = self._command_item_sequence(normalized_map, set_keys)
            payload_run = self._command_item_sequence(payload_map, run_keys)
            payload_set = self._command_item_sequence(payload_map, set_keys)
            has_requested_controls = bool(normalized_run or normalized_set or payload_run or payload_set)

            if not has_requested_controls:
                filtered_history.append(item)
                continue
            if accepted_count <= 0:
                changed = True
                continue

            source_run = normalized_run if normalized_has_control_keys else payload_run
            source_set = normalized_set if normalized_has_control_keys else payload_set
            requested_run = self._normalize_run_command_items(source_run)
            requested_set = self._normalize_set_command_items(source_set)
            retained_run = self._filter_defined_run_command_items(requested_run)
            retained_set = self._filter_defined_set_command_items(requested_set)
            try:
                retained_run = self._validate_run_command_items(retained_run)
                retained_set = self._validate_set_command_items(
                    retained_set,
                    strict=True,
                )
            except ValueError:
                # Persisted entries retain their original batch semantics.  A
                # corrupt or now-unsafe member invalidates the whole entry.
                changed = True
                continue
            if not retained_run and not retained_set:
                changed = True
                continue

            cleaned = dict(item)
            cleaned_normalized = dict(normalized_map)
            cleaned_normalized["run_status"] = retained_run
            cleaned_normalized["set_values"] = retained_set
            cleaned["normalized"] = cleaned_normalized

            if payload_map:
                cleaned_payload = dict(payload_map)
                for key in run_keys:
                    if key in cleaned_payload:
                        cleaned_payload[key] = [dict(row) for row in retained_run]
                for key in set_keys:
                    if key in cleaned_payload:
                        cleaned_payload[key] = [dict(row) for row in retained_set]
                cleaned["payload"] = cleaned_payload

            cleaned_accepted = dict(accepted_map)
            removed_count = max(0, len(requested_run) - len(retained_run)) + max(
                0,
                len(requested_set) - len(retained_set),
            )
            cleaned_accepted["run_status"] = len(retained_run)
            cleaned_accepted["set_values"] = len(retained_set)
            cleaned_accepted["ignored"] = int(_to_float(accepted_map.get("ignored"), 0) or 0) + removed_count
            cleaned["accepted"] = cleaned_accepted

            if cleaned != item:
                changed = True
            filtered_history.append(cleaned)

        return filtered_history, changed

    def _read_command_history(self) -> List[Dict[str, Any]]:
        items = _read_json(self.commands_file, [])
        if not isinstance(items, list):
            return []
        history = [item for item in items if isinstance(item, dict)]
        changed = self._repair_legacy_cancel_command_entries(history)
        history, definition_changed = self._filter_loaded_command_history_to_definitions(history)
        changed = changed or definition_changed
        changed = self._compact_command_history_payloads(history) or changed
        compacted = self._compact_command_history(history)
        if len(compacted) != len(history):
            changed = True
            history = compacted
        if changed:
            _write_json(self.commands_file, history, compact=True)
        self._command_history_persisted_signature = self._command_history_signature(history)
        return history

    @staticmethod
    def _command_history_signature(history: Sequence[Mapping[str, Any]]) -> str:
        encoded = json.dumps(history, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _compact_command_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Keep transport metadata without duplicating normalized controls or a full plan."""
        compacted: Dict[str, Any] = {}
        sequence_fields = {
            "run_status": "run_status_count",
            "runStatus": "run_status_count",
            "set_values": "set_values_count",
            "setValues": "set_values_count",
            "setpoints": "set_values_count",
            "command_rows": "command_rows_count",
            "commandRows": "command_rows_count",
        }
        strategy_fields = (
            "name",
            "strategy_id",
            "generation",
            "replace_strategy_generation",
            "loop_mode",
            "trigger",
            "time",
            "load_kw",
            "renewable_available_kw",
            "renewable_used_kw",
            "storage_kw",
            "storage_current_kw",
            "storage_soc",
            "acdc_current_kw",
            "acdc_target_kw",
            "diesel_residual_kw",
            "diesel_min_kw",
            "diesel_target_kw",
            "curtail_kw",
            "data_quality",
        )
        for key, value in payload.items():
            count_key = sequence_fields.get(str(key))
            if count_key is not None:
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    compacted[count_key] = max(int(compacted.get(count_key, 0)), len(value))
                continue
            if key == "strategy" and isinstance(value, Mapping):
                summary = {
                    field: copy.deepcopy(value[field])
                    for field in strategy_fields
                    if field in value
                }
                if summary:
                    compacted[key] = summary
                continue
            compacted[key] = copy.deepcopy(value)
        return compacted

    def _compact_command_history_payloads(
        self,
        history: Sequence[Dict[str, Any]],
    ) -> bool:
        changed = False
        for entry in history:
            payload = entry.get("payload")
            if not isinstance(payload, Mapping):
                continue
            compacted = self._compact_command_payload(payload)
            if compacted != payload:
                entry["payload"] = compacted
                changed = True
        return changed

    def _preserve_command_history_entry(self, item: Mapping[str, Any]) -> bool:
        return (
            _manual_command_holds_across_clock_lifecycle(item)
            and self._command_entry_has_accepted_controls(item)
            and not item.get("cancelled")
        )

    def _compact_command_history(self, history: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        recent_start = max(0, len(history) - COMMAND_HISTORY_RECENT_LIMIT)
        recent_ids = {id(item) for item in history[recent_start:]}
        current_run_id = int(_to_float(self.clock.run_id, 0) or 0)
        latest_automatic_owner: Dict[Tuple[str, str, str, str], int] = {}
        for item in history:
            if (
                _command_origin(item) != "automatic"
                or not self._command_entry_has_recorded_controls(item)
                or int(_to_float(item.get("run_id"), -1)) != current_run_id
                or self._automatic_command_was_reset(item)
            ):
                continue
            for key in self._command_entry_control_keys(item):
                latest_automatic_owner[key] = id(item)
        latched_automatic_ids = set(latest_automatic_owner.values())
        return [
            item
            for item in history
            if id(item) in recent_ids
            or id(item) in latched_automatic_ids
            or self._preserve_command_history_entry(item)
        ]

    def _trim_command_history(self) -> None:
        self._ensure_strategy_generation_index()
        acknowledged_ids = {id(item) for item in self.command_history[: self._last_command_response_index]}
        compacted = self._compact_command_history(self.command_history)
        if len(compacted) == len(self.command_history):
            self._strategy_generation_index_token = self._command_history_identity_token()
            return
        self.command_history = compacted
        self._last_command_response_index = sum(1 for item in self.command_history if id(item) in acknowledged_ids)
        retained_ids = {id(item) for item in compacted}
        self._strategy_generation_entries = {
            strategy_id: [
                entry for entry in entries if id(entry) in retained_ids
            ]
            for strategy_id, entries in self._strategy_generation_entries.items()
            if any(id(entry) in retained_ids for entry in entries)
        }
        self._strategy_generation_index_token = self._command_history_identity_token()

    def _write_command_history(self, *, prepared: bool = False) -> None:
        if not prepared:
            self._prepare_command_history_for_persistence()
        signature = self._command_history_signature(self.command_history)
        if signature == self._command_history_persisted_signature and self.commands_file.exists():
            return
        _write_json(self.commands_file, self.command_history, compact=True)
        self._command_history_persisted_signature = signature

    def _prepare_command_history_for_persistence(self) -> None:
        self._trim_command_history()
        self._compact_command_history_payloads(self.command_history)

    def _clear_command_history(self) -> Dict[str, int]:
        control_keys: set[Tuple[str, str, str, str]] = set()
        for entry in self.command_history:
            if isinstance(entry, Mapping):
                control_keys.update(self._command_entry_control_keys(entry))
        cleared = {
            "entries": len(self.command_history),
            "remote_controls": sum(1 for key in control_keys if key[0] == "remote_control"),
            "remote_adjustments": sum(1 for key in control_keys if key[0] == "remote_adjustment"),
        }
        self.command_history = []
        self._last_command_response_index = 0
        self._strategy_generation_entries = {}
        self._strategy_generation_index_token = self._command_history_identity_token()
        _write_json(self.commands_file, [], compact=True)
        self._command_history_persisted_signature = self._command_history_signature([])
        return cleared

    def _remove_automatic_command_history_for_restart(self) -> Dict[str, int]:
        self._ensure_strategy_generation_index()
        acknowledged_ids = {id(item) for item in self.command_history[: self._last_command_response_index]}
        retained: List[Dict[str, Any]] = []
        removed_keys: set[Tuple[str, str, str, str]] = set()
        removed_entries = 0
        for entry in self.command_history:
            if _command_origin(entry) == "manual":
                retained.append(entry)
                continue
            removed_entries += 1
            removed_keys.update(self._command_entry_control_keys(entry))

        if removed_entries:
            self.command_history = retained
            self._last_command_response_index = sum(
                1 for item in self.command_history if id(item) in acknowledged_ids
            )
            self._strategy_generation_entries = {}
            self._strategy_generation_index_token = self._command_history_identity_token()
        self._force_control_targets_after_automatic_removal(removed_keys)
        self._write_command_history()

        return {
            "entries": removed_entries,
            "remote_controls": sum(1 for key in removed_keys if key[0] == "remote_control"),
            "remote_adjustments": sum(1 for key in removed_keys if key[0] == "remote_adjustment"),
        }

    def _force_control_targets_after_automatic_removal(
        self,
        control_keys: Iterable[Tuple[str, str, str, str]],
    ) -> None:
        for kind, dev_type, dev_name, field_name in control_keys:
            if kind != "remote_adjustment":
                continue
            key = (dev_type, dev_name, field_name)
            self._remote_adjustment_execution[key] = {
                "force_target_once": True,
                "last_cycle_token": None,
            }

    def _apply_stored_system_parameters(self) -> None:
        params = self.local_settings.get("system_parameters", {})
        if not isinstance(params, Mapping):
            return
        self.clock.step_minutes = 1.0 / 60.0
        if "clock_speed" in params or "speed" in params:
            self.clock.speed = _nearest_clock_speed(params.get("clock_speed", params.get("speed")))
        if "compute_interval_seconds" in params or "calculation_period_seconds" in params:
            self.compute_interval_seconds = _compute_interval_seconds(
                params.get("compute_interval_seconds", params.get("calculation_period_seconds")),
                self.compute_interval_seconds,
            )
        if "storage_initial_soc" in params or "initial_storage_soc" in params:
            self.storage_initial_soc = _storage_initial_soc(
                params.get("storage_initial_soc", params.get("initial_storage_soc")),
                self.storage_initial_soc,
            )
        if "remote_adjustment_response_ratio" in params or "adjustment_response_ratio" in params:
            self.remote_adjustment_response_ratio = _remote_adjustment_response_ratio(
                params.get(
                    "remote_adjustment_response_ratio",
                    params.get("adjustment_response_ratio"),
                ),
                self.remote_adjustment_response_ratio,
            )

    def _apply_mode_default_clock_speed(self, mode: str, *, persist: bool) -> None:
        self.clock.step_minutes = 1.0 / 60.0
        self.clock.speed = _simulation_mode_default_clock_speed(mode)
        if not persist:
            return
        stored_params = self.local_settings.get("system_parameters", {})
        params = dict(stored_params) if isinstance(stored_params, Mapping) else {}
        params["clock_speed"] = self.clock.speed
        self.local_settings["system_parameters"] = params
        _write_json(self.settings_file, self.local_settings)

    def system_parameters(self) -> Dict[str, Any]:
        effective_step_minutes = _effective_clock_step(self.clock.step_minutes, self.clock.speed)
        return {
            "clock_speed": _nearest_clock_speed(self.clock.speed),
            "compute_interval_seconds": self.compute_interval_seconds,
            "storage_initial_soc": self.storage_initial_soc,
            "remote_adjustment_response_ratio": self.remote_adjustment_response_ratio,
            "clock_step_seconds": self.clock.step_minutes * 60.0,
            "clock_step_minutes": self.clock.step_minutes,
            "effective_step_seconds": effective_step_minutes * 60.0,
            "effective_step_minutes": effective_step_minutes,
        }

    def simulation_timing(self) -> Dict[str, float]:
        parameters = self.system_parameters()
        return {
            "simulation_step_seconds": float(parameters["effective_step_seconds"]),
            "simulation_period_seconds": float(self.compute_interval_seconds),
        }

    def set_system_parameters(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            timing_keys = {
                "clock_speed",
                "speed",
                "simulation_speed",
                "compute_interval_seconds",
                "calculation_period_seconds",
            }
            if timing_keys.intersection(payload):
                self.clock.step_minutes = 1.0 / 60.0
            if "clock_speed" in payload or "speed" in payload or "simulation_speed" in payload:
                self.clock.speed = _nearest_clock_speed(
                    payload.get("clock_speed", payload.get("speed", payload.get("simulation_speed")))
                )
            if "compute_interval_seconds" in payload or "calculation_period_seconds" in payload:
                self.compute_interval_seconds = _compute_interval_seconds(
                    payload.get("compute_interval_seconds", payload.get("calculation_period_seconds")),
                    self.compute_interval_seconds,
                )
            if "storage_initial_soc" in payload or "initial_storage_soc" in payload:
                self.storage_initial_soc = _storage_initial_soc(
                    payload.get("storage_initial_soc", payload.get("initial_storage_soc")),
                    self.storage_initial_soc,
                )
            if "remote_adjustment_response_ratio" in payload or "adjustment_response_ratio" in payload:
                self.remote_adjustment_response_ratio = _remote_adjustment_response_ratio(
                    payload.get(
                        "remote_adjustment_response_ratio",
                        payload.get("adjustment_response_ratio"),
                    ),
                    self.remote_adjustment_response_ratio,
                )

            effective_step = _effective_clock_step(self.clock.step_minutes, self.clock.speed)
            self.clock.absolute_minute = _align_minute_to_step(self.clock.absolute_minute, effective_step)
            self.clock.minute = self.clock.absolute_minute % 1440
            self.clock.updated_at = time.time()

            stored_params = self.local_settings.get("system_parameters", {})
            params = dict(stored_params) if isinstance(stored_params, Mapping) else {}
            params.update(
                {
                    "clock_speed": self.clock.speed,
                    "compute_interval_seconds": self.compute_interval_seconds,
                    "storage_initial_soc": self.storage_initial_soc,
                    "remote_adjustment_response_ratio": self.remote_adjustment_response_ratio,
                }
            )
            self.local_settings["system_parameters"] = params
            _write_json(self.settings_file, self.local_settings)
            self._append_runtime_log(
                "参数配置",
                "系统参数",
                "已更新",
                [
                    f"仿真步长/加速比 x{format_number(self.clock.speed)}",
                    f"仿真周期 {format_number(self.compute_interval_seconds)} s",
                    f"储能SOC初始值 {format_number(self.storage_initial_soc * 100.0)}%",
                    f"遥调指令响应系数 {format_number(self.remote_adjustment_response_ratio)}",
                    f"每次计算推进 {format_number(effective_step * 60.0)} s",
                ],
                level="ok",
                simu_time=minute_to_time(self.clock.minute),
            )
            return {"system_parameters": self.system_parameters(), "clock": self.clock.as_dict()}

    def web_runtime_settings(self, role: str) -> Dict[str, Any]:
        with self.lock:
            return runtime_settings_payload(
                self.local_settings,
                role,
                model_id=self.model_id,
            )

    def set_web_runtime_settings(self, role: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            with self._service_instance_lifecycle_lock:
                if not self._service_instance_active_locked():
                    raise ServiceInstanceRetiredError(
                        "运行参数请求所属模型生命周期已失效或已退休。"
                    )
                entry = updated_runtime_settings_entry(
                    self.local_settings,
                    role,
                    payload,
                    updated_at=_now_text(),
                )
                existing = self.local_settings.get("web_runtime_parameters", {})
                parameters = dict(existing) if isinstance(existing, Mapping) else {}
                parameters[str(role).strip().lower()] = entry
                self.local_settings["web_runtime_parameters"] = parameters
                _write_json(self.settings_file, self.local_settings)
                return runtime_settings_payload(
                    self.local_settings,
                    role,
                    model_id=self.model_id,
                )

    def clone_files_to(self, target_dir: Path) -> None:
        with self.lock:
            _write_json(self.curves_file, self.curves)
            _write_json(self.settings_file, self.local_settings)
            self._write_command_history()
            target_dir.mkdir(parents=True, exist_ok=False)
            for name in SOURCE_DEFINITION_FILES:
                source = self.sim_dir / name
                if source.exists():
                    shutil.copy2(source, target_dir / name)
            diagram = self.sim_dir / DIAGRAM_FILE_NAME
            if diagram.exists():
                shutil.copy2(diagram, target_dir / DIAGRAM_FILE_NAME)
            if self.curves:
                _write_json(target_dir / "curves.json", self.curves)

    def _read_weather_defaults(self) -> Dict[str, Optional[float]]:
        values = dict(DEFAULT_WEATHER)
        path = self.source_files.get("weather", self.files["weather"])
        if not path.exists():
            return values
        try:
            book = EBook(path)
        except Exception:
            return values
        block = book.data.get("Weather")
        if block is None or not block.data:
            return values
        row = block.data[0]
        if "name" in block.header_list and "value" in block.header_list:
            row = {str(item.get("name", "")): item.get("value", "") for item in block.data}
        for key in DEFAULT_WEATHER:
            number = _to_float(row.get(key), None)
            if number is not None:
                values[key] = number
        return values

    def _ensure_runtime_stat_book(self) -> None:
        book = self.runtime_stat_book
        for name, headers in STAT_HEADERS.items():
            _ensure_block(book, name, headers)
        simu_loop.ensure_hydrogen_storage_state_rows_book(
            book,
            self.definition_snapshot.model_book,
        )
        self.runtime_stat_book = book

    def _reset_storage_soc_to_initial(self) -> None:
        book = self.runtime_stat_book
        storage_block = book.data.get("StorageSoc") or book.data.get("StorageStatus")
        if storage_block is None:
            return
        if storage_block is not book.data.get("StorageSoc"):
            legacy_rows = [
                {
                    "dev_type": row.get("dev_type", ""),
                    "idx": row.get("idx", ""),
                    "name": row.get("name", row.get("dev_name", "")),
                    "soc_curr": row.get("soc_curr", row.get("soc", row.get("soc_cur", ""))),
                }
                for row in storage_block.data
            ]
            storage_block = _ensure_block(book, "StorageSoc", STAT_HEADERS["StorageSoc"])
            storage_block.data = legacy_rows
        else:
            storage_block = _ensure_block(book, "StorageSoc", STAT_HEADERS["StorageSoc"])
        initial_soc = _number_text(self.storage_initial_soc)
        for row in storage_block.data:
            row["soc_curr"] = initial_soc
        self.runtime_stat_book = book
        self._sync_latest_storage_soc_measurement_rows()

    def _reset_hydrogen_storage_state_to_initial(self) -> None:
        simu_loop.reset_hydrogen_storage_state_book(
            self.runtime_stat_book,
            self.definition_snapshot.model_book,
        )
        self._sync_latest_hydrogen_storage_measurement_rows()

    def _simulation_cycle_minutes(self) -> int:
        return int(_simulation_mode_duration_minutes(self.curves.get("mode", "day")))

    def _crossed_simulation_cycle_start(self, start_minute: int | float, end_minute: int | float) -> bool:
        cycle_minutes = float(self._simulation_cycle_minutes())
        start = max(0.0, float(start_minute))
        end = max(0.0, float(end_minute))
        if end <= start:
            return False
        return math.floor((end + 1e-9) / cycle_minutes) > math.floor((start + 1e-9) / cycle_minutes)

    def _storage_target_aliases(self) -> Dict[str, set[Tuple[str, str]]]:
        return resource_keys_by_alias(
            self.definition_snapshot.model_book,
            ("storage",),
        )

    def _runtime_storage_soc_values(self) -> Dict[Tuple[str, str], float]:
        storage_block = self.runtime_stat_book.data.get("StorageSoc") or self.runtime_stat_book.data.get("StorageStatus")
        resources = [
            resource
            for resource in structured_resources(self.definition_snapshot.model_book)
            if resource.technology == "storage"
        ]
        resolved: Dict[Tuple[str, str], float] = {}
        for row in getattr(storage_block, "data", []):
            value = _to_float(
                row.get("soc_curr", row.get("soc", row.get("soc_cur", 0.0))),
                0.0,
            ) or 0.0
            resource_key = resolve_resource_reference(resources, row)
            if resource_key is not None:
                resolved[resource_key] = value
        return resolved

    def _storage_runtime_protocol_keys(self) -> Dict[Tuple[str, str], set[Tuple[str, str]]]:
        resources = [
            resource
            for resource in structured_resources(self.definition_snapshot.model_book)
            if resource.technology == "storage"
        ]
        keys_by_resource = {resource.device_key: {resource.device_key} for resource in resources}
        storage_block = self.runtime_stat_book.data.get("StorageSoc") or self.runtime_stat_book.data.get("StorageStatus")
        for row in getattr(storage_block, "data", []):
            resource_key = resolve_resource_reference(resources, row)
            dev_type = str(row.get("dev_type", "")).strip()
            dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
            if resource_key is not None and dev_type and dev_name:
                keys_by_resource.setdefault(resource_key, {resource_key}).add((dev_type, dev_name))
        return keys_by_resource

    def _sync_latest_storage_soc_measurement_rows(self) -> None:
        soc_values = self._runtime_storage_soc_values()
        if not soc_values:
            return
        resource_by_protocol_key = {
            protocol_key: resource_key
            for resource_key, protocol_keys in self._storage_runtime_protocol_keys().items()
            for protocol_key in protocol_keys
        }

        changed = False

        def sync_rows(rows: List[List[str]]) -> None:
            nonlocal changed
            for row in rows:
                if len(row) < len(MEAS_HEADER):
                    continue
                if str(row[4]).upper() != "SOC":
                    continue
                dev_type = str(row[2]).strip()
                dev_name = str(row[3]).strip()
                key = resource_by_protocol_key.get((dev_type, dev_name), (dev_type, dev_name))
                if key in soc_values:
                    value = _number_text(soc_values[key])
                    if row[7] != value:
                        row[7] = value
                        changed = True

        sync_rows(self.latest_real_rows)
        sync_rows(self.latest_scada_rows)
        if changed:
            self._invalidate_measurement_delta_cache()
        if changed and self.latest_measurements:
            self.latest_measurements = self.measurements()

    def _sync_latest_hydrogen_storage_measurement_rows(self) -> None:
        state_values = simu_loop.hydrogen_storage_state_values_from_book(
            self.runtime_stat_book
        )
        if not state_values:
            return
        definition_rows = self.definition_snapshot.measurement_rows

        field_by_measurement_type = {
            "PRESS": "pressure",
            "PRESSURE": "pressure",
            "FLOW": "flow",
            "GASQUANTITY": "gas_quantity",
            "GAS_QUANTITY": "gas_quantity",
            "SOC": "soc",
        }
        changed = False

        def sync_rows(rows: List[List[str]]) -> None:
            nonlocal changed
            populated_keys: set[Tuple[str, str]] = set()
            for row in rows:
                if len(row) < len(MEAS_HEADER):
                    continue
                if str(row[2]).strip() != "HydroStorage":
                    continue
                field = field_by_measurement_type.get(str(row[4]).strip().upper())
                if field is None:
                    continue
                dev_name = str(row[3]).strip()
                values = state_values.get(("HydroStorage", dev_name)) or state_values.get(dev_name)
                if not values or field not in values:
                    continue
                populated_keys.add((dev_name, field))
                value = _number_text(values[field])
                if row[7] != value:
                    row[7] = value
                    changed = True

            for definition in definition_rows:
                if len(definition) < len(MEAS_HEADER):
                    continue
                if str(definition[2]).strip() != "HydroStorage":
                    continue
                field = field_by_measurement_type.get(
                    str(definition[4]).strip().upper()
                )
                dev_name = str(definition[3]).strip()
                if field is None or (dev_name, field) in populated_keys:
                    continue
                values = state_values.get(("HydroStorage", dev_name)) or state_values.get(dev_name)
                if not values or field not in values:
                    continue
                row = list(definition)
                row[7] = _number_text(values[field])
                rows.append(row)
                populated_keys.add((dev_name, field))
                changed = True

        sync_rows(self.latest_real_rows)
        sync_rows(self.latest_scada_rows)
        if changed:
            self._invalidate_measurement_delta_cache()
        if changed and self.latest_measurements:
            self.latest_measurements = self.measurements()

    def _base_stat_book_for_controls(self) -> EBook:
        book = simu_loop._clone_ebook(self.source_stat_book)
        for name, headers in STAT_HEADERS.items():
            _ensure_block(book, name, headers)

        runtime_book = self.runtime_stat_book
        runtime_storage = runtime_book.data.get("StorageSoc") or runtime_book.data.get("StorageStatus")
        if runtime_storage is not None:
            storage_block = _ensure_block(book, "StorageSoc", STAT_HEADERS["StorageSoc"])
            storage_block.data = self._merge_runtime_storage_soc(storage_block.data, runtime_storage.data)
        runtime_hydrogen = runtime_book.data.get(simu_loop.HYDROGEN_STORAGE_STATE_BLOCK)
        if runtime_hydrogen is not None:
            hydrogen_block = _ensure_block(
                book,
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK,
                simu_loop.HYDROGEN_STORAGE_STATE_HEADERS,
            )
            hydrogen_block.data = self._merge_runtime_hydrogen_storage_state(
                hydrogen_block.data,
                runtime_hydrogen.data,
            )
        simu_loop.ensure_hydrogen_storage_state_rows_book(
            book,
            self.definition_snapshot.model_book,
        )
        return book

    def _storage_soc_identity(self, row: Mapping[str, Any]) -> Optional[Tuple[str, str, str]]:
        dev_type = str(row.get("dev_type", "")).strip()
        name = str(row.get("name", row.get("dev_name", ""))).strip()
        idx = str(row.get("idx", "")).strip()
        if dev_type and name:
            return ("name", dev_type, name)
        if dev_type and idx:
            return ("idx", dev_type, idx)
        return None

    def _merge_runtime_storage_soc(
        self,
        source_rows: Sequence[Mapping[str, Any]],
        runtime_rows: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Preserve SOC only for storage rows that still belong to the current source model."""
        runtime_by_key: Dict[Tuple[str, str, str], Mapping[str, Any]] = {}
        for row in runtime_rows:
            key = self._storage_soc_identity(row)
            if key is not None:
                runtime_by_key[key] = row

        source_list = list(source_rows)
        if not source_list:
            return [{header: row.get(header, "") for header in STAT_HEADERS["StorageSoc"]} for row in runtime_rows]

        merged: List[Dict[str, Any]] = []
        for source_row in source_list:
            row = {header: source_row.get(header, "") for header in STAT_HEADERS["StorageSoc"]}
            runtime_row = runtime_by_key.get(self._storage_soc_identity(source_row))
            if runtime_row is not None and runtime_row.get("soc_curr", "") != "":
                row["soc_curr"] = runtime_row.get("soc_curr", "")
            merged.append(row)
        return merged

    def _merge_runtime_hydrogen_storage_state(
        self,
        current_rows: Sequence[Mapping[str, Any]],
        incoming_rows: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        headers = simu_loop.HYDROGEN_STORAGE_STATE_HEADERS
        incoming_by_key = {
            simu_loop._hydrogen_storage_state_key(row): row
            for row in incoming_rows
        }
        merged: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str]] = set()
        for current in current_rows:
            key = simu_loop._hydrogen_storage_state_key(current)
            incoming = incoming_by_key.get(key)
            source = incoming if incoming is not None else current
            merged.append({header: source.get(header, "") for header in headers})
            seen.add(key)
        for incoming in incoming_rows:
            key = simu_loop._hydrogen_storage_state_key(incoming)
            if key in seen:
                continue
            merged.append({header: incoming.get(header, "") for header in headers})
            seen.add(key)
        return merged

    def _normalize_run_command_items(self, items: Sequence[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            dev_type = str(item.get("dev_type", item.get("type", "")))
            dev_name = str(item.get("dev_name", item.get("name", "")))
            if not dev_type or not dev_name:
                continue
            run_stat = item.get("run_stat", item.get("running", item.get("value", "")))
            if isinstance(run_stat, bool):
                run_stat = 1 if run_stat else 0
            row = {"dev_type": dev_type, "dev_name": dev_name, "run_stat": _number_text(run_stat)}
            if "status" in item:
                row["status"] = _number_text(item.get("status"))
            normalized.append(row)
        return normalized

    def _normalize_set_command_items(self, items: Sequence[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in self._expand_set_values(items):
            dev_type = str(item.get("dev_type", item.get("type", "")))
            dev_name = str(item.get("dev_name", item.get("name", "")))
            set_type = str(item.get("set_type", ""))
            if not dev_type or not dev_name or not set_type:
                continue
            normalized.append(
                {
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "set_type": set_type,
                    "set_value": _number_text(item.get("set_value", "")),
                }
            )
        return normalized

    def _write_active_yt_ctrl_file(self, set_rows: Sequence[Mapping[str, Any]], *, persist: bool = False) -> None:
        unique_rows: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in set_rows:
            dev_type = str(row.get("dev_type", ""))
            dev_name = str(row.get("dev_name", row.get("name", "")))
            set_type = str(row.get("set_type", ""))
            if not dev_type or not dev_name or not set_type:
                continue
            unique_rows[(dev_type, dev_name, set_type)] = {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "set_type": set_type,
                "set_value": row.get("set_value", ""),
            }
        self.yt_ctrl_book = _make_book({"SetValue": (STAT_HEADERS["SetValue"], list(unique_rows.values()))})
        if persist:
            simu_loop.write_ebook_aligned(self.yt_ctrl_book, self.files["yt_ctrl"])

    def _command_entry_is_active(
        self,
        item: Mapping[str, Any],
        absolute_minute: int | float,
        run_id: Optional[int] = None,
    ) -> bool:
        current = float(absolute_minute)
        manual_hold = _manual_command_holds_across_clock_lifecycle(item)
        if not manual_hold and _command_origin(item) == "automatic":
            if (
                not self._command_entry_has_recorded_controls(item)
                or self._automatic_command_was_reset(item)
            ):
                return False
            entry_run_id = _to_float(item.get("run_id"), None)
            expected_run_id = int(
                run_id
                if run_id is not None
                else (_to_float(self.clock.run_id, 0) or 0)
            )
            if entry_run_id is None or int(entry_run_id) != expected_run_id:
                return False
            issued = _to_float(item.get("issued_absolute_minute"), None)
            if issued is None or issued > current + 1e-9:
                return False
            cycle_minutes = float(self._simulation_cycle_minutes())
            issued_cycle = math.floor((issued + 1e-9) / cycle_minutes)
            current_cycle = math.floor((current + 1e-9) / cycle_minutes)
            return issued_cycle == current_cycle
        if not self._command_entry_has_accepted_controls(item):
            return False
        if manual_hold:
            return True
        if not manual_hold:
            entry_run_id = _to_float(item.get("run_id"), None)
            expected_run_id = int(run_id if run_id is not None else (_to_float(self.clock.run_id, 0) or 0))
            if entry_run_id is None or int(entry_run_id) != expected_run_id:
                return False
        issued = _to_float(item.get("issued_absolute_minute"), None)
        expires = _to_float(item.get("expires_at_absolute_minute"), None)
        if issued is None or expires is None:
            return False
        return current < expires and (manual_hold or issued <= current)

    @staticmethod
    def _automatic_command_was_reset(item: Mapping[str, Any]) -> bool:
        reason = str(item.get("cancelled_reason", "")).strip().casefold()
        return reason.startswith("simulation_") or reason == "runtime_reset"

    def _command_entry_has_recorded_controls(self, item: Mapping[str, Any]) -> bool:
        if not isinstance(item, Mapping) or not item.get("eligible_source"):
            return False
        accepted = item.get("accepted", {})
        if not isinstance(accepted, Mapping):
            return False
        accepted_count = int(_to_float(accepted.get("run_status"), 0) or 0) + int(
            _to_float(accepted.get("set_values"), 0) or 0
        )
        return accepted_count > 0

    def _command_entry_has_accepted_controls(self, item: Mapping[str, Any]) -> bool:
        return self._command_entry_has_recorded_controls(item) and not item.get(
            "cancelled"
        )

    def _command_entry_can_be_cancelled(
        self,
        item: Mapping[str, Any],
        absolute_minute: int | float,
        run_id: Optional[int] = None,
    ) -> bool:
        if not self._command_entry_has_accepted_controls(item):
            return False
        if _manual_command_holds_across_clock_lifecycle(item):
            return True
        return self._command_entry_is_active(item, absolute_minute, run_id)

    def _active_control_command_entries(self, absolute_minute: int | float) -> List[Mapping[str, Any]]:
        current_run_id = int(_to_float(self.clock.run_id, 0) or 0)
        active: List[Tuple[int, Mapping[str, Any]]] = []
        for index, item in enumerate(self.command_history):
            if self._command_entry_is_active(item, absolute_minute, current_run_id):
                active.append((index, item))
        # Materialization is last-write-wins. Automatic targets are the lower
        # priority fallback; a manual command always owns the same control point
        # until the operator explicitly exits it.
        active.sort(key=lambda pair: (0 if _command_origin(pair[1]) == "automatic" else 1, pair[0]))
        return [item for _index, item in active]

    def _effective_active_control_command_entries(self, absolute_minute: int | float) -> List[Mapping[str, Any]]:
        active_entries = self._active_control_command_entries(absolute_minute)
        effective_by_control: Dict[Tuple[str, str, str, str], Mapping[str, Any]] = {}
        simulator_ui_overrides = self._simulator_ui_control_override_keys()
        for entry in active_entries:
            normalized = entry.get("normalized", {})
            if not isinstance(normalized, Mapping):
                continue
            run_items = normalized.get("run_status", [])
            if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
                for item in run_items:
                    if not isinstance(item, Mapping):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    if not dev_type or not dev_name:
                        continue
                    if (
                        item.get("run_stat", "") != ""
                        and ("remote_control", dev_type, dev_name, "run_stat")
                        not in simulator_ui_overrides
                    ):
                        effective_by_control[("remote_control", dev_type, dev_name, "run_stat")] = entry
                    if (
                        item.get("status", "") != ""
                        and ("remote_control", dev_type, dev_name, "status")
                        not in simulator_ui_overrides
                    ):
                        effective_by_control[("remote_control", dev_type, dev_name, "status")] = entry
            set_items = normalized.get("set_values", [])
            if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
                for item in set_items:
                    if not isinstance(item, Mapping):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    set_type = str(item.get("set_type", "")).strip()
                    if (
                        dev_type
                        and dev_name
                        and set_type
                        and ("remote_adjustment", dev_type, dev_name, set_type)
                        not in simulator_ui_overrides
                    ):
                        effective_by_control[("remote_adjustment", dev_type, dev_name, set_type)] = entry
        effective_ids = {id(entry) for entry in effective_by_control.values()}
        return [entry for entry in active_entries if id(entry) in effective_ids]

    def _effective_active_control_command_views(
        self,
        absolute_minute: int | float,
    ) -> List[Mapping[str, Any]]:
        """Project active history to the last owner of each control point."""
        active_entries = self._active_control_command_entries(absolute_minute)
        owner_by_control: Dict[Tuple[str, str, str, str], int] = {}
        simulator_ui_overrides = self._simulator_ui_control_override_keys()
        for entry_index, entry in enumerate(active_entries):
            normalized = entry.get("normalized", {})
            if not isinstance(normalized, Mapping):
                continue
            run_items = normalized.get("run_status", [])
            if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
                for item in run_items:
                    if not isinstance(item, Mapping):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    if not dev_type or not dev_name:
                        continue
                    if item.get("run_stat", "") != "":
                        key = ("remote_control", dev_type, dev_name, "run_stat")
                        if key not in simulator_ui_overrides:
                            owner_by_control[key] = entry_index
                    if item.get("status", "") != "":
                        key = ("remote_control", dev_type, dev_name, "status")
                        if key not in simulator_ui_overrides:
                            owner_by_control[key] = entry_index
            set_items = normalized.get("set_values", [])
            if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
                for item in set_items:
                    if not isinstance(item, Mapping):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    set_type = str(item.get("set_type", "")).strip()
                    key = ("remote_adjustment", dev_type, dev_name, set_type)
                    if dev_type and dev_name and set_type and key not in simulator_ui_overrides:
                        owner_by_control[key] = entry_index

        projected: List[Mapping[str, Any]] = []
        for entry_index, entry in enumerate(active_entries):
            normalized = entry.get("normalized", {})
            if not isinstance(normalized, Mapping):
                continue
            selected_run_by_device: Dict[Tuple[str, str], Dict[str, Any]] = {}
            run_items = normalized.get("run_status", [])
            if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
                for item in run_items:
                    if not isinstance(item, Mapping):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    if not dev_type or not dev_name:
                        continue
                    selected = {"dev_type": dev_type, "dev_name": dev_name}
                    for field_name in ("run_stat", "status"):
                        key = ("remote_control", dev_type, dev_name, field_name)
                        if item.get(field_name, "") != "" and owner_by_control.get(key) == entry_index:
                            selected[field_name] = item.get(field_name)
                    if len(selected) > 2:
                        selected_run_by_device[(dev_type, dev_name)] = selected
            selected_set: List[Dict[str, Any]] = []
            set_items = normalized.get("set_values", [])
            if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
                for item in set_items:
                    if not isinstance(item, Mapping):
                        continue
                    key = (
                        "remote_adjustment",
                        str(item.get("dev_type", "")).strip(),
                        str(item.get("dev_name", "")).strip(),
                        str(item.get("set_type", "")).strip(),
                    )
                    if owner_by_control.get(key) == entry_index:
                        selected_set.append(dict(item))
            selected_run = list(selected_run_by_device.values())
            if not selected_run and not selected_set:
                continue

            original_run = normalized.get("run_status", [])
            original_set = normalized.get("set_values", [])
            if selected_run == original_run and selected_set == original_set:
                projected.append(entry)
                continue
            view = dict(entry)
            view_normalized = dict(normalized)
            view_normalized["run_status"] = selected_run
            view_normalized["set_values"] = selected_set
            view["normalized"] = view_normalized
            accepted = entry.get("accepted", {})
            view_accepted = dict(accepted) if isinstance(accepted, Mapping) else {}
            view_accepted["run_status"] = len(selected_run)
            view_accepted["set_values"] = len(selected_set)
            view["accepted"] = view_accepted
            projected.append(view)
        return projected

    def _defined_run_control_fields(self) -> Dict[Tuple[str, str], set[str]]:
        fields: Dict[Tuple[str, str], set[str]] = {}
        for row in self._control_definition_rows("RunStat"):
            dev_type = str(row.get("dev_type", "")).strip()
            dev_name = _dev_name(row).strip()
            if dev_type and dev_name:
                fields.setdefault((dev_type, dev_name), set()).add("run_stat")
        for row in self._control_definition_rows("CbOpenStat"):
            dev_type = str(row.get("dev_type", "")).strip()
            dev_name = _dev_name(row).strip()
            if dev_type and dev_name:
                fields.setdefault((dev_type, dev_name), set()).add("status")
        return fields

    def _defined_set_control_keys(self) -> set[Tuple[str, str, str]]:
        keys: set[Tuple[str, str, str]] = set()
        for row in self._control_definition_rows("SetValue"):
            dev_type = str(row.get("dev_type", "")).strip()
            dev_name = _dev_name(row).strip()
            set_type = str(row.get("set_type", "")).strip()
            if dev_type and dev_name and set_type:
                keys.add((dev_type, dev_name, set_type))
        return keys

    def _filter_defined_run_command_items(self, items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        allowed_fields = self._defined_run_control_fields()
        filtered: List[Dict[str, Any]] = []
        for item in items:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", "")).strip()
            fields = allowed_fields.get((dev_type, dev_name), set())
            if not dev_type or not dev_name or not fields:
                continue
            row: Dict[str, Any] = {"dev_type": dev_type, "dev_name": dev_name}
            if item.get("run_stat", "") != "" and "run_stat" in fields:
                row["run_stat"] = _number_text(item.get("run_stat"))
            if "status" in item and "status" in fields:
                row["status"] = _number_text(item.get("status"))
            if len(row) > 2:
                filtered.append(row)
        return filtered

    @staticmethod
    def _validate_run_command_items(
        items: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        validated: List[Dict[str, Any]] = []
        for item in items:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", "")).strip()
            row: Dict[str, Any] = {"dev_type": dev_type, "dev_name": dev_name}
            for field in ("run_stat", "status"):
                if field not in item or item.get(field, "") == "":
                    continue
                number = _to_float(item.get(field), None)
                if number not in (0.0, 1.0):
                    raise ValueError(
                        f"遥控安全校验失败：{dev_type}/{dev_name} 的 {field}="
                        f"{item.get(field)} 只能取 0 或 1；"
                        "本批指令未下发，仿真边界未修改。"
                    )
                row[field] = _number_text(number)
            validated.append(row)
        return validated

    def _filter_defined_set_command_items(self, items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        allowed_keys = self._defined_set_control_keys()
        filtered: List[Dict[str, Any]] = []
        for item in items:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", "")).strip()
            set_type = str(item.get("set_type", "")).strip()
            if (dev_type, dev_name, set_type) not in allowed_keys:
                continue
            filtered.append(
                {
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "set_type": set_type,
                    "set_value": _number_text(item.get("set_value", "")),
                }
            )
        return filtered

    def _validated_command_entry_items(
        self,
        command: Mapping[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        normalized = command.get("normalized", {})
        normalized_map = normalized if isinstance(normalized, Mapping) else {}
        raw_run = normalized_map.get("run_status", [])
        raw_set = normalized_map.get("set_values", [])
        run_sequence = (
            list(raw_run)
            if isinstance(raw_run, Sequence) and not isinstance(raw_run, (str, bytes))
            else []
        )
        set_sequence = (
            list(raw_set)
            if isinstance(raw_set, Sequence) and not isinstance(raw_set, (str, bytes))
            else []
        )
        run_items = self._filter_defined_run_command_items(
            self._normalize_run_command_items(run_sequence)
        )
        set_items = self._filter_defined_set_command_items(
            self._normalize_set_command_items(set_sequence)
        )
        return (
            self._validate_run_command_items(run_items),
            self._validate_set_command_items(set_items, strict=True),
        )

    def _materialize_active_control_commands(
        self,
        absolute_minute: int | float,
        *,
        persist: bool = False,
        additional_ui_overrides: Optional[set[Tuple[str, str, str, str]]] = None,
    ) -> Dict[str, int]:
        active_entries = self._effective_active_control_command_views(absolute_minute)
        allowed_set_keys = self._defined_set_control_keys()
        active_adjustment_keys = self._remote_adjustment_keys_from_command_views(
            active_entries,
            allowed_set_keys=allowed_set_keys,
        )
        book = self._base_stat_book_for_controls()
        run_block = _ensure_block(book, "RunStat", STAT_HEADERS["RunStat"])
        cb_block = _ensure_block(book, "CbOpenStat", STAT_HEADERS["CbOpenStat"])
        set_block = _ensure_block(book, "SetValue", STAT_HEADERS["SetValue"])
        allowed_run_fields = self._defined_run_control_fields()
        source_curve_defaults = self._apply_default_source_curves(
            book,
            absolute_minute,
            allowed_set_keys=allowed_set_keys,
            active_command_keys=active_adjustment_keys,
        )
        load_curve_defaults = self._apply_default_non_electric_load_curves(
            book,
            absolute_minute,
            active_command_keys=active_adjustment_keys,
        )
        applied_run = 0
        applied_set = 0
        safe_active_entries = 0
        active_set_rows: List[Dict[str, Any]] = []
        unsafe_command_items: List[str] = []
        simulator_ui_overrides = self._simulator_ui_control_override_keys()
        if additional_ui_overrides:
            simulator_ui_overrides.update(additional_ui_overrides)

        for command in active_entries:
            try:
                run_items, set_items = self._validated_command_entry_items(command)
            except ValueError as exc:
                unsafe_command_items.append(str(exc))
                continue
            if not run_items and not set_items:
                continue
            safe_active_entries += 1
            for item in run_items:
                    dev_type = str(item.get("dev_type", ""))
                    dev_name = str(item.get("dev_name", ""))
                    if not dev_type or not dev_name:
                        continue
                    fields = allowed_run_fields.get((dev_type, dev_name), set())
                    if not fields:
                        continue
                    row = _find_dev_row(run_block, dev_type, dev_name)
                    run_stat_overridden = (
                        "remote_control", dev_type, dev_name, "run_stat"
                    ) in simulator_ui_overrides
                    status_overridden = (
                        "remote_control", dev_type, dev_name, "status"
                    ) in simulator_ui_overrides
                    if (
                        row is None
                        and not run_stat_overridden
                        and "run_stat" in fields
                        and item.get("run_stat", "") != ""
                    ):
                        row = {"dev_type": dev_type, "dev_name": dev_name, "run_stat": ""}
                        run_block.data.append(row)
                    if (
                        not run_stat_overridden
                        and row is not None
                        and item.get("run_stat", "") != ""
                        and "run_stat" in fields
                    ):
                        row["run_stat"] = _number_text(item.get("run_stat"))
                        applied_run += 1
                    if not status_overridden and "status" in item and "status" in fields:
                        cb_row = _find_dev_row(cb_block, dev_type, dev_name)
                        if cb_row is None:
                            cb_row = {"dev_type": dev_type, "dev_name": dev_name, "status": ""}
                            cb_block.data.append(cb_row)
                        cb_row["status"] = _number_text(item.get("status"))
                        applied_run += 1
            for item in set_items:
                    dev_type = str(item.get("dev_type", ""))
                    dev_name = str(item.get("dev_name", ""))
                    set_type = str(item.get("set_type", ""))
                    if not dev_type or not dev_name or not set_type:
                        continue
                    if (dev_type, dev_name, set_type) not in allowed_set_keys:
                        continue
                    if (
                        "remote_adjustment", dev_type, dev_name, set_type
                    ) in simulator_ui_overrides:
                        continue
                    row = _find_set_row(set_block, dev_type, dev_name, set_type)
                    if row is None:
                        row = {"dev_type": dev_type, "dev_name": dev_name, "set_type": set_type, "set_value": ""}
                        set_block.data.append(row)
                    row["set_value"] = item["set_value"]
                    applied_set += 1
                    active_set_rows.append(
                        {
                            "dev_type": dev_type,
                            "dev_name": dev_name,
                            "set_type": set_type,
                            "set_value": row["set_value"],
                        }
                    )

        self.runtime_stat_book = book
        if persist:
            simu_loop.write_ebook_aligned(book, self.files["stat"])
        self._write_active_yt_ctrl_file(active_set_rows, persist=persist)
        if unsafe_command_items:
            self._append_runtime_log(
                "控制安全边界",
                "持久化指令物化",
                "越界指令已阻断",
                [
                    *unsafe_command_items,
                    "包含不安全值的整批指令未写入运行控制文件和潮流边界。",
                ],
                level="warn",
            )
        return {
            "active_commands": safe_active_entries,
            "run_status": applied_run,
            "set_values": applied_set,
            "source_curve_defaults": source_curve_defaults,
            "load_curve_defaults": load_curve_defaults,
        }

    def _manual_source_curve_override_keys(self) -> set[Tuple[str, str, str]]:
        keys: set[Tuple[str, str, str]] = set()
        for item in self._manual_definition_changes.values():
            if item.get("kind") != "device" or item.get("effective") is False:
                continue
            dev_type = str(item.get("block_name", "")).strip()
            set_type = str(item.get("field", "")).strip().casefold()
            row_key = item.get("row_key", {})
            dev_name = (
                str(row_key.get("name", "")).strip()
                if isinstance(row_key, Mapping)
                else ""
            )
            if dev_type and dev_name and set_type:
                keys.add((dev_type, dev_name, set_type))
        return keys

    def _simulator_ui_control_override_keys(self) -> set[Tuple[str, str, str, str]]:
        keys: set[Tuple[str, str, str, str]] = set()
        for item in self._manual_definition_changes.values():
            if item.get("kind") != "device" or item.get("effective") is False:
                continue
            dev_type = str(item.get("block_name", "")).strip()
            field_name = str(item.get("field", "")).strip().casefold()
            row_key = item.get("row_key", {})
            dev_name = (
                str(row_key.get("name", "")).strip()
                if isinstance(row_key, Mapping)
                else ""
            )
            if not dev_type or not dev_name:
                continue
            if field_name in RUNTIME_CONTROL_STATUS_FIELDS:
                keys.add(("remote_control", dev_type, dev_name, field_name))
                continue
            set_type = self._runtime_control_set_type(dev_type, field_name)
            if set_type:
                keys.add(("remote_adjustment", dev_type, dev_name, set_type))
        return keys

    def _inactive_coupling_default_curve_keys(self) -> set[Tuple[str, str, str]]:
        active_by_endpoint: Dict[Tuple[str, str, str], bool] = {}
        for bindings in energy_coupling_control_bindings(
            self.definition_snapshot.model_book
        ).values():
            for binding in bindings:
                key = (
                    str(binding.get("target_dev_type", "")).strip(),
                    str(binding.get("target_dev_name", "")).strip(),
                    str(binding.get("target_set_type", binding.get("set_type", ""))).strip(),
                )
                if not all(key):
                    continue
                active_by_endpoint[key] = active_by_endpoint.get(key, False) or bool(
                    binding.get("active")
                )
        return {key for key, active in active_by_endpoint.items() if not active}

    def _apply_default_source_curves(
        self,
        book: EBook,
        absolute_minute: int | float,
        *,
        allowed_set_keys: Optional[set[Tuple[str, str, str]]] = None,
        active_command_keys: Optional[set[Tuple[str, str, str]]] = None,
    ) -> int:
        sources = self.curves.get("sources", [])
        if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
            return 0
        catalog = source_curve_catalog_by_identity(self.definition_snapshot.model_book)
        allowed = allowed_set_keys if allowed_set_keys is not None else self._defined_set_control_keys()
        manual_overrides = self._manual_source_curve_override_keys()
        active_commands = (
            active_command_keys
            if active_command_keys is not None
            else self._active_remote_adjustment_keys(absolute_minute)
        )
        inactive_coupling_keys = self._inactive_coupling_default_curve_keys()
        curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        period_minutes = _simulation_mode_duration_minutes(curve_mode)
        applied = 0
        for item in sources:
            if not isinstance(item, Mapping):
                continue
            key = source_curve_identity(item)
            if (
                key not in catalog
                or key in manual_overrides
                or key in active_commands
                or key in inactive_coupling_keys
            ):
                continue
            points = item.get("points", [])
            if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                continue
            value = self._interpolate_curve_series(
                points,
                absolute_minute,
                "value",
                None,
                period_minutes=period_minutes,
            )
            if value is None or not math.isfinite(value):
                continue
            try:
                safe = self._validated_set_command_item(
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "set_type": key[2],
                        "set_value": value,
                    },
                    strict=True,
                )
            except ValueError:
                continue
            self._write_boundary_set_value(book, key, float(safe["set_value"]))
            applied += 1
        return applied

    def _apply_default_non_electric_load_curves(
        self,
        book: EBook,
        absolute_minute: int | float,
        *,
        active_command_keys: Optional[set[Tuple[str, str, str]]] = None,
    ) -> int:
        catalog = {
            str(item["key"]): item
            for item in self._external_curve_catalog()
            if item.get("curve_type") == "load"
            and item.get("dev_type") in {"HydroLoad", "HeatLoad"}
        }
        manual_overrides = self._manual_source_curve_override_keys()
        active_commands = (
            active_command_keys
            if active_command_keys is not None
            else self._active_remote_adjustment_keys(absolute_minute)
        )
        inactive_coupling_keys = self._inactive_coupling_default_curve_keys()
        curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        period_minutes = _simulation_mode_duration_minutes(curve_mode)
        applied = 0
        for item in catalog.values():
            key = load_curve_identity(item)
            if key in manual_overrides or key in active_commands or key in inactive_coupling_keys:
                continue
            points = item.get("points", [])
            aliases = tuple(item.get("value_aliases", ("value",)))
            value = None
            for alias in aliases:
                value = self._interpolate_curve_series(
                    points,
                    absolute_minute,
                    str(alias),
                    None,
                    period_minutes=period_minutes,
                )
                if value is not None:
                    break
            if value is None or not math.isfinite(value):
                continue
            try:
                safe = self._validated_set_command_item(
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "set_type": key[2],
                        "set_value": value,
                    },
                    strict=True,
                )
            except ValueError:
                continue
            self._write_boundary_set_value(book, key, float(safe["set_value"]))
            applied += 1
        return applied

    def _remote_adjustment_keys_from_command_views(
        self,
        command_views: Sequence[Mapping[str, Any]],
        *,
        allowed_set_keys: Optional[set[Tuple[str, str, str]]] = None,
    ) -> set[Tuple[str, str, str]]:
        allowed = (
            allowed_set_keys
            if allowed_set_keys is not None
            else self._defined_set_control_keys()
        )
        active_keys: set[Tuple[str, str, str]] = set()
        simulator_ui_overrides = {
            (dev_type, dev_name, field_name)
            for kind, dev_type, dev_name, field_name in self._simulator_ui_control_override_keys()
            if kind == "remote_adjustment"
        }
        for command in command_views:
            try:
                _run_items, set_items = self._validated_command_entry_items(command)
            except ValueError:
                continue
            for item in set_items:
                key = (
                    str(item.get("dev_type", "")),
                    str(item.get("dev_name", "")),
                    str(item.get("set_type", "")),
                )
                if key in allowed and key not in simulator_ui_overrides:
                    active_keys.add(key)
        return active_keys

    def _active_remote_adjustment_keys(self, absolute_minute: int | float) -> set[Tuple[str, str, str]]:
        return self._remote_adjustment_keys_from_command_views(
            self._effective_active_control_command_views(absolute_minute)
        )

    @staticmethod
    def _set_value_from_book(book: EBook, key: Tuple[str, str, str]) -> Optional[float]:
        block = book.data.get("SetValue")
        if block is None:
            return None
        row = _find_set_row(block, *key)
        if row is None:
            return None
        value = _to_float(row.get("set_value"), None)
        return float(value) if value is not None and math.isfinite(value) else None

    def _model_control_row(self, dev_type: str, dev_name: str) -> Optional[Mapping[str, Any]]:
        block = self.definition_snapshot.model_book.data.get(dev_type)
        if block is None:
            return None
        return next(
            (
                row
                for row in getattr(block, "data", [])
                if str(row.get("name", "")).strip() == dev_name
            ),
            None,
        )

    def _control_target_row(
        self,
        dev_type: str,
        dev_name: str,
    ) -> Optional[Mapping[str, Any]]:
        direct = self._model_control_row(dev_type, dev_name)
        resources = structured_resources(self.definition_snapshot.model_book)
        resource_by_key = {resource.device_key: resource for resource in resources}
        matched_resources = []
        if direct is not None:
            direct_resource = resource_by_key.get((dev_type, dev_name))
            return self._control_safety_row(direct, direct_resource)

        protocol_key = (dev_type, dev_name)
        for resource_key, protocol_keys in self._storage_runtime_protocol_keys().items():
            if protocol_key in protocol_keys and resource_key in resource_by_key:
                matched_resources.append(resource_by_key[resource_key])
        matched_resources.extend(
            resource
            for resource in resources
            if dev_name in resource_aliases(resource)
            and (not dev_type or dev_type in {"ESS", resource.source_block})
        )
        unique = {resource.device_key: resource for resource in matched_resources}
        if len(unique) != 1:
            return None
        resource = next(iter(unique.values()))
        return self._control_safety_row(resource.source, resource)

    @staticmethod
    def _control_safety_row(
        source: Mapping[str, Any],
        resource: Any = None,
    ) -> Mapping[str, Any]:
        """Combine source and capability limits without changing model data."""

        row = dict(source)
        if resource is None:
            return row
        parameter = dict(resource.parameter)
        for field, value in parameter.items():
            row.setdefault(field, value)

        source_p_min = _to_float(row.get("p_min"), None)
        source_p_max = _to_float(row.get("p_max"), None)
        parameter_p_min = _to_float(parameter.get("p_min"), None)
        parameter_p_max = _to_float(parameter.get("p_max"), None)
        source_pair_is_placeholder = (
            source_p_min == 0.0
            and source_p_max == 0.0
            and any(value not in (None, 0.0) for value in (parameter_p_min, parameter_p_max))
        )
        if source_p_min is None or source_pair_is_placeholder:
            if parameter_p_min is not None:
                row["p_min"] = parameter_p_min
        if source_p_max is None or source_pair_is_placeholder:
            if parameter_p_max is not None:
                row["p_max"] = parameter_p_max

        if resource.technology == "storage" and (
            source_p_min is None
            or source_p_max is None
            or (source_p_min == 0.0 and source_p_max == 0.0)
        ):
            max_charge = _to_float(
                parameter.get("max_charge_power", parameter.get("charge_p_max")),
                None,
            )
            max_discharge = _to_float(
                parameter.get("max_discharge_power", parameter.get("dis_charge_p_max")),
                None,
            )
            if max_charge is not None and max_charge >= 0.0:
                row["p_min"] = -float(max_charge)
            if max_discharge is not None and max_discharge >= 0.0:
                row["p_max"] = float(max_discharge)
        return row

    def _validated_set_command_item(
        self,
        item: Mapping[str, Any],
        *,
        strict: bool,
    ) -> Dict[str, Any]:
        dev_type = str(item.get("dev_type", "")).strip()
        dev_name = str(item.get("dev_name", "")).strip()
        set_type = str(item.get("set_type", "")).strip()
        value = item.get("set_value", "")
        target = self._control_target_row(dev_type, dev_name)
        if target is None:
            if strict:
                raise ValueError(
                    f"遥调安全校验失败：未找到 {dev_type}/{dev_name} 的模型设备；"
                    "本批指令未下发，仿真边界未修改。"
                )
            return {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "set_type": set_type,
                "set_value": _number_text(value),
            }

        target_type = str(dev_type)
        target_set_type = simu_loop._set_value_target_column(
            target_type,
            set_type,
            dict(target),
        )
        if not self.enforce_runtime_setpoint_bounds:
            number = _to_float(value, None)
            if number is None or not math.isfinite(number):
                raise ValueError(
                    f"遥调数值校验失败：{dev_type}/{dev_name} 的 "
                    f"{set_type}={value} 不是有限数值；"
                    "本批指令未下发，仿真边界未修改。"
                )
            return {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "set_type": set_type,
                "set_value": _number_text(number),
            }
        try:
            requested_number = _to_float(value, None)
            if requested_number is None or not math.isfinite(requested_number):
                raise ValueError(f"{set_type}={value} 不是有限数值")
            number, bounds, device_clamped = clamp_setpoint_safety_bounds(
                target,
                target_set_type,
                requested_number,
            )
            hydrogen_safety = validate_hydrogen_power_setpoint_safety(
                self.definition_snapshot.model_book,
                dev_type,
                dev_name,
                target_set_type,
                number,
                clamp_to_bounds=True,
            )
            hydrogen_clamped = bool(
                hydrogen_safety and hydrogen_safety.get("clamped")
            )
            if hydrogen_clamped:
                number = float(hydrogen_safety["p_set"])
            number, _final_bounds, electrical_reclamped = (
                clamp_setpoint_safety_bounds(
                    target,
                    target_set_type,
                    number,
                )
            )
        except ValueError as exc:
            raise ValueError(
                f"遥调数值或模型校验失败：{dev_type}/{dev_name} 的 "
                f"{set_type}={_number_text(value)} 无法形成有效有限目标（{exc}）；"
                "本批指令未下发，仿真边界未修改。"
            ) from exc
        if device_clamped or hydrogen_clamped or electrical_reclamped:
            bound_text = ""
            if bounds is not None:
                lower_name, lower, upper_name, upper = bounds
                parts = []
                if lower is not None:
                    parts.append(f"{lower_name}={_number_text(lower)}")
                if upper is not None:
                    parts.append(f"{upper_name}={_number_text(upper)}")
                bound_text = "，设备边界 " + "，".join(parts)
            detail = [
                (
                    f"{dev_type}/{dev_name}.{set_type} 请求值 "
                    f"{_number_text(requested_number)} 已限幅为 {_number_text(number)}"
                    f"{bound_text}"
                ),
                "设备运行状态保持不变；限幅后的遥调指令继续登记、物化并送入潮流边界。",
            ]
            if hydrogen_clamped:
                detail.append("电氢转换目标同时按显式耦合关系和氢端流量边界完成限幅。")
            if electrical_reclamped:
                detail.append("电端与氢端边界没有完全重合，最终以电端设备边界为准并保留告警。")
            self._append_runtime_log(
                "控制安全边界",
                "遥调指令限幅",
                "越界值已限幅并继续下发",
                detail,
                level="warn",
            )
        return {
            "dev_type": dev_type,
            "dev_name": dev_name,
            "set_type": set_type,
            "set_value": _number_text(number),
        }

    def _validate_set_command_items(
        self,
        items: Sequence[Mapping[str, Any]],
        *,
        strict: bool,
    ) -> List[Dict[str, Any]]:
        return [
            self._validated_set_command_item(item, strict=strict)
            for item in items
        ]

    def _remote_adjustment_measurement_types(self, key: Tuple[str, str, str]) -> Tuple[str, ...]:
        dev_type, dev_name, set_type = key
        target_row = self._model_control_row(dev_type, dev_name)
        resolved_type = set_type
        if target_row is not None:
            resolved_type = simu_loop._set_value_target_column(dev_type, set_type, dict(target_row))

        direct_types = {
            "p_ac_set": ("P_AC",),
            "p_dc_set": ("P_DC",),
            "q_ac_set": ("Q_AC",),
            "q_dc_set": ("Q_DC",),
            "v_ac_set": ("V_AC",),
            "v_dc_set": ("V_DC",),
            "p_from_set": ("P_FROM",),
            "q_from_set": ("Q_FROM",),
            "v_from_set": ("V_FROM",),
            "p_to_set": ("P_TO",),
            "q_to_set": ("Q_TO",),
            "v_to_set": ("V_TO",),
        }
        if resolved_type in direct_types:
            return direct_types[resolved_type]
        if resolved_type in {"pv0", "p_set"}:
            if dev_type in {"ACGenerator", "DCGenerator"}:
                return ("P_GEN", "P")
            if dev_type in {"ACLoad", "DCLoad"}:
                return ("P_LOAD", "P")
            if dev_type == "ESS":
                return ("P", "P_GEN")
            if dev_type in {"DCDCConverter", "ACACConverter"}:
                return ("P_FROM", "P_TO", "P")
            return ("P", "P_GEN", "P_LOAD")
        if resolved_type in {"qv0", "q_set"}:
            if dev_type == "ACGenerator":
                return ("Q_GEN", "Q")
            if dev_type == "ACLoad":
                return ("Q_LOAD", "Q")
            if dev_type == "ESS":
                return ("Q", "Q_GEN")
            return ("Q", "Q_GEN", "Q_LOAD")
        if resolved_type == "v_set":
            if dev_type in {"ACGenerator", "DCGenerator"}:
                return ("V_GEN", "V")
            if dev_type in {"ACLoad", "DCLoad"}:
                return ("V_LOAD", "V")
            if dev_type in {"DCDCConverter", "ACACConverter"}:
                return ("V_TO", "V_FROM", "V")
            return ("V", "V_GEN", "V_LOAD")
        if resolved_type == "i_set":
            if dev_type in {"ACGenerator", "DCGenerator"}:
                return ("I_GEN", "I")
            if dev_type in {"ACLoad", "DCLoad"}:
                return ("I_LOAD", "I")
            return ("I", "I_FROM", "I_TO")
        return (resolved_type.removesuffix("_set").upper(),)

    def _latest_true_remote_adjustment_value(self, key: Tuple[str, str, str]) -> Optional[float]:
        dev_type, dev_name, _set_type = key
        candidates: Dict[str, float] = {}
        for raw_row in self.latest_real_rows:
            row = _measurement_row_to_dict(raw_row)
            if str(row.get("dev_type", "")) != dev_type or str(row.get("dev_name", "")) != dev_name:
                continue
            if int(_to_float(row.get("valid"), 1) or 0) != 1:
                continue
            meas_type = str(row.get("meas_type", "")).upper()
            value = _to_float(row.get("value"), None)
            if meas_type and value is not None and math.isfinite(value):
                candidates[meas_type] = float(value)
        for meas_type in self._remote_adjustment_measurement_types(key):
            if meas_type in candidates:
                return candidates[meas_type]
        return None

    @staticmethod
    def _write_boundary_set_value(book: EBook, key: Tuple[str, str, str], value: float) -> None:
        block = _ensure_block(book, "SetValue", STAT_HEADERS["SetValue"])
        row = _find_set_row(block, *key)
        if row is None:
            row = {
                "dev_type": key[0],
                "dev_name": key[1],
                "set_type": key[2],
                "set_value": "",
            }
            block.data.append(row)
        row["set_value"] = _number_text(value)

    def _remote_adjustment_boundary_books(
        self,
        absolute_minute: int | float,
        cycle_token: int,
    ) -> Tuple[EBook, EBook]:
        stat_book = simu_loop._clone_ebook(self.runtime_stat_book)
        yt_ctrl_book = simu_loop._clone_ebook(self.yt_ctrl_book)
        active_keys = self._active_remote_adjustment_keys(absolute_minute)
        tracked_keys = active_keys | set(self._remote_adjustment_execution)
        response_ratio = self.remote_adjustment_response_ratio

        for key in sorted(tracked_keys):
            target = self._set_value_from_book(self.runtime_stat_book, key)
            if target is None:
                self._remote_adjustment_execution.pop(key, None)
                continue
            try:
                safe_target = self._validated_set_command_item(
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "set_type": key[2],
                        "set_value": target,
                    },
                    strict=True,
                )
                target = float(safe_target["set_value"])
            except ValueError as exc:
                self._append_runtime_log(
                    "控制安全边界",
                    "潮流边界准备",
                    "不安全目标已阻断",
                    [str(exc), "本轮潮流计算未接收该不安全遥调边界。"],
                    level="warn",
                )
                raise ValueError(
                    f"潮流边界安全校验失败：{key[0]}/{key[1]} 的 {key[2]}="
                    f"{_number_text(target)} 超出允许范围；本轮潮流计算已阻断。"
                ) from exc

            state = self._remote_adjustment_execution.get(key)
            if state is None:
                fallback = self._set_value_from_book(self.source_stat_book, key)
                current = self._latest_true_remote_adjustment_value(key)
                if current is None:
                    current = target if fallback is None else fallback
                state = {"executed_value": float(current), "last_cycle_token": None}
                self._remote_adjustment_execution[key] = state

            if state.pop("force_target_once", False):
                state["executed_value"] = float(target)
                state["target_value"] = float(target)
                state["last_cycle_token"] = cycle_token
            elif state.get("last_cycle_token") != cycle_token:
                current = self._latest_true_remote_adjustment_value(key)
                if current is None:
                    current = float(state.get("executed_value", target))
                tolerance = max(1e-9, abs(target) * 1e-9)
                if abs(target - current) <= tolerance or response_ratio >= 1.0:
                    executed = target
                else:
                    executed = target * response_ratio + current * (1.0 - response_ratio)
                    if abs(target - executed) <= tolerance:
                        executed = target
                state["executed_value"] = float(executed)
                state["target_value"] = float(target)
                state["last_cycle_token"] = cycle_token

            executed_value = float(state.get("executed_value", target))
            try:
                requested_executed_value = executed_value
                safe_executed = self._validated_set_command_item(
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "set_type": key[2],
                        "set_value": executed_value,
                    },
                    strict=True,
                )
                executed_value = float(safe_executed["set_value"])
                if not math.isclose(
                    executed_value,
                    requested_executed_value,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                ):
                    state["executed_value"] = executed_value
                    state["target_value"] = float(target)
                    self._append_runtime_log(
                        "控制安全边界",
                        "遥调逐步响应",
                        "越界中间值已限幅并继续执行",
                        [
                            (
                                f"逐步响应中间值 {_number_text(requested_executed_value)} "
                                f"已限幅为 {_number_text(executed_value)}。"
                            ),
                            (
                                f"安全目标 {_number_text(target)} 保持不变；后续周期继续按响应步长"
                                "向该目标调节。"
                            ),
                        ],
                        level="warn",
                    )
            except ValueError as exc:
                unsafe_executed = executed_value
                executed_value = float(target)
                state["executed_value"] = executed_value
                state["target_value"] = float(target)
                self._append_runtime_log(
                    "控制安全边界",
                    "遥调逐步响应",
                    "越界中间值已阻断",
                    [
                        str(exc),
                        f"逐步响应中间值 {_number_text(unsafe_executed)} 未送入潮流内核。",
                        f"已显式告警并直接采用已校验的安全目标 {_number_text(target)}。",
                    ],
                    level="warn",
                )
            self._write_boundary_set_value(stat_book, key, executed_value)
            if key in active_keys or self._set_value_from_book(yt_ctrl_book, key) is not None:
                self._write_boundary_set_value(yt_ctrl_book, key, executed_value)

            if key not in active_keys and math.isclose(executed_value, target, rel_tol=1e-9, abs_tol=1e-9):
                self._remote_adjustment_execution.pop(key, None)

        return stat_book, yt_ctrl_book

    def _cancel_command_input_items(self, payload: Mapping[str, Any]) -> List[Any]:
        collected: List[Any] = []
        for key in ("cancel_commands", "cancelCommands", "cancel_items", "cancelItems"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                collected.extend(value)
        for key in ("cancel_names", "cancelNames", "names"):
            value = payload.get(key)
            if isinstance(value, str):
                collected.extend(part.strip() for part in re.split(r"[,;\s]+", value) if part.strip())
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                collected.extend(str(item).strip() for item in value if str(item).strip())
        if not collected:
            for key in ("commands", "items", "controls"):
                value = payload.get(key)
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    collected.extend(value)
        if payload.get("cancel") is True or str(payload.get("action", payload.get("operation", ""))).strip().casefold() in {
            "cancel",
            "cancel_command",
            "cancel_commands",
            "取消",
            "取消指令",
        }:
            for key in ("commands", "items", "controls"):
                value = payload.get(key)
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    collected.extend(value)
            if payload.get("name"):
                collected.append(str(payload.get("name")))
        return collected

    def _cancel_command_key_from_item(self, item: Any) -> Optional[Tuple[Tuple[str, str, str, str], str]]:
        if isinstance(item, str):
            raw_item: Mapping[str, Any] = {"name": item}
        elif isinstance(item, Mapping):
            raw_item = item
        else:
            return None
        raw_name = str(raw_item.get("name", raw_item.get("command_name", raw_item.get("control_name", "")))).strip()
        definition = self._control_name_index().get(raw_name, {})
        dev_type = str(raw_item.get("dev_type", raw_item.get("type", definition.get("dev_type", "")))).strip()
        dev_name = str(raw_item.get("dev_name", raw_item.get("device", definition.get("dev_name", "")))).strip()
        command_kind = str(raw_item.get("command_kind", definition.get("command_kind", ""))).strip().lower()
        control_type = str(raw_item.get("control_type", raw_item.get("meas_type", definition.get("control_type", "")))).strip()
        set_type = str(raw_item.get("set_type", definition.get("set_type", ""))).strip()
        if (not dev_type or not dev_name or not (set_type or control_type)) and raw_name:
            parts = raw_name.split(".")
            if len(parts) >= 3:
                dev_type = dev_type or parts[0]
                dev_name = dev_name or ".".join(parts[1:-1])
                tail = parts[-1]
                if tail in ("run_stat", "status"):
                    control_type = control_type or tail
                else:
                    set_type = set_type or tail
        if not dev_type or not dev_name:
            return None
        if set_type or command_kind in ("remote_adjustment", "yt", "遥调"):
            if not set_type:
                return None
            name = raw_name or automatic_point_name(dev_type, dev_name, set_type)
            return ("remote_adjustment", dev_type, dev_name, set_type), name
        field_name = "status" if control_type == "status" else "run_stat"
        name = raw_name or automatic_point_name(dev_type, dev_name, field_name)
        return ("remote_control", dev_type, dev_name, field_name), name

    def _cancel_command_targets(self, payload: Mapping[str, Any]) -> Dict[Tuple[str, str, str, str], str]:
        targets: Dict[Tuple[str, str, str, str], str] = {}
        for item in self._cancel_command_input_items(payload):
            resolved = self._cancel_command_key_from_item(item)
            if resolved is None:
                continue
            key, name = resolved
            targets[key] = name
        return targets

    def _command_entry_control_keys(self, entry: Mapping[str, Any]) -> set[Tuple[str, str, str, str]]:
        keys: set[Tuple[str, str, str, str]] = set()
        normalized = entry.get("normalized", {})
        if not isinstance(normalized, Mapping):
            return keys
        run_items = normalized.get("run_status", [])
        if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
            for item in run_items:
                if not isinstance(item, Mapping):
                    continue
                dev_type = str(item.get("dev_type", ""))
                dev_name = str(item.get("dev_name", ""))
                if not dev_type or not dev_name:
                    continue
                if item.get("run_stat", "") != "":
                    keys.add(("remote_control", dev_type, dev_name, "run_stat"))
                if "status" in item:
                    keys.add(("remote_control", dev_type, dev_name, "status"))
        set_items = normalized.get("set_values", [])
        if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
            for item in set_items:
                if not isinstance(item, Mapping):
                    continue
                dev_type = str(item.get("dev_type", ""))
                dev_name = str(item.get("dev_name", ""))
                set_type = str(item.get("set_type", ""))
                if dev_type and dev_name and set_type:
                    keys.add(("remote_adjustment", dev_type, dev_name, set_type))
        return keys

    def _clear_automatic_commands_for_simulation_restart(
        self,
        *,
        reason: str = "simulation_restart",
    ) -> Dict[str, int]:
        cancelled_wall_time = _now_text()
        cancelled_simu_time = minute_to_time(self.clock.minute)
        cancelled_absolute_minute = float(self.clock.absolute_minute)
        cancelled_entries = 0
        cancelled_keys: set[Tuple[str, str, str, str]] = set()

        for entry in self.command_history:
            if not isinstance(entry, dict):
                continue
            if _command_origin(entry) != "automatic":
                continue
            if not self._command_entry_has_recorded_controls(entry):
                continue
            entry_keys = self._command_entry_control_keys(entry)
            if not entry_keys:
                continue
            entry["cancelled"] = True
            entry["cancelled_reason"] = reason
            entry["expires_at_absolute_minute"] = cancelled_absolute_minute
            entry["cancelled_names"] = sorted(
                f"{dev_type}.{dev_name}.{field_name}"
                for _kind, dev_type, dev_name, field_name in entry_keys
            )
            entry["cancelled_wall_time"] = cancelled_wall_time
            entry["cancelled_simu_time"] = cancelled_simu_time
            entry["cancelled_absolute_minute"] = cancelled_absolute_minute
            entry["cancelled_run_id"] = int(self.clock.run_id)
            cancelled_entries += 1
            cancelled_keys.update(entry_keys)

        self._force_control_targets_after_automatic_removal(cancelled_keys)

        return {
            "entries": cancelled_entries,
            "remote_controls": sum(1 for key in cancelled_keys if key[0] == "remote_control"),
            "remote_adjustments": sum(1 for key in cancelled_keys if key[0] == "remote_adjustment"),
        }

    def _delete_command_entry_controls(
        self,
        entry: Dict[str, Any],
        targets: set[Tuple[str, str, str, str]],
        *,
        deleted_names: Mapping[Tuple[str, str, str, str], str],
        deleted_wall_time: str,
        deleted_simu_time: str,
        deleted_absolute_minute: float,
    ) -> set[Tuple[str, str, str, str]]:
        normalized = entry.get("normalized")
        if not isinstance(normalized, dict):
            return set()

        removed: set[Tuple[str, str, str, str]] = set()
        retained_run: List[Dict[str, Any]] = []
        run_items = normalized.get("run_status", [])
        if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
            for raw_item in run_items:
                if not isinstance(raw_item, Mapping):
                    continue
                item = dict(raw_item)
                dev_type = str(item.get("dev_type", ""))
                dev_name = str(item.get("dev_name", ""))
                run_key = ("remote_control", dev_type, dev_name, "run_stat")
                status_key = ("remote_control", dev_type, dev_name, "status")
                if item.get("run_stat", "") != "" and run_key in targets:
                    item.pop("run_stat", None)
                    removed.add(run_key)
                if "status" in item and status_key in targets:
                    item.pop("status", None)
                    removed.add(status_key)
                if item.get("run_stat", "") != "" or "status" in item:
                    retained_run.append(item)

        retained_set: List[Dict[str, Any]] = []
        set_items = normalized.get("set_values", [])
        if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
            for raw_item in set_items:
                if not isinstance(raw_item, Mapping):
                    continue
                item = dict(raw_item)
                key = (
                    "remote_adjustment",
                    str(item.get("dev_type", "")),
                    str(item.get("dev_name", "")),
                    str(item.get("set_type", "")),
                )
                if key in targets:
                    removed.add(key)
                    continue
                retained_set.append(item)

        if not removed:
            return set()

        normalized["run_status"] = retained_run
        normalized["set_values"] = retained_set
        accepted = entry.get("accepted")
        if not isinstance(accepted, dict):
            accepted = {}
            entry["accepted"] = accepted
        accepted["run_status"] = len(retained_run)
        accepted["set_values"] = len(retained_set)

        remaining_controls = bool(retained_run or retained_set)
        if remaining_controls:
            entry["partially_cancelled"] = True
        else:
            entry["cancelled"] = True
            entry["expires_at_absolute_minute"] = deleted_absolute_minute

        existing_names = entry.get("cancelled_names", [])
        merged_names = {
            str(name)
            for name in existing_names
            if str(name).strip()
        } if isinstance(existing_names, Sequence) and not isinstance(existing_names, (str, bytes)) else set()
        merged_names.update(deleted_names[key] for key in removed if key in deleted_names)
        entry["cancelled_names"] = sorted(merged_names)
        entry["cancelled_wall_time"] = deleted_wall_time
        entry["cancelled_simu_time"] = deleted_simu_time
        entry["cancelled_absolute_minute"] = deleted_absolute_minute
        return removed

    def _cancel_payload_from_history_entry(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        payload = entry.get("payload") if isinstance(entry.get("payload"), Mapping) else {}
        cancel_payload = dict(payload)
        for key in (
            "cancel_commands",
            "cancelCommands",
            "cancel_items",
            "cancelItems",
            "cancel_names",
            "cancelNames",
            "names",
            "name",
            "action",
            "operation",
            "cancel",
            "command_origin",
            "commandOrigin",
            "origin",
        ):
            if key in entry and key not in cancel_payload:
                cancel_payload[key] = entry.get(key)
        if "source" not in cancel_payload and entry.get("source"):
            cancel_payload["source"] = entry.get("source")
        return cancel_payload

    def _repair_legacy_cancel_command_entries(self, history: List[Dict[str, Any]]) -> bool:
        changed = False
        for index, entry in enumerate(history):
            if not isinstance(entry, dict):
                continue
            cancel_payload = self._cancel_payload_from_history_entry(entry)
            if not _has_cancel_command_payload(cancel_payload):
                continue
            source = str(entry.get("source") or cancel_payload.get("source") or "")
            if not _is_trainee_command_source(source):
                continue
            targets = self._cancel_command_targets(cancel_payload)
            if not targets:
                continue
            origin_filter = _cancel_command_origin_filter(cancel_payload)
            cancel_minute = _to_float(
                entry.get("received_absolute_minute", entry.get("issued_absolute_minute", entry.get("expires_at_absolute_minute"))),
                None,
            )
            if cancel_minute is None:
                continue
            run_id = _to_float(entry.get("run_id"), None)
            cancelled_keys: set[Tuple[str, str, str, str]] = set()
            for previous in reversed(history[:index]):
                if not isinstance(previous, dict):
                    continue
                if not self._command_entry_can_be_cancelled(previous, cancel_minute, int(run_id) if run_id is not None else None):
                    continue
                if origin_filter != "all" and _command_origin(previous) != origin_filter:
                    continue
                matched = self._command_entry_control_keys(previous) & set(targets)
                if not matched:
                    continue
                previous["expires_at_absolute_minute"] = cancel_minute
                previous["cancelled"] = True
                previous["cancelled_names"] = [targets[key] for key in sorted(matched)]
                previous["cancelled_wall_time"] = entry.get("received_wall_time", entry.get("time", ""))
                previous["cancelled_simu_time"] = entry.get("received_simu_time", minute_to_time(cancel_minute))
                previous["cancelled_absolute_minute"] = cancel_minute
                cancelled_keys.update(matched)
                changed = True

            accepted = entry.get("accepted")
            if not isinstance(accepted, dict):
                accepted = {}
                entry["accepted"] = accepted
                changed = True
            cancelled_remote = sum(1 for key in cancelled_keys if key[0] == "remote_control")
            cancelled_adjustment = sum(1 for key in cancelled_keys if key[0] == "remote_adjustment")
            missing = max(0, len(targets) - len(cancelled_keys))
            for key, value in {
                "cancelled_run_status": cancelled_remote,
                "cancelled_set_values": cancelled_adjustment,
                "missing": missing,
            }.items():
                if accepted.get(key) != value:
                    accepted[key] = value
                    changed = True

            normalized = entry.get("normalized")
            if not isinstance(normalized, dict):
                normalized = {"run_status": [], "set_values": []}
                entry["normalized"] = normalized
                changed = True
            cancel_rows = [
                {"name": targets[key], "cancelled": key in cancelled_keys}
                for key in sorted(targets)
            ]
            if normalized.get("cancel_commands") != cancel_rows:
                normalized["cancel_commands"] = cancel_rows
                changed = True
        return changed

    def _command_history_identity_token(self) -> Tuple[int, int, int]:
        return (
            id(self.command_history),
            len(self.command_history),
            id(self.command_history[-1]) if self.command_history else 0,
        )

    @staticmethod
    def _strategy_generation_entry_metadata(entry: Mapping[str, Any]) -> Tuple[str, Any, bool]:
        strategy_id, generation, replace_generation = _strategy_generation_metadata(entry)
        payload = entry.get("payload")
        if isinstance(payload, Mapping):
            payload_strategy_id, payload_generation, payload_replace_generation = _strategy_generation_metadata(payload)
            strategy_id = strategy_id or payload_strategy_id
            if generation in (None, ""):
                generation = payload_generation
            replace_generation = replace_generation or payload_replace_generation
        return strategy_id, generation, replace_generation

    def _entry_belongs_in_strategy_generation_index(
        self,
        entry: Mapping[str, Any],
    ) -> Tuple[str, bool]:
        if entry.get("cancelled") or _command_origin(entry) != "automatic":
            return "", False
        strategy_id, _generation, replace_generation = (
            self._strategy_generation_entry_metadata(entry)
        )
        indexed = bool(
            strategy_id
            and (
                replace_generation
                or self._command_entry_has_accepted_controls(entry)
            )
        )
        return strategy_id, indexed

    def _rebuild_strategy_generation_index(self) -> None:
        indexed: Dict[str, List[Dict[str, Any]]] = {}
        for entry in self.command_history:
            if not isinstance(entry, dict):
                continue
            strategy_id, include = self._entry_belongs_in_strategy_generation_index(
                entry
            )
            if include:
                indexed.setdefault(strategy_id, []).append(entry)
        self._strategy_generation_entries = indexed
        self._strategy_generation_index_token = self._command_history_identity_token()

    def _ensure_strategy_generation_index(self) -> None:
        if self._strategy_generation_index_token != self._command_history_identity_token():
            self._rebuild_strategy_generation_index()

    def _append_command_history_entry(self, entry: Dict[str, Any]) -> None:
        self._ensure_strategy_generation_index()
        self.command_history.append(entry)
        strategy_id, include = self._entry_belongs_in_strategy_generation_index(entry)
        if include:
            self._strategy_generation_entries.setdefault(strategy_id, []).append(entry)
        self._strategy_generation_index_token = self._command_history_identity_token()

    def _matching_complete_strategy_snapshot(
        self,
        *,
        strategy_id: str,
        generation: Any,
        run_items: Sequence[Mapping[str, Any]],
        set_items: Sequence[Mapping[str, Any]],
        absolute_minute: float,
    ) -> Optional[Mapping[str, Any]]:
        self._ensure_strategy_generation_index()
        for entry in reversed(self._strategy_generation_entries.get(strategy_id, ())):
            _entry_strategy_id, entry_generation, replace_generation = (
                self._strategy_generation_entry_metadata(entry)
            )
            if (
                not replace_generation
                or not entry.get("snapshot_complete")
                or not _strategy_generation_matches(entry_generation, generation)
                or not self._command_entry_is_active(entry, absolute_minute)
            ):
                continue
            normalized = entry.get("normalized", {})
            if not isinstance(normalized, Mapping):
                continue
            if (
                list(normalized.get("run_status", [])) == list(run_items)
                and list(normalized.get("set_values", [])) == list(set_items)
            ):
                return entry
        return None

    def _mark_strategy_generations_cancelled(
        self,
        *,
        strategy_id: str,
        generation: Any = None,
        reason: str,
        cancelled_wall_time: str,
        cancelled_simu_time: str,
        cancelled_absolute_minute: float,
        require_generation_match: bool,
    ) -> Tuple[int, set[Tuple[str, str, str, str]]]:
        self._ensure_strategy_generation_index()
        cancelled_entries = 0
        cancelled_keys: set[Tuple[str, str, str, str]] = set()
        indexed_entries = list(self._strategy_generation_entries.get(strategy_id, ()))
        retained_entries: List[Dict[str, Any]] = []
        for entry in indexed_entries:
            entry_strategy_id, entry_generation, replace_generation = self._strategy_generation_entry_metadata(entry)
            if entry_strategy_id != strategy_id:
                retained_entries.append(entry)
                continue
            if require_generation_match and not _strategy_generation_matches(entry_generation, generation):
                retained_entries.append(entry)
                continue
            # A strategy snapshot can legitimately contain no control points.  Keep
            # those records cancellable, but do not reinterpret unrelated metadata
            # as a replaceable strategy generation.
            if not replace_generation and not self._command_entry_has_accepted_controls(entry):
                continue
            entry_keys = self._command_entry_control_keys(entry)
            entry["cancelled"] = True
            entry["cancelled_reason"] = reason
            entry["expires_at_absolute_minute"] = cancelled_absolute_minute
            entry["cancelled_names"] = sorted(
                f"{dev_type}.{dev_name}.{field_name}"
                for _kind, dev_type, dev_name, field_name in entry_keys
            )
            entry["cancelled_wall_time"] = cancelled_wall_time
            entry["cancelled_simu_time"] = cancelled_simu_time
            entry["cancelled_absolute_minute"] = cancelled_absolute_minute
            entry["cancelled_run_id"] = int(self.clock.run_id)
            cancelled_entries += 1
            cancelled_keys.update(entry_keys)
        if retained_entries:
            self._strategy_generation_entries[strategy_id] = retained_entries
        else:
            self._strategy_generation_entries.pop(strategy_id, None)
        self._strategy_generation_index_token = self._command_history_identity_token()
        return cancelled_entries, cancelled_keys

    def _cancel_strategy_generation(
        self,
        payload: Mapping[str, Any],
        source: str,
    ) -> Dict[str, Any]:
        strategy_id, generation, _replace_generation = _strategy_generation_metadata(payload)
        cancel_all_raw = payload.get(
            "cancel_all_generations",
            payload.get("cancelAllGenerations", False),
        )
        cancel_all_generations = bool(
            cancel_all_raw is True
            or str(cancel_all_raw or "").strip().casefold()
            in {"1", "true", "yes", "on"}
        )
        eligible_source = _is_trainee_command_source(source)
        current = float(self.clock.absolute_minute)
        received_wall_time = _now_text()
        received_simu_time = minute_to_time(self.clock.minute)
        reason = str(payload.get("reason", payload.get("cancelled_reason", "strategy_generation_revoked")) or "").strip()
        reason = reason or "strategy_generation_revoked"
        cancelled_entries = 0
        cancelled_keys: set[Tuple[str, str, str, str]] = set()

        if eligible_source and strategy_id and (
            cancel_all_generations or generation not in (None, "")
        ):
            cancelled_entries, cancelled_keys = self._mark_strategy_generations_cancelled(
                strategy_id=strategy_id,
                generation=generation,
                reason=reason,
                cancelled_wall_time=received_wall_time,
                cancelled_simu_time=received_simu_time,
                cancelled_absolute_minute=current,
                require_generation_match=not cancel_all_generations,
            )

        cancel_entry = {
            "time": received_wall_time,
            "received_wall_time": received_wall_time,
            "received_simu_time": received_simu_time,
            "received_absolute_minute": current,
            "run_id": int(self.clock.run_id),
            "source": source,
            "eligible_source": eligible_source,
            "manual_hold": False,
            "command_origin": "automatic",
            "issued_absolute_minute": current,
            "expires_at_absolute_minute": current,
            "valid_for_minutes": 0.0,
            "strategy_id": strategy_id,
            "generation": generation,
            "cancel_all_generations": cancel_all_generations,
            "cancelled_reason": reason,
            "accepted": {
                "run_status": 0,
                "set_values": 0,
                "cancelled_generations": cancelled_entries,
                "ignored": 0 if eligible_source else 1,
            },
            "normalized": {
                "run_status": [],
                "set_values": [],
                "cancel_strategy_generation": {
                    "strategy_id": strategy_id,
                    "generation": generation,
                    "cancel_all_generations": cancel_all_generations,
                    "cancelled": cancelled_entries > 0,
                },
            },
            "payload": json.loads(json.dumps(payload, ensure_ascii=False, default=str)),
        }
        self._append_command_history_entry(cancel_entry)
        self._prepare_command_history_for_persistence()
        self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
        self._write_command_history(prepared=True)
        self._append_runtime_log(
            "控制指令",
            "学员台 /api/student/commands",
            "策略代次已结束" if cancelled_entries else "无可结束策略代次",
            [
                f"来源 {source}",
                (
                    f"策略 {strategy_id or '--'}，全部代次"
                    if cancel_all_generations
                    else f"策略 {strategy_id or '--'}，代次 {generation if generation not in (None, '') else '--'}"
                ),
                (
                    f"结束代次 {cancelled_entries} 个，涉及控制点 {len(cancelled_keys)} 个，"
                    f"原因 {reason}"
                ),
                "已下发的自动遥控和遥调不随策略代次结束而撤销，继续锁存至仿真重置、归零重启或本仿真周期结束。",
            ],
            level="ok" if cancelled_entries else "warn",
        )
        return {
            "cancelled_generations": cancelled_entries,
            "cancelled_controls": len(cancelled_keys),
            "ignored": 0 if eligible_source else 1,
            "strategy_id": strategy_id,
            "generation": generation,
            "cancel_all_generations": cancel_all_generations,
        }

    def cancel_student_commands(self, payload: Mapping[str, Any], source: str = "") -> Dict[str, Any]:
        with self.lock:
            source = source or str(payload.get("source", ""))
            action = str(payload.get("action", payload.get("operation", "")) or "").strip().casefold()
            if action in {
                "cancel_strategy_generation",
                "cancel-strategy-generation",
                "revoke_strategy_generation",
                "revoke-strategy-generation",
            }:
                return self._cancel_strategy_generation(payload, source)
            eligible_source = _is_trainee_command_source(source)
            targets = self._cancel_command_targets(payload)
            origin_filter = _cancel_command_origin_filter(payload)
            current = float(self.clock.absolute_minute)
            received_wall_time = _now_text()
            received_simu_time = minute_to_time(self.clock.minute)
            cancelled_keys: set[Tuple[str, str, str, str]] = set()
            if eligible_source and targets:
                for entry in self.command_history:
                    if not isinstance(entry, dict):
                        continue
                    if not self._command_entry_can_be_cancelled(entry, current, int(self.clock.run_id)):
                        continue
                    if _command_origin(entry) == "automatic":
                        continue
                    if origin_filter != "all" and _command_origin(entry) != origin_filter:
                        continue
                    matched = self._command_entry_control_keys(entry) & set(targets)
                    if not matched:
                        continue
                    entry["expires_at_absolute_minute"] = current
                    entry["cancelled"] = True
                    entry["cancelled_names"] = [targets[key] for key in sorted(matched)]
                    entry["cancelled_wall_time"] = received_wall_time
                    entry["cancelled_simu_time"] = received_simu_time
                    entry["cancelled_absolute_minute"] = current
                    cancelled_keys.update(matched)

            cancelled_remote = sum(1 for key in cancelled_keys if key[0] == "remote_control")
            cancelled_adjustment = sum(1 for key in cancelled_keys if key[0] == "remote_adjustment")
            ignored = 0 if eligible_source else len(targets)
            missing = max(0, len(targets) - len(cancelled_keys)) if eligible_source else 0
            result_counts = {
                "remote_controls": cancelled_remote,
                "remote_adjustments": cancelled_adjustment,
                "missing": missing,
                "ignored": ignored,
                "command_origin": origin_filter,
            }
            cancel_entry = {
                "time": received_wall_time,
                "received_wall_time": received_wall_time,
                "received_simu_time": received_simu_time,
                "received_absolute_minute": current,
                "run_id": int(self.clock.run_id),
                "source": source,
                "command_origin": origin_filter,
                "eligible_source": eligible_source,
                "issued_absolute_minute": current,
                "expires_at_absolute_minute": current,
                "valid_for_minutes": 0.0,
                "accepted": {
                    "run_status": 0,
                    "set_values": 0,
                    "cancelled_run_status": cancelled_remote,
                    "cancelled_set_values": cancelled_adjustment,
                    "ignored": ignored,
                    "missing": missing,
                },
                "normalized": {
                    "run_status": [],
                    "set_values": [],
                    "cancel_commands": [
                        {"name": targets[key], "cancelled": key in cancelled_keys}
                        for key in sorted(targets)
                    ],
                },
                "payload": json.loads(json.dumps(payload, ensure_ascii=False, default=str)),
            }
            self._append_command_history_entry(cancel_entry)
            self._prepare_command_history_for_persistence()
            self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            self._write_command_history(prepared=True)
            time_payload = self._api_time_payload()
            cancelled_items = [
                {
                    "name": targets[key],
                    "cancelled": key in cancelled_keys,
                    **self._external_update_time_fields(time_payload),
                }
                for key in sorted(targets)
            ]
            detail = [
                f"来源 {source}",
                f"取消范围 {'人工指令' if origin_filter == 'manual' else '自动指令' if origin_filter == 'automatic' else '全部有效指令'}",
                f"取消遥控 {cancelled_remote} 条，取消遥调 {cancelled_adjustment} 条，缺失 {missing} 条，忽略 {ignored} 条",
            ]
            if targets:
                detail.append(
                    "取消对象 "
                    + "，".join(
                        f"{targets[key]}={'已取消' if key in cancelled_keys else '未匹配'}"
                        for key in list(sorted(targets))[:8]
                    )
                    + (" ..." if len(targets) > 8 else "")
                )
            self._append_runtime_log(
                "控制指令",
                "学员台 /api/student/commands",
                "取消成功" if cancelled_keys else "无可取消指令",
                detail,
                level="ok" if cancelled_keys else "warn",
            )
            return {
                **result_counts,
                "cancelled": result_counts,
                "cancelled_items": cancelled_items,
            }

    def delete_active_commands(self, payload: Mapping[str, Any], source: str = "simulator-ui") -> Dict[str, Any]:
        """Remove active command overlays while preserving control definitions and defaults."""
        with self.lock:
            source = source or "simulator-ui"
            eligible_source = _is_simulator_command_source(source)
            targets = self._cancel_command_targets(payload)
            current = float(self.clock.absolute_minute)
            received_wall_time = _now_text()
            received_simu_time = minute_to_time(self.clock.minute)
            deleted_keys: set[Tuple[str, str, str, str]] = set()

            if eligible_source and targets:
                target_keys = set(targets)
                for entry in self.command_history:
                    if not isinstance(entry, dict):
                        continue
                    if not self._command_entry_can_be_cancelled(entry, current, int(self.clock.run_id)):
                        continue
                    if _command_origin(entry) == "automatic":
                        continue
                    matched = self._command_entry_control_keys(entry) & target_keys
                    if not matched:
                        continue
                    deleted_keys.update(
                        self._delete_command_entry_controls(
                            entry,
                            matched,
                            deleted_names=targets,
                            deleted_wall_time=received_wall_time,
                            deleted_simu_time=received_simu_time,
                            deleted_absolute_minute=current,
                        )
                    )

            deleted_remote = sum(1 for key in deleted_keys if key[0] == "remote_control")
            deleted_adjustment = sum(1 for key in deleted_keys if key[0] == "remote_adjustment")
            ignored = 0 if eligible_source else len(targets)
            missing = max(0, len(targets) - len(deleted_keys)) if eligible_source else 0
            result_counts = {
                "remote_controls": deleted_remote,
                "remote_adjustments": deleted_adjustment,
                "missing": missing,
                "ignored": ignored,
            }
            delete_entry = {
                "time": received_wall_time,
                "received_wall_time": received_wall_time,
                "received_simu_time": received_simu_time,
                "received_absolute_minute": current,
                "run_id": int(self.clock.run_id),
                "source": source,
                "command_origin": "all",
                "eligible_source": eligible_source,
                "issued_absolute_minute": current,
                "expires_at_absolute_minute": current,
                "valid_for_minutes": 0.0,
                "accepted": {
                    "run_status": 0,
                    "set_values": 0,
                    "deleted_run_status": deleted_remote,
                    "deleted_set_values": deleted_adjustment,
                    "ignored": ignored,
                    "missing": missing,
                },
                "normalized": {
                    "run_status": [],
                    "set_values": [],
                    "delete_commands": [
                        {"name": targets[key], "deleted": key in deleted_keys}
                        for key in sorted(targets)
                    ],
                },
                "payload": self._compact_command_payload(
                    json.loads(json.dumps(payload, ensure_ascii=False, default=str))
                ),
            }
            self._append_command_history_entry(delete_entry)
            self._prepare_command_history_for_persistence()
            self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            self._write_command_history(prepared=True)
            time_payload = self._api_time_payload()
            deleted_items = [
                {
                    "name": targets[key],
                    "deleted": key in deleted_keys,
                    **self._external_update_time_fields(time_payload),
                }
                for key in sorted(targets)
            ]
            detail = [
                f"来源 {source}",
                "删除范围 当前控制点的全部有效指令覆盖，控制值恢复模拟台默认值",
                f"删除遥控 {deleted_remote} 条，删除遥调 {deleted_adjustment} 条，缺失 {missing} 条，忽略 {ignored} 条",
            ]
            if targets:
                detail.append(
                    "删除对象 "
                    + "，".join(
                        f"{targets[key]}={'已删除' if key in deleted_keys else '未匹配'}"
                        for key in list(sorted(targets))[:8]
                    )
                    + (" ..." if len(targets) > 8 else "")
                )
            self._append_runtime_log(
                "控制指令",
                "模拟台 /api/simulator/commands/delete",
                "删除成功" if deleted_keys else "无可删除指令",
                detail,
                level="ok" if deleted_keys else "warn",
            )
            return {
                **result_counts,
                "deleted": result_counts,
                "deleted_items": deleted_items,
            }

    def _merge_execution_runtime_stat_book(self, execution_book: EBook) -> None:
        incoming_storage = execution_book.data.get("StorageSoc") or execution_book.data.get("StorageStatus")
        if incoming_storage is not None:
            current_storage = _ensure_block(self.runtime_stat_book, "StorageSoc", STAT_HEADERS["StorageSoc"])
            current_storage.data = self._merge_runtime_storage_soc(
                current_storage.data,
                incoming_storage.data,
            )
        incoming_hydrogen = execution_book.data.get(simu_loop.HYDROGEN_STORAGE_STATE_BLOCK)
        if incoming_hydrogen is not None:
            current_hydrogen = _ensure_block(
                self.runtime_stat_book,
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK,
                simu_loop.HYDROGEN_STORAGE_STATE_HEADERS,
            )
            current_hydrogen.data = self._merge_runtime_hydrogen_storage_state(
                current_hydrogen.data,
                incoming_hydrogen.data,
            )

    def _make_config(
        self,
        period_seconds: Optional[float] = None,
        *,
        dev_stat_book: Optional[EBook] = None,
        yt_ctrl_book: Optional[EBook] = None,
    ) -> simu_loop.SimulationConfig:
        definition_snapshot = self.definition_snapshot
        if self._measurement_bindings_cache_revision != definition_snapshot.revision:
            self._measurement_bindings_cache = simu_loop.compile_measurement_bindings(
                definition_snapshot.measurement_rows,
                definition_snapshot.model_book,
            )
            self._measurement_bindings_cache_revision = definition_snapshot.revision
        return simu_loop.SimulationConfig(
            model_file=self.files["model"],
            meas_file=self.files["meas"],
            weather_file=self.files["weather"],
            dev_stat_file=self.files["stat"],
            dev_define_file=None,
            mode_file=None,
            yt_ctrl_file=self.files["yt_ctrl"],
            real_file=self.files["real"],
            scada_file=self.files["scada"],
            period_seconds=self.period_seconds if period_seconds is None else period_seconds,
            noise_std=self.noise_std,
            random_seed=self.random_seed,
            loop_count=1,
            log_file=None,
            step_mode=True,
            write_output_files=False,
            model_book=definition_snapshot.model_book,
            meas_before=list(definition_snapshot.measurement_before),
            meas_rows=[list(row) for row in definition_snapshot.measurement_rows],
            meas_after=list(definition_snapshot.measurement_after),
            weather_book=simu_loop._clone_ebook(self.weather_book),
            dev_stat_book=simu_loop._clone_ebook(dev_stat_book or self.runtime_stat_book),
            yt_ctrl_book=simu_loop._clone_ebook(yt_ctrl_book or self.yt_ctrl_book),
            dev_define_book=definition_snapshot.dev_define_book,
            mode_book=simu_loop._clone_ebook(self.mode_book) if self.mode_book is not None else None,
            measurement_bindings=self._measurement_bindings_cache,
            measurement_median_deviations=_measurement_median_deviation_map(
                definition_snapshot
            ),
        )

    def _execute_kernel(self, config: simu_loop.SimulationConfig) -> PowerFlowExecution:
        if self.kernel_runner is not None:
            return self.kernel_runner.run(config)
        started = time.perf_counter()
        result = self.kernel(config)
        elapsed = max(0.0, time.perf_counter() - started)
        return PowerFlowExecution(
            result=result,
            runtime_stat_book=config.dev_stat_book,
            worker_pid=os.getpid(),
            compute_seconds=elapsed,
            round_trip_seconds=elapsed,
            mode="embedded",
        )

    def _record_compute_execution(self, execution: PowerFlowExecution, status: str = "ok") -> None:
        self.latest_compute = {
            "mode": execution.mode,
            "http_pid": os.getpid(),
            "worker_pid": int(execution.worker_pid),
            "compute_ms": round(max(0.0, execution.compute_seconds) * 1000.0, 3),
            "round_trip_ms": round(max(0.0, execution.round_trip_seconds) * 1000.0, 3),
            "status": status,
            "resident_model": execution.mode == "embedded",
        }

    def _legacy_dev_define_file(self) -> Optional[Path]:
        path = self.sim_dir / "device.e"
        return path if path.exists() and path.is_file() else None

    def _append_runtime_log(
        self,
        log_type: str,
        target: str,
        result: str,
        detail: Any = "",
        *,
        level: str = "info",
        simu_time: Optional[str] = None,
    ) -> None:
        with self._runtime_log_persistence_lock:
            self._runtime_log_seq += 1
            entry = {
                "seq": self._runtime_log_seq,
                "wall_time": _now_text(),
                "simu_time": simu_time or minute_to_time(self.clock.minute),
                "type": log_type,
                "target": target,
                "result": result,
                "detail": _format_log_detail(detail),
                "level": level,
            }
            self.runtime_logs.append(entry)
            self.runtime_logs = self.runtime_logs[-RUNTIME_LOG_HISTORY_LIMIT:]
            self._append_runtime_log_journal(entry)

    def clear_runtime_logs(self) -> Dict[str, int]:
        with self._runtime_log_persistence_lock:
            count = len(self.runtime_logs)
            self.runtime_logs = []
            self._runtime_log_seq = 0
            self._write_runtime_logs()
        return {"cleared": count}

    def runtime_logs_delta(
        self,
        after_seq: int | float = 0,
        *,
        limit: int = 100,
        before_seq: Optional[int | float] = None,
        log_type: str = "",
    ) -> Dict[str, Any]:
        """Return runtime log rows incrementally.

        ``after_seq`` is used by live polling. ``before_seq`` is available for
        history paging without forcing snapshots to carry the log tail.
        """
        try:
            after = int(after_seq)
        except (TypeError, ValueError):
            after = 0
        try:
            capped_limit = max(1, min(500, int(limit)))
        except (TypeError, ValueError):
            capped_limit = 100
        try:
            before = int(before_seq) if before_seq is not None else None
        except (TypeError, ValueError):
            before = None

        rows = list(self.runtime_logs)
        if log_type and log_type != "all":
            rows = [row for row in rows if str(row.get("type", "")) == log_type]
        latest_seq = max((int(_to_float(row.get("seq"), 0) or 0) for row in self.runtime_logs), default=0)
        reset = bool(after > latest_seq and latest_seq >= 0)

        if before is not None:
            page_rows = [row for row in rows if int(_to_float(row.get("seq"), 0) or 0) < before]
            selected = page_rows[-capped_limit:]
        elif reset:
            selected = rows[-capped_limit:]
        else:
            selected = [row for row in rows if int(_to_float(row.get("seq"), 0) or 0) > after][:capped_limit]

        oldest_seq = min((int(_to_float(row.get("seq"), 0) or 0) for row in rows), default=0)
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "items": selected,
            "logs": selected,
            "latest_seq": latest_seq,
            "oldest_seq": oldest_seq,
            "total": len(rows),
            "has_more_before": bool(selected and oldest_seq < int(_to_float(selected[0].get("seq"), 0) or 0)),
            "reset": reset,
        }

    def _command_accept_detail(
        self,
        payload: Mapping[str, Any],
        source: str,
        accepted: Mapping[str, int],
        run_items: Sequence[Any],
        set_items: Sequence[Mapping[str, Any]],
        *,
        eligible_source: bool,
        issued_absolute_minute: float,
        expires_at_absolute_minute: Optional[float],
    ) -> List[str]:
        valid_text = (
            "无时间限制，人工指令保持有效直到取消"
            if expires_at_absolute_minute is None
            else (
                f"有效期 {format_number(max(0.0, expires_at_absolute_minute - issued_absolute_minute))} min，"
                f"截止累计分钟 {format_number(expires_at_absolute_minute)}"
            )
        )
        lines = [
            f"来源 {source}",
            (
                f"来源校验 {'学员台有效来源' if eligible_source else '非学员台来源，忽略为无效控制'}，"
                f"{valid_text}"
            ),
            f"接受投退 {accepted.get('run_status', 0)} 条，设值 {accepted.get('set_values', 0)} 条，忽略 {accepted.get('ignored', 0)} 条",
        ]
        run_preview = []
        for item in run_items:
            if not isinstance(item, Mapping):
                continue
            dev_type = str(item.get("dev_type", item.get("type", "")))
            dev_name = str(item.get("dev_name", item.get("name", "")))
            if not dev_type or not dev_name:
                continue
            if item.get("run_stat", "") != "" or "running" in item:
                run_stat = item.get("run_stat", item.get("running", item.get("value", "")))
                if isinstance(run_stat, bool):
                    run_stat = 1 if run_stat else 0
                run_preview.append(f"{dev_type}.{dev_name}.run_stat={_number_text(run_stat)}")
            if "status" in item:
                status = item.get("status")
                if isinstance(status, bool):
                    status = 1 if status else 0
                run_preview.append(f"{dev_type}.{dev_name}.status={_number_text(status)}")
        if run_preview:
            lines.append("投退明细 " + "，".join(run_preview[:6]) + (" ..." if len(run_preview) > 6 else ""))
        set_preview = [
            f"{item.get('dev_type', item.get('type', ''))}.{item.get('dev_name', item.get('name', ''))}.{item.get('set_type', '')}={_number_text(item.get('set_value', ''))}"
            for item in set_items[:8]
        ]
        set_preview = [text for text in set_preview if not text.startswith(".")]
        if set_preview:
            lines.append("设值明细 " + "，".join(set_preview) + (" ..." if len(set_items) > 8 else ""))
        strategy = payload.get("strategy")
        if isinstance(strategy, Mapping):
            strategy_lines = []
            for key, label in (
                ("name", "策略"),
                ("trigger", "触发"),
                ("load_kw", "负荷"),
                ("renewable_available_kw", "新能源可用"),
                ("renewable_used_kw", "计划消纳"),
                ("storage_kw", "储能"),
                ("diesel_residual_kw", "柴油缺额"),
                ("curtail_kw", "弃电"),
            ):
                if key in strategy:
                    strategy_lines.append(f"{label} {_number_text(strategy.get(key))}")
            if strategy_lines:
                lines.append("策略信息 " + "，".join(strategy_lines))
        if eligible_source and (accepted.get("run_status", 0) or accepted.get("set_values", 0)):
            lines.append("已登记为有效控制指令，并已同步到内存控制边界，等待下一轮潮流计算响应")
        else:
            lines.append("未写入有效控制边界，模拟台不会响应执行该控制指令")
        return lines

    def _command_response_detail(self, item: Mapping[str, Any], result: Mapping[str, Any]) -> List[str]:
        accepted = item.get("accepted", {})
        eligible_source = bool(item.get("eligible_source"))
        expires = _to_float(item.get("expires_at_absolute_minute"), None)
        valid_text = "无有效期" if expires is None else f"有效截止累计分钟 {format_number(expires)}"
        detail = [
            f"来源 {item.get('source', 'student')}，模拟台记录 {item.get('time', '--')}",
            (
                f"{'已响应' if eligible_source else '未响应'}投退 "
                f"{accepted.get('run_status', 0) if isinstance(accepted, Mapping) else 0} 条，设值 "
                f"{accepted.get('set_values', 0) if isinstance(accepted, Mapping) else 0} 条，{valid_text}"
            ),
            f"求解器 {result.get('solver_info', 'not-run')}，量测更新 {result.get('updated', 0)} 条，缺失 {result.get('missing', 0)} 条，叠加修正 {result.get('overlay_updates', 0)} 条",
        ]
        payload = item.get("payload", {})
        strategy = payload.get("strategy") if isinstance(payload, Mapping) else None
        if isinstance(strategy, Mapping):
            detail.append(
                "策略响应 "
                + "，".join(
                    [
                        f"负荷 {_number_text(strategy.get('load_kw', ''))} kW",
                        f"新能源可用 {_number_text(strategy.get('renewable_available_kw', ''))} kW",
                        f"计划消纳 {_number_text(strategy.get('renewable_used_kw', ''))} kW",
                        f"储能 {_number_text(strategy.get('storage_kw', ''))} kW",
                        f"柴油缺额 {_number_text(strategy.get('diesel_residual_kw', ''))} kW",
                    ]
                )
            )
        detail.append("本轮真值与 SCADA 内存快照已刷新")
        return detail

    def _collect_command_response_lines(self, result: Mapping[str, Any]) -> List[str]:
        if self._last_command_response_index >= len(self.command_history):
            active = self._active_control_command_entries(self.clock.absolute_minute)
            return [
                f"控制响应 本轮无新增学员台控制指令；当前有效控制指令 {len(active)} 条"
            ]
        pending_items = self.command_history[self._last_command_response_index :]
        effective_count = sum(1 for item in pending_items if item.get("eligible_source"))
        lines = [f"控制响应 本轮新增控制记录 {len(pending_items)} 条，其中学员台有效来源 {effective_count} 条"]
        for item in pending_items:
            lines.extend(f"控制响应 {line}" for line in self._command_response_detail(item, result))
        self._last_command_response_index = len(self.command_history)
        return lines

    def _curve_point_index(self, target_minute: float, period_minutes: float) -> int:
        points = self.curves.get("weather", [])
        if isinstance(points, Sequence) and not isinstance(points, (str, bytes)) and points:
            target = target_minute % period_minutes
            best_index = 0
            best_distance = period_minutes
            for idx, point in enumerate(points):
                if not isinstance(point, Mapping):
                    continue
                point_minute = float(_to_float(point.get("minute", idx), float(idx)) or 0.0) % period_minutes
                distance = abs(point_minute - target)
                distance = min(distance, period_minutes - distance)
                if distance < best_distance:
                    best_index = idx
                    best_distance = distance
            return best_index + 1
        step = max(1e-9, _to_float(self.curves.get("time_step_minutes"), 1.0) or 1.0)
        return int((target_minute % period_minutes) // step) + 1

    def _append_environment_load_log(
        self,
        minute: int | float,
        target_minute: float,
        period_minutes: float,
        row: Mapping[str, Any],
        load_details: Sequence[Tuple[str, float]],
        *,
        load_seen: bool,
    ) -> None:
        curve_mode = str(self.curves.get("mode", "day") or "day")
        load_total = row.get("load_kw", 0)
        load_parts = [f"{name}={_number_text(value)} kW" for name, value in load_details[:8]]
        if len(load_details) > 8:
            load_parts.append("...")
        detail = [
            f"曲线模式 {curve_mode}，目标分钟 {format_number(float(target_minute % period_minutes))}，点号 {self._curve_point_index(target_minute, period_minutes)}",
            (
                f"环境 风速 {_value_with_unit(row.get('wind_speed_mps', ''), 'm/s')}，"
                f"光照 {_value_with_unit(row.get('solar_irradiance_w_m2', ''), 'W/m2')}，"
                f"气温 {_value_with_unit(row.get('air_temp_c', ''), '℃')}，"
                f"气压 {_value_with_unit(row.get('air_pressure_hpa', ''), 'hPa')}，"
                f"湿度 {_value_with_unit(row.get('humidity_pct', ''), '%')}"
            ),
            f"负荷合计 {load_total} kW" + (f"；{ '，'.join(load_parts) }" if load_parts else "；未配置分项负荷，使用默认/总负荷"),
            "已更新内存天气边界，并作为本轮负荷、新能源限值计算输入",
        ]
        self._append_runtime_log(
            "环境/负荷",
            "weather / curves",
            "逐点读取",
            detail,
            level="ok" if load_seen else "warn",
            simu_time=minute_to_time(minute),
        )

    def _short_list(self, items: Sequence[str], limit: int = 24) -> str:
        if not items:
            return "无"
        visible = list(items[:limit])
        if len(items) > limit:
            visible.append(f"... 共 {len(items)} 项")
        return "，".join(visible)

    def _weather_boundary_values(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        book = self.weather_book
        block = book.data.get("Weather")
        if block is None or not block.data:
            return values
        row = block.data[0]
        return {header: row.get(header, "") for header in block.header_list}

    def _load_flow_input_model_book(
        self,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> Optional[EBook]:
        if self.latest_model_book is not None:
            return self.latest_model_book
        active_snapshot = definition_snapshot or self.definition_snapshot
        return active_snapshot.model_book

    def _renewable_limit_boundary_lines(
        self,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> List[str]:
        active_snapshot = definition_snapshot or self.definition_snapshot
        weather = simu_loop._weather_values_from_book(self.weather_book)
        model_book = self._load_flow_input_model_book(active_snapshot)
        if model_book is None:
            return ["新能源限值 未读取到潮流输入模型"]
        device_book = active_snapshot.dev_define_book
        if not device_book.data:
            return ["新能源限值 未读取到 model.e 内的设备能力参数"]

        wind_count = 0
        wind_available_total = 0.0
        wind_execute_total = 0.0
        wind_speed = weather.get("wind_speed_mps")
        if wind_speed is not None:
            for _table_name, row, define, _pos in simu_loop._renewable_target_rows(
                model_book,
                device_book,
                "wind_generator",
                ("ACGenerator", "DCGenerator"),
            ):
                rated = simu_loop._wind_rated_power_kw(row, define)
                rated_speed = simu_loop._safe_float((define or {}).get("rated_wind_speed", 15.0), 15.0) or 15.0
                cut_in = simu_loop._safe_float((define or {}).get("cut_in_speed", 5.0), 5.0) or 5.0
                cut_out = simu_loop._safe_float((define or {}).get("cut_out_speed", 30.0), 30.0) or 30.0
                available = simu_loop._available_with_bounds(
                    simu_loop.wind_available_power(float(wind_speed), rated, rated_speed, cut_in, cut_out),
                    define,
                )
                column = "p_ac_set" if "p_ac_set" in row else "p_set"
                wind_count += 1
                wind_available_total += float(available)
                wind_execute_total += abs(_to_float(row.get(column), 0.0) or 0.0)

        pv_count = 0
        pv_available_total = 0.0
        pv_execute_total = 0.0
        irradiance = weather.get("solar_irradiance_w_m2")
        if irradiance is not None:
            air_temp = float(weather.get("air_temp_c", 25.0))
            for _table_name, row, define, _pos in simu_loop._renewable_target_rows(
                model_book,
                device_book,
                "pv_generator",
                ("ACGenerator", "DCGenerator"),
            ):
                rated = simu_loop._pv_rated_power_kw(row, define)
                temp_coef = simu_loop._safe_float((define or {}).get("temp_coefficient", 0.0), 0.0) or 0.0
                ref_irrad = simu_loop._safe_float((define or {}).get("reference_irradiance", 1000.0), 1000.0) or 1000.0
                ref_temp = simu_loop._safe_float((define or {}).get("reference_temperature", 25.0), 25.0) or 25.0
                available = simu_loop._available_with_bounds(
                    simu_loop.pv_available_power(float(irradiance), air_temp, rated, temp_coef, ref_irrad, ref_temp),
                    define,
                )
                pv_count += 1
                pv_available_total += float(available)
                pv_execute_total += abs(_to_float(row.get("p_set"), 0.0) or 0.0)

        wind_summary = (
            "风电 风速未知，未执行最大可发限值计算"
            if wind_speed is None
            else f"风电 {wind_count} 台，可用 {format_number(wind_available_total)} kW，执行 {format_number(wind_execute_total)} kW"
        )
        pv_summary = (
            "光伏 辐照未知，未执行最大可发限值计算"
            if irradiance is None
            else f"光伏 {pv_count} 台，可用 {format_number(pv_available_total)} kW，执行 {format_number(pv_execute_total)} kW"
        )
        return [
            f"新能源限值 {wind_summary}；{pv_summary}"
        ]

    def _input_boundary_lines(
        self,
        minute: int | float,
        absolute_minute: int | float,
        clock_advance: int | float,
        period_seconds: float,
    ) -> List[str]:
        weather = self._weather_boundary_values()
        stat_book = self.runtime_stat_book
        run_rows = list(getattr(stat_book.data.get("RunStat"), "data", []))
        cb_rows = list(getattr(stat_book.data.get("CbOpenStat"), "data", []))
        set_rows = list(getattr(stat_book.data.get("SetValue"), "data", []))
        soc_block = stat_book.data.get("StorageSoc") or stat_book.data.get("StorageStatus")
        soc_rows = list(getattr(soc_block, "data", []))

        run_off = [row for row in run_rows if int(_to_float(row.get("run_stat"), 1) or 0) == 0]
        cb_zero = [row for row in cb_rows if int(_to_float(row.get("status"), 1) or 0) == 0]
        run_on = len(run_rows) - len(run_off)
        cb_one = len(cb_rows) - len(cb_zero)
        weather_text = (
            f"风速 {_value_with_unit(weather.get('wind_speed_mps', ''), 'm/s')}，"
            f"辐照 {_value_with_unit(weather.get('solar_irradiance_w_m2', ''), 'W/m2')}，"
            f"气温 {_value_with_unit(weather.get('air_temp_c', ''), '℃')}，"
            f"负荷 {_value_with_unit(weather.get('load_kw', ''), 'kW')}"
            if weather
            else "未读取到 Weather 块"
        )
        return [
            (
                f"仿真边界 时刻 {minute_to_time(minute)}，日内分钟 {format_number(minute)}，"
                f"累计分钟 {format_number(absolute_minute)}，本步推进 {format_number(clock_advance * 60.0)} s，"
                f"等效计算周期 {format_number(period_seconds)} s"
            ),
            f"输入边界 {weather_text}；投入设备 {run_on}/{len(run_rows)}，退出 {len(run_off)}，开关合位 {cb_one}/{len(cb_rows)}，分位 {len(cb_zero)}，设值 {len(set_rows)} 条，储能SOC {len(soc_rows)} 条",
            *self._renewable_limit_boundary_lines(),
        ]

    def _device_flow_lines(self, real_measurements: Sequence[Mapping[str, Any]]) -> List[str]:
        grouped: Dict[Tuple[str, str], List[str]] = {}
        for item in real_measurements:
            dev_type = str(item.get("dev_type", ""))
            dev_name = str(item.get("dev_name", ""))
            meas_type = str(item.get("meas_type", ""))
            if not dev_type or not dev_name or not meas_type:
                continue
            value = _number_text(item.get("value", ""))
            valid_flag = "" if int(_to_float(item.get("valid"), 1) or 0) == 1 else "(无效)"
            grouped.setdefault((dev_type, dev_name), []).append(f"{meas_type}={value}{valid_flag}")
        return [
            f"{dev_type}.{dev_name}: {', '.join(values)}"
            for (dev_type, dev_name), values in grouped.items()
        ]

    def _internal_power_converter_keys(
        self,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> set[Tuple[str, str]]:
        active_snapshot = definition_snapshot or self.definition_snapshot
        cached = self._internal_power_converter_keys_cache
        if cached is not None and cached[0] == active_snapshot.revision:
            return cached[1]

        model_book = active_snapshot.model_book
        boundary_keys = grid_converter_keys(model_book)
        keys: set[Tuple[str, str]] = set()
        for converter_type in ("ACDCConverter", "DCACConverter"):
            for row in getattr(model_book.data.get(converter_type), "data", []):
                name = str(row.get("name", "")).strip()
                if name and (converter_type, name) not in boundary_keys:
                    keys.add((converter_type, name))

        self._internal_power_converter_keys_cache = (active_snapshot.revision, keys)
        return keys

    def _canonical_power_device_name(self, category: str, dev_name: str) -> str:
        return dev_name

    def _preferred_power_value(self, category: str, values: Mapping[str, float]) -> Optional[float]:
        preferences = {
            "wind": ("P_AC", "P_DC", "P_GEN", "P", "P_FROM", "P_TO"),
            "pv": ("P_TO", "P_FROM", "P_GEN", "P", "P_DC", "P_AC"),
            "diesel": ("P_GEN", "P", "P_AC", "P_TO", "P_FROM"),
            "load": ("P_LOAD", "P", "P_AC", "P_TO", "P_FROM"),
            "storage": ("P", "P_GEN", "P_FROM", "P_TO"),
            "fuelCell": ("P", "P_GEN", "P_DC", "P_AC"),
            "electrolyzer": ("P", "P_LOAD", "P_AC", "P_DC"),
        }
        for meas_type in preferences.get(category, ("P",)):
            if meas_type in values:
                return values[meas_type]
        return None

    def _power_flow_connection_sides(
        self,
        resources: Sequence[Tuple[str, str, str]],
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> Dict[Tuple[str, str], str]:
        resource_key = tuple(sorted(set(resources)))
        definition_snapshot = definition_snapshot or self.definition_snapshot
        cached = self._power_flow_connection_sides_cache
        if cached is not None and cached[0] == definition_snapshot.revision and cached[1] == resource_key:
            return dict(cached[2])

        model_book = definition_snapshot.model_book

        def rows(block_name: str) -> Sequence[Mapping[str, Any]]:
            return getattr(model_book.data.get(block_name), "data", [])

        def node_id(value: Any) -> str:
            return str(value).strip() if value is not None else ""

        adjacency: Dict[
            Tuple[str, str],
            List[Tuple[Tuple[str, str], Tuple[int, int]]],
        ] = {}

        def add_edge(
            left: Tuple[str, str],
            right: Tuple[str, str],
            cost: Tuple[int, int],
        ) -> None:
            adjacency.setdefault(left, []).append((right, cost))
            adjacency.setdefault(right, []).append((left, cost))

        same_domain_edges = (
            ("ACBranch", "ac", False),
            ("ACLine", "ac", False),
            ("ACTransformer", "ac", False),
            ("ACZeroBranch", "ac", True),
            ("ACSwitch", "ac", True),
            ("ACBreak", "ac", True),
            ("ACACConverter", "ac", False),
            ("DCBranch", "dc", False),
            ("DCLine", "dc", False),
            ("DCZeroBranch", "dc", True),
            ("DCSwitch", "dc", True),
            ("DCBreak", "dc", True),
            ("DCDCConverter", "dc", False),
        )
        for block_name, domain, switchlike in same_domain_edges:
            for row in rows(block_name):
                left_id = node_id(row.get("i_node"))
                right_id = node_id(row.get("j_node"))
                if not left_id or not right_id:
                    continue
                add_edge(
                    (domain, left_id),
                    (domain, right_id),
                    (0, 0) if switchlike else (0, 1),
                )

        for converter_type in ("ACDCConverter", "DCACConverter"):
            for row in rows(converter_type):
                ac_node = node_id(row.get("ac_node"))
                dc_node = node_id(row.get("dc_node"))
                if ac_node and dc_node:
                    add_edge(("ac", ac_node), ("dc", dc_node), (1, 1))

        anchors: Dict[Tuple[str, str], set[str]] = {}
        for block_name, domain in (("ACRealBs", "ac"), ("DCRealBs", "dc")):
            for row in rows(block_name):
                terminal = node_id(row.get("node"))
                if terminal:
                    anchors.setdefault((domain, terminal), set()).add(domain)

        generators_by_name = {
            dev_type: {
                str(row.get("name", "")).strip(): row
                for row in rows(dev_type)
                if str(row.get("name", "")).strip()
            }
            for dev_type in ("ACGenerator", "DCGenerator")
        }
        sides: Dict[Tuple[str, str], str] = {}
        for _category, dev_type, dev_name in resource_key:
            native_side = "ac" if dev_type == "ACGenerator" else "dc" if dev_type == "DCGenerator" else ""
            generator = generators_by_name.get(dev_type, {}).get(dev_name)
            terminal = node_id(generator.get("node")) if generator is not None else ""
            if not native_side or not terminal:
                continue
            start = (native_side, terminal)
            queue: List[Tuple[int, int, Tuple[str, str]]] = [(0, 0, start)]
            best_node_cost: Dict[Tuple[str, str], Tuple[int, int]] = {start: (0, 0)}
            best_anchor_cost: Dict[str, Tuple[int, int]] = {}
            while queue:
                domain_changes, hop_count, node = heapq.heappop(queue)
                cost = (domain_changes, hop_count)
                if best_node_cost.get(node) != cost:
                    continue
                node_anchors = anchors.get(node, set())
                if node_anchors:
                    for anchor_side in node_anchors:
                        current = best_anchor_cost.get(anchor_side)
                        if current is None or cost < current:
                            best_anchor_cost[anchor_side] = cost
                    continue
                for neighbor, edge_cost in adjacency.get(node, []):
                    next_cost = (cost[0] + edge_cost[0], cost[1] + edge_cost[1])
                    current = best_node_cost.get(neighbor)
                    if current is not None and current <= next_cost:
                        continue
                    best_node_cost[neighbor] = next_cost
                    heapq.heappush(queue, (next_cost[0], next_cost[1], neighbor))

            ac_cost = best_anchor_cost.get("ac")
            dc_cost = best_anchor_cost.get("dc")
            if ac_cost is None and dc_cost is None:
                continue
            if dc_cost is None or (ac_cost is not None and ac_cost < dc_cost):
                sides[(dev_type, dev_name)] = "ac"
            elif ac_cost is None or dc_cost < ac_cost:
                sides[(dev_type, dev_name)] = "dc"

        self._power_flow_connection_sides_cache = (
            definition_snapshot.revision,
            resource_key,
            dict(sides),
        )
        return sides

    def _power_flow_device_profiles(
        self,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> List[Dict[str, Any]]:
        active_snapshot = definition_snapshot or self.definition_snapshot
        model_book = active_snapshot.model_book
        resources = structured_resources(model_book)
        run_stats, _cb_status, set_values, _soc_values = self._stat_maps()
        storage_protocol_keys = self._storage_runtime_protocol_keys()
        active_adjustment_values: Dict[Tuple[str, str, str], float] = {}
        for key in self._active_remote_adjustment_keys(float(self.clock.absolute_minute)):
            value = self._set_value_from_book(self.runtime_stat_book, key)
            if value is not None:
                active_adjustment_values[key] = value
        latest_states = {
            (str(item.get("dev_type", "")), str(item.get("dev_name", item.get("name", "")))): item
            for item in self.latest_device_states
            if str(item.get("dev_type", "")) and str(item.get("dev_name", item.get("name", "")))
        }

        def block_rows(name: str) -> List[Mapping[str, Any]]:
            return list(getattr(model_book.data.get(name), "data", []))

        effective_model_book = self.latest_model_book
        effective_rows: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        if effective_model_book is not None:
            for block_name, block in effective_model_book.data.items():
                for row in getattr(block, "data", []):
                    name = str(row.get("name", "")).strip()
                    if name:
                        effective_rows[(str(block_name), name)] = row

        model_rows_by_key: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        for block_name, block in model_book.data.items():
            for row in getattr(block, "data", []):
                name = str(row.get("name", "")).strip()
                if name:
                    model_rows_by_key[(str(block_name), name)] = row
        coupling_bindings = energy_coupling_control_bindings(model_book)
        coupling_electric_endpoints = {
            (
                str(binding.get("target_dev_type", "")),
                str(binding.get("target_dev_name", "")),
            )
            for bindings in coupling_bindings.values()
            for binding in bindings
            if str(binding.get("target_dev_type", ""))
            in {"ACGenerator", "DCGenerator", "ACLoad", "DCLoad"}
        }

        weather = simu_loop._weather_values_from_book(self.weather_book)

        def is_grid_forming(side: str, mode: str) -> bool:
            normalized = str(mode or "").strip().upper().replace("-", "").replace("_", "")
            if side == "dc":
                return normalized in {"V", "VDC", "VF", "PH", "SLACK", "SWING", "VOLTAGE"}
            return normalized in {"V", "VF", "PH", "SLACK", "SWING", "VOLTAGE"}

        def flow_group_key(category: str, side: str, mode: str = "") -> str:
            if category == "wind":
                return "dcWind" if side == "dc" else "acWind"
            if category == "pv":
                return "dcSolar" if side == "dc" else "acSolar"
            if category == "storage":
                suffix = "GridFormingStorage" if is_grid_forming(side, mode) else "GridFollowingStorage"
                return f"{side}{suffix[0].upper()}{suffix[1:]}"
            if category == "diesel":
                return "diesel"
            if category == "load":
                return "dcLoad" if side == "dc" else "acLoad"
            return ""

        def profile_state_keys(dev_type: str, name: str, category: str) -> List[Tuple[str, str]]:
            source_key = (dev_type, name)
            if category != "storage":
                return [source_key]
            return sorted(storage_protocol_keys.get(source_key, {source_key}))

        def first_power_setpoint(
            state_keys: Sequence[Tuple[str, str]],
            fields: Sequence[str],
        ) -> Optional[float]:
            for state_key in state_keys:
                values = set_values.get(state_key, {})
                for field in fields:
                    value = _to_float(values.get(field), None)
                    if value is not None:
                        return float(value)
            return None

        def first_active_power_setpoint(
            state_keys: Sequence[Tuple[str, str]],
            fields: Sequence[str],
        ) -> Optional[Tuple[str, float]]:
            for state_key in state_keys:
                for field in fields:
                    value = active_adjustment_values.get((state_key[0], state_key[1], field))
                    if value is not None:
                        return field, float(value)
            return None

        def endpoint_target_value(
            bindings: Sequence[Mapping[str, Any]],
            set_type: str,
        ) -> Optional[float]:
            binding = next(
                (
                    item
                    for item in bindings
                    if str(item.get("target_set_type", item.get("set_type", "")))
                    == set_type
                ),
                None,
            )
            if binding is None:
                return None
            target_key = (
                str(binding.get("target_dev_type", "")),
                str(binding.get("target_dev_name", "")),
            )
            active_value = active_adjustment_values.get(
                (target_key[0], target_key[1], set_type)
            )
            if active_value is not None:
                return float(active_value)
            effective_row = effective_rows.get(target_key)
            value = _to_float((effective_row or {}).get(set_type), None)
            if value is not None:
                return float(value)
            value = _to_float(set_values.get(target_key, {}).get(set_type), None)
            if value is not None:
                return float(value)
            value = _to_float(model_rows_by_key.get(target_key, {}).get(set_type), None)
            return float(value) if value is not None else None

        def target_power(
            dev_type: str,
            name: str,
            category: str,
            row: Mapping[str, Any],
            state_keys: Sequence[Tuple[str, str]],
        ) -> Optional[float]:
            effective_row = effective_rows.get((dev_type, name))
            if category == "load":
                target_row = effective_row or row
                pbase = _to_float(target_row.get("pbase"), 1.0)
                if pbase is None or pbase <= 0.0:
                    pbase = 1.0
                active_power = first_active_power_setpoint(state_keys, ("p_set", "pv0"))
                if active_power is not None:
                    multiplier = active_power[1]
                elif effective_row is not None:
                    multiplier = _to_float(target_row.get("pv0", target_row.get("p_set")), None)
                else:
                    multiplier = first_power_setpoint(state_keys, ("p_set", "pv0"))
                    if multiplier is None:
                        multiplier = _to_float(target_row.get("pv0", target_row.get("p_set")), None)
                return float(pbase) * float(multiplier) if multiplier is not None else None

            if category == "converter":
                target_row = effective_row or row
                power_field = ""
                value = None
                power_fields = converter_power_setpoint_fields(target_row)
                active_power = first_active_power_setpoint(state_keys, power_fields)
                if active_power is not None:
                    power_field, value = active_power
                elif effective_row is not None:
                    for field in power_fields:
                        value = _to_float(target_row.get(field), None)
                        if value is not None:
                            power_field = field
                            break
                else:
                    for state_key in state_keys:
                        values = set_values.get(state_key, {})
                        for field in power_fields:
                            value = _to_float(values.get(field), None)
                            if value is not None:
                                power_field = field
                                break
                        if value is not None:
                            break
                    if value is None:
                        for field in power_fields:
                            value = _to_float(target_row.get(field), None)
                            if value is not None:
                                power_field = field
                                break
                if value is None:
                    return None
                return converter_power_in_dc_to_ac_convention(
                    value,
                    AC_TO_DC,
                    power_field or "p_ac_set",
                )

            active_power = first_active_power_setpoint(
                state_keys,
                ("p_set", "p_ac_set", "p_dc_set"),
            )
            if active_power is not None:
                value = active_power[1]
            elif effective_row is not None:
                value = _to_float(
                    effective_row.get(
                        "p_set",
                        effective_row.get("p_ac_set", effective_row.get("p_dc_set")),
                    ),
                    None,
                )
            else:
                value = first_power_setpoint(state_keys, ("p_set", "p_ac_set", "p_dc_set"))
                if value is None:
                    value = _to_float(
                        row.get("p_set", row.get("p_ac_set", row.get("p_dc_set"))),
                        None,
                    )
            return float(value) if value is not None else None

        def renewable_max_available(
            category: str,
            row: Mapping[str, Any],
            parameter: Mapping[str, Any],
        ) -> Optional[float]:
            rated = _to_float(
                parameter.get(
                    "rated_power",
                    parameter.get(
                        "p_max",
                        row.get("rated_capacity", row.get("p_max")),
                    ),
                ),
                None,
            )
            if rated is None:
                return None
            return renewable_weather_available_kw(
                category,
                parameter,
                rated,
                wind_speed=_to_float(weather.get("wind_speed_mps"), None),
                solar_irradiance=_to_float(
                    weather.get("solar_irradiance_w_m2"),
                    None,
                ),
                air_temperature=_to_float(weather.get("air_temp_c"), None),
            )

        def operating_state(
            dev_type: str,
            name: str,
            category: str,
            row: Mapping[str, Any],
        ) -> Tuple[int, bool]:
            state_keys = profile_state_keys(dev_type, name, category)
            run_stat: Optional[int] = None
            for key in state_keys:
                if key in run_stats:
                    run_stat = int(_to_float(run_stats[key], 1) or 0)
                    break
            if run_stat is None:
                for key in state_keys:
                    if key in latest_states:
                        run_stat = int(_to_float(latest_states[key].get("run_stat"), 1) or 0)
                        break
            if run_stat is None:
                run_stat = int(_to_float(row.get("run_stat"), 1) or 0)
            dead_island = run_stat != 0 and any(
                bool(latest_states.get(key, {}).get("dead_island", False))
                for key in state_keys
            )
            return run_stat, dead_island

        profiles: List[Dict[str, Any]] = []
        seen_profiles: set[Tuple[str, str]] = set()
        classified_generators = [
            (
                resource.source_block,
                "ac" if resource.source_block == "ACGenerator" else "dc",
                resource.source,
                resource.technology,
                resource.parameter,
            )
            for resource in resources
        ]

        connection_sides = self._power_flow_connection_sides(
            [
                (category, dev_type, str(row.get("name", "")).strip())
                for dev_type, _native_side, row, category, _parameter in classified_generators
                if category in {"wind", "pv", "storage"}
            ],
            active_snapshot,
        )
        for dev_type, native_side, row, category, parameter in classified_generators:
            name = str(row.get("name", "")).strip()
            if (dev_type, name) in coupling_electric_endpoints:
                continue
            side = connection_sides.get((dev_type, name), native_side)
            canonical = self._canonical_power_device_name(category, name)
            mode = str(
                row.get("control_type")
                or row.get("ac_control_type")
                or row.get("dc_control_type")
                or row.get("mode", "")
            )
            group_key = flow_group_key(category, side, mode)
            identity = (group_key, canonical)
            if not group_key or identity in seen_profiles:
                continue
            seen_profiles.add(identity)
            run_stat, dead_island = operating_state(dev_type, name, category, row)
            state_keys = profile_state_keys(dev_type, name, category)
            capacity = None
            if category == "storage":
                capacity = _to_float(
                    parameter.get(
                        "energy_capacity",
                        parameter.get("rated_capacity", parameter.get("emva")),
                    ),
                    None,
                )
            profiles.append(
                {
                    "dev_type": dev_type,
                    "dev_name": name,
                    "canonical_name": canonical,
                    "category": category,
                    "side": side,
                    "control_mode": mode,
                    "group_key": group_key,
                    "run_stat": run_stat,
                    "dead_island": dead_island,
                    "online": run_stat != 0 and not dead_island,
                    "capacity": float(capacity) if capacity is not None and capacity > 0 else None,
                    "state_keys": state_keys,
                    "target_power": target_power(dev_type, name, category, row, state_keys),
                    "max_available_power": renewable_max_available(category, row, parameter),
                }
            )

        internal_converter_keys = self._internal_power_converter_keys(active_snapshot)
        for converter_type in ("ACDCConverter", "DCACConverter"):
            for row in block_rows(converter_type):
                name = str(row.get("name", "")).strip()
                converter_key = (converter_type, name)
                if not name or converter_key in internal_converter_keys:
                    continue
                identity = ("acdcConverter", f"{converter_type}\0{name}")
                if identity in seen_profiles:
                    continue
                seen_profiles.add(identity)
                run_stat, dead_island = operating_state(
                    converter_type,
                    name,
                    "converter",
                    row,
                )
                state_keys = [converter_key]
                profiles.append(
                    {
                        "dev_type": converter_type,
                        "dev_name": name,
                        "canonical_name": name,
                        "category": "converter",
                        "side": "bridge",
                        "control_mode": converter_control_mode(row),
                        "converter_direction": AC_TO_DC,
                        "group_key": "acdcConverter",
                        "run_stat": run_stat,
                        "dead_island": dead_island,
                        "online": run_stat != 0 and not dead_island,
                        "capacity": None,
                        "state_keys": state_keys,
                        "target_power": target_power(
                            converter_type,
                            name,
                            "converter",
                            row,
                            state_keys,
                        ),
                        "max_available_power": None,
                    }
                )

        hydrogen_conversion_specs = (
            ("Hydro2AcE", "fuelCell", "ac", "fuelCell"),
            ("Hydro2DcE", "fuelCell", "dc", "fuelCell"),
            ("AcE2Hydro", "electrolyzer", "ac", "electrolyzer"),
            ("DcE2Hydro", "electrolyzer", "dc", "electrolyzer"),
        )
        for dev_type, category, side, group_key in hydrogen_conversion_specs:
            for row in block_rows(dev_type):
                name = str(row.get("name", "")).strip()
                bindings = coupling_bindings.get((dev_type, name), ())
                if not name or not bindings:
                    continue
                identity = (group_key, f"{dev_type}\0{name}")
                if identity in seen_profiles:
                    continue
                seen_profiles.add(identity)
                run_stat, dead_island = operating_state(dev_type, name, category, row)
                profiles.append(
                    {
                        "dev_type": dev_type,
                        "dev_name": name,
                        "canonical_name": name,
                        "category": category,
                        "side": side,
                        "control_mode": str(row.get("control_type", "")),
                        "group_key": group_key,
                        "run_stat": run_stat,
                        "dead_island": dead_island,
                        "online": run_stat != 0 and not dead_island,
                        "capacity": None,
                        "state_keys": [(dev_type, name)],
                        "measurement_keys": [
                            (dev_type, name),
                            *[
                                (
                                    str(binding.get("target_dev_type", "")),
                                    str(binding.get("target_dev_name", "")),
                                )
                                for binding in bindings
                            ],
                        ],
                        "target_power": endpoint_target_value(bindings, "p_set"),
                        "target_gas_flow": endpoint_target_value(bindings, "flow_set"),
                        "max_available_power": None,
                    }
                )

        for row in block_rows("HydroStorage"):
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            identity = ("hydrogenStorage", name)
            if identity in seen_profiles:
                continue
            seen_profiles.add(identity)
            run_stat, dead_island = operating_state(
                "HydroStorage",
                name,
                "hydrogenStorage",
                row,
            )
            capacity = _first_number(
                row,
                ("rated_capacity", "capacity", "rated_gas_capacity", "gas_capacity"),
            )
            profiles.append(
                {
                    "dev_type": "HydroStorage",
                    "dev_name": name,
                    "canonical_name": name,
                    "category": "hydrogenStorage",
                    "side": "hydrogen",
                    "control_mode": "",
                    "group_key": "hydrogenStorage",
                    "run_stat": run_stat,
                    "dead_island": dead_island,
                    "online": run_stat != 0 and not dead_island,
                    "capacity": (
                        float(capacity)
                        if capacity is not None and capacity > 0.0
                        else None
                    ),
                    "state_keys": [("HydroStorage", name)],
                    "target_power": None,
                    "target_gas_flow": None,
                    "max_available_power": None,
                }
            )

        for dev_type, side in (("ACLoad", "ac"), ("DCLoad", "dc")):
            for row in block_rows(dev_type):
                name = str(row.get("name", "")).strip()
                if not name or (dev_type, name) in coupling_electric_endpoints:
                    continue
                group_key = flow_group_key("load", side)
                identity = (group_key, name)
                if identity in seen_profiles:
                    continue
                seen_profiles.add(identity)
                run_stat, dead_island = operating_state(dev_type, name, "load", row)
                state_keys = [(dev_type, name)]
                profiles.append(
                    {
                        "dev_type": dev_type,
                        "dev_name": name,
                        "canonical_name": name,
                        "category": "load",
                        "side": side,
                        "control_mode": "",
                        "group_key": group_key,
                        "run_stat": run_stat,
                        "dead_island": dead_island,
                        "online": run_stat != 0 and not dead_island,
                        "capacity": None,
                        "state_keys": state_keys,
                        "target_power": target_power(dev_type, name, "load", row, state_keys),
                        "max_available_power": None,
                    }
                )
        return profiles

    def _power_flow_profile_indexes(
        self,
        profiles: Sequence[Mapping[str, Any]],
    ) -> Tuple[
        Dict[Tuple[str, str], Mapping[str, Any]],
        Dict[Tuple[str, str], Mapping[str, Any]],
        Dict[Tuple[str, str, str], Mapping[str, Any]],
    ]:
        by_measurement: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        by_category_name: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        by_power_key: Dict[Tuple[str, str, str], Mapping[str, Any]] = {}
        for profile in profiles:
            dev_type = str(profile.get("dev_type", ""))
            dev_name = str(profile.get("dev_name", ""))
            category = str(profile.get("category", ""))
            canonical = str(profile.get("canonical_name", dev_name))
            group_key = str(profile.get("group_key", ""))
            by_measurement[(dev_type, dev_name)] = profile
            for measurement_type, measurement_name in profile.get(
                "measurement_keys",
                (),
            ):
                by_measurement.setdefault(
                    (str(measurement_type), str(measurement_name)),
                    profile,
                )
            by_category_name[(category, canonical)] = profile
            by_power_key[(category, canonical, group_key)] = profile
            if category == "storage":
                for alias_type, alias_name in profile.get("state_keys", []):
                    by_measurement.setdefault((str(alias_type), str(alias_name)), profile)
        return by_measurement, by_category_name, by_power_key

    def _flow_group_status(self, group: Mapping[str, Any]) -> Tuple[str, str]:
        total_count = int(group.get("totalCount", 0) or 0)
        online_count = int(group.get("onlineCount", 0) or 0)
        retired_count = int(group.get("retiredCount", 0) or 0)
        dead_count = int(group.get("deadIslandCount", 0) or 0)
        if total_count and online_count == 0:
            if dead_count:
                return "deadIsland", "idle"
            if retired_count:
                return "retired", "idle"
        category = str(group.get("category", ""))
        if category == "hydrogenStorage":
            gas_flow = group.get("gasFlow")
            if gas_flow is None:
                return "unmeasured", "idle"
            gas_flow_value = float(gas_flow)
            if abs(gas_flow_value) <= 1e-9:
                return "idle", "idle"
            return (
                ("releasingHydrogen", "fromTank")
                if gas_flow_value > 0.0
                else ("storingHydrogen", "toTank")
            )
        power = group.get("power")
        if power is None:
            return "unmeasured", "idle"
        power_value = float(power)
        if abs(power_value) <= 1e-9:
            return "idle", "idle"
        if category == "storage":
            return ("discharge", "toBus") if power_value > 0 else ("charge", "fromBus")
        if category in {"load", "electrolyzer"}:
            return ("consumption", "fromBus") if power_value > 0 else ("generation", "toBus")
        if category == "converter":
            return ("dcToAc", "toAc") if power_value > 0 else ("acToDc", "toDc")
        return ("generation", "toBus") if power_value > 0 else ("absorption", "fromBus")

    def _power_flow_summary(self, realtime_measurements: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        definition_snapshot = self.definition_snapshot
        internal_converter_keys = self._internal_power_converter_keys(definition_snapshot)
        profiles = self._power_flow_device_profiles(definition_snapshot)
        (
            profiles_by_measurement,
            profiles_by_category_name,
            profiles_by_power_key,
        ) = self._power_flow_profile_indexes(profiles)
        power_by_device: Dict[Tuple[str, str, str], Dict[str, float]] = {}
        soc_by_storage: Dict[str, float] = {}
        measured_converter_power_by_key: Dict[Tuple[str, str], float] = {}
        converter_dc_terminal_power_by_key: Dict[Tuple[str, str], float] = {}
        converter_power_values_by_key: Dict[Tuple[str, str], Dict[str, float]] = {}
        hydrogen_measurements_by_device: Dict[
            Tuple[str, str, str],
            Dict[str, float],
        ] = {}

        for item in realtime_measurements:
            if int(_to_float(item.get("valid"), 1) or 0) != 1:
                continue
            dev_type = str(item.get("dev_type", ""))
            dev_name = str(item.get("dev_name", ""))
            meas_type = str(item.get("meas_type", "")).upper()
            value = _to_float(item.get("value"), None)
            if not dev_type or not dev_name or meas_type == "" or value is None:
                continue
            profile = profiles_by_measurement.get((dev_type, dev_name))
            if (
                profile is not None
                and profile.get("category") == "converter"
                and meas_type in {"P_AC", "P_DC", "P"}
            ):
                converter_key = (dev_type, dev_name)
                if profile is not None and converter_key not in internal_converter_keys:
                    converter_power_values_by_key.setdefault(converter_key, {})[
                        meas_type
                    ] = value
                continue
            category = str(profile.get("category", "")) if profile else ""
            if category == "storage" and meas_type == "SOC":
                canonical_name = str(profile.get("canonical_name", dev_name))
                soc_by_storage[canonical_name] = value
                continue
            if category in {"fuelCell", "electrolyzer", "hydrogenStorage"}:
                canonical_name = str(profile.get("canonical_name", dev_name))
                group_key = str(profile.get("group_key", ""))
                hydrogen_measurements_by_device.setdefault(
                    (category, canonical_name, group_key),
                    {},
                )[meas_type] = value
                if category == "hydrogenStorage" or not meas_type.startswith("P"):
                    continue
            if not meas_type.startswith("P"):
                continue
            if not category:
                continue
            canonical_name = str(profile.get("canonical_name", dev_name))
            group_key = str(profile.get("group_key", "")) if profile else ""
            device_key = (category, canonical_name, group_key)
            power_by_device.setdefault(device_key, {})[meas_type] = value

        for converter_key, values in converter_power_values_by_key.items():
            raw_power_item = next(
                ((key, values[key]) for key in ("P_AC", "P_DC", "P") if key in values),
                None,
            )
            if raw_power_item is None:
                continue
            raw_power_type, raw_power = raw_power_item
            measured_converter_power_by_key[converter_key] = raw_power
            profile = profiles_by_measurement.get(converter_key)
            direction = str(profile.get("converter_direction", "")) if profile else ""
            if direction:
                converter_dc_terminal_power_by_key[converter_key] = (
                    converter_power_in_dc_to_ac_convention(
                        raw_power,
                        direction,
                        raw_power_type,
                    )
                )

        totals = {"wind": 0.0, "pv": 0.0, "diesel": 0.0, "load": 0.0}
        counts = {
            "wind": 0,
            "pv": 0,
            "diesel": 0,
            "load": 0,
            "storage": 0,
            "fuelCell": 0,
            "electrolyzer": 0,
            "hydrogenStorage": 0,
            "greenPowerConverter": len(measured_converter_power_by_key),
        }
        storage_generation = 0.0
        storage_charge = 0.0
        storage_total = 0.0
        fuel_cell_generation = 0.0
        electrolyzer_consumption = 0.0
        measured_group_devices: Dict[str, set[Tuple[str, str]]] = {}
        group_power_totals: Dict[str, float] = {}
        for (category, dev_name, group_key), values in power_by_device.items():
            power = self._preferred_power_value(category, values)
            if power is None:
                continue
            profile = profiles_by_power_key.get((category, dev_name, group_key))
            if profile is not None and not bool(profile.get("online", False)):
                continue
            counts[category] += 1
            if category == "storage":
                storage_total += power
                if power >= 0.0:
                    storage_generation += power
                else:
                    storage_charge += -power
            elif category == "fuelCell":
                fuel_cell_generation += power
            elif category == "electrolyzer":
                electrolyzer_consumption += power
            else:
                totals[category] += power

            if profile is not None:
                if group_key:
                    group_power_totals[group_key] = group_power_totals.get(group_key, 0.0) + power
                    measured_group_devices.setdefault(group_key, set()).add(
                        (
                            str(profile.get("dev_type", "")),
                            str(profile.get("dev_name", dev_name)),
                        )
                    )

        for converter_key, power in converter_dc_terminal_power_by_key.items():
            profile = profiles_by_measurement.get(converter_key)
            if profile is None or not bool(profile.get("online", False)):
                continue
            group_key = str(profile.get("group_key", ""))
            if not group_key:
                continue
            group_power_totals[group_key] = group_power_totals.get(group_key, 0.0) + power
            measured_group_devices.setdefault(group_key, set()).add(converter_key)

        soc_values = [value * 100.0 if abs(value) <= 2.0 else value for value in soc_by_storage.values()]
        soc_average = sum(soc_values) / len(soc_values) if soc_values else None
        soc_total = sum(soc_by_storage.values()) if soc_values else None
        has_power = any(
            counts[key]
            for key in (
                "wind",
                "pv",
                "diesel",
                "load",
                "storage",
                "fuelCell",
                "electrolyzer",
            )
        )
        load_total = totals["load"] + electrolyzer_consumption
        generation_total = (
            totals["wind"]
            + totals["pv"]
            + totals["diesel"]
            + storage_generation
            + fuel_cell_generation
        )
        consumption_total = load_total + storage_charge
        power_difference = generation_total - consumption_total
        flow_groups: Dict[str, Dict[str, Any]] = {}
        group_target_totals: Dict[str, float] = {}
        group_target_counts: Dict[str, int] = {}
        group_target_gas_flow_totals: Dict[str, float] = {}
        group_target_gas_flow_counts: Dict[str, int] = {}
        group_available_totals: Dict[str, float] = {}
        group_available_counts: Dict[str, int] = {}
        for profile in profiles:
            group_key = str(profile.get("group_key", ""))
            if not group_key:
                continue
            group = flow_groups.setdefault(
                group_key,
                {
                    "category": profile.get("category", ""),
                    "side": profile.get("side", ""),
                    "powerConvention": (
                        "P_DC"
                        if profile.get("category") == "converter"
                        else ""
                    ),
                    "controlMode": (
                        str(profile.get("control_mode", "")).strip().upper()
                        if profile.get("category") in {"fuelCell", "electrolyzer"}
                        else "gridForming"
                        if "GridForming" in group_key
                        else "gridFollowing"
                        if "GridFollowing" in group_key
                        else ""
                    ),
                    "power": None,
                    "targetPower": None,
                    "maxAvailablePower": None,
                    "gasFlow": None,
                    "targetGasFlow": None,
                    "gasPressure": None,
                    "gasQuantity": None,
                    "soc": None,
                    "totalCount": 0,
                    "onlineCount": 0,
                    "retiredCount": 0,
                    "deadIslandCount": 0,
                    "measuredCount": 0,
                },
            )
            if profile.get("category") in {"fuelCell", "electrolyzer"}:
                profile_mode = str(profile.get("control_mode", "")).strip().upper()
                group_mode = str(group.get("controlMode", "")).strip().upper()
                if profile_mode and group_mode and profile_mode != group_mode:
                    group["controlMode"] = "MIXED"
                elif profile_mode:
                    group["controlMode"] = profile_mode
            group["totalCount"] += 1
            if int(profile.get("run_stat", 1) or 0) == 0:
                group["retiredCount"] += 1
            elif bool(profile.get("dead_island", False)):
                group["deadIslandCount"] += 1
            else:
                group["onlineCount"] += 1
                target = _to_float(profile.get("target_power"), None)
                if target is not None:
                    group_target_totals[group_key] = group_target_totals.get(group_key, 0.0) + target
                    group_target_counts[group_key] = group_target_counts.get(group_key, 0) + 1
                target_gas_flow = _to_float(profile.get("target_gas_flow"), None)
                if target_gas_flow is not None:
                    group_target_gas_flow_totals[group_key] = (
                        group_target_gas_flow_totals.get(group_key, 0.0)
                        + target_gas_flow
                    )
                    group_target_gas_flow_counts[group_key] = (
                        group_target_gas_flow_counts.get(group_key, 0) + 1
                    )
                available = _to_float(profile.get("max_available_power"), None)
                if available is not None:
                    group_available_totals[group_key] = group_available_totals.get(group_key, 0.0) + available
                    group_available_counts[group_key] = group_available_counts.get(group_key, 0) + 1

        hydrogen_metric_values: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
        hydrogen_measured_devices: Dict[str, set[Tuple[str, str]]] = {}
        for (category, dev_name, group_key), values in hydrogen_measurements_by_device.items():
            profile = profiles_by_power_key.get((category, dev_name, group_key))
            if profile is None or not bool(profile.get("online", False)):
                continue
            device_key = (
                str(profile.get("dev_type", "")),
                str(profile.get("dev_name", dev_name)),
            )
            measured_group_devices.setdefault(group_key, set()).add(device_key)
            hydrogen_measured_devices.setdefault(category, set()).add(device_key)
            metrics = hydrogen_metric_values.setdefault(group_key, {})
            capacity = _to_float(profile.get("capacity"), None)
            if "FLOW" in values:
                metrics.setdefault("gasFlow", []).append((float(values["FLOW"]), 1.0))
            if category == "hydrogenStorage":
                pressure = values.get("PRESSURE")
                if pressure is not None:
                    metrics.setdefault("gasPressure", []).append((float(pressure), 1.0))
                if "GAS_QUANTITY" in values:
                    gas_quantity = float(values["GAS_QUANTITY"])
                    metrics.setdefault("gasQuantity", []).append(
                        (gas_quantity, 1.0)
                    )
                    if capacity is not None and capacity > 0.0:
                        metrics.setdefault("soc", []).append(
                            (gas_quantity / capacity * 100.0, float(capacity))
                        )
                elif "SOC" in values:
                    raw_soc = float(values["SOC"])
                    soc_percent = raw_soc * 100.0 if abs(raw_soc) <= 2.0 else raw_soc
                    metrics.setdefault("soc", []).append(
                        (soc_percent, max(1e-9, float(capacity or 1.0)))
                    )

        counts["hydrogenStorage"] = len(
            hydrogen_measured_devices.get("hydrogenStorage", set())
        )
        for group_key, metric_values in hydrogen_metric_values.items():
            group = flow_groups.get(group_key)
            if group is None:
                continue
            for metric_name, values in metric_values.items():
                if not values:
                    continue
                if metric_name in {"gasPressure", "soc"}:
                    total_weight = sum(weight for _value, weight in values)
                    group[metric_name] = (
                        sum(value * weight for value, weight in values) / total_weight
                        if total_weight > 0.0
                        else None
                    )
                else:
                    group[metric_name] = sum(value for value, _weight in values)

        for group_key, group in flow_groups.items():
            online_count = int(group.get("onlineCount", 0) or 0)
            if online_count == 0:
                group["targetPower"] = 0.0
                if str(group.get("category", "")) in {"wind", "pv"}:
                    group["maxAvailablePower"] = 0.0
            elif group_target_counts.get(group_key, 0) == online_count:
                group["targetPower"] = group_target_totals.get(group_key, 0.0)
            if online_count == 0:
                group["targetGasFlow"] = 0.0
            elif group_target_gas_flow_counts.get(group_key, 0) == online_count:
                group["targetGasFlow"] = group_target_gas_flow_totals.get(
                    group_key,
                    0.0,
                )
            if (
                str(group.get("category", "")) in {"wind", "pv"}
                and group_available_counts.get(group_key, 0) == online_count
            ):
                group["maxAvailablePower"] = group_available_totals.get(group_key, 0.0)
            measured_devices = measured_group_devices.get(group_key, set())
            group["measuredCount"] = len(measured_devices)
            if measured_devices:
                group["power"] = group_power_totals.get(group_key, 0.0)
            elif int(group.get("onlineCount", 0) or 0) == 0:
                group["power"] = 0.0

        storage_soc_groups: Dict[str, List[Tuple[float, float]]] = {}
        for storage_name, raw_soc in soc_by_storage.items():
            profile = profiles_by_category_name.get(("storage", storage_name))
            if profile is None:
                continue
            group_key = str(profile.get("group_key", ""))
            if not group_key:
                continue
            soc_percent = raw_soc * 100.0 if abs(raw_soc) <= 2.0 else raw_soc
            weight = _to_float(profile.get("capacity"), 1.0) or 1.0
            storage_soc_groups.setdefault(group_key, []).append((soc_percent, max(1e-9, float(weight))))
        for group_key, values in storage_soc_groups.items():
            total_weight = sum(weight for _soc, weight in values)
            if total_weight > 0 and group_key in flow_groups:
                flow_groups[group_key]["soc"] = sum(soc * weight for soc, weight in values) / total_weight

        for group in flow_groups.values():
            status, direction = self._flow_group_status(group)
            group["status"] = status
            group["flowDirection"] = direction

        def green_metric_group_power(group_key: str) -> Optional[float]:
            group = flow_groups.get(group_key)
            if group is None:
                return 0.0
            return _to_float(group.get("power"), None)

        dc_load_power = green_metric_group_power("dcLoad")
        ac_load_power = green_metric_group_power("acLoad")
        electrolyzer_power = green_metric_group_power("electrolyzer")
        diesel_power = green_metric_group_power("diesel")
        if any(
            value is None
            for value in (
                dc_load_power,
                ac_load_power,
                electrolyzer_power,
                diesel_power,
            )
        ):
            green_power = None
            green_power_share = None
        else:
            green_load_power = (
                float(dc_load_power)
                + float(ac_load_power)
                + float(electrolyzer_power)
            )
            green_power = green_load_power - float(diesel_power)
            green_power_share = (
                green_power / green_load_power * 100.0
                if abs(green_load_power) > 1e-9
                else None
            )
        return {
            "wind": totals["wind"] if counts["wind"] else None,
            "solar": totals["pv"] if counts["pv"] else None,
            "diesel": totals["diesel"] if counts["diesel"] else None,
            "load": (
                load_total
                if counts["load"] or counts["electrolyzer"]
                else None
            ),
            "storage": storage_total if counts["storage"] else None,
            "storageDischarge": storage_generation if counts["storage"] else None,
            "storageCharge": storage_charge if counts["storage"] else None,
            "greenPower": green_power,
            "greenPowerShare": green_power_share,
            "soc": soc_average,
            "socTotal": soc_total if soc_values else None,
            "generation": generation_total if has_power else None,
            "consumption": consumption_total if has_power else None,
            "balance": power_difference if has_power else None,
            "flowGroups": flow_groups,
            "counts": {
                "wind": counts["wind"],
                "solar": counts["pv"],
                "diesel": counts["diesel"],
                "load": counts["load"],
                "storage": counts["storage"],
                "fuelCell": counts["fuelCell"],
                "electrolyzer": counts["electrolyzer"],
                "hydrogenStorage": counts["hydrogenStorage"],
                "greenPowerConverter": counts["greenPowerConverter"],
                "soc": len(soc_values),
            },
        }

    def _latest_power_summary(
        self,
        measurements: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> Dict[str, Any]:
        cache_key: Optional[Tuple[Any, ...]] = None
        if measurements is self.latest_measurements:
            cache_key = (
                id(measurements),
                self.definition_snapshot.revision,
                self.clock.step_count,
                float(self.clock.absolute_minute),
                id(self.runtime_stat_book),
                id(self.latest_model_book),
                id(self.latest_device_states),
                id(self.weather_book),
            )
            if (
                cache_key == self._latest_power_summary_cache_key
                and self._latest_power_summary_cache_value is not None
            ):
                return self._latest_power_summary_cache_value

        empty_summary = self._power_flow_summary([])
        for source in ("scada", "real"):
            rows = measurements.get(source, [])
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            summary = self._power_flow_summary(rows)
            if any(summary["counts"].values()):
                result = {"source": source, **summary}
                break
        else:
            result = {"source": "", **empty_summary}
        if cache_key is not None:
            self._latest_power_summary_cache_key = cache_key
            self._latest_power_summary_cache_value = result
        return result

    def _power_flow_summary_lines(self, real_measurements: Sequence[Mapping[str, Any]]) -> List[str]:
        summary = self._power_flow_summary(real_measurements)
        counts = summary["counts"]
        wind = summary["wind"] if summary["wind"] is not None else 0.0
        solar = summary["solar"] if summary["solar"] is not None else 0.0
        diesel = summary["diesel"] if summary["diesel"] is not None else 0.0
        load = summary["load"] if summary["load"] is not None else 0.0
        storage_generation = (
            summary["storageDischarge"] if summary["storageDischarge"] is not None else 0.0
        )
        storage_charge = summary["storageCharge"] if summary["storageCharge"] is not None else 0.0
        soc_average = summary["soc"]
        soc_total = summary["socTotal"]
        soc_text = (
            f"储能SOC 平均 {format_number(soc_average)}%，储能总SOC {format_number(soc_total)}，台数 {counts['soc']}"
            if soc_average is not None
            else "储能SOC 平均 --，储能总SOC --，台数 0"
        )
        generation_total = summary["generation"] if summary["generation"] is not None else 0.0
        consumption_total = summary["consumption"] if summary["consumption"] is not None else 0.0
        power_difference = summary["balance"] if summary["balance"] is not None else 0.0
        return [
            (
                f"分类统计 风力发电总功率 {format_number(wind)} kW（{counts['wind']} 台），"
                f"光伏发电总功率 {format_number(solar)} kW（{counts['solar']} 台）"
            ),
            (
                f"分类统计 柴油发电总功率 {format_number(diesel)} kW（{counts['diesel']} 台），"
                f"负荷用电总功率 {format_number(load)} kW（{counts['load']} 个）"
            ),
            (
                f"分类统计 储能发电总功率 {format_number(storage_generation)} kW，"
                f"储能充电总功率 {format_number(storage_charge)} kW（{counts['storage']} 台），{soc_text}"
            ),
            (
                f"功率平衡 电源发电总功率 {format_number(generation_total)} kW，"
                f"用电及充电总功率 {format_number(consumption_total)} kW，"
                f"功率差额 {format_number(power_difference)} kW（含网络与变流损耗）"
            ),
        ]

    def _compact_command_response_lines(self, lines: Sequence[str]) -> List[str]:
        if not lines:
            return []
        first_line = str(lines[0])
        if len(lines) > 1:
            first_line = f"{first_line}；其余控制响应明细 {len(lines) - 1} 条已省略"
        return [first_line]

    def _append_power_flow_log(
        self,
        result: Mapping[str, Any],
        measurements: Mapping[str, Sequence[Mapping[str, Any]]],
        minute: int | float,
        absolute_minute: int | float,
        clock_advance: int | float,
        period_seconds: float,
        command_response_lines: Sequence[str],
    ) -> None:
        real_measurements = measurements.get("real", [])
        simu_time = minute_to_time(minute)
        control_detail = [
            *self._compact_command_response_lines(command_response_lines),
            *self._input_boundary_lines(minute, absolute_minute, clock_advance, period_seconds),
        ]
        self._append_runtime_log(
            "控制响应",
            "运行边界 / 控制指令",
            "完成",
            control_detail,
            level="ok",
            simu_time=simu_time,
        )
        power_flow_detail = [
            (
                f"计算摘要 时刻 {simu_time}，累计分钟 {absolute_minute}，推进 {clock_advance} min，"
                f"求解器 {result.get('solver_info', 'not-run')}，"
                f"真值量测 {len(real_measurements)} 条，更新 {result.get('updated', 0)} 条，"
                f"缺失 {result.get('missing', 0)} 条，叠加修正 {result.get('overlay_updates', 0)} 条"
            ),
            *self._power_flow_summary_lines(real_measurements),
        ]
        self._append_runtime_log(
            "潮流计算",
            "内存模型 / 量测快照",
            "完成" if int(_to_float(result.get("missing"), 0) or 0) == 0 else "有缺失",
            power_flow_detail,
            level="ok" if int(_to_float(result.get("missing"), 0) or 0) == 0 else "warn",
            simu_time=simu_time,
        )

    def _power_flow_failure_result(self, error: BaseException) -> str:
        text = f"{type(error).__name__}: {error}".casefold()
        divergence_markers = (
            "normf=nan",
            "normf=inf",
            "nan",
            "overflow",
            "singular",
            "未收敛",
            "发散",
            "load flow failed",
            "潮流",
        )
        return "数值发散" if any(marker in text for marker in divergence_markers) else "失败"

    def _append_power_flow_failure_log(
        self,
        error: BaseException,
        minute: int | float,
        absolute_minute: int | float,
        clock_advance: int | float,
        period_seconds: float,
        *,
        auto_paused: bool,
    ) -> None:
        simu_time = minute_to_time(minute)
        result = self._power_flow_failure_result(error)
        detail = [
            (
                f"计算失败 时刻 {simu_time}，累计分钟 {format_number(absolute_minute)}，"
                f"推进 {format_number(clock_advance * 60.0)} s，"
                f"仿真周期 {format_number(period_seconds)} s"
            ),
            f"失败类型 {result}，异常 {type(error).__name__}: {error}",
            (
                "处理措施 本轮潮流结果未写入，仿真时钟不推进；运行中的仿真已自动暂停"
                if auto_paused
                else "处理措施 本轮潮流结果未写入，仿真时钟不推进；当前时钟状态保持不变"
            ),
            *self._input_boundary_lines(minute, absolute_minute, clock_advance, period_seconds),
        ]
        self._append_runtime_log(
            "潮流计算",
            "内存模型 / 量测快照",
            result,
            detail,
            level="error",
            simu_time=simu_time,
        )

    def apply_student_commands(self, payload: Mapping[str, Any], source: str = "") -> Dict[str, int]:
        if _has_cancel_command_payload(payload):
            return self.cancel_student_commands(payload, source=source)  # type: ignore[return-value]
        with self.lock:
            run_items = payload.get("run_status", payload.get("runStatus", [])) or []
            set_items = payload.get("set_values", payload.get("setValues", payload.get("setpoints", []))) or []
            run_sequence = list(run_items) if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)) else []
            set_sequence = list(set_items) if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)) else []
            requested_run_items = self._normalize_run_command_items(run_sequence)
            requested_set_items = self._normalize_set_command_items(set_sequence)
            normalized_run_items = self._filter_defined_run_command_items(requested_run_items)
            normalized_set_items = self._filter_defined_set_command_items(requested_set_items)
            eligible_source = _is_trainee_command_source(source)
            if eligible_source and (normalized_run_items or normalized_set_items):
                try:
                    normalized_run_items = self._validate_run_command_items(
                        normalized_run_items
                    )
                    normalized_set_items = self._validate_set_command_items(
                        normalized_set_items,
                        strict=True,
                    )
                except ValueError as exc:
                    self._append_runtime_log(
                        "控制安全边界",
                        "遥调指令接收",
                        "整批拒绝",
                        [
                            str(exc),
                            "本批遥控/遥调未写入指令历史、运行控制文件或潮流边界。",
                        ],
                        level="warn",
                    )
                    raise
            issued_absolute_minute = float(self.clock.absolute_minute)
            received_wall_time = _now_text()
            received_simu_time = minute_to_time(self.clock.minute)
            manual_hold = _manual_command_holds_across_clock_lifecycle(payload, source)
            command_origin = "manual" if manual_hold else "automatic"
            strategy_id, generation, replace_strategy_generation = _strategy_generation_metadata(payload)
            complete_strategy_snapshot = bool(
                eligible_source
                and command_origin == "automatic"
                and strategy_id
                and generation not in (None, "")
                and replace_strategy_generation
            )
            expires_at_absolute_minute = (
                None
                if manual_hold
                else _command_expires_at(payload, None, issued_absolute_minute)
            )
            if command_origin == "automatic":
                cycle_minutes = float(self._simulation_cycle_minutes())
                cycle_end = (
                    math.floor((issued_absolute_minute + 1e-9) / cycle_minutes) + 1
                ) * cycle_minutes
                expires_at_absolute_minute = cycle_end
            accepted_run = len(normalized_run_items) if eligible_source else 0
            accepted_set = len(normalized_set_items) if eligible_source else 0
            requested_count = len(requested_run_items) + len(requested_set_items)
            ignored = requested_count - accepted_run - accepted_set if eligible_source else requested_count
            accepted = {"run_status": accepted_run, "set_values": accepted_set, "ignored": ignored}
            if complete_strategy_snapshot and self._matching_complete_strategy_snapshot(
                strategy_id=strategy_id,
                generation=generation,
                run_items=normalized_run_items,
                set_items=normalized_set_items,
                absolute_minute=issued_absolute_minute,
            ) is not None:
                return accepted
            valid_for_minutes = (
                None
                if expires_at_absolute_minute is None
                else max(0.0, expires_at_absolute_minute - issued_absolute_minute)
            )
            superseded_generations = 0
            superseded_controls: set[Tuple[str, str, str, str]] = set()
            if complete_strategy_snapshot:
                superseded_generations, superseded_controls = self._mark_strategy_generations_cancelled(
                    strategy_id=strategy_id,
                    reason="superseded_strategy_generation",
                    cancelled_wall_time=received_wall_time,
                    cancelled_simu_time=received_simu_time,
                    cancelled_absolute_minute=issued_absolute_minute,
                    require_generation_match=False,
                )
            command_entry = {
                "time": received_wall_time,
                "received_wall_time": received_wall_time,
                "received_simu_time": received_simu_time,
                "received_absolute_minute": issued_absolute_minute,
                "run_id": int(self.clock.run_id),
                "source": source,
                "eligible_source": eligible_source,
                "manual_hold": manual_hold,
                "command_origin": command_origin,
                "issued_absolute_minute": issued_absolute_minute,
                "expires_at_absolute_minute": expires_at_absolute_minute,
                "valid_for_minutes": valid_for_minutes,
                "strategy_id": strategy_id,
                "generation": generation,
                "replace_strategy_generation": replace_strategy_generation,
                "snapshot_complete": complete_strategy_snapshot,
                "superseded_generations": superseded_generations,
                "superseded_controls": len(superseded_controls),
                "accepted": accepted,
                "normalized": {
                    "run_status": normalized_run_items if eligible_source else [],
                    "set_values": normalized_set_items if eligible_source else [],
                },
                "payload": self._compact_command_payload(
                    json.loads(json.dumps(payload, ensure_ascii=False, default=str))
                ),
            }
            self._append_command_history_entry(command_entry)
            self._prepare_command_history_for_persistence()
            self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            self._write_command_history(prepared=True)
            self._append_runtime_log(
                "控制指令",
                "学员台 /api/student/commands",
                (
                    "策略快照已替换"
                    if complete_strategy_snapshot
                    else ("接受成功" if accepted_run or accepted_set else "无有效指令")
                ),
                self._command_accept_detail(
                    payload,
                    source,
                    accepted,
                    run_sequence,
                    normalized_set_items,
                    eligible_source=eligible_source,
                    issued_absolute_minute=issued_absolute_minute,
                    expires_at_absolute_minute=expires_at_absolute_minute,
                ),
                level="ok" if accepted_run or accepted_set else "warn",
            )
            return accepted

    def _expand_set_values(self, items: Iterable[Any]) -> List[Dict[str, Any]]:
        expanded: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            if "set_type" in item:
                expanded.append(dict(item))
                continue
            for key in (
                "p_set",
                "q_set",
                "v_set",
                "p_ac_set",
                "q_ac_set",
                "v_ac_set",
                "p_dc_set",
                "q_dc_set",
                "v_dc_set",
            ):
                if key in item:
                    expanded.append(
                        {
                            "dev_type": item.get("dev_type", item.get("type", "")),
                            "dev_name": item.get("dev_name", item.get("name", "")),
                            "set_type": key,
                            "set_value": item[key],
                        }
                    )
        return expanded

    def set_curves(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock, self.curves_lock:
            current_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            mode = _normalize_simulation_mode(payload.get("mode", current_mode), current_mode)
            if mode != current_mode and self.clock.state != "stopped":
                raise ValueError("仿真运行过程中不能切换仿真模式，请先停止仿真")
            default_step = _simulation_mode_curve_step_minutes(mode)
            time_step_minutes = float(_to_float(payload.get("time_step_minutes"), default_step) or default_step)
            if time_step_minutes <= 0:
                time_step_minutes = default_step
            default_point_count = _simulation_mode_point_count(mode)
            point_count = int(_to_float(payload.get("point_count"), default_point_count) or 0)
            weather_points = _normalize_points(payload.get("weather"), WEATHER_HEADER[1:])
            loads_payload = payload.get("loads", {})
            loads: Dict[str, List[Dict[str, Any]]] = {}
            if isinstance(loads_payload, Mapping):
                for name, points in loads_payload.items():
                    loads[str(name)] = _normalize_points(points, ("p_kw", "value", "load_kw"))
            elif isinstance(loads_payload, Sequence) and not isinstance(loads_payload, (str, bytes)):
                for item in loads_payload:
                    if not isinstance(item, Mapping):
                        continue
                    name = str(item.get("dev_name", item.get("name", "load")))
                    loads.setdefault(name, []).append(
                        {
                            "minute": _to_float(item.get("minute", len(loads.get(name, []))), 0.0) or 0.0,
                            "p_kw": item.get("p_kw", item.get("value", item.get("load_kw", 0))),
                        }
                    )
            resolved_point_count = point_count or len(weather_points) or default_point_count
            self.curves = {
                "mode": mode,
                "time_step_minutes": time_step_minutes,
                "point_count": resolved_point_count,
                "weather": weather_points,
                "loads": loads,
                "sources": self._normalized_source_curves(
                    payload.get("sources"),
                    resolved_point_count,
                    time_step_minutes,
                ),
            }
            if mode != current_mode:
                self._apply_mode_default_clock_speed(mode, persist=True)
            self.clock.absolute_minute = _align_minute_to_step(
                self.clock.absolute_minute,
                _effective_clock_step(self.clock.step_minutes, self.clock.speed),
            )
            self.clock.minute = self.clock.absolute_minute % 1440
            self.clock.updated_at = time.time()
            _write_json(self.curves_file, self.curves)
            self._curve_revision += 1
            return {
                "weather_points": len(weather_points),
                "load_devices": len(loads),
                "source_devices": len(self.curves["sources"]),
                "mode": mode,
            }

    def curves_summary(self) -> Dict[str, Any]:
        with self.curves_lock:
            mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            default_step = _simulation_mode_curve_step_minutes(mode)
            default_point_count = _simulation_mode_point_count(mode)
            weather = self.curves.get("weather", [])
            loads = self.curves.get("loads", {})
            sources = self.curves.get("sources", [])
            point_count = int(_to_float(self.curves.get("point_count"), 0) or 0)
            if not point_count:
                point_count = len(weather) if isinstance(weather, Sequence) else 0
            load_catalog = {
                str(item.get("storage_key", "")): item
                for item in self._external_curve_catalog()
                if item.get("curve_type") == "load"
            }
            return {
                "mode": mode,
                "time_step_minutes": float(_to_float(self.curves.get("time_step_minutes"), default_step) or default_step),
                "point_count": point_count or default_point_count,
                "environment": [
                    {
                        "key": key,
                        "point_count": len(weather) if isinstance(weather, Sequence) else 0,
                    }
                    for key in ("wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c")
                ],
                "loads": [
                    {
                        "key": f"load:{name}",
                        "name": str(name),
                        "point_count": len(points) if isinstance(points, Sequence) else 0,
                        **{
                            key: load_catalog[str(name)].get(key)
                            for key in ("dev_type", "dev_name", "set_type", "family", "unit")
                            if str(name) in load_catalog and load_catalog[str(name)].get(key) is not None
                        },
                    }
                    for name, points in (loads.items() if isinstance(loads, Mapping) else [])
                ],
                "sources": [
                    {
                        key: item.get(key)
                        for key in (
                            "key",
                            "dev_type",
                            "dev_name",
                            "name",
                            "set_type",
                            "family",
                            "unit",
                            "default_value",
                            "min",
                            "max",
                        )
                        if item.get(key) is not None
                    }
                    | {
                        "point_count": len(item.get("points", []))
                        if isinstance(item.get("points"), Sequence)
                        and not isinstance(item.get("points"), (str, bytes))
                        else 0
                    }
                    for item in (
                        sources
                        if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes))
                        else []
                    )
                    if isinstance(item, Mapping)
                ],
            }

    def _curve_series_values(self, key: str) -> List[float]:
        if key in ("wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"):
            weather = self.curves.get("weather", [])
            if not isinstance(weather, Sequence) or isinstance(weather, (str, bytes)):
                return []
            return [float(_to_float(point.get(key), 0.0) or 0.0) for point in weather if isinstance(point, Mapping)]
        if key.startswith("load:"):
            load_name = key.replace("load:", "", 1)
            loads = self.curves.get("loads", {})
            points = loads.get(load_name, []) if isinstance(loads, Mapping) else []
            if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                return []
            catalog_item = next(
                (
                    item for item in self._external_curve_catalog()
                    if item.get("curve_type") == "load"
                    and str(item.get("storage_key", "")) == load_name
                ),
                None,
            )
            aliases = tuple(catalog_item.get("value_aliases", ())) if catalog_item else ("p_kw", "value", "load_kw")
            return [
                float(
                    next(
                        (
                            _to_float(point.get(alias), 0.0)
                            for alias in aliases
                            if point.get(alias) not in (None, "")
                        ),
                        0.0,
                    )
                    or 0.0
                )
                for point in points
                if isinstance(point, Mapping)
            ]
        if key.startswith("source:"):
            sources = self.curves.get("sources", [])
            if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
                return []
            item = next(
                (
                    item
                    for item in sources
                    if isinstance(item, Mapping) and str(item.get("key", "")) == key
                ),
                None,
            )
            if item is None:
                return []
            points = item.get("points", [])
            if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                return []
            return [
                float(_to_float(point.get("value", point.get("set_value")), 0.0) or 0.0)
                for point in points
                if isinstance(point, Mapping)
            ]
        return []

    def curves_series(self, keys: Sequence[str]) -> Dict[str, Any]:
        with self.curves_lock:
            mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            default_step = _simulation_mode_curve_step_minutes(mode)
            default_point_count = _simulation_mode_point_count(mode)
            point_count = int(_to_float(self.curves.get("point_count"), default_point_count) or 0)
            requested = [str(key).strip() for key in keys if str(key).strip()]
            if not requested:
                requested = ["wind_speed_mps"]
            series: Dict[str, List[float]] = {}
            for key in requested:
                values = self._curve_series_values(key)
                if values:
                    series[key] = values
            return {
                "mode": mode,
                "time_step_minutes": float(_to_float(self.curves.get("time_step_minutes"), default_step) or default_step),
                "point_count": point_count or default_point_count,
                "series": series,
            }

    @staticmethod
    def _external_curve_range(
        item: Mapping[str, Any],
        fallback: Mapping[str, Any],
    ) -> Tuple[Optional[float], Optional[float]]:
        raw_start = item.get("start_minute", fallback.get("start_minute"))
        raw_end = item.get("end_minute", fallback.get("end_minute"))
        if raw_start in (None, "") and raw_end in (None, ""):
            return None, None
        if raw_start in (None, "") or raw_end in (None, ""):
            raise ValueError("曲线时间范围必须同时提供 start_minute 和 end_minute")
        start = _to_float(raw_start, None)
        end = _to_float(raw_end, None)
        if start is None or end is None or not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("曲线时间范围必须是有限数值")
        if start < 0 or end < 0:
            raise ValueError("曲线时间范围不能为负数")
        if start > end:
            raise ValueError("曲线时间范围 start_minute 不能大于 end_minute")
        return float(start), float(end)

    @staticmethod
    def _load_curve_storage_key(
        item: Mapping[str, Any],
        loads: Mapping[str, Any],
        name_counts: Mapping[str, int],
    ) -> str:
        structured_key = str(item["key"])
        dev_type = str(item["dev_type"])
        dev_name = str(item["dev_name"])
        for candidate in (structured_key, f"{dev_type}:{dev_name}", dev_name):
            if candidate in loads and (candidate != dev_name or name_counts.get(dev_name, 0) == 1):
                return candidate
        return dev_name if name_counts.get(dev_name, 0) == 1 else f"{dev_type}:{dev_name}"

    def _external_curve_catalog(self, curves: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        current = curves if isinstance(curves, Mapping) else self.curves
        weather = current.get("weather", [])
        catalog: List[Dict[str, Any]] = [
            {
                "key": key,
                "curve_type": "environment",
                "energy_type": "environment",
                "dev_type": "Environment",
                "dev_name": "weather",
                "set_type": key,
                "unit": unit,
                "storage_kind": "weather",
                "storage_key": key,
                "value_aliases": (key,),
                "points": weather,
            }
            for key, unit in EXTERNAL_CURVE_ENVIRONMENT_SPECS.items()
        ]

        loads = current.get("loads", {})
        loads = loads if isinstance(loads, Mapping) else {}
        load_items = load_curve_catalog(self.definition_snapshot.model_book)
        name_counts: Dict[str, int] = {}
        for item in load_items:
            name = str(item["dev_name"])
            name_counts[name] = name_counts.get(name, 0) + 1
        for item in load_items:
            storage_key = self._load_curve_storage_key(item, loads, name_counts)
            catalog.append(
                {
                    **dict(item),
                    "curve_type": "load",
                    "energy_type": item.get("family", ""),
                    "storage_kind": "load",
                    "storage_key": storage_key,
                    "points": loads.get(storage_key, []),
                }
            )

        sources = current.get("sources", [])
        source_points = {
            str(item.get("key", "")): item.get("points", [])
            for item in sources
            if isinstance(item, Mapping)
        } if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)) else {}
        for item in source_curve_catalog(self.definition_snapshot.model_book):
            key = str(item["key"])
            catalog.append(
                {
                    **dict(item),
                    "curve_type": "source",
                    "energy_type": item.get("family", ""),
                    "storage_kind": "source",
                    "storage_key": key,
                    "value_aliases": ("value", "set_value", "p_kw", "flow_set"),
                    "points": source_points.get(key, []),
                }
            )
        return catalog

    @staticmethod
    def _external_curve_public_item(
        item: Mapping[str, Any],
        start_minute: Optional[float] = None,
        end_minute: Optional[float] = None,
    ) -> Dict[str, Any]:
        aliases = tuple(str(alias) for alias in item.get("value_aliases", ("value",)))
        points: List[Dict[str, float]] = []
        raw_points = item.get("points", [])
        if isinstance(raw_points, Sequence) and not isinstance(raw_points, (str, bytes)):
            for index, point in enumerate(raw_points):
                if not isinstance(point, Mapping):
                    continue
                minute = _to_float(point.get("minute"), float(index))
                value = next(
                    (
                        _to_float(point.get(alias), None)
                        for alias in aliases
                        if point.get(alias) not in (None, "")
                    ),
                    None,
                )
                if minute is None or value is None or not math.isfinite(minute) or not math.isfinite(value):
                    continue
                if start_minute is not None and minute < start_minute:
                    continue
                if end_minute is not None and minute > end_minute:
                    continue
                points.append({"minute": float(minute), "value": float(value)})
        points.sort(key=lambda point: point["minute"])
        return {
            key: item.get(key, "")
            for key in (
                "key", "curve_type", "energy_type", "dev_type",
                "dev_name", "set_type", "unit",
            )
        } | {"points": points}

    @staticmethod
    def _external_curve_selectors(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        raw_curves = payload.get("curves")
        if raw_curves is not None:
            if not isinstance(raw_curves, Sequence) or isinstance(raw_curves, (str, bytes)):
                raise ValueError("curves 必须是曲线选择数组")
            if any(not isinstance(item, Mapping) for item in raw_curves):
                raise ValueError("curves 中的每一项必须是曲线对象")
            return list(raw_curves)
        raw_keys = payload.get("keys")
        if raw_keys is None:
            return []
        if isinstance(raw_keys, str):
            raw_keys = [key.strip() for key in raw_keys.split(",")]
        if not isinstance(raw_keys, Sequence) or isinstance(raw_keys, (str, bytes)):
            raise ValueError("keys 必须是曲线键数组")
        return [{"key": str(key).strip()} for key in raw_keys if str(key).strip()]

    @staticmethod
    def _resolve_external_curve(
        selector: Mapping[str, Any],
        catalog: Mapping[str, Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        key = str(selector.get("key", "")).strip()
        item = catalog.get(key) if key else None
        if item is None and not key:
            identity = tuple(
                str(selector.get(field, "")).strip()
                for field in ("dev_type", "dev_name", "set_type")
            )
            if all(identity):
                matches = [
                    candidate
                    for candidate in catalog.values()
                    if tuple(str(candidate.get(field, "")) for field in ("dev_type", "dev_name", "set_type"))
                    == identity
                ]
                item = matches[0] if len(matches) == 1 else None
        if item is None:
            identity_text = "/".join(
                str(selector.get(field, "")).strip()
                for field in ("dev_type", "dev_name", "set_type")
            ).strip("/")
            raise ValueError(f"曲线不存在：{key or identity_text or '<empty>'}")
        key = str(item["key"])
        for field in ("curve_type", "energy_type", "dev_type", "dev_name", "set_type"):
            requested = str(selector.get(field, "")).strip()
            if requested and requested != str(item.get(field, "")):
                raise ValueError(f"曲线 {key} 的 {field} 身份不匹配")
        return item

    def external_curves_query(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.curves_lock:
            catalog = self._external_curve_catalog()
            by_key = {str(item["key"]): item for item in catalog}
            selectors = self._external_curve_selectors(payload)
            if not selectors:
                selectors = [{"key": item["key"]} for item in catalog]
            curves = []
            for selector in selectors:
                item = self._resolve_external_curve(selector, by_key)
                start, end = self._external_curve_range(selector, payload)
                curves.append(self._external_curve_public_item(item, start, end))
            mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            default_step = _simulation_mode_curve_step_minutes(mode)
            return {
                **self._external_response_metadata(),
                "mode": mode,
                "time_step_minutes": float(
                    _to_float(self.curves.get("time_step_minutes"), default_step) or default_step
                ),
                "returned_count": len(curves),
                "available_count": len(catalog),
                "curves": curves,
            }

    @staticmethod
    def _validated_external_curve_points(raw_points: Any) -> List[Dict[str, float]]:
        if not isinstance(raw_points, Sequence) or isinstance(raw_points, (str, bytes)):
            raise ValueError("曲线 points 必须是时间点数组")
        points: List[Dict[str, float]] = []
        seen: set[float] = set()
        for raw_point in raw_points:
            if not isinstance(raw_point, Mapping):
                raise ValueError("曲线时间点必须包含 minute 和 value")
            minute = _to_float(raw_point.get("minute"), None)
            value = _to_float(raw_point.get("value"), None)
            if minute is None or value is None or not math.isfinite(minute) or not math.isfinite(value):
                raise ValueError("曲线 minute 和 value 必须是有限数值")
            minute = float(minute)
            if minute < 0:
                raise ValueError("曲线 minute 不能为负数")
            if minute in seen:
                raise ValueError(f"曲线存在重复时刻：{minute:g}")
            seen.add(minute)
            points.append({"minute": minute, "value": float(value)})
        points.sort(key=lambda point: point["minute"])
        return points

    @staticmethod
    def _store_external_curve_points(
        curves: Dict[str, Any],
        item: Mapping[str, Any],
        points: Sequence[Mapping[str, float]],
    ) -> None:
        kind = str(item.get("storage_kind", ""))
        storage_key = str(item.get("storage_key", item.get("key", "")))
        if kind == "weather":
            weather = curves.setdefault("weather", [])
            if not isinstance(weather, list):
                weather = []
                curves["weather"] = weather
            field = str(item["set_type"])
            for row in weather:
                if isinstance(row, dict):
                    row.pop(field, None)
            rows_by_minute = {
                float(_to_float(row.get("minute"), index) or 0.0): row
                for index, row in enumerate(weather)
                if isinstance(row, dict)
            }
            for point in points:
                minute = float(point["minute"])
                row = rows_by_minute.get(minute)
                if row is None:
                    row = {"minute": minute}
                    weather.append(row)
                    rows_by_minute[minute] = row
                row[field] = float(point["value"])
            weather.sort(key=lambda row: float(_to_float(row.get("minute"), 0.0) or 0.0))
            return
        if kind == "load":
            loads = curves.setdefault("loads", {})
            if not isinstance(loads, dict):
                loads = {}
                curves["loads"] = loads
            field = "p_kw" if item.get("set_type") == "p_set" else str(item["set_type"])
            loads[storage_key] = [
                {"minute": float(point["minute"]), field: float(point["value"])}
                for point in points
            ]
            return
        sources = curves.setdefault("sources", [])
        if not isinstance(sources, list):
            sources = []
            curves["sources"] = sources
        target = next(
            (
                source for source in sources
                if isinstance(source, dict) and str(source.get("key", "")) == storage_key
            ),
            None,
        )
        if target is None:
            target = {
                key: item.get(key)
                for key in ("key", "dev_type", "dev_name", "name", "set_type", "family", "unit")
            }
            sources.append(target)
        target["points"] = [
            {"minute": float(point["minute"]), "value": float(point["value"])}
            for point in points
        ]

    def external_curves_update(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock, self.curves_lock:
            raw_updates = payload.get("curves")
            if not isinstance(raw_updates, Sequence) or isinstance(raw_updates, (str, bytes)) or not raw_updates:
                raise ValueError("curves 必须是非空曲线更新数组")
            staged = copy.deepcopy(self.curves)
            by_key = {str(item["key"]): item for item in self._external_curve_catalog(staged)}
            prepared = []
            seen_keys: set[str] = set()
            for raw_item in raw_updates:
                if not isinstance(raw_item, Mapping):
                    raise ValueError("curves 中的每一项必须是曲线对象")
                item = self._resolve_external_curve(raw_item, by_key)
                key = str(item["key"])
                if key in seen_keys:
                    raise ValueError(f"同一批更新中曲线重复：{key}")
                seen_keys.add(key)
                start, end = self._external_curve_range(raw_item, payload)
                points = self._validated_external_curve_points(raw_item.get("points"))
                if start is not None and any(point["minute"] < start or point["minute"] > end for point in points):
                    raise ValueError(f"曲线 {key} 的更新点超出指定时间范围")
                prepared.append((item, points, start, end))

            results = []
            for item, incoming, start, end in prepared:
                points = list(incoming)
                if start is not None:
                    points = [
                        point for point in self._external_curve_public_item(item)["points"]
                        if point["minute"] < start or point["minute"] > end
                    ] + points
                    points.sort(key=lambda point: point["minute"])
                self._store_external_curve_points(staged, item, points)
                result = {
                    "key": item["key"],
                    "update_scope": "time_range" if start is not None else "whole_curve",
                    "point_count": len(points),
                }
                if start is not None:
                    result.update({"start_minute": start, "end_minute": end})
                results.append(result)

            atomic_write_text(
                self.curves_file,
                json.dumps(staged, ensure_ascii=False, indent=2) + "\n",
            )
            self.curves = staged
            self._curve_revision += 1
            final_catalog = {str(item["key"]): item for item in self._external_curve_catalog()}
            return {
                **self._external_response_metadata(),
                "updated_count": len(results),
                "results": results,
                "curves": [
                    self._external_curve_public_item(final_catalog[str(item["key"])])
                    for item, _points, _start, _end in prepared
                ],
            }

    def _ensure_weather_curve_points(self, point_count: int, step_minutes: float) -> List[Dict[str, Any]]:
        weather = self.curves.get("weather", [])
        if not isinstance(weather, list):
            weather = []
        defaults = dict(DEFAULT_WEATHER)
        while len(weather) < point_count:
            index = len(weather)
            weather.append({"minute": index * step_minutes, **defaults})
        if len(weather) > point_count:
            del weather[point_count:]
        for index, point in enumerate(weather):
            if not isinstance(point, dict):
                point = {}
                weather[index] = point
            point["minute"] = _to_float(point.get("minute"), index * step_minutes) or index * step_minutes
            for key, value in defaults.items():
                point.setdefault(key, value)
        self.curves["weather"] = weather
        return weather

    def _ensure_load_curve_points(self, load_name: str, point_count: int, step_minutes: float) -> List[Dict[str, Any]]:
        loads = self.curves.get("loads")
        if not isinstance(loads, dict):
            loads = {}
            self.curves["loads"] = loads
        points = loads.get(load_name)
        if not isinstance(points, list):
            points = []
            loads[load_name] = points
        while len(points) < point_count:
            index = len(points)
            points.append({"minute": index * step_minutes, "p_kw": DEFAULT_WEATHER["load_kw"]})
        if len(points) > point_count:
            del points[point_count:]
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                point = {"p_kw": point}
                points[index] = point
            point["minute"] = _to_float(point.get("minute"), index * step_minutes) or index * step_minutes
            point.setdefault("p_kw", DEFAULT_WEATHER["load_kw"])
        return points

    def _ensure_source_curve_points(
        self,
        curve_key: str,
        point_count: int,
        step_minutes: float,
    ) -> Optional[List[Dict[str, Any]]]:
        catalog_item = source_curve_catalog_by_key(self.definition_snapshot.model_book).get(curve_key)
        if catalog_item is None:
            return None
        sources = self.curves.get("sources")
        if not isinstance(sources, list):
            sources = []
            self.curves["sources"] = sources
        item = next(
            (
                item
                for item in sources
                if isinstance(item, dict) and str(item.get("key", "")) == curve_key
            ),
            None,
        )
        if item is None:
            item = {**catalog_item, "points": []}
            sources.append(item)
        else:
            item.update(catalog_item)
        points = item.get("points")
        if not isinstance(points, list):
            points = []
            item["points"] = points
        fallback = float(catalog_item.get("default_value", 0.0) or 0.0)
        while len(points) < point_count:
            index = len(points)
            points.append({"minute": index * step_minutes, "value": fallback})
        if len(points) > point_count:
            del points[point_count:]
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                point = {"value": point}
                points[index] = point
            point["minute"] = _to_float(point.get("minute"), index * step_minutes) or 0.0
            point.setdefault("value", fallback)
        return points

    def update_curve_series(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock, self.curves_lock:
            current_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            mode = _normalize_simulation_mode(payload.get("mode", current_mode), current_mode)
            if mode != current_mode and self.clock.state != "stopped":
                raise ValueError("仿真运行过程中不能切换仿真模式，请先停止仿真")
            default_step = _simulation_mode_curve_step_minutes(mode)
            step_minutes = float(
                _to_float(payload.get("time_step_minutes"), self.curves.get("time_step_minutes", default_step))
                or default_step
            )
            if step_minutes <= 0:
                step_minutes = default_step
            default_point_count = _simulation_mode_point_count(mode)
            point_count = int(
                _to_float(payload.get("point_count"), self.curves.get("point_count", default_point_count)) or 0
            )
            raw_series = payload.get("series", {})
            if not isinstance(raw_series, Mapping):
                raw_series = {}
            for values in raw_series.values():
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                    point_count = max(point_count, len(values))
            point_count = point_count or default_point_count
            self.curves["mode"] = mode
            self.curves["time_step_minutes"] = step_minutes
            self.curves["point_count"] = point_count
            updated: List[str] = []
            for key, values in raw_series.items():
                curve_key = str(key).strip()
                if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                    continue
                if curve_key in ("wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"):
                    weather = self._ensure_weather_curve_points(point_count, step_minutes)
                    for index, value in enumerate(values[:point_count]):
                        weather[index][curve_key] = _to_float(value, 0.0) or 0.0
                    updated.append(curve_key)
                elif curve_key.startswith("load:"):
                    load_name = curve_key.replace("load:", "", 1)
                    if not load_name:
                        continue
                    points = self._ensure_load_curve_points(load_name, point_count, step_minutes)
                    for index, value in enumerate(values[:point_count]):
                        points[index]["p_kw"] = _to_float(value, 0.0) or 0.0
                    updated.append(curve_key)
                elif curve_key.startswith("source:"):
                    points = self._ensure_source_curve_points(curve_key, point_count, step_minutes)
                    if points is None:
                        continue
                    for index, value in enumerate(values[:point_count]):
                        points[index]["value"] = _to_float(value, 0.0) or 0.0
                    updated.append(curve_key)
            if mode != current_mode:
                self._apply_mode_default_clock_speed(mode, persist=True)
            self.clock.absolute_minute = _align_minute_to_step(
                self.clock.absolute_minute,
                _effective_clock_step(self.clock.step_minutes, self.clock.speed),
            )
            self.clock.minute = self.clock.absolute_minute % 1440
            self.clock.updated_at = time.time()
            _write_json(self.curves_file, self.curves)
            self._curve_revision += 1
            return {
                "updated": updated,
                "mode": mode,
                "time_step_minutes": step_minutes,
                "point_count": point_count,
            }

    def _external_load_catalog(self) -> List[Dict[str, str]]:
        catalog: List[Dict[str, str]] = []
        model_book = self.definition_snapshot.model_book
        for dev_type in ("ACLoad", "DCLoad"):
            block = model_book.data.get(dev_type)
            if block is None:
                continue
            for row in block.data:
                dev_name = str(row.get("name", "")).strip()
                if not dev_name:
                    continue
                catalog.append(
                    {
                        "key": f"{dev_type}:{dev_name}",
                        "dev_type": dev_type,
                        "dev_name": dev_name,
                        "unit": "kW",
                    }
                )
        catalog.sort(key=lambda item: (item["dev_type"], item["dev_name"]))
        return catalog

    @staticmethod
    def _external_finite_number(field: str, value: Any) -> float:
        number = _to_float(value, None)
        if number is None or not math.isfinite(number):
            raise ValueError(f"{field} 必须是有限数值")
        return float(number)

    @staticmethod
    def _external_load_lookup(
        catalog: Sequence[Mapping[str, str]],
    ) -> Tuple[Dict[str, Mapping[str, str]], Dict[str, List[str]]]:
        by_key = {str(item["key"]): item for item in catalog}
        by_name: Dict[str, List[str]] = {}
        for item in catalog:
            by_name.setdefault(str(item["dev_name"]), []).append(str(item["key"]))
        return by_key, by_name

    @staticmethod
    def _resolve_external_load_key(
        raw_key: Any,
        by_key: Mapping[str, Mapping[str, str]],
        by_name: Mapping[str, Sequence[str]],
    ) -> str:
        key = str(raw_key or "").strip()
        if not key:
            raise ValueError("负荷输入缺少设备名称")
        if key in by_key:
            return key
        if ":" in key:
            raise ValueError(f"负荷 {key} 在当前模型中不存在")
        matches = list(by_name.get(key, []))
        if not matches:
            raise ValueError(f"负荷 {key} 在当前模型中不存在")
        if len(matches) > 1:
            raise ValueError(
                f"负荷名称 {key} 不唯一，请使用 ACLoad:{key} 或 DCLoad:{key}"
            )
        return matches[0]

    def _normalize_external_realtime_weather(self, payload: Mapping[str, Any]) -> Dict[str, float]:
        raw_weather = payload.get("weather", {})
        if raw_weather in (None, ""):
            raw_weather = {}
        if not isinstance(raw_weather, Mapping):
            raise ValueError("weather 必须是对象")
        unknown = sorted(str(key) for key in raw_weather if str(key) not in EXTERNAL_REALTIME_WEATHER_FIELD_SET)
        if unknown:
            raise ValueError(f"weather 包含不支持的字段: {', '.join(unknown)}")

        values: Dict[str, float] = {}
        for key, _unit in EXTERNAL_REALTIME_WEATHER_FIELDS:
            if key in payload:
                values[key] = self._external_finite_number(key, payload.get(key))
            if key in raw_weather:
                values[key] = self._external_finite_number(key, raw_weather.get(key))

        for key in ("wind_speed_mps", "solar_irradiance_w_m2"):
            if key in values and values[key] < 0:
                raise ValueError(f"{key} 不能小于 0")
        if "air_pressure_hpa" in values and values["air_pressure_hpa"] <= 0:
            raise ValueError("air_pressure_hpa 必须大于 0")
        if "humidity_pct" in values and not 0 <= values["humidity_pct"] <= 100:
            raise ValueError("humidity_pct 必须在 0 到 100 之间")
        return values

    def _normalize_external_realtime_loads(
        self,
        payload: Mapping[str, Any],
        catalog: Sequence[Mapping[str, str]],
    ) -> Dict[str, float]:
        by_key, by_name = self._external_load_lookup(catalog)

        values: Dict[str, float] = {}

        def resolve_key(raw_key: Any) -> str:
            return self._resolve_external_load_key(raw_key, by_key, by_name)

        def add(raw_key: Any, raw_value: Any) -> None:
            key = resolve_key(raw_key)
            if isinstance(raw_value, Mapping):
                sentinel = object()
                value: Any = sentinel
                for field in ("p_kw", "value", "load_kw"):
                    if field in raw_value:
                        value = raw_value.get(field)
                        break
                if value is sentinel:
                    raise ValueError(f"{key} 缺少 p_kw/value/load_kw")
                raw_value = value
            number = self._external_finite_number(key, raw_value)
            if number < 0:
                raise ValueError(f"{key} 不能小于 0")
            values[key] = number

        def add_items(raw_items: Any, field_name: str) -> None:
            if raw_items in (None, ""):
                return
            if isinstance(raw_items, Mapping):
                for raw_key, raw_value in raw_items.items():
                    add(raw_key, raw_value)
                return
            if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
                raise ValueError(f"{field_name} 必须是对象或数组")
            for item in raw_items:
                if not isinstance(item, Mapping):
                    raise ValueError(f"{field_name} 数组项必须是对象")
                raw_key = item.get("key")
                if raw_key in (None, ""):
                    dev_type = str(item.get("dev_type", item.get("type", ""))).strip()
                    dev_name = str(item.get("dev_name", item.get("name", ""))).strip()
                    if dev_type:
                        if dev_type not in {"ACLoad", "DCLoad"}:
                            raise ValueError(f"负荷类型 {dev_type} 不支持，只允许 ACLoad 或 DCLoad")
                        raw_key = f"{dev_type}:{dev_name}"
                    else:
                        raw_key = dev_name
                sentinel = object()
                raw_value: Any = sentinel
                for value_key in ("p_kw", "value", "load_kw"):
                    if value_key in item:
                        raw_value = item.get(value_key)
                        break
                if raw_value is sentinel:
                    raise ValueError(f"负荷 {raw_key} 缺少 p_kw/value/load_kw")
                add(raw_key, raw_value)

        add_items(payload.get("loads"), "loads")
        add_items(payload.get("load_values"), "load_values")
        return values

    def _external_realtime_target_locked(
        self,
        target_absolute_minute: Optional[float] = None,
    ) -> Dict[str, Any]:
        mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        default_step = _simulation_mode_curve_step_minutes(mode)
        step_minutes = float(_to_float(self.curves.get("time_step_minutes"), default_step) or default_step)
        if step_minutes <= 0:
            step_minutes = default_step
        period_minutes = _simulation_mode_duration_minutes(mode)
        default_point_count = _simulation_mode_point_count(mode)
        point_count = int(_to_float(self.curves.get("point_count"), 0) or 0)
        weather = self.curves.get("weather", [])
        weather_count = (
            len(weather)
            if isinstance(weather, Sequence) and not isinstance(weather, (str, bytes))
            else 0
        )
        loads = self.curves.get("loads", {})
        load_point_count = 0
        if isinstance(loads, Mapping):
            load_point_count = max(
                (
                    len(points)
                    for points in loads.values()
                    if isinstance(points, Sequence) and not isinstance(points, (str, bytes))
                ),
                default=0,
            )
        point_count = point_count or weather_count or load_point_count or default_point_count
        if target_absolute_minute is None:
            target_absolute_minute = float(_to_float(self.clock.absolute_minute, 0.0) or 0.0)
        else:
            target_absolute_minute = float(target_absolute_minute)
        if weather_count >= point_count:
            target_index = self._curve_point_index(target_absolute_minute, period_minutes) - 1
        else:
            target_index = int((target_absolute_minute % period_minutes) // step_minutes)
        target_index = max(0, min(point_count - 1, target_index))
        point_minute = target_index * step_minutes
        if weather_count > target_index and isinstance(weather[target_index], Mapping):
            point_minute = float(_to_float(weather[target_index].get("minute"), point_minute) or point_minute)
        return {
            "mode": mode,
            "time_step_minutes": step_minutes,
            "period_minutes": period_minutes,
            "point_count": point_count,
            "absolute_minute": target_absolute_minute,
            "simu_time": minute_to_time(target_absolute_minute),
            "index": target_index,
            "point_number": target_index + 1,
            "point_minute": point_minute,
        }

    def _external_realtime_target_for_time_locked(
        self,
        absolute_minute: float,
        field_label: str,
    ) -> Dict[str, Any]:
        target = self._external_realtime_target_locked(absolute_minute)
        period_minutes = float(target["period_minutes"])
        point_delta = abs(
            (absolute_minute % period_minutes)
            - float(target["point_minute"])
        )
        point_delta = min(point_delta, max(0.0, period_minutes - point_delta))
        tolerance = max(1e-9, float(target["time_step_minutes"]) * 1e-9)
        if point_delta > tolerance:
            raise ValueError(f"{field_label} 必须落在当前曲线采样网格上")
        return target

    @staticmethod
    def _external_integer_field(
        payload: Mapping[str, Any],
        keys: Sequence[str],
        *,
        required: bool,
        default: Optional[int] = None,
        minimum: int = 0,
    ) -> Optional[int]:
        selected_key = next((key for key in keys if key in payload), "")
        if not selected_key:
            if required:
                raise ValueError(f"{keys[0]} 为必填整数参数")
            return default
        raw_value = payload.get(selected_key)
        if isinstance(raw_value, bool):
            raise ValueError(f"{selected_key} 必须是整数")
        number = _to_float(raw_value, None)
        if number is None or not math.isfinite(number) or int(number) != number:
            raise ValueError(f"{selected_key} 必须是整数")
        value = int(number)
        if value < minimum:
            raise ValueError(f"{selected_key} 不能小于 {minimum}")
        return value

    def _external_input_contract_locked(
        self,
        payload: Mapping[str, Any],
        *,
        expected_count: int,
        batch: bool,
    ) -> Dict[str, Any]:
        has_count = "point_count" in payload
        interval_keys = [
            key
            for key in (
                "point_interval_seconds",
                "point_interval_minutes",
                "data_interval_seconds",
                "data_interval_minutes",
            )
            if key in payload
        ]
        if batch and not has_count:
            raise ValueError("point_count 为批量输入必填参数")
        if batch and not interval_keys:
            raise ValueError("point_interval_seconds 或 point_interval_minutes 为批量输入必填参数")
        if not batch and (has_count or interval_keys) and not (has_count and interval_keys):
            raise ValueError("单点输入显式定义数据契约时，point_count 和数据点间隔必须同时提供")
        if len(interval_keys) > 1:
            raise ValueError("数据点间隔只能使用 seconds 或 minutes 中的一种")

        point_count = self._external_integer_field(
            payload,
            ("point_count",),
            required=batch or has_count,
            default=1,
            minimum=1,
        )
        if point_count != expected_count:
            raise ValueError(
                f"point_count={point_count} 与实际数据点数量 {expected_count} 不一致"
            )

        curve_target = self._external_realtime_target_locked()
        curve_interval_minutes = float(curve_target["time_step_minutes"])
        if interval_keys:
            interval_key = interval_keys[0]
            interval_value = self._external_finite_number(interval_key, payload.get(interval_key))
            if interval_value <= 0:
                raise ValueError(f"{interval_key} 必须大于 0")
            interval_minutes = interval_value / 60.0 if interval_key.endswith("seconds") else interval_value
        else:
            interval_minutes = curve_interval_minutes
        interval_ratio = interval_minutes / curve_interval_minutes
        curve_step_count = int(round(interval_ratio))
        tolerance = max(1e-9, abs(interval_ratio) * 1e-9)
        if curve_step_count < 1 or abs(interval_ratio - curve_step_count) > tolerance:
            raise ValueError(
                "数据点间隔必须是当前曲线采样间隔 "
                f"{format_number(curve_interval_minutes * 60.0)} 秒的正整数倍"
            )
        return {
            "point_count": int(point_count or 0),
            "point_interval_minutes": interval_minutes,
            "point_interval_seconds": interval_minutes * 60.0,
            "curve_step_count": curve_step_count,
        }

    def _external_target_from_index_locked(
        self,
        target_index: int,
        *,
        reference_absolute_minute: Optional[float] = None,
    ) -> Dict[str, Any]:
        current = self._external_realtime_target_locked()
        point_count = int(current["point_count"])
        if target_index < 0 or target_index >= point_count:
            raise ValueError(
                f"目标曲线索引 {target_index} 越界，允许范围为 0..{point_count - 1}"
            )
        point_minute = target_index * float(current["time_step_minutes"])
        weather = self.curves.get("weather", [])
        if (
            isinstance(weather, Sequence)
            and not isinstance(weather, (str, bytes))
            and len(weather) > target_index
            and isinstance(weather[target_index], Mapping)
        ):
            point_minute = float(
                _to_float(weather[target_index].get("minute"), point_minute) or point_minute
            )
        reference = (
            float(reference_absolute_minute)
            if reference_absolute_minute is not None
            else float(current["absolute_minute"])
        )
        period_minutes = float(current["period_minutes"])
        cycle_start = math.floor(reference / period_minutes) * period_minutes
        absolute_minute = cycle_start + point_minute
        return {
            **current,
            "absolute_minute": absolute_minute,
            "simu_time": minute_to_time(absolute_minute),
            "index": target_index,
            "point_number": target_index + 1,
            "point_minute": point_minute,
        }

    def _external_batch_start_target_locked(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        index_keys = ("start_index", "start_point_index")
        point_number_keys = ("start_point_number",)
        has_index = any(key in payload for key in index_keys)
        has_point_number = any(key in payload for key in point_number_keys)
        has_time = any(
            key in payload
            for key in (
                "start_absolute_minute",
                "start_minute",
                "start_absolute_second",
                "start_second",
                "start_time",
            )
        )
        if not has_time:
            raise ValueError(
                "批量输入必须提供起始点时刻 start_time、start_absolute_minute 或 start_absolute_second"
            )

        index_target: Optional[Dict[str, Any]] = None
        if has_index:
            target_index = self._external_integer_field(
                payload,
                index_keys,
                required=True,
                minimum=0,
            )
            index_target = self._external_target_from_index_locked(int(target_index or 0))
        elif has_point_number:
            point_number = self._external_integer_field(
                payload,
                point_number_keys,
                required=True,
                minimum=1,
            )
            index_target = self._external_target_from_index_locked(int(point_number or 1) - 1)

        time_target: Optional[Dict[str, Any]] = None
        if has_time:
            absolute_minute = self._external_history_absolute_minute(payload, "start")
            time_target = self._external_realtime_target_for_time_locked(
                absolute_minute,
                "起始点时刻",
            )

        if index_target is not None and time_target is not None:
            if int(index_target["index"]) != int(time_target["index"]):
                raise ValueError("起始点索引与起始点时刻不一致")
        return time_target or self._external_realtime_target_locked()

    def _external_point_target_locked(
        self,
        payload: Mapping[str, Any],
        expected_index: int,
        expected_absolute_minute: Optional[float] = None,
    ) -> Dict[str, Any]:
        has_index = any(key in payload for key in ("target_index", "index"))
        has_point_number = any(key in payload for key in ("target_point_number", "point_number"))
        has_time = any(
            key in payload
            for key in (
                "target_absolute_minute",
                "target_minute",
                "target_absolute_second",
                "target_second",
                "target_time",
            )
        )
        target = (
            self._external_realtime_target_locked(expected_absolute_minute)
            if expected_absolute_minute is not None
            else self._external_target_from_index_locked(expected_index)
        )
        explicit_targets: List[Dict[str, Any]] = []
        if has_index:
            index = self._external_integer_field(
                payload,
                ("target_index", "index"),
                required=True,
                minimum=0,
            )
            explicit_targets.append(self._external_target_from_index_locked(int(index or 0)))
        if has_point_number:
            point_number = self._external_integer_field(
                payload,
                ("target_point_number", "point_number"),
                required=True,
                minimum=1,
            )
            explicit_targets.append(
                self._external_target_from_index_locked(int(point_number or 1) - 1)
            )
        if has_time:
            absolute_minute = self._external_history_absolute_minute(payload, "target")
            if (
                expected_absolute_minute is not None
                and abs(absolute_minute - expected_absolute_minute) > 1e-9
            ):
                raise ValueError(
                    "多点输入目标时刻不连续："
                    f"期望 {format_number(expected_absolute_minute)} 分钟，"
                    f"收到 {format_number(absolute_minute)} 分钟"
                )
            explicit_targets.append(
                self._external_realtime_target_for_time_locked(
                    absolute_minute,
                    "目标时刻",
                )
            )
        for explicit in explicit_targets:
            if int(explicit["index"]) != expected_index:
                raise ValueError(
                    f"多点输入目标不连续：期望索引 {expected_index}，收到 {explicit['index']}"
                )
            target = explicit
        return target

    def _normalize_external_realtime_request_locked(
        self,
        payload: Mapping[str, Any],
        catalog: Sequence[Mapping[str, str]],
    ) -> Dict[str, Any]:
        has_points = "points" in payload
        has_series = "series" in payload
        if has_points and has_series:
            raise ValueError("points 和 series 不能在同一请求中同时出现")

        current_target = self._external_realtime_target_locked()
        curve_point_count = int(current_target["point_count"])
        operations: List[Dict[str, Any]] = []
        updated_weather_fields: set[str] = set()
        updated_loads: set[str] = set()

        if has_points:
            raw_points = payload.get("points")
            if not isinstance(raw_points, Sequence) or isinstance(raw_points, (str, bytes)):
                raise ValueError("points 必须是非空数组")
            points = list(raw_points)
            if not points:
                raise ValueError("points 必须是非空数组")
            if any(not isinstance(item, Mapping) for item in points):
                raise ValueError("points 数组项必须是对象")
            contract = self._external_input_contract_locked(
                payload,
                expected_count=len(points),
                batch=True,
            )
            start_target = self._external_batch_start_target_locked(payload)
            start_index = int(start_target["index"])
            curve_step_count = int(contract["curve_step_count"])
            final_index = start_index + (len(points) - 1) * curve_step_count
            if final_index >= curve_point_count:
                raise ValueError(
                    "起始点、point_count 和数据点间隔共同确定的结束时刻超出曲线范围"
                )
            field_signature: Optional[Tuple[Tuple[str, ...], Tuple[str, ...]]] = None
            for offset, raw_item in enumerate(points):
                item = raw_item if isinstance(raw_item, Mapping) else {}
                expected_index = start_index + offset * curve_step_count
                expected_absolute_minute = (
                    float(start_target["absolute_minute"])
                    + offset * float(contract["point_interval_minutes"])
                )
                target = self._external_point_target_locked(
                    item,
                    expected_index,
                    expected_absolute_minute,
                )
                weather_values = self._normalize_external_realtime_weather(item)
                load_values = self._normalize_external_realtime_loads(item, catalog)
                if not weather_values and not load_values:
                    raise ValueError(f"points[{offset}] 至少提供一个天气量或负荷值")
                signature = (
                    tuple(sorted(weather_values)),
                    tuple(sorted(load_values)),
                )
                if field_signature is None:
                    field_signature = signature
                elif signature != field_signature:
                    raise ValueError("points 中每个数据点的天气字段和负荷字段必须完整且一致")
                updated_weather_fields.update(weather_values)
                updated_loads.update(load_values)
                operations.append(
                    {
                        "target": target,
                        "weather": weather_values,
                        "loads": load_values,
                    }
                )
            return {
                "update_mode": "points",
                "contract": contract,
                "start_target": start_target,
                "operations": operations,
                "updated_weather_fields": sorted(updated_weather_fields),
                "updated_loads": sorted(updated_loads),
            }

        if has_series:
            raw_series = payload.get("series")
            if not isinstance(raw_series, Mapping):
                raise ValueError("series 必须是对象")
            nested_weather = raw_series.get("weather", {})
            nested_loads = raw_series.get("loads", {})
            if nested_weather in (None, ""):
                nested_weather = {}
            if nested_loads in (None, ""):
                nested_loads = {}
            if not isinstance(nested_weather, Mapping):
                raise ValueError("series.weather 必须是对象")
            if not isinstance(nested_loads, Mapping):
                raise ValueError("series.loads 必须是对象")

            raw_weather_series: Dict[str, Any] = dict(nested_weather)
            raw_load_series: Dict[str, Any] = dict(nested_loads)
            for raw_key, raw_values in raw_series.items():
                key = str(raw_key)
                if key in {"weather", "loads"}:
                    continue
                if key in EXTERNAL_REALTIME_WEATHER_FIELD_SET:
                    if key in raw_weather_series:
                        raise ValueError(f"series 中重复定义 {key}")
                    raw_weather_series[key] = raw_values
                elif key.startswith("load:"):
                    load_key = key.replace("load:", "", 1)
                    if load_key in raw_load_series:
                        raise ValueError(f"series 中重复定义负荷 {load_key}")
                    raw_load_series[load_key] = raw_values
                else:
                    raise ValueError(f"series 包含不支持的曲线字段: {key}")
            if not raw_weather_series and not raw_load_series:
                raise ValueError("series 至少提供一条天气或负荷曲线")

            declared_count = self._external_integer_field(
                payload,
                ("point_count",),
                required=True,
                minimum=1,
            )
            contract = self._external_input_contract_locked(
                payload,
                expected_count=int(declared_count or 0),
                batch=True,
            )
            point_count = int(contract["point_count"])
            start_target = self._external_batch_start_target_locked(payload)
            start_index = int(start_target["index"])
            curve_step_count = int(contract["curve_step_count"])
            final_index = start_index + (point_count - 1) * curve_step_count
            if final_index >= curve_point_count:
                raise ValueError(
                    "起始点、point_count 和数据点间隔共同确定的结束时刻超出曲线范围"
                )

            weather_series: Dict[str, List[float]] = {}
            for raw_key, raw_values in raw_weather_series.items():
                key = str(raw_key)
                if key not in EXTERNAL_REALTIME_WEATHER_FIELD_SET:
                    raise ValueError(f"series.weather 包含不支持的字段: {key}")
                if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
                    raise ValueError(f"series.{key} 必须是数组")
                values = list(raw_values)
                if len(values) != point_count:
                    raise ValueError(
                        f"series.{key} 长度 {len(values)} 与 point_count={point_count} 不一致"
                    )
                weather_series[key] = [
                    self._normalize_external_realtime_weather({key: value})[key]
                    for value in values
                ]
                updated_weather_fields.add(key)

            by_key, by_name = self._external_load_lookup(catalog)
            load_series: Dict[str, List[float]] = {}
            for raw_key, raw_values in raw_load_series.items():
                canonical_key = self._resolve_external_load_key(raw_key, by_key, by_name)
                if canonical_key in load_series:
                    raise ValueError(f"series 中重复定义负荷 {canonical_key}")
                if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
                    raise ValueError(f"series 负荷 {canonical_key} 必须是数组")
                values = list(raw_values)
                if len(values) != point_count:
                    raise ValueError(
                        f"series 负荷 {canonical_key} 长度 {len(values)} 与 point_count={point_count} 不一致"
                    )
                normalized_values: List[float] = []
                for value in values:
                    number = self._external_finite_number(canonical_key, value)
                    if number < 0:
                        raise ValueError(f"{canonical_key} 不能小于 0")
                    normalized_values.append(number)
                load_series[canonical_key] = normalized_values
                updated_loads.add(canonical_key)

            for offset in range(point_count):
                absolute_minute = (
                    float(start_target["absolute_minute"])
                    + offset * float(contract["point_interval_minutes"])
                )
                target = self._external_realtime_target_for_time_locked(
                    absolute_minute,
                    f"第 {offset + 1} 个数据点时刻",
                )
                expected_index = start_index + offset * curve_step_count
                if int(target["index"]) != expected_index:
                    raise ValueError(
                        f"第 {offset + 1} 个数据点时刻未映射到预期曲线索引 {expected_index}"
                    )
                operations.append(
                    {
                        "target": target,
                        "weather": {
                            key: values[offset]
                            for key, values in weather_series.items()
                        },
                        "loads": {
                            key: values[offset]
                            for key, values in load_series.items()
                        },
                    }
                )
            return {
                "update_mode": "series",
                "contract": contract,
                "start_target": start_target,
                "operations": operations,
                "updated_weather_fields": sorted(updated_weather_fields),
                "updated_loads": sorted(updated_loads),
            }

        contract = self._external_input_contract_locked(
            payload,
            expected_count=1,
            batch=False,
        )
        weather_values = self._normalize_external_realtime_weather(payload)
        load_values = self._normalize_external_realtime_loads(payload, catalog)
        if not weather_values and not load_values:
            raise ValueError("至少提供一个天气量或负荷值")

        target = current_target
        has_start_time = any(
            key in payload
            for key in (
                "start_absolute_minute",
                "start_minute",
                "start_absolute_second",
                "start_second",
                "start_time",
            )
        )
        if has_start_time:
            start_minute = self._external_history_absolute_minute(payload, "start")
            target = self._external_realtime_target_for_time_locked(
                start_minute,
                "起始点时刻",
            )
        if any(
            key in payload
            for key in (
                "target_absolute_minute",
                "target_minute",
                "target_absolute_second",
                "target_second",
                "target_time",
            )
        ):
            target_minute = self._external_history_absolute_minute(payload, "target")
            explicit_target = self._external_realtime_target_for_time_locked(
                target_minute,
                "目标时刻",
            )
            if has_start_time and int(explicit_target["index"]) != int(target["index"]):
                raise ValueError("单点输入的起始时刻与目标时刻不一致")
            target = explicit_target
        elif any(key in payload for key in ("target_index", "index")):
            target_index = self._external_integer_field(
                payload,
                ("target_index", "index"),
                required=True,
                minimum=0,
            )
            explicit_target = self._external_target_from_index_locked(int(target_index or 0))
            if has_start_time and int(explicit_target["index"]) != int(target["index"]):
                raise ValueError("单点输入的起始时刻与目标索引不一致")
            target = explicit_target
        elif any(key in payload for key in ("target_point_number", "point_number")):
            point_number = self._external_integer_field(
                payload,
                ("target_point_number", "point_number"),
                required=True,
                minimum=1,
            )
            explicit_target = self._external_target_from_index_locked(int(point_number or 1) - 1)
            if has_start_time and int(explicit_target["index"]) != int(target["index"]):
                raise ValueError("单点输入的起始时刻与目标点号不一致")
            target = explicit_target
        target = self._external_point_target_locked(
            payload,
            int(target["index"]),
            float(target["absolute_minute"]),
        )
        return {
            "update_mode": "single_point",
            "contract": contract,
            "start_target": target,
            "operations": [
                {
                    "target": target,
                    "weather": weather_values,
                    "loads": load_values,
                }
            ],
            "updated_weather_fields": sorted(weather_values),
            "updated_loads": sorted(load_values),
        }

    def external_realtime_input_schema(self) -> Dict[str, Any]:
        with self.lock, self.curves_lock:
            target = self._external_realtime_target_locked()
            load_catalog = self._external_load_catalog()
            return {
                **self._external_response_metadata(),
                "endpoint": "/api/external/realtime-inputs",
                "methods": ["GET", "POST"],
                "weather_fields": [
                    {"key": key, "unit": unit}
                    for key, unit in EXTERNAL_REALTIME_WEATHER_FIELDS
                ],
                "loads": load_catalog,
                "target_point": target,
                "curve_contract": {
                    "point_count": target["point_count"],
                    "point_interval_minutes": target["time_step_minutes"],
                    "point_interval_seconds": float(target["time_step_minutes"]) * 60.0,
                    "start_fields": [
                        "start_time",
                        "start_absolute_minute",
                        "start_absolute_second",
                    ],
                    "start_time_is_authoritative": True,
                    "batch_requires_start_time_count_and_interval": True,
                    "interval_must_be_curve_step_multiple": True,
                    "series_lengths_must_equal_point_count": True,
                    "point_fields_must_be_complete_and_consistent": True,
                },
                "request_formats": {
                    "single_point": {
                        "description": "未提供时标时写入下一未求解点；也可显式提供起始时刻",
                        "legacy_without_contract_supported": True,
                    },
                    "multiple_points": {
                        "container": "points",
                        "required": ["start_time", "point_count", "point_interval_seconds|minutes"],
                    },
                    "series": {
                        "container": "series",
                        "required": ["start_time", "point_count", "point_interval_seconds|minutes"],
                    },
                },
                "example_request": {
                    "start_time": target["simu_time"],
                    "point_count": 1,
                    "point_interval_seconds": float(target["time_step_minutes"]) * 60.0,
                    "weather": {
                        "wind_speed_mps": 9.6,
                        "solar_irradiance_w_m2": 650,
                        "air_temp_c": -12,
                        "air_pressure_hpa": 965,
                        "humidity_pct": 70,
                    },
                    "loads": {
                        item["key"]: 100
                        for item in load_catalog[:2]
                    },
                },
                "applies_on_next_power_flow": True,
            }

    def apply_external_realtime_inputs(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("请求体必须是 JSON 对象")
        with self._step_lock:
            with self.lock, self.curves_lock:
                catalog = self._external_load_catalog()
                normalized = self._normalize_external_realtime_request_locked(payload, catalog)
                operations = list(normalized["operations"])
                current_target = self._external_realtime_target_locked()
                point_count = int(current_target["point_count"])
                step_minutes = float(current_target["time_step_minutes"])
                weather_points = self.curves.get("weather")
                if not isinstance(weather_points, list):
                    weather_points = []
                    self.curves["weather"] = weather_points
                while len(weather_points) < point_count:
                    index = len(weather_points)
                    weather_points.append({"minute": index * step_minutes, **DEFAULT_WEATHER})

                catalog_by_name: Dict[str, List[str]] = {}
                for item in catalog:
                    catalog_by_name.setdefault(item["dev_name"], []).append(item["key"])
                configured_loads = self.curves.get("loads", {})
                curve_key_by_load: Dict[str, str] = {}
                for canonical_key in normalized["updated_loads"]:
                    _dev_type, dev_name = canonical_key.split(":", 1)
                    curve_key = canonical_key
                    if isinstance(configured_loads, Mapping):
                        if canonical_key in configured_loads:
                            curve_key = canonical_key
                        elif dev_name in configured_loads and len(catalog_by_name.get(dev_name, [])) == 1:
                            curve_key = dev_name
                    curve_key_by_load[canonical_key] = curve_key

                load_points_by_key: Dict[str, List[Dict[str, Any]]] = {}
                loads = self.curves.get("loads")
                if not isinstance(loads, dict):
                    loads = {}
                    self.curves["loads"] = loads
                for canonical_key, curve_key in curve_key_by_load.items():
                    points = loads.get(curve_key)
                    if not isinstance(points, list):
                        points = []
                        loads[curve_key] = points
                    while len(points) < point_count:
                        index = len(points)
                        points.append(
                            {
                                "minute": index * step_minutes,
                                "p_kw": DEFAULT_WEATHER["load_kw"],
                            }
                        )
                    load_points_by_key[canonical_key] = points

                point_results: List[Dict[str, Any]] = []
                updated_indices: set[int] = set()
                for operation in operations:
                    target = operation["target"]
                    target_index = int(target["index"])
                    updated_indices.add(target_index)
                    if not isinstance(weather_points[target_index], dict):
                        weather_points[target_index] = {
                            "minute": target_index * step_minutes,
                            **DEFAULT_WEATHER,
                        }
                    weather_points[target_index].setdefault(
                        "minute",
                        target_index * step_minutes,
                    )
                    for key, value in operation["weather"].items():
                        weather_points[target_index][key] = value
                    for canonical_key, value in operation["loads"].items():
                        points = load_points_by_key[canonical_key]
                        if not isinstance(points[target_index], dict):
                            points[target_index] = {
                                "minute": target_index * step_minutes,
                                "p_kw": points[target_index],
                            }
                        points[target_index].setdefault(
                            "minute",
                            target_index * step_minutes,
                        )
                        points[target_index]["p_kw"] = value
                    if normalized["update_mode"] != "series":
                        point_results.append(
                            {
                                "target_absolute_minute": target["absolute_minute"],
                                "target_simu_time": target["simu_time"],
                                "target_index": target_index,
                                "target_point_number": target["point_number"],
                                "weather": operation["weather"],
                                "loads": operation["loads"],
                            }
                        )

                _write_json(self.curves_file, self.curves)
                self._curve_revision += 1
                sorted_indices = sorted(updated_indices)
                start_target = normalized["start_target"]
                end_target = operations[-1]["target"]
                applies_on_next_power_flow = int(current_target["index"]) in updated_indices
                self._append_runtime_log(
                    "外部实时输入",
                    "weather / load curves",
                    "已按时标写入曲线",
                    [
                        f"输入模式 {normalized['update_mode']}，起始时刻 {start_target['simu_time']}，结束时刻 {end_target['simu_time']}",
                        f"数据点 {normalized['contract']['point_count']} 个，间隔 {format_number(normalized['contract']['point_interval_seconds'])} 秒，更新曲线点 {len(sorted_indices)} 个",
                        "天气字段 " + ("，".join(normalized["updated_weather_fields"]) or "未更新"),
                        "负荷字段 " + ("，".join(normalized["updated_loads"]) or "未更新"),
                        "已更新运行曲线；潮流后台将在对应仿真时刻读取，接口未主动推进仿真时钟",
                    ],
                    level="ok",
                    simu_time=str(start_target["simu_time"]),
                )
                legacy_operation = operations[0]
                legacy_target = legacy_operation["target"]
                return {
                    **self._external_response_metadata(),
                    "update_mode": normalized["update_mode"],
                    "input_point_count": normalized["contract"]["point_count"],
                    "point_interval_minutes": normalized["contract"]["point_interval_minutes"],
                    "point_interval_seconds": normalized["contract"]["point_interval_seconds"],
                    "curve_step_count": normalized["contract"]["curve_step_count"],
                    "start_absolute_minute": start_target["absolute_minute"],
                    "start_simu_time": start_target["simu_time"],
                    "start_index": start_target["index"],
                    "end_absolute_minute": end_target["absolute_minute"],
                    "end_simu_time": end_target["simu_time"],
                    "end_index": end_target["index"],
                    "target_absolute_minute": legacy_target["absolute_minute"],
                    "target_simu_time": legacy_target["simu_time"],
                    "target_index": legacy_target["index"],
                    "target_point_number": legacy_target["point_number"],
                    "target_curve_minute": legacy_target["point_minute"],
                    "weather": legacy_operation["weather"] if normalized["update_mode"] == "single_point" else {},
                    "loads": legacy_operation["loads"] if normalized["update_mode"] == "single_point" else {},
                    "point_results": point_results,
                    "updated_indices": sorted_indices,
                    "updated_point_numbers": [index + 1 for index in sorted_indices],
                    "updated_point_count": len(sorted_indices),
                    "updated_weather_fields": normalized["updated_weather_fields"],
                    "updated_loads": normalized["updated_loads"],
                    "covers_full_curve": bool(
                        int(start_target["index"]) == 0
                        and int(normalized["contract"]["curve_step_count"]) == 1
                        and int(normalized["contract"]["point_count"]) == point_count
                    ),
                    "curve_revision": self._curve_revision,
                    "applies_on_next_power_flow": applies_on_next_power_flow,
                    "applies_to_power_flow_backend": True,
                    "next_power_flow_target": current_target,
                    "curve_boundary": self.curve_boundary(),
                }

    def set_local_settings(self, payload: Mapping[str, Any]) -> Dict[str, int]:
        with self.lock:
            measurement_cache_changed = False
            aliases = {
                "device_faults": ("device_faults", "deviceFaults", "faults"),
                "measurement_faults": ("measurement_faults", "measurementFaults", "meas_faults"),
                "measurement_statuses": ("measurement_statuses", "measurementStatuses"),
                "modes": ("modes", "device_modes", "deviceModes"),
            }
            for target_key, names in aliases.items():
                for name in names:
                    if name in payload:
                        value = payload.get(name) or []
                        if target_key == "measurement_statuses":
                            normalized_value = dict(value) if isinstance(value, Mapping) else {}
                        else:
                            normalized_value = list(value) if isinstance(value, Sequence) else []
                        if self.local_settings.get(target_key) != normalized_value:
                            self.local_settings[target_key] = normalized_value
                            if target_key in {"measurement_faults", "measurement_statuses"}:
                                measurement_cache_changed = True
                        break
            if measurement_cache_changed:
                self._invalidate_measurement_delta_cache()
            _write_json(self.settings_file, self.local_settings)
            return {
                "device_faults": len(self.local_settings.get("device_faults", [])),
                "measurement_faults": len(self.local_settings.get("measurement_faults", [])),
                "measurement_statuses": len(self.local_settings.get("measurement_statuses", {})),
                "modes": len(self.local_settings.get("modes", [])),
            }

    def _invalidate_automatic_runtime_state_for_simulation_reset(self) -> None:
        """Drop the completed automatic frame while preserving manual definitions and controls."""

        # Keep the current, possibly manually edited definition rows available to
        # clients, but detach every calculated value from the new lifecycle.
        current_measurements = self.measurements()
        definitions = [
            dict(row)
            for row in current_measurements.get("definitions", [])
            if isinstance(row, Mapping)
        ]
        self.latest_real_rows = []
        self.latest_scada_rows = []
        self._automatic_runtime_state_invalidated = True
        self.latest_measurements = {
            "definitions": definitions,
            "real": [],
            "scada": [],
        }
        self.latest_measurement_clock = {}
        self.latest_result = {}
        self.latest_model_book = None
        self.latest_device_states = []
        self._last_scada_values = {}
        self._latest_power_summary_cache_key = None
        self._latest_power_summary_cache_value = None
        self._device_runtime_frame_cache_key = None
        self._device_runtime_frame_cache_value = None
        self._measurement_history.clear()

        # Keep the sequence monotonic across a same-service clock reset.  The
        # empty history then forces every cursor from the previous lifecycle to
        # receive a full reset frame instead of accidentally matching by seq.
        self._measurement_delta_seq += 1
        self._measurement_delta_state = self._measurement_delta_current_items(
            self.latest_measurements,
            measurement_clock=self.clock.as_dict(),
        )
        self._measurement_delta_history = []
        self._measurement_delta_definition_signature = measurement_definition_signature(
            definitions
        )
        self._measurement_delta_definition_count = len(definitions)
        self._measurement_delta_definition_revision = self.definition_snapshot.revision
        self._measurement_delta_step_count = self.clock.step_count
        self._measurement_delta_runtime_marker = self._measurement_delta_runtime_state_marker()

        compute = dict(self.latest_compute)
        self.latest_compute = {
            "mode": str(compute.get("mode", "embedded")),
            "http_pid": int(compute.get("http_pid", os.getpid()) or os.getpid()),
            "worker_pid": int(compute.get("worker_pid", 0) or 0),
            "compute_ms": 0.0,
            "round_trip_ms": 0.0,
            "status": "idle",
            "resident_model": bool(compute.get("resident_model", self.kernel_runner is None)),
        }

        for path in (self.files["real"], self.files["scada"]):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def control_clock(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            action = str(payload.get("action", "")).lower()
            previous_state = self.clock.state
            previous_absolute_minute = float(self.clock.absolute_minute)
            if "step_seconds" in payload:
                step_seconds = float(_to_float(payload.get("step_seconds"), self.clock.step_minutes * 60.0) or 0.0)
                self.clock.step_minutes = max(1e-9, step_seconds / 60.0)
            if "step_minutes" in payload:
                self.clock.step_minutes = max(
                    1e-9,
                    float(_to_float(payload.get("step_minutes"), self.clock.step_minutes) or self.clock.step_minutes),
                )
            requested_absolute_minute: Optional[float] = None
            if "absolute_second" in payload or "second" in payload:
                second = float(
                    _to_float(payload.get("absolute_second", payload.get("second")), self.clock.absolute_minute * 60.0)
                    or 0.0
                )
                requested_absolute_minute = max(0.0, second / 60.0)
            elif "minute" in payload:
                requested_absolute_minute = max(
                    0.0,
                    float(_to_float(payload.get("minute"), self.clock.minute) or 0.0),
                )
            if "speed" in payload:
                self.clock.speed = _nearest_clock_speed(payload.get("speed"))
            starts_new_lifecycle = action == "start" and (
                previous_state == "stopped"
                or (
                    requested_absolute_minute is not None
                    and (
                        requested_absolute_minute <= 1e-9
                        or requested_absolute_minute < previous_absolute_minute - 1e-9
                    )
                )
            )
            time_reset_requested = bool(
                requested_absolute_minute is not None
                and (
                    requested_absolute_minute <= 1e-9
                    or requested_absolute_minute < previous_absolute_minute - 1e-9
                )
            )
            remove_automatic_command_history = bool(
                self.clear_commands_on_start_and_reset
                and (starts_new_lifecycle or action == "stop" or time_reset_requested)
            )
            commands_cleared = False
            if remove_automatic_command_history:
                cleared = self._remove_automatic_command_history_for_restart()
                commands_cleared = True
                if cleared["entries"]:
                    self._append_runtime_log(
                        "控制指令",
                        "仿真时钟",
                        "自动指令已清空",
                        [
                            f"模拟台重启或归零前清空自动指令记录 {cleared['entries']} 条",
                            (
                                f"涉及遥控 {cleared['remote_controls']} 个控制点，"
                                f"遥调 {cleared['remote_adjustments']} 个控制点"
                            ),
                            "人工指令继续保持，人工界面修改不受影响",
                        ],
                        level="ok",
                        simu_time=minute_to_time(self.clock.minute),
                    )
            elif starts_new_lifecycle or action == "stop" or time_reset_requested:
                cleared = self._clear_automatic_commands_for_simulation_restart()
                if cleared["entries"]:
                    self._write_command_history()
                    self._append_runtime_log(
                        "控制指令",
                        "仿真时钟",
                        "自动指令已清空",
                        [
                            f"新仿真生命周期启动前清空自动指令记录 {cleared['entries']} 条",
                            (
                                f"涉及遥控 {cleared['remote_controls']} 个控制点，"
                                f"遥调 {cleared['remote_adjustments']} 个控制点"
                            ),
                            "人工指令继续保持，直至人工退出",
                        ],
                        level="ok",
                        simu_time=minute_to_time(self.clock.minute),
                    )
            if requested_absolute_minute is not None:
                self.clock.absolute_minute = requested_absolute_minute
                self.clock.minute = requested_absolute_minute % 1440.0
            history_reset_requested = bool(
                starts_new_lifecycle
                or action == "stop"
                or time_reset_requested
            )
            should_reset_storage_soc = False
            if time_reset_requested and not starts_new_lifecycle:
                self.clock.step_count = 0
                should_reset_storage_soc = True
            if action == "start":
                if starts_new_lifecycle:
                    self.clock.run_id += 1
                    self.clock.step_count = 0
                    should_reset_storage_soc = True
                self.clock.state = "running"
            elif action == "pause":
                self.clock.state = "paused"
            elif action == "stop":
                self.clock.state = "stopped"
                self.clock.absolute_minute = 0.0
                self.clock.minute = 0.0
                self.clock.step_count = 0
                should_reset_storage_soc = True
            elif action in ("faster", "speed_up"):
                self.clock.speed = _next_clock_speed(self.clock.speed)
            elif action in ("slower", "speed_down"):
                self.clock.speed = _previous_clock_speed(self.clock.speed)
            effective_step = _effective_clock_step(self.clock.step_minutes, self.clock.speed)
            self.clock.absolute_minute = _align_minute_to_step(self.clock.absolute_minute, effective_step)
            self.clock.minute = self.clock.absolute_minute % 1440.0
            if should_reset_storage_soc:
                self._reset_storage_soc_to_initial()
                self._reset_hydrogen_storage_state_to_initial()
            if history_reset_requested:
                self._invalidate_automatic_runtime_state_for_simulation_reset()
            if action in ("start", "stop") or commands_cleared or time_reset_requested:
                self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            if action == "step":
                return self.step(advance_minutes=effective_step)["clock"]
            self.clock.updated_at = time.time()
            return self.clock.as_dict()

    def clock_state(self) -> Dict[str, Any]:
        """Return only the scheduler clock state without assembling a service snapshot."""
        with self.lock:
            return self.clock.as_dict()

    def step(
        self,
        advance_minutes: Optional[int | float] = None,
        *,
        advance_seconds: Optional[int | float] = None,
        return_snapshot: bool = True,
    ) -> Optional[Dict[str, Any]]:
        with self._step_lock:
            with self.lock:
                if advance_seconds is not None:
                    clock_advance = max(1e-9, float(advance_seconds) / 60.0)
                elif advance_minutes is not None:
                    clock_advance = max(1e-9, float(advance_minutes))
                else:
                    clock_advance = _effective_clock_step(self.clock.step_minutes, self.clock.speed)
                self.clock.absolute_minute = _align_minute_to_step(self.clock.absolute_minute, clock_advance)
                self.clock.minute = self.clock.absolute_minute % 1440.0
                period_seconds = clock_advance * 60.0
                minute = self.clock.minute
                absolute_minute = self.clock.absolute_minute
                start_clock_state = self.clock.state
                start_run_id = self.clock.run_id
                start_step_count = self.clock.step_count
                definition_revision = self.definition_snapshot.revision
                curve_revision = self._curve_revision
                self._remote_adjustment_cycle_seq += 1
                boundary_stat_book, boundary_yt_ctrl_book = self._prepare_runtime_inputs(
                    minute,
                    absolute_minute,
                    remote_adjustment_cycle_token=self._remote_adjustment_cycle_seq,
                )
                config = self._make_config(
                    period_seconds=period_seconds,
                    dev_stat_book=boundary_stat_book,
                    yt_ctrl_book=boundary_yt_ctrl_book,
                )

            execution_started = time.perf_counter()
            try:
                execution = self._execute_kernel(config)
            except Exception as exc:
                elapsed = max(0.0, time.perf_counter() - execution_started)
                compute_status = "timeout" if isinstance(exc, PowerFlowTimeoutError) else "failed"
                with self.lock:
                    last_successful_simu_time = str(
                        self.latest_measurement_clock.get("time", "") or ""
                    )
                    if start_clock_state == "running":
                        self.clock.state = "paused"
                    self.latest_compute = {
                        "mode": "process" if self.kernel_runner is not None else "embedded",
                        "http_pid": os.getpid(),
                        "worker_pid": (
                            int(self.latest_compute.get("worker_pid", 0) or 0)
                            if self.kernel_runner is not None
                            else os.getpid()
                        ),
                        "compute_ms": round(elapsed * 1000.0, 3),
                        "round_trip_ms": round(elapsed * 1000.0, 3),
                        "status": compute_status,
                        "resident_model": self.kernel_runner is None,
                        "error": f"{type(exc).__name__}: {exc}",
                        "simu_time": minute_to_time(minute),
                        "absolute_minute": float(absolute_minute),
                        "failed_at": _now_text(),
                        "result_discarded": True,
                        "measurement_frame_stale": True,
                        "last_successful_simu_time": last_successful_simu_time,
                    }
                    self.latest_result = {
                        "solver_info": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    self._append_power_flow_failure_log(
                        exc,
                        minute,
                        absolute_minute,
                        clock_advance,
                        period_seconds,
                        auto_paused=start_clock_state == "running",
                    )
                    self.clock.updated_at = time.time()
                raise

            with self.lock:
                stale = (
                    not self.service_instance_active()
                    or self.definition_snapshot.revision != definition_revision
                    or self._curve_revision != curve_revision
                    or self.clock.run_id != start_run_id
                    or self.clock.step_count != start_step_count
                    or abs(float(self.clock.absolute_minute) - float(absolute_minute)) > 1e-9
                    or (start_clock_state != "stopped" and self.clock.state == "stopped")
                )
                if stale:
                    self._record_compute_execution(execution, status="discarded")
                    self.clock.updated_at = time.time()
                    if return_snapshot:
                        return self.snapshot()
                    return None

                if execution.runtime_stat_book is not None:
                    self._merge_execution_runtime_stat_book(execution.runtime_stat_book)
                kernel_result = execution.result
                self._record_compute_execution(execution)
                self.latest_model_book = getattr(kernel_result, "model_book", None)
                self.latest_device_states = [
                    dict(item)
                    for item in (getattr(kernel_result, "device_states", None) or [])
                    if isinstance(item, Mapping)
                ]
                self._store_kernel_measurement_rows(kernel_result)
                self._apply_measurement_faults(minute, absolute_minute)
                self._apply_measurement_statuses(minute, absolute_minute)
                self._automatic_runtime_state_invalidated = False
                self.latest_measurements = self.measurements()
                measurement_updated_at = time.time()
                measurement_clock = self.clock.as_dict()
                measurement_clock["step_count"] = self.clock.step_count + 1
                measurement_clock["updated_at"] = measurement_updated_at
                self.latest_measurement_clock = measurement_clock
                result_dict = self._kernel_result_dict(kernel_result)
                self.latest_result = result_dict
                command_response_lines = self._collect_command_response_lines(result_dict)
                self._append_power_flow_log(
                    result_dict,
                    self.latest_measurements,
                    minute,
                    absolute_minute,
                    clock_advance,
                    period_seconds,
                    command_response_lines,
                )
                next_absolute_minute = self.clock.absolute_minute + clock_advance
                crossed_cycle_start = self._crossed_simulation_cycle_start(
                    self.clock.absolute_minute,
                    next_absolute_minute,
                )
                self.clock.absolute_minute = round(next_absolute_minute, 9)
                self.clock.minute = self.clock.absolute_minute % 1440.0
                self.clock.step_count += 1
                self.clock.updated_at = measurement_updated_at
                if crossed_cycle_start:
                    self._reset_storage_soc_to_initial()
                    self._reset_hydrogen_storage_state_to_initial()
                    if self.clear_commands_on_start_and_reset:
                        cleared = self._remove_automatic_command_history_for_restart()
                    else:
                        cleared = self._clear_automatic_commands_for_simulation_restart(
                            reason="simulation_cycle_reset",
                        )
                        if cleared["entries"]:
                            self._write_command_history()
                    self._materialize_active_control_commands(
                        self.clock.absolute_minute,
                        persist=True,
                    )
                    if cleared["entries"]:
                        self._append_runtime_log(
                            "控制指令",
                            "仿真时钟",
                            "周期归零自动指令已清空",
                            [
                                f"新仿真周期开始前清空自动指令记录 {cleared['entries']} 条",
                                (
                                    f"涉及遥控 {cleared['remote_controls']} 个控制点，"
                                    f"遥调 {cleared['remote_adjustments']} 个控制点"
                                ),
                                "人工指令继续保持，自动指令对潮流边界的影响已撤销",
                            ],
                            level="ok",
                            simu_time=minute_to_time(self.clock.minute),
                        )
                    self._invalidate_automatic_runtime_state_for_simulation_reset()
                else:
                    self._refresh_measurement_delta_state(
                        measurements=self.latest_measurements,
                        measurement_clock=measurement_clock,
                    )
                    self._measurement_delta_step_count = self.clock.step_count
                    self._measurement_history.append(
                        measurement_clock,
                        self.latest_measurements,
                        definition_revision=self.definition_snapshot.revision,
                    )
                if return_snapshot:
                    return self.snapshot()
                return None

    def _store_kernel_measurement_rows(self, result: Optional[simu_loop.SimulationResult]) -> None:
        if result is None:
            return
        real_rows = getattr(result, "real_rows", None)
        scada_rows = getattr(result, "scada_rows", None)
        changed = False
        if real_rows is not None:
            self.latest_real_rows = [list(row) for row in real_rows]
            changed = True
        if scada_rows is not None:
            self.latest_scada_rows = [list(row) for row in scada_rows]
            changed = True
        if changed:
            self._invalidate_measurement_delta_cache()

    def _prepare_runtime_inputs(
        self,
        minute: int | float,
        absolute_minute: int | float,
        *,
        remote_adjustment_cycle_token: Optional[int] = None,
    ) -> Tuple[EBook, EBook]:
        if remote_adjustment_cycle_token is None:
            self._remote_adjustment_cycle_seq += 1
            remote_adjustment_cycle_token = self._remote_adjustment_cycle_seq
        self._write_current_weather(minute, absolute_minute)
        self._materialize_active_control_commands(absolute_minute)
        self._apply_device_faults(minute, absolute_minute)
        self._write_modes_file()
        return self._remote_adjustment_boundary_books(
            absolute_minute,
            remote_adjustment_cycle_token,
        )

    def _write_current_weather(self, minute: int | float, absolute_minute: int | float | None = None) -> None:
        curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        period_minutes = _simulation_mode_duration_minutes(curve_mode)
        target_minute = absolute_minute if absolute_minute is not None else minute
        row = {"time": minute_to_time(minute)}
        for key, default in self.weather_defaults.items():
            row[key] = _number_text(
                self._interpolate_curve_series(
                    self.curves.get("weather", []),
                    target_minute,
                    key,
                    default,
                    period_minutes=period_minutes,
                )
            )
        load_targets = self._current_load_power_targets(float(target_minute), period_minutes)
        load_total = sum(float(target["p_kw"]) for target in load_targets)
        load_seen = bool(load_targets)
        load_details = [(str(target["dev_name"]), float(target["p_kw"])) for target in load_targets]
        row["load_kw"] = _number_text(load_total if load_seen else self.weather_defaults.get("load_kw", 0.0))
        self._write_weather_row(row, load_targets=load_targets)
        self._append_environment_load_log(
            minute,
            float(target_minute),
            period_minutes,
            row,
            load_details,
            load_seen=load_seen,
        )

    def _interpolate_curve_series(
        self,
        points: Sequence[Mapping[str, Any]],
        minute: int | float,
        key: str,
        default: Optional[float],
        *,
        period_minutes: float,
    ) -> Optional[float]:
        if self._compiled_curve_revision != self._curve_revision:
            self._compiled_curve_revision = self._curve_revision
            self._compiled_curve_series_cache.clear()
            self._load_curve_target_cache_key = None
            self._load_curve_target_cache_value = {}
        cache_key = (id(points), str(key), float(period_minutes))
        series = self._compiled_curve_series_cache.get(cache_key)
        if series is None:
            series = _compile_interpolation_series(points, key, period_minutes)
            self._compiled_curve_series_cache[cache_key] = series
        return _interpolate_compiled_series(
            series,
            minute,
            default,
            period_minutes=period_minutes,
        )

    def _load_curve_targets(self) -> Dict[str, Tuple[int, Tuple[Tuple[str, str], ...]]]:
        definition_revision = self.definition_snapshot.revision
        cache_key = (definition_revision, self._curve_revision)
        if self._load_curve_target_cache_key == cache_key:
            return self._load_curve_target_cache_value

        model_book = self.definition_snapshot.model_book
        model_targets: Dict[str, List[Tuple[str, str]]] = {}
        for block_name in ("ACLoad", "DCLoad"):
            block = model_book.data.get(block_name)
            if block is None:
                continue
            for model_row in block.data:
                name = str(model_row.get("name", "")).strip()
                if name:
                    model_targets.setdefault(name, []).append((block_name, name))

        resolved: Dict[str, Tuple[int, Tuple[Tuple[str, str], ...]]] = {}
        loads = self.curves.get("loads", {})
        if isinstance(loads, Mapping):
            for raw_name in loads:
                curve_name = str(raw_name).strip()
                if not curve_name:
                    continue
                explicit_type = ""
                model_name = curve_name
                prefix, separator, suffix = curve_name.partition(":")
                if separator and prefix in {"ACLoad", "DCLoad"}:
                    explicit_type = prefix
                    model_name = suffix.strip()
                matches = model_targets.get(model_name, [])
                if explicit_type:
                    matches = [match for match in matches if match[0] == explicit_type]
                resolved[curve_name] = (
                    1 if explicit_type else 0,
                    tuple(matches),
                )
        self._load_curve_target_cache_key = cache_key
        self._load_curve_target_cache_value = resolved
        return resolved

    def _current_load_power_targets(
        self,
        target_minute: float,
        period_minutes: float,
    ) -> List[Dict[str, Any]]:
        loads = self.curves.get("loads", {})
        if not isinstance(loads, Mapping):
            return []

        curve_targets = self._load_curve_targets()
        manual_overrides = self._manual_source_curve_override_keys()
        active_commands = self._active_remote_adjustment_keys(target_minute)
        inactive_coupling_keys = self._inactive_coupling_default_curve_keys()
        targets_by_device: Dict[Tuple[str, str], Tuple[int, Dict[str, Any]]] = {}
        for raw_name, points in loads.items():
            curve_name = str(raw_name).strip()
            if not curve_name:
                continue
            priority, matches = curve_targets.get(curve_name, (0, ()))
            value = self._interpolate_curve_series(
                points,
                target_minute,
                "p_kw",
                float("nan"),
                period_minutes=period_minutes,
            )
            if value != value:
                continue
            for block_name, dev_name in matches:
                key = (block_name, dev_name)
                control_key = (block_name, dev_name, "p_set")
                if (
                    control_key in manual_overrides
                    or control_key in active_commands
                    or control_key in inactive_coupling_keys
                ):
                    continue
                current = targets_by_device.get(key)
                if current is not None and current[0] > priority:
                    continue
                targets_by_device[key] = (
                    priority,
                    {
                        "dev_type": block_name,
                        "dev_name": dev_name,
                        "p_kw": max(0.0, float(value)),
                    },
                )
        return [targets_by_device[key][1] for key in sorted(targets_by_device)]

    def _write_weather_row(
        self,
        row: Mapping[str, Any],
        *,
        load_targets: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        clean = {
            header: UNKNOWN_WEATHER_VALUE if row.get(header, "") is None else row.get(header, "")
            for header in WEATHER_HEADER
        }
        blocks: Dict[str, Tuple[Sequence[str], Sequence[Mapping[str, Any]]]] = {
            "Weather": (WEATHER_HEADER, [clean])
        }
        if load_targets:
            blocks["LoadPower"] = (RUNTIME_LOAD_POWER_HEADER, load_targets)
        self.weather_book = _make_book(blocks)

    def _apply_device_faults(self, minute: int | float, absolute_minute: int | float) -> None:
        book = self.runtime_stat_book
        run_block = _ensure_block(book, "RunStat", STAT_HEADERS["RunStat"])
        cb_block = _ensure_block(book, "CbOpenStat", STAT_HEADERS["CbOpenStat"])
        active_keys: set[Tuple[str, str, str]] = set()

        curve_mode = str(self.curves.get("mode", "day") or "day").lower()
        for fault in self.local_settings.get("device_faults", []):
            if not isinstance(fault, Mapping) or not _active_window(fault, minute, absolute_minute, curve_mode):
                continue
            dev_type = str(fault.get("dev_type", fault.get("type", "")))
            dev_name = str(fault.get("dev_name", fault.get("name", "")))
            if not dev_type or not dev_name:
                continue
            run_key = ("RunStat", dev_type, dev_name)
            active_keys.add(run_key)
            run_row = _find_dev_row(run_block, dev_type, dev_name)
            if run_row is None:
                run_row = {"dev_type": dev_type, "dev_name": dev_name, "run_stat": "1"}
                run_block.data.append(run_row)
            if run_key not in self._fault_restore:
                self._fault_restore[run_key] = str(run_row.get("run_stat", "1"))
            run_row["run_stat"] = _number_text(fault.get("run_stat", 0))

            if "status" in fault or dev_type.endswith("Break") or dev_type.endswith("Switch"):
                cb_key = ("CbOpenStat", dev_type, dev_name)
                active_keys.add(cb_key)
                cb_row = _find_dev_row(cb_block, dev_type, dev_name)
                if cb_row is None:
                    cb_row = {"dev_type": dev_type, "dev_name": dev_name, "status": "1"}
                    cb_block.data.append(cb_row)
                if cb_key not in self._fault_restore:
                    self._fault_restore[cb_key] = str(cb_row.get("status", "1"))
                cb_row["status"] = _number_text(fault.get("status", 0))

        for key, old_value in list(self._fault_restore.items()):
            if key in active_keys:
                continue
            block_name, dev_type, dev_name = key
            block = run_block if block_name == "RunStat" else cb_block
            value_column = "run_stat" if block_name == "RunStat" else "status"
            row = _find_dev_row(block, dev_type, dev_name)
            if row is not None:
                row[value_column] = old_value
            del self._fault_restore[key]

        self.runtime_stat_book = book

    def _write_modes_file(self) -> None:
        modes = self.local_settings.get("modes", [])
        if not modes:
            self.mode_book = None
            return
        rows: List[Dict[str, Any]] = []
        for mode in modes:
            if not isinstance(mode, Mapping):
                continue
            dev_type = str(mode.get("dev_type", mode.get("type", "")))
            dev_name = str(mode.get("dev_name", mode.get("name", "")))
            mode_value = str(mode.get("mode", mode.get("control_type", "")))
            if not dev_type or not dev_name or not mode_value:
                continue
            rows.append({"dev_type": dev_type, "dev_name": dev_name, "mode": mode_value})
        if not rows:
            self.mode_book = None
            return
        self.mode_book = _make_book({"ControlMode": (("dev_type", "dev_name", "mode"), rows)})

    def _apply_measurement_faults(self, minute: int | float, absolute_minute: int | float) -> None:
        faults = [fault for fault in self.local_settings.get("measurement_faults", []) if isinstance(fault, Mapping)]
        curve_mode = str(self.curves.get("mode", "day") or "day").lower()
        active_faults = [fault for fault in faults if _active_window(fault, minute, absolute_minute, curve_mode)]
        if not active_faults or not self.latest_scada_rows:
            return
        rows = [list(row) for row in self.latest_scada_rows]
        changed = False
        for row in rows:
            row_key = self._measurement_key(row)
            for fault in active_faults:
                if not self._measurement_matches(row, fault):
                    continue
                fault_type = str(fault.get("fault_type", fault.get("type", "bias"))).lower()
                if fault_type in ("normal", "ok", "healthy", "none"):
                    continue
                current_value = _to_float(row[7], 0.0) or 0.0
                if fault_type in ("zero", "0", "zero_value"):
                    row[7] = "0"
                elif fault_type in ("dead", "deadband", "stuck", "stale"):
                    median = _to_float(
                        fault.get("median", fault.get("middle", fault.get("fixed_value", fault.get("value")))),
                        None,
                    )
                    bias = _to_float(fault.get("bias", fault.get("error", 0.0)), 0.0) or 0.0
                    base_value = median if median is not None else self._last_scada_values.get(row_key, current_value)
                    row[7] = _number_text(base_value + bias)
                else:
                    bias = _to_float(fault.get("bias", fault.get("error", fault.get("offset", 10.0))), 10.0) or 0.0
                    row[7] = _number_text(current_value + bias)
                changed = True
        if changed:
            self.latest_scada_rows = rows
            self._invalidate_measurement_delta_cache()

    def _measurement_status_override(self, row: Mapping[str, Any] | Sequence[Any]) -> Tuple[str, Optional[float]]:
        if isinstance(row, Mapping):
            name = str(row.get("name", "")).strip()
            default_valid = row.get("valid", 1)
        else:
            name = str(row[1] if len(row) > 1 else "").strip()
            default_valid = row[6] if len(row) > 6 else 1
        statuses = self.local_settings.get("measurement_statuses", {})
        configured = statuses.get(name) if isinstance(statuses, Mapping) else None
        if not isinstance(configured, Mapping):
            configured = self._source_measurement_statuses.get(name)
        if not isinstance(configured, Mapping):
            status = _measurement_status_from_valid(default_valid)
            return status, None
        status = str(configured.get("status", "")).strip().casefold()
        if status not in MEASUREMENT_STATUS_TOKENS:
            status = _measurement_status_from_valid(default_valid)
        fixed_value = _to_float(configured.get("fixed_value"), None)
        return status, fixed_value

    def effective_measurement_status_defaults(self) -> Dict[str, Dict[str, Any]]:
        """Return non-default measurement states for a materialized definition export."""
        with self.definition_update_lock:
            statuses: Dict[str, Dict[str, Any]] = {}
            for row in self.definition_snapshot.measurement_rows:
                name = str(row[1] if len(row) > 1 else "").strip()
                if not name:
                    continue
                status, fixed_value = self._measurement_status_override(row)
                default_status = _measurement_status_from_valid(row[6] if len(row) > 6 else 1)
                if status == default_status and fixed_value is None:
                    continue
                statuses[name] = {
                    "status": status,
                    "fixed_value": fixed_value if status == "fixed" else None,
                }
            return statuses

    def effective_measurement_median_deviation_defaults(self) -> Dict[str, float]:
        """Return nonzero Gaussian error means for a materialized definition export."""
        with self.definition_update_lock:
            return _measurement_median_deviation_map(self.definition_snapshot)

    def _apply_measurement_statuses(self, minute: int | float, absolute_minute: int | float) -> None:
        del minute, absolute_minute
        statuses = self.local_settings.get("measurement_statuses", {})
        has_local_statuses = isinstance(statuses, Mapping) and bool(statuses)
        if not (has_local_statuses or self._source_measurement_statuses) or not self.latest_scada_rows:
            return
        rows = [list(row) for row in self.latest_scada_rows]
        changed = False
        for row in rows:
            status, fixed_value = self._measurement_status_override(row)
            if status == "zero":
                row[7] = "0"
                changed = True
            elif status == "fixed" and fixed_value is not None:
                row[7] = _number_text(fixed_value)
                changed = True
            elif status == "dead":
                key = self._measurement_key(row)
                current_value = _to_float(row[7], 0.0) or 0.0
                row[7] = _number_text(self._last_scada_values.get(key, current_value))
                changed = True
        if changed:
            self.latest_scada_rows = rows
            self._invalidate_measurement_delta_cache()

    def _measurement_matches(self, row: Sequence[str], fault: Mapping[str, Any]) -> bool:
        name, dev_type, dev_name, meas_type = row[1], row[2], row[3], row[4]
        target = str(fault.get("target", fault.get("name", "")))
        if target and target not in {
            name,
            dev_name,
            f"{dev_type}.{dev_name}.{meas_type}",
            f"{dev_type}:{dev_name}:{meas_type}",
            f"{dev_name}.{meas_type}",
        }:
            return False
        if fault.get("dev_type") not in (None, "", dev_type):
            return False
        if fault.get("dev_name") not in (None, "", dev_name):
            return False
        if str(fault.get("meas_type", "")).upper() not in ("", meas_type.upper()):
            return False
        return True

    def _measurement_key(self, row: Sequence[str]) -> str:
        return f"{row[1]}|{row[2]}|{row[3]}|{row[4]}"

    def _kernel_result_dict(self, result: Optional[simu_loop.SimulationResult]) -> Dict[str, Any]:
        if result is None:
            return {"updated": 0, "missing": 0, "overlay_updates": 0, "solver_info": "not-run"}
        return {
            "updated": getattr(result, "updated", 0),
            "missing": getattr(result, "missing", 0),
            "overlay_updates": getattr(result, "overlay_updates", 0),
            "solver_info": getattr(result, "solver_info", ""),
            "real_file": str(getattr(result, "real_file", self.files["real"])),
            "scada_file": str(getattr(result, "scada_file", self.files["scada"])),
        }

    def _current_weather_values(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {**self.weather_defaults, "time": minute_to_time(self.clock.minute)}
        book = self.weather_book
        block = book.data.get("Weather")
        if block is None or not block.data:
            return values
        row: Mapping[str, Any] = block.data[0]
        if "name" in block.header_list and "value" in block.header_list:
            row = {str(item.get("name", "")): item.get("value", "") for item in block.data}
        if row.get("time") not in (None, ""):
            values["time"] = row.get("time")
        for key in DEFAULT_WEATHER:
            number = _to_float(row.get(key), None)
            if number is not None:
                values[key] = number
        return values

    def _is_weather_measurement_row(self, row: Mapping[str, Any]) -> bool:
        return (
            str(row.get("dev_type", "")) == "Environment"
            and str(row.get("dev_name", "")) == "weather"
            and str(row.get("meas_type", "")).upper() in WEATHER_MEASUREMENT_TYPE_SET
        )

    def _weather_measurement_rows(self, start_idx: int) -> List[Dict[str, Any]]:
        weather = self._current_weather_values()
        rows: List[Dict[str, Any]] = []
        for offset, (weather_key, _name_suffix, meas_type) in enumerate(WEATHER_MEASUREMENTS):
            value = _to_float(weather.get(weather_key), None)
            rows.append(
                {
                    "idx": start_idx + offset,
                    "name": automatic_point_name("Environment", "weather", meas_type),
                    "dev_type": "Environment",
                    "dev_name": "weather",
                    "meas_type": meas_type,
                    "weight": 1.0,
                    "valid": 1 if value is not None else 0,
                    "value": value if value is not None else 0.0,
                }
            )
        return rows

    def _is_signal_measurement_row(self, row: Mapping[str, Any]) -> bool:
        return (
            str(row.get("dev_type", "")).strip() != ""
            and str(row.get("dev_name", "")).strip() != ""
            and str(row.get("meas_type", "")).upper() in SIGNAL_MEASUREMENT_TYPES
        )

    def _signal_definition_paths(self) -> List[Path]:
        return []

    def _signal_measurement_key(self, row: Mapping[str, Any]) -> Tuple[str, str, str]:
        return (
            str(row.get("dev_type", "")),
            str(row.get("dev_name", "")),
            str(row.get("meas_type", "")).upper(),
        )

    def _current_signal_values(self) -> Dict[Tuple[str, str, str], float]:
        run_stats, cb_status, _set_values, _soc_values = self._stat_maps()
        values: Dict[Tuple[str, str, str], float] = {}
        for (dev_type, dev_name), value in run_stats.items():
            number = _to_float(value, None)
            if number is not None:
                values[(dev_type, dev_name, "RUN_STAT")] = number
        for (dev_type, dev_name), value in cb_status.items():
            number = _to_float(value, None)
            if number is not None:
                values[(dev_type, dev_name, "STATUS")] = number
        return simu_loop._effective_signal_measurement_values(
            values,
            self.latest_device_states,
        )

    def _signal_measurement_rows(self, start_idx: int) -> List[Dict[str, Any]]:
        values = self._current_signal_values()
        rows: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str, str]] = set()
        for book in (self.control_book, self.source_stat_book):
            for block_name, value_column, meas_type, name_suffix in SIGNAL_MEASUREMENTS:
                block = book.data.get(block_name)
                if block is None:
                    continue
                for item in getattr(block, "data", []):
                    dev_type = str(item.get("dev_type", ""))
                    dev_name = _dev_name(item)
                    if not dev_type or not dev_name:
                        continue
                    key = (dev_type, dev_name, meas_type)
                    if key in seen:
                        continue
                    seen.add(key)
                    value = values.get(key)
                    if value is None:
                        value = _to_float(item.get(value_column), 0.0) or 0.0
                    rows.append(
                        {
                            "idx": start_idx + len(rows),
                            "name": automatic_point_name(dev_type, dev_name, name_suffix),
                            "dev_type": dev_type,
                            "dev_name": dev_name,
                            "meas_type": meas_type,
                            "weight": 1.0,
                            "valid": 1,
                            "value": value,
                        }
                    )
        return rows

    def _apply_signal_measurement_value(
        self,
        row: Dict[str, Any],
        values: Mapping[Tuple[str, str, str], float],
    ) -> None:
        row["meas_type"] = str(row.get("meas_type", "")).upper()
        value = values.get(self._signal_measurement_key(row))
        if value is None:
            value = _to_float(row.get("value"), 0.0) or 0.0
        row["value"] = value
        row["valid"] = 1
        row.setdefault("weight", 1.0)

    def _with_weather_measurements(self, measurements: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        weather = self._current_weather_values()
        weather_values = {
            meas_type: _to_float(weather.get(weather_key), None)
            for weather_key, _name_suffix, meas_type in WEATHER_MEASUREMENTS
        }
        normalized: Dict[str, List[Dict[str, Any]]] = {
            channel: [dict(row) for row in measurements.get(channel, [])]
            for channel in ("definitions", "real", "scada")
        }

        max_idx = -1
        for rows in normalized.values():
            for row in rows:
                idx = int(_to_float(row.get("idx"), -1) or -1)
                max_idx = max(max_idx, idx)
                if not self._is_weather_measurement_row(row):
                    continue
                meas_type = str(row.get("meas_type", "")).upper()
                value = weather_values.get(meas_type)
                if value is not None:
                    row["value"] = value
                    row["valid"] = 1
                else:
                    row["value"] = _to_float(row.get("value"), 0.0) or 0.0
                    row["valid"] = 0
                row.setdefault("weight", 1.0)

        definition_weather_rows = [
            row for row in normalized["definitions"] if self._is_weather_measurement_row(row)
        ]
        if not definition_weather_rows:
            missing_start_idx = max_idx + 1
            definition_weather_rows = self._weather_measurement_rows(missing_start_idx)
            normalized["definitions"].extend(dict(row) for row in definition_weather_rows)

        for channel in ("real", "scada"):
            rows = normalized[channel]
            present_types = {
                str(row.get("meas_type", "")).upper()
                for row in rows
                if self._is_weather_measurement_row(row)
            }
            for definition_row in definition_weather_rows:
                meas_type = str(definition_row.get("meas_type", "")).upper()
                if meas_type not in present_types:
                    rows.append(dict(definition_row))
        return normalized

    def _with_signal_measurements(self, measurements: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        values = self._current_signal_values()
        normalized: Dict[str, List[Dict[str, Any]]] = {
            channel: [dict(row) for row in measurements.get(channel, [])]
            for channel in ("definitions", "real", "scada")
        }

        max_idx = -1
        for rows in normalized.values():
            for row in rows:
                idx = int(_to_float(row.get("idx"), -1) or -1)
                max_idx = max(max_idx, idx)
                if self._is_signal_measurement_row(row):
                    self._apply_signal_measurement_value(row, values)

        definition_by_key = {
            self._signal_measurement_key(row): row
            for row in normalized["definitions"]
            if self._is_signal_measurement_row(row)
        }
        for expected in self._signal_measurement_rows(max_idx + 1):
            key = self._signal_measurement_key(expected)
            if key in definition_by_key:
                self._apply_signal_measurement_value(definition_by_key[key], values)
                continue
            row = dict(expected)
            self._apply_signal_measurement_value(row, values)
            normalized["definitions"].append(row)
            definition_by_key[key] = row

        valid_signal_keys = set(definition_by_key)
        definition_signal_rows = [
            row
            for row in normalized["definitions"]
            if self._is_signal_measurement_row(row)
            and self._signal_measurement_key(row) in valid_signal_keys
        ]
        for channel in ("real", "scada"):
            rows = [
                row
                for row in normalized[channel]
                if not self._is_signal_measurement_row(row)
                or self._signal_measurement_key(row) in valid_signal_keys
            ]
            by_key = {
                self._signal_measurement_key(row): row
                for row in rows
                if self._is_signal_measurement_row(row)
            }
            for definition_row in definition_signal_rows:
                key = self._signal_measurement_key(definition_row)
                target = by_key.get(key)
                if target is None:
                    target = dict(definition_row)
                    rows.append(target)
                    by_key[key] = target
                self._apply_signal_measurement_value(target, values)
            normalized[channel] = rows
        return normalized

    def _with_realtime_measurements(self, measurements: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        return self._with_signal_measurements(self._with_weather_measurements(measurements))

    def measurements(self) -> Dict[str, List[Dict[str, Any]]]:
        definition_snapshot = self.definition_snapshot
        median_deviations = _measurement_median_deviation_map(definition_snapshot)
        definitions = [
            _measurement_definition_row_to_dict(row, median_deviations)
            for row in definition_snapshot.measurement_rows
        ]
        real = [_measurement_row_to_dict(row) for row in self.latest_real_rows]
        scada = [_measurement_row_to_dict(row) for row in self.latest_scada_rows]
        for rows in (real, scada):
            aligned_rows = measurement_rows_by_definition_index(definitions, rows)
            for definition, row in zip(definitions, aligned_rows):
                if row is None:
                    continue
                row["weight"] = definition.get("weight", row.get("weight"))
                row["valid"] = definition.get("valid", row.get("valid"))
        measurements = self._with_realtime_measurements({"definitions": definitions, "real": real, "scada": scada})
        if self._automatic_runtime_state_invalidated:
            # Before the first successful calculation of a lifecycle, weather
            # and signal projections are definitions only, not valid automatic
            # real/scada samples from a previous run.
            measurements["real"] = []
            measurements["scada"] = []
        for channel_rows in measurements.values():
            for row in channel_rows:
                status, fixed_value = self._measurement_status_override(row)
                row["status"] = status
                row["fixed_value"] = fixed_value
                row["valid"] = MEASUREMENT_STATUS_VALIDITY.get(status, int(_to_float(row.get("valid"), 0) or 0))
        for item in measurements["scada"]:
            self._last_scada_values[
                f"{item['name']}|{item['dev_type']}|{item['dev_name']}|{item['meas_type']}"
            ] = item.get("value", 0.0) or 0.0
        return measurements

    def _measurement_delta_current_items(
        self,
        measurements: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
        measurement_clock: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        measurements = dict(measurements or self.measurements())
        definitions = measurements.get("definitions") or measurements.get("scada") or measurements.get("real") or []
        real_rows = measurement_rows_by_definition_index(definitions, measurements.get("real", []) or [])
        scada_rows = measurement_rows_by_definition_index(definitions, measurements.get("scada", []) or [])
        time_payload = self._api_time_payload(measurement_clock)
        items: Dict[str, Dict[str, Any]] = {}
        for index, definition in enumerate(definitions):
            key = str(index)
            name = str(definition.get("name", "")).strip()
            real = real_rows[index]
            scada = scada_rows[index]
            real_value = real.get("value") if real else None
            scada_value = scada.get("value") if scada else None
            value = scada_value if scada is not None else real_value
            valid = definition.get("valid", 0)
            items[key] = {
                "name": name,
                "value": _json_scalar(value),
                "real_value": _json_scalar(real_value),
                "scada_value": _json_scalar(scada_value),
                "valid": int(_to_float(valid, 0) or 0),
                "weight": _json_scalar(definition.get("weight", "")),
                "status": str(definition.get("status", _measurement_status_from_valid(valid))),
                "fixed_value": _json_scalar(definition.get("fixed_value")),
                **self._external_update_time_fields(time_payload),
            }
        return items

    def _measurement_delta_signature(self, item: Mapping[str, Any]) -> Tuple[Any, ...]:
        return (
            item.get("value"),
            item.get("real_value"),
            item.get("scada_value"),
            item.get("valid"),
            item.get("weight"),
            item.get("status"),
            item.get("fixed_value"),
        )

    def _measurement_delta_runtime_state_marker(self) -> Tuple[Any, ...]:
        def values(rows: Sequence[Sequence[Any]]) -> Tuple[Any, ...]:
            return tuple(row[7] if len(row) > 7 else None for row in rows)

        return (
            id(self.latest_measurements),
            id(self.latest_result),
            id(self.latest_device_states),
            id(self.latest_real_rows),
            id(self.latest_scada_rows),
            values(self.latest_real_rows),
            values(self.latest_scada_rows),
        )

    def _invalidate_measurement_delta_cache(self) -> None:
        self._measurement_delta_step_count = None
        self._measurement_delta_runtime_marker = None

    def _refresh_measurement_delta_state(
        self,
        measurements: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
        measurement_clock: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        measurement_payload = dict(measurements or self.measurements())
        sample_clock = dict(measurement_clock or self.latest_measurement_clock or self.clock.as_dict())
        definitions = [
            row
            for row in measurement_payload.get("definitions", []) or []
            if isinstance(row, Mapping)
        ]
        definition_signature = measurement_definition_signature(definitions)
        definition_changed = definition_signature != self._measurement_delta_definition_signature
        current = self._measurement_delta_current_items(
            measurement_payload,
            measurement_clock=sample_clock,
        )
        previous = self._measurement_delta_state
        changed_keys: List[str] = []
        removed_keys = [key for key in previous if key not in current]
        for key, item in current.items():
            previous_item = previous.get(key)
            if (
                definition_changed
                or previous_item is None
                or self._measurement_delta_signature(previous_item)
                != self._measurement_delta_signature(item)
            ):
                changed_keys.append(key)
        if definition_changed or changed_keys or removed_keys:
            self._measurement_delta_seq += 1
            changed_items = [current[key] for key in changed_keys]
            changed_items.extend(
                {
                    "name": str(previous.get(key, {}).get("name", key)),
                    "deleted": True,
                    **self._external_update_time_fields(self._api_time_payload(sample_clock)),
                }
                for key in removed_keys
            )
            self._measurement_delta_history.append(
                {
                    "seq": self._measurement_delta_seq,
                    "items": changed_items,
                    "keys": [*changed_keys, *removed_keys],
                }
            )
            self._measurement_delta_history = self._measurement_delta_history[-200:]
            self._measurement_delta_state = current
        self._measurement_delta_definition_signature = definition_signature
        self._measurement_delta_definition_count = len(definitions)
        self._measurement_delta_definition_revision = self.definition_snapshot.revision
        self._measurement_delta_step_count = self.clock.step_count
        self._measurement_delta_runtime_marker = self._measurement_delta_runtime_state_marker()
        return current

    def measurement_runtime_definitions(
        self,
        definitions: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Attach local runtime-device identities without changing wire point identity."""

        with self.lock:
            definition_snapshot = self.definition_snapshot
            rows = [
                dict(row)
                for row in (
                    definitions
                    if definitions is not None
                    else self.measurements().get("definitions", [])
                )
                if isinstance(row, Mapping)
            ]
            if self._measurement_bindings_cache_revision != definition_snapshot.revision:
                self._measurement_bindings_cache = simu_loop.compile_measurement_bindings(
                    definition_snapshot.measurement_rows,
                    definition_snapshot.model_book,
                )
                self._measurement_bindings_cache_revision = definition_snapshot.revision
            bindings = self._measurement_bindings_cache
            if len(bindings) != len(rows):
                return rows
            storage_resource_by_protocol_key = {
                protocol_key: resource_key
                for resource_key, protocol_keys in self._storage_runtime_protocol_keys().items()
                for protocol_key in protocol_keys
            }
            for row, binding in zip(rows, bindings):
                runtime_key = (binding.target_type, binding.target_name)
                if str(row.get("meas_type", "")).strip().upper() == "SOC":
                    runtime_key = storage_resource_by_protocol_key.get(
                        (
                            str(row.get("dev_type", "")).strip(),
                            str(row.get("dev_name", "")).strip(),
                        ),
                        runtime_key,
                    )
                row["runtime_dev_type"], row["runtime_dev_name"] = runtime_key
            return rows

    def measurement_delta(self, after_seq: int | float = 0, *, compact: bool = False) -> Dict[str, Any]:
        """Return changed measurement values keyed by measurement name."""
        try:
            after = int(after_seq)
        except (TypeError, ValueError):
            after = 0
        with self.lock:
            cache_valid = (
                self._measurement_delta_step_count == self.clock.step_count
                and self._measurement_delta_definition_revision == self.definition_snapshot.revision
                and self._measurement_delta_runtime_marker is not None
            )
            if cache_valid and (
                self._measurement_delta_runtime_marker
                == self._measurement_delta_runtime_state_marker()
            ):
                current = self._measurement_delta_state
            else:
                current = self._refresh_measurement_delta_state()
            reset = False
            frame = after != self._measurement_delta_seq
            if compact and frame:
                items = list(current.values())
                reset = after <= 0 or after > self._measurement_delta_seq
            elif after <= 0:
                items = list(current.values())
                reset = True
            elif after > self._measurement_delta_seq:
                items = list(current.values())
                reset = True
            elif after == self._measurement_delta_seq:
                items = []
            else:
                history = [
                    entry
                    for entry in self._measurement_delta_history
                    if int(entry.get("seq", 0)) > after
                ]
                if not history:
                    items = list(current.values())
                    reset = True
                else:
                    by_key: Dict[str, Dict[str, Any]] = {}
                    for entry in history:
                        entry_items = entry.get("items", [])
                        entry_keys = entry.get("keys", [])
                        if not isinstance(entry_keys, Sequence) or isinstance(entry_keys, (str, bytes)):
                            entry_keys = []
                        for position, item in enumerate(entry_items):
                            if isinstance(item, Mapping):
                                key = (
                                    str(entry_keys[position])
                                    if position < len(entry_keys)
                                    else str(item.get("name", ""))
                                )
                                by_key[key] = dict(item)
                    items = list(by_key.values())
            payload = {
                "model_id": self.model_id,
                "model_name": self.model_name,
                **self._api_time_payload(self.latest_measurement_clock or self.clock.as_dict()),
                "measurement_clock": dict(self.latest_measurement_clock or self.clock.as_dict()),
                "seq": self._measurement_delta_seq,
                "items": items,
                "reset": reset,
            }
            if compact:
                payload.update(
                    {
                        "frame": frame,
                        "count": self._measurement_delta_definition_count,
                        "definition_revision": self._measurement_delta_definition_revision,
                        "definition_signature": self._measurement_delta_definition_signature,
                    }
                )
        return compact_measurement_delta(payload) if compact else payload

    def measurement_history(
        self,
        *,
        indices: Optional[Sequence[int]] = None,
        after_seq: int | float = 0,
    ) -> Dict[str, Any]:
        """Return compact current-run history aligned to measurement order."""

        with self.lock:
            measurements = self.latest_measurements
            if not isinstance(measurements, Mapping) or not measurements.get("definitions"):
                measurements = self.measurements()
            definitions = [
                row
                for row in measurements.get("definitions", []) or []
                if isinstance(row, Mapping)
            ]
            self._measurement_history.ensure_definition(
                definitions,
                definition_revision=self.definition_snapshot.revision,
            )
            return self._measurement_history.payload(
                indices=indices,
                after_seq=after_seq,
                model_id=self.model_id,
                model_name=self.model_name,
            )

    def _read_measurement_file(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            _before, rows, _after = parse_measurement_rows(path)
        except Exception:
            return []
        return [_measurement_row_to_dict(row) for row in rows]

    def devices(self) -> List[Dict[str, Any]]:
        definition_snapshot = self.definition_snapshot
        model_book = definition_snapshot.model_book
        run_stats, cb_status, set_values, soc_values = self._stat_maps()
        resources_by_key = resources_by_device_key(model_book)
        coupling_bindings = energy_coupling_control_bindings(model_book)
        devices: List[Dict[str, Any]] = []
        device_blocks = (
            "ACGenerator",
            "DCGenerator",
            "ACLoad",
            "DCLoad",
            "DCDCConverter",
            "ACDCConverter",
            "DCACConverter",
            "ACACConverter",
            "ACBreak",
            "DCBreak",
            "ACSwitch",
            "DCSwitch",
            "HydroSource",
            "HydroLoad",
            "HydroStorage",
            "AcE2Hydro",
            "DcE2Hydro",
            "Hydro2AcE",
            "Hydro2DcE",
        )
        for dev_type in device_blocks:
            block = model_book.data.get(dev_type)
            if block is None:
                continue
            for row in block.data:
                name = str(row.get("name", ""))
                key = (dev_type, name)
                terminal_domains = terminal_domains_from_block(dev_type)
                resource = resources_by_key.get(key)
                set_types = []
                for column in (
                    "p_set",
                    "q_set",
                    "v_set",
                    "p_ac_set",
                    "q_ac_set",
                    "v_ac_set",
                    "p_dc_set",
                    "v_dc_set",
                    "pv0",
                    "qv0",
                    "flow_set",
                ):
                    if column in block.header_list:
                        set_types.append(column)
                devices.append(
                    {
                        "dev_type": dev_type,
                        "dev_name": name,
                        "model_block": dev_type,
                        "device_family": device_family_from_block(dev_type),
                        "terminal_domains": list(terminal_domains),
                        "resource_technology": resource.technology if resource else "",
                        "run_stat": int(_to_float(run_stats.get(key, row.get("run_stat", 1)), 1) or 0),
                        "status": int(_to_float(cb_status.get(key, row.get("status", 1)), 1) or 0),
                        "mode": (
                            converter_control_mode(row)
                            if set(terminal_domains) == {"AC", "DC"}
                            else (
                                row.get("control_type")
                                or row.get("ac_control_type")
                                or row.get("dc_control_type")
                                or row.get("mode", "")
                            )
                        ),
                        "set_types": set_types,
                        "set_values": set_values.get(key, {}),
                        "control_bindings": list(coupling_bindings.get(key, ())),
                        "raw": {header: row.get(header, "") for header in block.header_list},
                    }
                )
        devices_by_key = {
            (str(device.get("dev_type", "")), str(device.get("dev_name", ""))): device
            for device in devices
        }
        def storage_soc_value(row: Mapping[str, Any], default: float = 0.0) -> float:
            value: Any = ""
            for column in ("state_of_charge", "soc_curr", "soc_cur", "soc"):
                if row.get(column, "") != "":
                    value = row.get(column)
                    break
            text = str(value or "").strip()
            if not text:
                return default
            try:
                return ratio_parameter_number(
                    "state_of_charge",
                    value,
                    legacy_percent_points=True,
                )
            except ValueError:
                return default
        for resource in structured_resources(model_book):
            if resource.technology != "storage":
                continue
            key = resource.device_key
            device = devices_by_key.get(key)
            if device is None:
                continue
            raw = dict(resource.parameter)
            soc_value = soc_values.get(
                key,
                storage_soc_value(resource.parameter),
            )
            device["soc_curr"] = soc_value
            device["raw"] = raw | dict(device.get("raw", {})) | {"soc_curr": soc_value}
            for set_type in ("p_set", "v_set"):
                if set_type not in device["set_types"]:
                    device["set_types"].append(set_type)
        return devices

    def device_states(self) -> List[Dict[str, Any]]:
        """Return the compact state needed by the live SVG diagram."""
        definition_snapshot = self.definition_snapshot
        model_blocks_by_key = {
            (str(block_name), str(row.get("name", "")).strip()): str(block_name)
            for block_name, block in definition_snapshot.model_book.data.items()
            for row in getattr(block, "data", [])
            if str(row.get("name", "")).strip()
        }
        states: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for item in self.latest_device_states:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", item.get("name", ""))).strip()
            if not dev_type or not dev_name:
                continue
            states[(dev_type, dev_name)] = {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "model_block": str(item.get("model_block", "")).strip()
                or model_blocks_by_key.get((dev_type, dev_name), ""),
                "run_stat": int(_to_float(item.get("run_stat"), 1) or 0),
                "dead_island": bool(item.get("dead_island", False)),
            }

        run_stats, _cb_status, _set_values, _soc_values = self._stat_maps()
        for dev_type, block in definition_snapshot.model_book.data.items():
            if "name" not in block.header_list or "run_stat" not in block.header_list:
                continue
            for row in block.data:
                dev_name = str(row.get("name", "")).strip()
                if not dev_name:
                    continue
                key = (str(dev_type), dev_name)
                run_stat = int(_to_float(run_stats.get(key, row.get("run_stat", 1)), 1) or 0)
                state = states.setdefault(
                    key,
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "model_block": str(dev_type),
                        "run_stat": run_stat,
                        "dead_island": False,
                    },
                )
                state["run_stat"] = run_stat
                if run_stat == 0:
                    state["dead_island"] = False

        for key, value in run_stats.items():
            dev_type, dev_name = str(key[0]).strip(), str(key[1]).strip()
            if not dev_type or not dev_name:
                continue
            run_stat = int(_to_float(value, 1) or 0)
            state = states.setdefault(
                (dev_type, dev_name),
                {
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "model_block": model_blocks_by_key.get((dev_type, dev_name), ""),
                    "run_stat": run_stat,
                    "dead_island": False,
                },
            )
            state["run_stat"] = run_stat
            if run_stat == 0:
                state["dead_island"] = False

        return [states[key] for key in sorted(states)]

    def device_runtime_frame(self) -> Dict[str, Any]:
        with self.lock:
            cache_key = (
                self.definition_snapshot.revision,
                self.clock.step_count,
                id(self.runtime_stat_book),
                id(self.latest_model_book),
                id(self.latest_device_states),
                id(self.mode_book),
                id(self.yt_ctrl_book),
                tuple(
                    (
                        str(item.get("dev_type", "")),
                        str(item.get("dev_name", item.get("name", ""))),
                        item.get("run_stat"),
                        bool(item.get("dead_island", False)),
                    )
                    for item in self.latest_device_states
                    if isinstance(item, Mapping)
                ),
            )
            if (
                cache_key == self._device_runtime_frame_cache_key
                and self._device_runtime_frame_cache_value is not None
            ):
                return self._device_runtime_frame_cache_value
            frame = compact_device_runtime_frame(
                self.devices(),
                self.device_states(),
                definition_revision=self.definition_snapshot.revision,
            )
            self._device_runtime_frame_cache_key = cache_key
            self._device_runtime_frame_cache_value = frame
            return frame

    def _api_time_payload(self, clock: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        source = clock if isinstance(clock, Mapping) else self.clock.as_dict()
        absolute_minute = _to_float(source.get("absolute_minute", source.get("minute")), 0.0) or 0.0
        minute = _to_float(source.get("minute"), None)
        if minute is None:
            minute = absolute_minute % 1440.0
        time_text = str(source.get("time") or minute_to_time(minute))
        return {
            "time": time_text,
            "simu_time": time_text,
            "absolute_minute": absolute_minute,
            "wall_time": _now_text(),
        }

    @staticmethod
    def _external_book_signature_payload(book: EBook) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        for block_name, block in book.data.items():
            headers = list(getattr(block, "header_list", []) or [])
            blocks.append(
                {
                    "name": str(block_name),
                    "headers": headers,
                    "rows": [
                        [_json_scalar(row.get(header, "")) for header in headers]
                        for row in getattr(block, "data", [])
                    ],
                }
            )
        return blocks

    def external_model_version(self) -> Dict[str, Any]:
        """Return a cached content version for every external API response."""
        snapshot = self.definition_snapshot
        cached = getattr(self, "_external_model_version_cache", None)
        if isinstance(cached, tuple) and len(cached) == 2 and cached[0] is snapshot:
            return dict(cached[1])
        canonical = json.dumps(
            {
                "model": self._external_book_signature_payload(snapshot.model_book),
                "control": self._external_book_signature_payload(snapshot.dev_define_book),
                "measurement": [list(row) for row in snapshot.measurement_rows],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        version = {
            "schema_version": 1,
            "revision": int(snapshot.revision),
            "signature": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "algorithm": "sha256",
        }
        self._external_model_version_cache = (snapshot, version)
        return dict(version)

    def _external_response_metadata(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "model_version": self.external_model_version(),
            **self._api_time_payload(),
        }

    @staticmethod
    def _external_names_signature(groups: Mapping[str, Sequence[str]]) -> str:
        canonical = json.dumps(
            {str(key): [str(name) for name in names] for key, names in groups.items()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _external_update_time_fields(self, time_payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "updated_wall_time": time_payload.get("wall_time", "--"),
            "updated_simu_time": time_payload.get("simu_time", time_payload.get("time", "--")),
            "updated_absolute_minute": time_payload.get("absolute_minute"),
        }

    def _compact_external_value_item(
        self,
        item: Mapping[str, Any],
        time_payload: Mapping[str, Any],
        *,
        include_found: bool = False,
        include_valid: bool = False,
        include_active: bool = False,
    ) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "name": str(item.get("name", "")),
            "value": _json_scalar(item.get("value")),
            "updated_wall_time": item.get("updated_wall_time", time_payload.get("wall_time", "--")),
            "updated_simu_time": item.get("updated_simu_time", time_payload.get("simu_time", time_payload.get("time", "--"))),
            "updated_absolute_minute": _json_scalar(item.get("updated_absolute_minute", time_payload.get("absolute_minute"))),
        }
        if include_found or "found" in item:
            row["found"] = bool(item.get("found", True))
        if include_valid or "valid" in item:
            row["valid"] = int(_to_float(item.get("valid"), 0) or 0)
        if include_active or "active" in item:
            row["active"] = bool(item.get("active", False))
            row["expires_at_absolute_minute"] = _json_scalar(item.get("expires_at_absolute_minute"))
            row["command_origin"] = str(item.get("command_origin", ""))
        return row

    def _latest_telemetry_items(self) -> List[Dict[str, Any]]:
        measurements = dict(self.latest_measurements or self.measurements())
        measurements = self._with_realtime_measurements(measurements)
        items: List[Dict[str, Any]] = []
        signal_keys: set[Tuple[str, str, str]] = set()
        for row in measurements.get("scada", []):
            name = str(row.get("name", "")).strip() or ".".join(
                str(row.get(key, "")).strip()
                for key in ("dev_type", "dev_name", "meas_type")
                if str(row.get(key, "")).strip()
            )
            if not name:
                continue
            is_signal = self._is_signal_measurement_row(row)
            if is_signal:
                signal_keys.add(self._signal_measurement_key(row))
            signal_value = int(_to_float(row.get("value"), 0) or 0)
            items.append(
                {
                    "name": name,
                    "point_type": "YX" if is_signal else "YC",
                    "category": "遥信" if is_signal else "遥测",
                    "dev_type": str(row.get("dev_type", "")),
                    "dev_name": str(row.get("dev_name", "")),
                    "meas_type": str(row.get("meas_type", "")),
                    "value": _json_scalar(row.get("value", 0.0)),
                    "valid": int(_to_float(row.get("valid"), 0) or 0),
                    "weight": _json_scalar(row.get("weight", "")),
                    **(
                        {
                            "text": (
                                ("闭合" if signal_value else "断开")
                                if str(row.get("meas_type", "")).upper() == "STATUS"
                                else ("投入" if signal_value else "退出")
                            )
                        }
                        if is_signal
                        else {}
                    ),
                }
            )

        for dev in self.devices():
            dev_type = str(dev.get("dev_type", ""))
            dev_name = str(dev.get("dev_name", ""))
            if not dev_type or not dev_name:
                continue
            run_key = (dev_type, dev_name, "RUN_STAT")
            if run_key not in signal_keys:
                run_stat = int(_to_float(dev.get("run_stat"), 0) or 0)
                items.append(
                    {
                        "name": automatic_point_name(dev_type, dev_name, "run_stat"),
                        "point_type": "YX",
                        "category": "遥信",
                        "dev_type": dev_type,
                        "dev_name": dev_name,
                        "meas_type": "run_stat",
                        "value": run_stat,
                        "valid": 1,
                        "text": "投入" if run_stat else "退出",
                    }
                )
            status_key = (dev_type, dev_name, "STATUS")
            if (
                status_key not in signal_keys
                and ("Switch" in dev_type or "Break" in dev_type or dev.get("raw", {}).get("status", "") not in ("", None))
            ):
                status = int(_to_float(dev.get("status"), 0) or 0)
                items.append(
                    {
                        "name": automatic_point_name(dev_type, dev_name, "status"),
                        "point_type": "YX",
                        "category": "遥信",
                        "dev_type": dev_type,
                        "dev_name": dev_name,
                        "meas_type": "status",
                        "value": status,
                        "valid": 1,
                        "text": "闭合" if status else "断开",
                    }
                )

        return items

    @staticmethod
    def _external_unique_items(
        items: Sequence[Mapping[str, Any]],
        discriminator: str,
        expected: str,
    ) -> List[Mapping[str, Any]]:
        selected: List[Mapping[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if str(item.get(discriminator, "")) != expected:
                continue
            name = str(item.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            selected.append(item)
        return selected

    def _external_telemetry_groups(
        self,
    ) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
        items = self._external_telemetry_catalog_items()
        return (
            self._external_unique_items(items, "point_type", "YC"),
            self._external_unique_items(items, "point_type", "YX"),
        )

    def _external_telemetry_catalog_items(self) -> List[Dict[str, Any]]:
        current_items = self._latest_telemetry_items()
        current_by_name = {
            str(item.get("name", "")): item
            for item in current_items
            if str(item.get("name", ""))
        }
        catalog: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for raw_row in self.definition_snapshot.measurement_rows:
            row = dict(zip(MEAS_HEADER, raw_row))
            name = str(row.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            current = current_by_name.get(name, {})
            is_signal = self._is_signal_measurement_row(row)
            catalog.append(
                {
                    "name": name,
                    "point_type": "YX" if is_signal else "YC",
                    "category": "遥信" if is_signal else "遥测",
                    "dev_type": str(row.get("dev_type", "")),
                    "dev_name": str(row.get("dev_name", "")),
                    "meas_type": str(row.get("meas_type", "")),
                    "value": _json_scalar(current.get("value", row.get("value"))),
                    "valid": int(_to_float(current.get("valid", row.get("valid")), 0) or 0),
                    "weight": _json_scalar(current.get("weight", row.get("weight", ""))),
                }
            )
        for item in current_items:
            name = str(item.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            catalog.append(dict(item))
        return catalog

    @staticmethod
    def _external_topology_fields(parameters: Mapping[str, Any]) -> Dict[str, Any]:
        topology: Dict[str, Any] = {}
        for raw_name, value in parameters.items():
            name = str(raw_name)
            lower = name.casefold()
            if (
                lower == "node"
                or lower.endswith("_node")
                or re.fullmatch(r"idx_.+_t[12]", lower)
            ):
                topology[name] = _json_scalar(value)
        return topology

    def external_device_information(self) -> Dict[str, Any]:
        """Return physical definitions enriched with topology, state, measurements and controls."""
        snapshot = self.definition_snapshot
        model_book = snapshot.model_book
        runtime_devices = {
            (str(item.get("dev_type", "")), str(item.get("dev_name", ""))): item
            for item in self.devices()
        }
        runtime_states = {
            (str(item.get("dev_type", "")), str(item.get("dev_name", ""))): item
            for item in self.device_states()
        }
        telemetry_by_device: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for item in self._latest_telemetry_items():
            key = (str(item.get("dev_type", "")), str(item.get("dev_name", "")))
            name = str(item.get("name", "")).strip()
            if key[0] and key[1] and name:
                telemetry_by_device.setdefault(key, {})[name] = _json_scalar(item.get("value"))
        for raw_row in snapshot.measurement_rows:
            row = dict(zip(MEAS_HEADER, raw_row))
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            name = str(row.get("name", "")).strip()
            if key[0] and key[1] and name:
                telemetry_by_device.setdefault(key, {}).setdefault(name, _json_scalar(row.get("value")))
        controls_by_device: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for item in self._latest_control_value_items():
            key = (str(item.get("dev_type", "")), str(item.get("dev_name", "")))
            name = str(item.get("name", "")).strip()
            if key[0] and key[1] and name:
                controls_by_device.setdefault(key, {})[name] = _json_scalar(item.get("value"))

        parameter_links = (
            ("ACWindGen", "ACGenerator", "idx_acgenerator"),
            ("DCWindGen", "DCGenerator", "idx_dcgenerator"),
            ("ACPVGen", "ACGenerator", "idx_acgenerator"),
            ("DCPVGen", "DCGenerator", "idx_dcgenerator"),
            ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
            ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
        )
        linked_parameters: Dict[Tuple[str, str], Dict[str, List[Dict[str, Any]]]] = {}
        for block_name, parent_type, index_field in parameter_links:
            parent_block = model_book.data.get(parent_type)
            parent_by_idx = {
                str(row.get("idx", "")): str(row.get("name", "")).strip()
                for row in getattr(parent_block, "data", [])
                if str(row.get("idx", "")) and str(row.get("name", "")).strip()
            }
            parameter_block = model_book.data.get(block_name)
            headers = list(getattr(parameter_block, "header_list", []) or [])
            for row in getattr(parameter_block, "data", []):
                parent_name = parent_by_idx.get(str(row.get(index_field, "")))
                if not parent_name:
                    continue
                linked_parameters.setdefault((parent_type, parent_name), {}).setdefault(block_name, []).append(
                    {header: _json_scalar(row.get(header, "")) for header in headers}
                )

        parameter_block_names = {item[0] for item in parameter_links}
        devices: List[Dict[str, Any]] = []
        device_keys: set[Tuple[str, str]] = set()
        connections: List[Dict[str, Any]] = []
        nodes: List[Dict[str, Any]] = []

        def append_device(dev_type: str, dev_name: str, parameters: Mapping[str, Any]) -> None:
            key = (dev_type, dev_name)
            if not dev_type or not dev_name or key in device_keys:
                return
            device_keys.add(key)
            runtime = runtime_devices.get(key, {})
            runtime_state = runtime_states.get(key, {})
            topology = self._external_topology_fields(parameters)
            state: Dict[str, Any] = {
                "run_stat": int(
                    _to_float(
                        runtime_state.get("run_stat", runtime.get("run_stat", parameters.get("run_stat", 1))),
                        1,
                    )
                    or 0
                ),
                "dead_island": bool(runtime_state.get("dead_island", False)),
            }
            if "status" in parameters or "Switch" in dev_type or "Break" in dev_type or "Valve" in dev_type:
                state["status"] = int(_to_float(runtime.get("status", parameters.get("status", 1)), 1) or 0)
            mode = runtime.get("mode") or parameters.get("control_type") or parameters.get("mode")
            if mode not in (None, ""):
                state["mode"] = str(mode)
            if runtime.get("soc_curr", "") != "":
                state["soc"] = _json_scalar(runtime.get("soc_curr"))
            device_id = f"{dev_type}.{dev_name}"
            devices.append(
                {
                    "id": device_id,
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "topology": topology,
                    "parameters": {str(name): _json_scalar(value) for name, value in parameters.items()},
                    "parameter_blocks": linked_parameters.get(key, {}),
                    "state": state,
                    "values": telemetry_by_device.get(key, {}),
                    "control_values": controls_by_device.get(key, {}),
                }
            )
            if topology:
                connections.append({"device_id": device_id, "terminals": topology})
            if dev_type in {"ACNode", "DCNode"}:
                nodes.append(
                    {
                        "device_id": device_id,
                        "network": "AC" if dev_type == "ACNode" else "DC",
                        "idx": _json_scalar(parameters.get("idx")),
                        "name": dev_name,
                    }
                )

        for block_name, block in model_book.data.items():
            if block_name in parameter_block_names or block_name in {"Model", "PowerBase", "basevoltage"}:
                continue
            headers = list(getattr(block, "header_list", []) or [])
            if "name" not in headers:
                continue
            physical_block = (
                "run_stat" in headers
                or block_name in {"ACNode", "DCNode"}
                or any(self._external_topology_fields({header: "" for header in headers}))
            )
            if not physical_block:
                continue
            for row in getattr(block, "data", []):
                name = str(row.get("name", "")).strip()
                if name:
                    append_device(
                        str(block_name),
                        name,
                        {header: row.get(header, "") for header in headers},
                    )

        for key, runtime in runtime_devices.items():
            if key in device_keys:
                continue
            parameters = runtime.get("raw", {})
            append_device(key[0], key[1], parameters if isinstance(parameters, Mapping) else {})

        devices.sort(key=lambda item: (str(item.get("dev_type", "")), str(item.get("dev_name", ""))))
        return {
            **self._external_response_metadata(),
            "device_count": len(devices),
            "devices": devices,
            "topology": {
                "nodes": nodes,
                "connections": connections,
            },
        }

    def latest_telemetry_values(self) -> Dict[str, Any]:
        """Return compact latest remote measurements and status points for external clients."""
        time_payload = self._api_time_payload()
        items = [
            self._compact_external_value_item(item, time_payload, include_valid=True)
            for item in self._latest_telemetry_items()
        ]
        return {
            **self._external_response_metadata(),
            "items": items,
            "values": {item["name"]: item.get("value") for item in items},
        }

    def external_telemetry_names(self) -> Dict[str, Any]:
        telemetry, signals = self._external_telemetry_groups()
        telemetry_names = [str(item.get("name", "")) for item in telemetry]
        signal_names = [str(item.get("name", "")) for item in signals]
        signature = self._external_names_signature(
            {
                "telemetry_names": telemetry_names,
                "signal_names": signal_names,
            }
        )
        return {
            **self._external_response_metadata(),
            "definition_signature": signature,
            "telemetry_count": len(telemetry_names),
            "signal_count": len(signal_names),
            "telemetry_names": telemetry_names,
            "signal_names": signal_names,
            "yc_names": telemetry_names,
            "yx_names": signal_names,
        }

    def external_telemetry_frame(self) -> Dict[str, Any]:
        telemetry, signals = self._external_telemetry_groups()
        telemetry_names = [str(item.get("name", "")) for item in telemetry]
        signal_names = [str(item.get("name", "")) for item in signals]
        return {
            **self._external_response_metadata(),
            "definition_signature": self._external_names_signature(
                {
                    "telemetry_names": telemetry_names,
                    "signal_names": signal_names,
                }
            ),
            "telemetry_count": len(telemetry),
            "signal_count": len(signals),
            "telemetry_values": [_json_scalar(item.get("value")) for item in telemetry],
            "signal_values": [_json_scalar(item.get("value")) for item in signals],
            "telemetry_valid": [int(_to_float(item.get("valid"), 0) or 0) for item in telemetry],
            "signal_valid": [int(_to_float(item.get("valid"), 0) or 0) for item in signals],
            "yc_values": [_json_scalar(item.get("value")) for item in telemetry],
            "yx_values": [_json_scalar(item.get("value")) for item in signals],
        }

    def _name_list_from_payload(self, payload: Mapping[str, Any], keys: Sequence[str]) -> List[str]:
        names: List[str] = []
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str):
                names.extend(part.strip() for part in re.split(r"[,;\s]+", value) if part.strip())
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                names.extend(str(item).strip() for item in value if str(item).strip())
        return names

    def selected_telemetry_values(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Return selected telemetry and signal values by requested point names."""
        yc_names = self._name_list_from_payload(
            payload,
            ("telemetry", "telemetries", "telemetry_names", "yc", "yc_names", "remote_measurements"),
        )
        yx_names = self._name_list_from_payload(
            payload,
            ("signals", "signal_names", "yx", "yx_names", "statuses", "status_names", "remote_signals"),
        )
        time_payload = self._api_time_payload()
        all_items = self._latest_telemetry_items()
        yc_index = {
            str(item.get("name", "")): item
            for item in all_items
            if isinstance(item, Mapping) and item.get("point_type") == "YC"
        }
        yx_index = {
            str(item.get("name", "")): item
            for item in all_items
            if isinstance(item, Mapping) and item.get("point_type") == "YX"
        }

        def pick(index: Mapping[str, Mapping[str, Any]], names: Sequence[str]) -> List[Dict[str, Any]]:
            rows: List[Dict[str, Any]] = []
            for name in names:
                item = index.get(name)
                if item is None:
                    rows.append(
                        {
                            "name": name,
                            "value": None,
                            **self._external_update_time_fields(time_payload),
                            "found": False,
                            "valid": 0,
                        }
                    )
                else:
                    rows.append(
                        self._compact_external_value_item(
                            item | {"found": True},
                            time_payload,
                            include_found=True,
                            include_valid=True,
                        )
                    )
            return rows

        telemetry = pick(yc_index, yc_names)
        signals = pick(yx_index, yx_names)
        return {
            **self._external_response_metadata(),
            "telemetry": telemetry,
            "signals": signals,
            "yc": telemetry,
            "yx": signals,
            "items": [*telemetry, *signals],
            "values": {item["name"]: item.get("value") for item in [*telemetry, *signals]},
            "missing": {
                "telemetry": [item["name"] for item in telemetry if not item.get("found")],
                "signals": [item["name"] for item in signals if not item.get("found")],
            },
        }

    def selected_external_telemetry_frame(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        telemetry_names = self._name_list_from_payload(
            payload,
            ("telemetry", "telemetries", "telemetry_names", "yc", "yc_names", "remote_measurements"),
        )
        signal_names = self._name_list_from_payload(
            payload,
            ("signals", "signal_names", "yx", "yx_names", "statuses", "status_names", "remote_signals"),
        )
        telemetry, signals = self._external_telemetry_groups()
        telemetry_index = {str(item.get("name", "")): item for item in telemetry}
        signal_index = {str(item.get("name", "")): item for item in signals}

        def selected_rows(
            names: Sequence[str],
            index: Mapping[str, Mapping[str, Any]],
        ) -> List[Dict[str, Any]]:
            rows: List[Dict[str, Any]] = []
            for name in names:
                item = index.get(name)
                rows.append(
                    {
                        "name": name,
                        "value": _json_scalar(item.get("value")) if item is not None else None,
                        "valid": int(_to_float(item.get("valid"), 0) or 0) if item is not None else 0,
                        "found": item is not None,
                    }
                )
            return rows

        telemetry_rows = selected_rows(telemetry_names, telemetry_index)
        signal_rows = selected_rows(signal_names, signal_index)
        return {
            **self._external_response_metadata(),
            "telemetry_names": telemetry_names,
            "signal_names": signal_names,
            "telemetry_values": [item["value"] for item in telemetry_rows],
            "signal_values": [item["value"] for item in signal_rows],
            "telemetry_valid": [item["valid"] for item in telemetry_rows],
            "signal_valid": [item["valid"] for item in signal_rows],
            "telemetry_found": [item["found"] for item in telemetry_rows],
            "signal_found": [item["found"] for item in signal_rows],
            "yc_names": telemetry_names,
            "yx_names": signal_names,
            "yc_values": [item["value"] for item in telemetry_rows],
            "yx_values": [item["value"] for item in signal_rows],
            "missing": {
                "telemetry": [item["name"] for item in telemetry_rows if not item["found"]],
                "signals": [item["name"] for item in signal_rows if not item["found"]],
            },
        }

    @staticmethod
    def _external_history_absolute_minute(payload: Mapping[str, Any], prefix: str) -> float:
        minute_keys = (
            f"{prefix}_absolute_minute",
            f"{prefix}_minute",
        )
        for key in minute_keys:
            if key not in payload:
                continue
            value = _to_float(payload.get(key), None)
            if value is None or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a non-negative number")
            return float(value)

        second_keys = (
            f"{prefix}_absolute_second",
            f"{prefix}_second",
        )
        for key in second_keys:
            if key not in payload:
                continue
            value = _to_float(payload.get(key), None)
            if value is None or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a non-negative number")
            return float(value) / 60.0

        key = f"{prefix}_time"
        raw_value = payload.get(key)
        if raw_value is None or str(raw_value).strip() == "":
            raise ValueError(f"{key} is required")
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            value = float(raw_value)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a non-negative absolute minute or HH:MM[:SS]")
            return value

        text = str(raw_value).strip()
        numeric = _to_float(text, None)
        if numeric is not None and ":" not in text:
            if not math.isfinite(numeric) or numeric < 0:
                raise ValueError(f"{key} must be a non-negative absolute minute or HH:MM[:SS]")
            return float(numeric)
        match = re.fullmatch(r"(?:(\d+)\+)?(\d+):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?", text)
        if not match:
            raise ValueError(f"{key} must use HH:MM[:SS] or day+HH:MM[:SS]")
        day_text, hour_text, minute_text, second_text = match.groups()
        day = int(day_text or 0)
        hour = int(hour_text)
        minute_part = int(minute_text)
        second = float(second_text or 0.0)
        if minute_part >= 60 or second >= 60 or (day_text is not None and hour >= 24):
            raise ValueError(f"{key} is outside the valid clock range")
        return day * 1440.0 + hour * 60.0 + minute_part + second / 60.0

    @staticmethod
    def _external_history_interval_seconds(payload: Mapping[str, Any]) -> float:
        raw_value: Any = None
        for key in (
            "interval_seconds",
            "data_interval_seconds",
            "sample_interval_seconds",
            "data_interval",
        ):
            if key in payload:
                raw_value = payload.get(key)
                break
        value = _to_float(raw_value, None)
        if value is None or not math.isfinite(value) or value <= 0:
            raise ValueError("interval_seconds must be a positive number")
        return float(value)

    def external_measurement_history(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Return sampled YC/YX history matrices for external clients."""

        interval_seconds = self._external_history_interval_seconds(payload)
        start_minute = self._external_history_absolute_minute(payload, "start")
        end_minute = self._external_history_absolute_minute(payload, "end")
        if end_minute < start_minute - 1e-9:
            raise ValueError("end_time must not be earlier than start_time")

        telemetry_names = self._name_list_from_payload(
            payload,
            ("telemetry", "telemetries", "telemetry_names", "yc", "yc_names", "remote_measurements"),
        )
        signal_names = self._name_list_from_payload(
            payload,
            ("signals", "signal_names", "yx", "yx_names", "statuses", "status_names", "remote_signals"),
        )
        if not telemetry_names and not signal_names:
            raise ValueError("telemetry_names or signal_names is required")
        if len(telemetry_names) + len(signal_names) > 256:
            raise ValueError("at most 256 telemetry and signal names may be queried at once")

        with self.lock:
            measurements = self.latest_measurements
            if not isinstance(measurements, Mapping) or not measurements.get("definitions"):
                measurements = self.measurements()
            definitions = [
                row
                for row in measurements.get("definitions", []) or []
                if isinstance(row, Mapping)
            ]
            definition_by_name: Dict[str, Tuple[int, Mapping[str, Any]]] = {}
            for index, row in enumerate(definitions):
                name = str(row.get("name", "")).strip()
                if name and name not in definition_by_name:
                    definition_by_name[name] = (index, row)

            def resolve_names(names: Sequence[str], expect_signal: bool) -> Tuple[List[bool], List[Optional[int]]]:
                found: List[bool] = []
                indices: List[Optional[int]] = []
                for name in names:
                    match = definition_by_name.get(name)
                    accepted = bool(
                        match is not None
                        and self._is_signal_measurement_row(match[1]) is expect_signal
                    )
                    found.append(accepted)
                    indices.append(match[0] if accepted and match is not None else None)
                return found, indices

            telemetry_found, telemetry_definition_indices = resolve_names(telemetry_names, False)
            signal_found, signal_definition_indices = resolve_names(signal_names, True)
            selected_indices: List[int] = []
            for index in [*telemetry_definition_indices, *signal_definition_indices]:
                if index is not None and index not in selected_indices:
                    selected_indices.append(index)
            history = self.measurement_history(indices=selected_indices)
            metadata = self._external_response_metadata()
            external_definition_signature = self.external_telemetry_names()["definition_signature"]

        selected_positions = {
            definition_index: position
            for position, definition_index in enumerate(history.get("indices", []))
        }
        telemetry_positions = [
            selected_positions.get(index) if index is not None else None
            for index in telemetry_definition_indices
        ]
        signal_positions = [
            selected_positions.get(index) if index is not None else None
            for index in signal_definition_indices
        ]
        frames = [
            frame
            for frame in history.get("frames", []) or []
            if isinstance(frame, Mapping)
            and _to_float(frame.get("absolute_minute"), None) is not None
        ]
        frames.sort(
            key=lambda frame: (
                float(_to_float(frame.get("absolute_minute"), 0.0) or 0.0),
                int(_to_float(frame.get("step_count"), 0) or 0),
                int(_to_float(frame.get("seq"), 0) or 0),
            )
        )

        interval_minutes = interval_seconds / 60.0
        available_start = (
            float(_to_float(frames[0].get("absolute_minute"), 0.0) or 0.0)
            if frames
            else None
        )
        available_end = (
            float(_to_float(frames[-1].get("absolute_minute"), 0.0) or 0.0)
            if frames
            else None
        )
        effective_start = max(start_minute, available_start) if available_start is not None else None
        effective_end = min(end_minute, available_end) if available_end is not None else None
        sample_count = 0
        if effective_start is not None and effective_end is not None and effective_start <= effective_end + 1e-9:
            raw_sample_count = (effective_end - effective_start + 1e-9) / interval_minutes + 1.0
            if not math.isfinite(raw_sample_count) or raw_sample_count > 10000:
                raise ValueError("history query would return more than 10000 samples; increase interval_seconds")
            sample_count = max(0, int(math.floor(raw_sample_count + 1e-9)))

        absolute_minutes: List[Any] = []
        simu_times: List[str] = []
        source_absolute_minutes: List[Any] = []
        source_simu_times: List[str] = []
        source_wall_times: List[str] = []
        telemetry_values: List[List[Any]] = []
        signal_values: List[List[Any]] = []
        telemetry_valid: List[List[int]] = []
        signal_valid: List[List[int]] = []

        def frame_values(
            frame: Mapping[str, Any],
            field: str,
            positions: Sequence[Optional[int]],
            *,
            signal: bool = False,
        ) -> List[Any]:
            values = frame.get(field, [])
            source = values if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) else []
            result: List[Any] = []
            for position in positions:
                if position is None or position >= len(source) or source[position] is None:
                    result.append(None)
                    continue
                if signal:
                    result.append(1 if float(_to_float(source[position], 0.0) or 0.0) > 0.5 else 0)
                else:
                    result.append(_json_scalar(source[position]))
            return result

        def frame_valid(frame: Mapping[str, Any], positions: Sequence[Optional[int]]) -> List[int]:
            values = frame.get("valid_values", [])
            source = values if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) else []
            return [
                int(_to_float(source[position], 0) or 0)
                if position is not None and position < len(source) and source[position] is not None
                else 0
                for position in positions
            ]

        frame_index = 0
        for sample_index in range(sample_count):
            target_minute = round(float(effective_start) + sample_index * interval_minutes, 9)
            while (
                frame_index + 1 < len(frames)
                and float(_to_float(frames[frame_index + 1].get("absolute_minute"), 0.0) or 0.0)
                <= target_minute + 1e-9
            ):
                frame_index += 1
            frame = frames[frame_index]
            source_minute = float(_to_float(frame.get("absolute_minute"), 0.0) or 0.0)
            absolute_minutes.append(_json_scalar(target_minute))
            simu_times.append(minute_to_time(target_minute))
            source_absolute_minutes.append(_json_scalar(source_minute))
            source_simu_times.append(str(frame.get("simu_time") or minute_to_time(source_minute)))
            source_wall_times.append(str(frame.get("wall_time") or "--"))
            telemetry_values.append(frame_values(frame, "scada_values", telemetry_positions))
            signal_values.append(frame_values(frame, "scada_values", signal_positions, signal=True))
            telemetry_valid.append(frame_valid(frame, telemetry_positions))
            signal_valid.append(frame_valid(frame, signal_positions))

        return {
            **metadata,
            "definition_signature": external_definition_signature,
            "measurement_definition_signature": history.get("definition_signature", ""),
            "run_id": int(history.get("run_id", 0) or 0),
            "start_time": minute_to_time(start_minute),
            "end_time": minute_to_time(end_minute),
            "start_absolute_minute": _json_scalar(start_minute),
            "end_absolute_minute": _json_scalar(end_minute),
            "available_start_absolute_minute": _json_scalar(available_start),
            "available_end_absolute_minute": _json_scalar(available_end),
            "effective_start_absolute_minute": _json_scalar(effective_start),
            "effective_end_absolute_minute": _json_scalar(effective_end),
            "interval_seconds": _json_scalar(interval_seconds),
            "value_layout": "time-major",
            "sample_count": len(absolute_minutes),
            "absolute_minutes": absolute_minutes,
            "simu_times": simu_times,
            "source_absolute_minutes": source_absolute_minutes,
            "source_simu_times": source_simu_times,
            "source_wall_times": source_wall_times,
            "telemetry_count": len(telemetry_names),
            "signal_count": len(signal_names),
            "telemetry_names": telemetry_names,
            "signal_names": signal_names,
            "telemetry_found": telemetry_found,
            "signal_found": signal_found,
            "telemetry_values": telemetry_values,
            "signal_values": signal_values,
            "telemetry_valid": telemetry_valid,
            "signal_valid": signal_valid,
            "yc_names": telemetry_names,
            "yx_names": signal_names,
            "yc_values": telemetry_values,
            "yx_values": signal_values,
            "missing": {
                "telemetry": [name for name, found in zip(telemetry_names, telemetry_found) if not found],
                "signals": [name for name, found in zip(signal_names, signal_found) if not found],
            },
        }

    def _command_entry_time_info(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        absolute_minute = _to_float(entry.get("received_absolute_minute", entry.get("issued_absolute_minute")), None)
        return {
            "wall_time": entry.get("received_wall_time", entry.get("time", "")) or "--",
            "simu_time": entry.get("received_simu_time") or (minute_to_time(absolute_minute) if absolute_minute is not None else "--"),
            "absolute_minute": absolute_minute,
            "expires_at_absolute_minute": _to_float(entry.get("expires_at_absolute_minute"), None),
            "source": entry.get("source", ""),
            "command_origin": _command_origin(entry),
        }

    def _latest_active_control_update(
        self,
        command_kind: str,
        dev_type: str,
        dev_name: str,
        field_name: str,
    ) -> Dict[str, Any]:
        override_key = (command_kind, dev_type, dev_name, field_name)
        if override_key in self._simulator_ui_control_override_keys():
            return {
                "wall_time": "--",
                "simu_time": "--",
                "absolute_minute": None,
                "expires_at_absolute_minute": None,
                "source": "simulator-ui",
                "command_origin": "simulator-ui",
                "active": True,
            }
        for entry in reversed(self._active_control_command_entries(self.clock.absolute_minute)):
            normalized = entry.get("normalized", {})
            if not isinstance(normalized, Mapping):
                continue
            if command_kind == "remote_adjustment":
                items = normalized.get("set_values", [])
                if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
                    continue
                for item in items:
                    if (
                        isinstance(item, Mapping)
                        and str(item.get("dev_type", "")) == dev_type
                        and str(item.get("dev_name", "")) == dev_name
                        and str(item.get("set_type", "")) == field_name
                    ):
                        return self._command_entry_time_info(entry) | {"active": True}
                continue
            items = normalized.get("run_status", [])
            if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
                continue
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                if str(item.get("dev_type", "")) != dev_type or str(item.get("dev_name", "")) != dev_name:
                    continue
                if field_name == "status" and "status" in item:
                    return self._command_entry_time_info(entry) | {"active": True}
                if field_name == "run_stat" and item.get("run_stat", "") != "":
                    return self._command_entry_time_info(entry) | {"active": True}
        return {
            "wall_time": "--",
            "simu_time": "--",
            "absolute_minute": None,
            "expires_at_absolute_minute": None,
            "source": "",
            "command_origin": "",
            "active": False,
        }

    def _control_definition_rows(self, block_name: str) -> List[Dict[str, Any]]:
        book = self.control_book if block_name in self.control_book.data else self.source_stat_book
        block = book.data.get(block_name)
        if block is None:
            return []
        return [
            {header: row.get(header, "") for header in block.header_list}
            for row in getattr(block, "data", [])
        ]

    def _latest_control_value_items(self) -> List[Dict[str, Any]]:
        run_stats, cb_status, set_values, _soc_values = self._stat_maps()
        items: List[Dict[str, Any]] = []

        for row in self._control_definition_rows("RunStat"):
            dev_type = str(row.get("dev_type", ""))
            dev_name = _dev_name(row)
            if not dev_type or not dev_name:
                continue
            value = int(_to_float(run_stats.get((dev_type, dev_name), row.get("run_stat", 0)), 0) or 0)
            update = self._latest_active_control_update("remote_control", dev_type, dev_name, "run_stat")
            items.append(
                {
                    "name": automatic_point_name(dev_type, dev_name, "run_stat"),
                    "command_kind": "remote_control",
                    "category": "遥控",
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "control_type": "run_stat",
                    "value": value,
                    "text": "投入" if value else "退出",
                    "updated_wall_time": update["wall_time"],
                    "updated_simu_time": update["simu_time"],
                    "updated_absolute_minute": update["absolute_minute"],
                    "expires_at_absolute_minute": update["expires_at_absolute_minute"],
                    "active": update["active"],
                    "source": update["source"],
                    "command_origin": update["command_origin"],
                }
            )

        for row in self._control_definition_rows("CbOpenStat"):
            dev_type = str(row.get("dev_type", ""))
            dev_name = _dev_name(row)
            if not dev_type or not dev_name:
                continue
            value = int(_to_float(cb_status.get((dev_type, dev_name), row.get("status", 0)), 0) or 0)
            update = self._latest_active_control_update("remote_control", dev_type, dev_name, "status")
            items.append(
                {
                    "name": automatic_point_name(dev_type, dev_name, "status"),
                    "command_kind": "remote_control",
                    "category": "遥控",
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "control_type": "status",
                    "value": value,
                    "text": "闭合" if value else "断开",
                    "updated_wall_time": update["wall_time"],
                    "updated_simu_time": update["simu_time"],
                    "updated_absolute_minute": update["absolute_minute"],
                    "expires_at_absolute_minute": update["expires_at_absolute_minute"],
                    "active": update["active"],
                    "source": update["source"],
                    "command_origin": update["command_origin"],
                }
            )

        for row in self._control_definition_rows("SetValue"):
            dev_type = str(row.get("dev_type", ""))
            dev_name = _dev_name(row)
            set_type = str(row.get("set_type", ""))
            if not dev_type or not dev_name or not set_type:
                continue
            value = set_values.get((dev_type, dev_name), {}).get(set_type, row.get("set_value", ""))
            update = self._latest_active_control_update("remote_adjustment", dev_type, dev_name, set_type)
            items.append(
                {
                    "name": automatic_point_name(dev_type, dev_name, set_type),
                    "command_kind": "remote_adjustment",
                    "category": "遥调",
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "set_type": set_type,
                    "value": _json_scalar(value),
                    "updated_wall_time": update["wall_time"],
                    "updated_simu_time": update["simu_time"],
                    "updated_absolute_minute": update["absolute_minute"],
                    "expires_at_absolute_minute": update["expires_at_absolute_minute"],
                    "active": update["active"],
                    "source": update["source"],
                    "command_origin": update["command_origin"],
                }
            )

        return items

    def _external_control_groups(
        self,
    ) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
        items = self._latest_control_value_items()
        return (
            self._external_unique_items(items, "command_kind", "remote_adjustment"),
            self._external_unique_items(items, "command_kind", "remote_control"),
        )

    def external_control_names(self) -> Dict[str, Any]:
        adjustments, controls = self._external_control_groups()
        adjustment_names = [str(item.get("name", "")) for item in adjustments]
        control_names = [str(item.get("name", "")) for item in controls]
        signature = self._external_names_signature(
            {
                "remote_adjustment_names": adjustment_names,
                "remote_control_names": control_names,
            }
        )
        return {
            **self._external_response_metadata(),
            "definition_signature": signature,
            "remote_adjustment_count": len(adjustment_names),
            "remote_control_count": len(control_names),
            "remote_adjustment_names": adjustment_names,
            "remote_control_names": control_names,
            "yt_names": adjustment_names,
            "yk_names": control_names,
        }

    def latest_control_values(self) -> Dict[str, Any]:
        """Return compact current remote-control and remote-adjustment values for external clients."""
        time_payload = self._api_time_payload()
        items = [
            self._compact_external_value_item(item, time_payload, include_active=True)
            for item in self._latest_control_value_items()
        ]
        return {
            **self._external_response_metadata(),
            "items": items,
            "values": {item["name"]: item.get("value") for item in items},
        }

    def _external_control_items(self, payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        collected: List[Mapping[str, Any]] = []
        for key in ("commands", "items", "controls"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                collected.extend(item for item in value if isinstance(item, Mapping))
        values = payload.get("values")
        if isinstance(values, Mapping):
            collected.extend({"name": name, "value": value} for name, value in values.items())
        if not collected and any(key in payload for key in ("name", "dev_type", "dev_name", "set_type", "control_type")):
            collected.append(payload)
        return collected

    def _control_name_index(self) -> Dict[str, Mapping[str, Any]]:
        return {
            str(item.get("name", "")): item
            for item in self._latest_control_value_items()
            if isinstance(item, Mapping) and item.get("name")
        }

    def _normalize_external_control_payload(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        run_items: List[Dict[str, Any]] = []
        set_items: List[Dict[str, Any]] = []
        if isinstance(payload.get("run_status"), Sequence) and not isinstance(payload.get("run_status"), (str, bytes)):
            run_items.extend(item for item in payload.get("run_status", []) if isinstance(item, Mapping))
        if isinstance(payload.get("remote_controls"), Sequence) and not isinstance(payload.get("remote_controls"), (str, bytes)):
            run_items.extend(item for item in payload.get("remote_controls", []) if isinstance(item, Mapping))
        for key in ("set_values", "setpoints", "remote_adjustments"):
            if isinstance(payload.get(key), Sequence) and not isinstance(payload.get(key), (str, bytes)):
                set_items.extend(item for item in payload.get(key, []) if isinstance(item, Mapping))

        name_index = self._control_name_index()
        resolved_items: List[Dict[str, Any]] = []
        for item in self._external_control_items(payload):
            raw_name = str(item.get("name", item.get("command_name", item.get("control_name", "")))).strip()
            definition = name_index.get(raw_name, {})
            dev_type = str(item.get("dev_type", item.get("type", definition.get("dev_type", ""))))
            dev_name = str(item.get("dev_name", item.get("device", definition.get("dev_name", ""))))
            value = item.get("value", item.get("set_value", item.get("run_stat", item.get("status", ""))))
            command_kind = str(item.get("command_kind", definition.get("command_kind", ""))).lower()
            control_type = str(item.get("control_type", item.get("meas_type", definition.get("control_type", ""))))
            set_type = str(item.get("set_type", definition.get("set_type", "")))
            if (not dev_type or not dev_name or not (set_type or control_type)) and raw_name:
                parts = raw_name.split(".")
                if len(parts) >= 3:
                    dev_type = dev_type or parts[0]
                    dev_name = dev_name or ".".join(parts[1:-1])
                    tail = parts[-1]
                    if tail in ("run_stat", "status"):
                        control_type = control_type or tail
                    else:
                        set_type = set_type or tail
            if not dev_type or not dev_name:
                continue
            if set_type or command_kind in ("remote_adjustment", "yt", "遥调"):
                if not set_type:
                    continue
                set_items.append({"dev_type": dev_type, "dev_name": dev_name, "set_type": set_type, "set_value": value})
                resolved_items.append(
                    {
                        "name": raw_name or automatic_point_name(dev_type, dev_name, set_type),
                        "value": _json_scalar(value),
                    }
                )
                continue
            field_name = "status" if control_type == "status" else "run_stat"
            run_row: Dict[str, Any] = {"dev_type": dev_type, "dev_name": dev_name}
            run_row[field_name] = value
            run_items.append(run_row)
            resolved_items.append(
                {
                    "name": raw_name or automatic_point_name(dev_type, dev_name, field_name),
                    "value": _json_scalar(value),
                }
            )

        return {"run_status": run_items, "set_values": set_items, "resolved_items": resolved_items}

    def apply_external_control_values(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if _has_cancel_command_payload(payload):
            source = str(payload.get("source") or "trainee-external-api")
            if not _is_trainee_command_source(source):
                source = f"trainee-{source}"
            result = self.cancel_student_commands(payload | {"source": source}, source=source)
            return {
                **self._external_response_metadata(),
                "cancelled": result["cancelled"],
                "cancelled_items": result["cancelled_items"],
                "control_values": self.latest_control_values(),
            }
        normalized = self._normalize_external_control_payload(payload)
        command_payload: Dict[str, Any] = {
            "run_status": normalized["run_status"],
            "set_values": normalized["set_values"],
        }
        for key in (
            "valid_for_minutes",
            "valid_minutes",
            "valid_for_seconds",
            "expires_at_absolute_minute",
            "expires_at_minute",
            "sent_wall_time",
            "sent_simu_time",
            "sent_absolute_minute",
            "command_origin",
            "commandOrigin",
            "origin",
            "manual_hold",
            "hold_until_cancelled",
        ):
            if key in payload:
                command_payload[key] = payload[key]
        source = str(payload.get("source") or "trainee-external-api")
        if not _is_trainee_command_source(source):
            source = f"trainee-{source}"
        result = self.apply_student_commands(command_payload | {"source": source}, source=source)
        time_payload = self._api_time_payload()
        updated_items = [
            item | self._external_update_time_fields(time_payload)
            for item in normalized["resolved_items"]
        ]
        return {
            **self._external_response_metadata(),
            "accepted": {
                "remote_controls": result.get("run_status", 0),
                "remote_adjustments": result.get("set_values", 0),
                "ignored": result.get("ignored", 0),
            },
            "updated_items": updated_items,
            "control_values": self.latest_control_values(),
        }

    @staticmethod
    def _external_payload_sequence(payload: Mapping[str, Any], keys: Sequence[str]) -> List[Any]:
        for key in keys:
            if key not in payload:
                continue
            value = payload.get(key)
            if value is None:
                return []
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return list(value)
            raise ValueError(f"{key} must be a list")
        return []

    def apply_external_control_frame(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        adjustment_names = [
            str(name).strip()
            for name in self._external_payload_sequence(
                payload,
                ("remote_adjustment_names", "adjustment_names", "yt_names"),
            )
        ]
        adjustment_values = self._external_payload_sequence(
            payload,
            ("remote_adjustment_values", "adjustment_values", "yt_values"),
        )
        control_names = [
            str(name).strip()
            for name in self._external_payload_sequence(
                payload,
                ("remote_control_names", "control_names", "yk_names"),
            )
        ]
        control_values = self._external_payload_sequence(
            payload,
            ("remote_control_values", "control_values", "yk_values"),
        )
        if len(adjustment_names) != len(adjustment_values):
            raise ValueError("remote adjustment name/value list length mismatch")
        if len(control_names) != len(control_values):
            raise ValueError("remote control name/value list length mismatch")

        all_definitions = self._control_name_index()
        adjustment_definitions = {
            name: item
            for name, item in all_definitions.items()
            if str(item.get("command_kind", "")) == "remote_adjustment"
        }
        control_definitions = {
            name: item
            for name, item in all_definitions.items()
            if str(item.get("command_kind", "")) == "remote_control"
        }
        commands: List[Dict[str, Any]] = []
        for name, value in zip(adjustment_names, adjustment_values):
            if name in adjustment_definitions:
                commands.append({"name": name, "value": value})
        for name, value in zip(control_names, control_values):
            if name in control_definitions:
                commands.append({"name": name, "value": value})
        unresolved_count = sum(name not in adjustment_definitions for name in adjustment_names) + sum(
            name not in control_definitions for name in control_names
        )

        delegated_keys = (
            "valid_for_minutes",
            "valid_minutes",
            "valid_for_seconds",
            "expires_at_absolute_minute",
            "expires_at_minute",
            "sent_wall_time",
            "sent_simu_time",
            "sent_absolute_minute",
            "source",
            "command_origin",
            "commandOrigin",
            "origin",
            "manual_hold",
            "hold_until_cancelled",
        )
        if commands:
            applied = self.apply_external_control_values(
                {"commands": commands}
                | {key: payload[key] for key in delegated_keys if key in payload}
            )
            accepted = dict(applied.get("accepted", {}))
            accepted["ignored"] = int(_to_float(accepted.get("ignored"), 0) or 0) + unresolved_count
        else:
            applied = {
                **self._external_response_metadata(),
                "accepted": {
                    "remote_controls": 0,
                    "remote_adjustments": 0,
                    "ignored": len(adjustment_names) + len(control_names),
                },
            }
            accepted = dict(applied["accepted"])

        current = self._control_name_index()

        def results(
            names: Sequence[str],
            values: Sequence[Any],
            definitions: Mapping[str, Mapping[str, Any]],
        ) -> List[Dict[str, Any]]:
            rows: List[Dict[str, Any]] = []
            for name, requested_value in zip(names, values):
                definition = definitions.get(name)
                item = current.get(name, {})
                found = definition is not None
                active = bool(item.get("active", False)) if found else False
                row = {
                    "name": name,
                    "requested_value": _json_scalar(requested_value),
                    "value": _json_scalar(item.get("value")) if found else None,
                    "found": found,
                    "accepted": bool(found and active),
                    "active": active,
                    "reason": "" if found and active else ("unknown control name" if not found else "command not active"),
                }
                if found:
                    row.update(
                        {
                            "updated_wall_time": item.get("updated_wall_time", "--"),
                            "updated_simu_time": item.get("updated_simu_time", "--"),
                            "updated_absolute_minute": _json_scalar(item.get("updated_absolute_minute")),
                            "expires_at_absolute_minute": _json_scalar(item.get("expires_at_absolute_minute")),
                            "command_origin": str(item.get("command_origin", "")),
                        }
                    )
                rows.append(row)
            return rows

        adjustment_results = results(adjustment_names, adjustment_values, adjustment_definitions)
        control_results = results(control_names, control_values, control_definitions)
        return {
            **self._external_response_metadata(),
            "definition_signature": self.external_control_names()["definition_signature"],
            "accepted": accepted,
            "remote_adjustment_results": adjustment_results,
            "remote_control_results": control_results,
            "yt_results": adjustment_results,
            "yk_results": control_results,
        }

    def _definition_row(self, block: EBlock, row_key: Any) -> Dict[str, Any]:
        if not isinstance(row_key, Mapping):
            raise ValueError("row_key must be an object")
        name = str(row_key.get("name", "")).strip()
        idx = str(row_key.get("idx", "")).strip()
        if not name and not idx:
            raise ValueError("row_key requires name or idx")

        matches: List[Dict[str, Any]] = []
        for item in block.data:
            if name:
                if "name" not in block.header_list or str(item.get("name", "")) != name:
                    continue
            if idx:
                if "idx" not in block.header_list or str(item.get("idx", "")) != idx:
                    continue
            matches.append(item)
        if not matches:
            identity = name or idx
            raise ValueError(f"Unknown definition row in {block.name}: {identity}")
        if len(matches) != 1:
            identity = name or idx
            raise ValueError(f"Definition row identity must be unique in {block.name}: {identity}")
        return matches[0]

    def _measurement_definition_row(
        self,
        rows: Sequence[Sequence[str]],
        payload: Mapping[str, Any],
    ) -> Tuple[int, Dict[str, Any]]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("Measurement name is required")
        matches: List[Tuple[int, Dict[str, Any]]] = []
        for index, row in enumerate(rows):
            item = _measurement_row_to_dict(row)
            if str(item.get("name", "")) == name:
                matches.append((index, item))
        if not matches:
            raise ValueError(f"Unknown measurement: {name}")
        if len(matches) != 1:
            raise ValueError(f"Measurement identity must be unique: {name}")
        index, item = matches[0]
        for identity_field in ("dev_type", "dev_name", "meas_type"):
            expected = str(payload.get(identity_field, "")).strip()
            if expected and str(item.get(identity_field, "")) != expected:
                raise ValueError(f"Measurement {identity_field} does not match: {name}")
        return index, item

    @staticmethod
    def _manual_change_value_text(value: Any) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _manual_change_values_equal(left: Any, right: Any) -> bool:
        left_text = str(left if left is not None else "").strip()
        right_text = str(right if right is not None else "").strip()
        if left_text == right_text:
            return True
        try:
            left_number = float(left_text[:-1].strip() if left_text.endswith("%") else left_text)
            right_number = float(right_text[:-1].strip() if right_text.endswith("%") else right_text)
        except (TypeError, ValueError):
            return False
        return math.isfinite(left_number) and math.isfinite(right_number) and math.isclose(
            left_number,
            right_number,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )

    @staticmethod
    def _manual_change_persistence_status(persisted: bool) -> str:
        return "覆盖层已保存" if persisted else "覆盖层保存失败"

    def _set_manual_change_sync_state_unlocked(
        self,
        item: Dict[str, Any],
        *,
        persisted: bool,
        error: str = "",
        increment_retry: bool = False,
    ) -> None:
        item["persisted"] = bool(persisted)
        item["persistence_status"] = self._manual_change_persistence_status(persisted)
        item["sync_status"] = "synced" if persisted else "failed"
        item["last_sync_time"] = _now_text()
        item["last_sync_error"] = "" if persisted else str(error or "人工覆盖层保存失败")
        retry_count = int(_to_float(item.get("retry_count"), 0) or 0)
        item["retry_count"] = retry_count + (1 if increment_retry else 0)

    @staticmethod
    def _manual_change_sigma(weight: Any) -> Optional[float]:
        number = _to_float(weight, None)
        if number is None or number <= 0:
            return None
        return 1.0 / math.sqrt(number)

    @staticmethod
    def _manual_change_id(kind: str, identity: Mapping[str, Any], field_name: str) -> str:
        canonical = json.dumps(
            {
                "kind": str(kind),
                "identity": {str(key): str(value) for key, value in sorted(identity.items())},
                "field": str(field_name),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return f"{kind}-{digest}"

    def _manual_definition_changes_payload_unlocked(
        self,
        *,
        accepted_source_fingerprints: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        changes = []
        for item in self._manual_definition_changes.values():
            copied = dict(item)
            if isinstance(copied.get("row_key"), Mapping):
                copied["row_key"] = dict(copied["row_key"])
            changes.append(copied)
        changes.sort(
            key=lambda item: (str(item.get("modified_at", "")), str(item.get("id", ""))),
            reverse=True,
        )
        source_fingerprint = self._manual_definition_source_fingerprint()
        accepted_fingerprints = list(
            dict.fromkeys(
                fingerprint
                for fingerprint in (
                    source_fingerprint,
                    *(accepted_source_fingerprints or ()),
                )
                if fingerprint
            )
        )
        return {
            "version": 5,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "source_fingerprint": source_fingerprint,
            "accepted_source_fingerprints": accepted_fingerprints,
            "revision": self.definition_snapshot.revision,
            "count": len(changes),
            "changes": changes,
        }

    def _write_manual_definition_changes_unlocked(
        self,
        *,
        accepted_source_fingerprints: Optional[Sequence[str]] = None,
    ) -> None:
        if not self._manual_definition_changes:
            self.manual_definition_changes_file.unlink(missing_ok=True)
            return
        self.manual_definition_changes_file.parent.mkdir(parents=True, exist_ok=True)
        payload = self._manual_definition_changes_payload_unlocked(
            accepted_source_fingerprints=accepted_source_fingerprints,
        )
        atomic_write_text(
            self.manual_definition_changes_file,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    def _manual_definition_source_fingerprint(
        self,
        text_overrides: Optional[Mapping[str, str]] = None,
    ) -> str:
        overrides = text_overrides or {}
        digest = hashlib.sha256()
        for file_key in ("model", "meas", "stat", "control"):
            path = self.source_files[file_key]
            digest.update(file_key.encode("ascii"))
            digest.update(b"\0")
            if file_key in overrides:
                digest.update(str(overrides[file_key]).encode("utf-8"))
            else:
                try:
                    digest.update(path.read_bytes())
                except OSError:
                    digest.update(b"<missing>")
            digest.update(b"\0")
        return digest.hexdigest()

    def _write_ahead_manual_definition_changes_unlocked(
        self,
    ) -> None:
        self._write_manual_definition_changes_unlocked()

    def _clear_manual_definition_changes_unlocked(self) -> int:
        cleared = len(self._manual_definition_changes)
        self._manual_definition_changes = {}
        self.manual_definition_changes_file.unlink(missing_ok=True)
        return cleared

    def clear_manual_definition_changes(self) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            cleared = self._clear_manual_definition_changes_unlocked()
            self._rebuild_effective_definitions_from_source_unlocked()
            return {
                **self._manual_definition_changes_payload_unlocked(),
                "cleared_count": cleared,
            }

    def _current_manual_change_value(
        self,
        item: Mapping[str, Any],
        snapshot: Optional[DefinitionSnapshot] = None,
    ) -> Optional[str]:
        active = snapshot or self.definition_snapshot
        kind = str(item.get("kind", ""))
        field_name = str(item.get("field", ""))
        if kind == "device":
            block = active.model_book.data.get(str(item.get("block_name", "")))
            if block is None or field_name not in block.header_list:
                return None
            row = self._definition_row(block, item.get("row_key", {}))
            return self._manual_change_value_text(row.get(field_name, ""))
        if kind == "measurement":
            index, _record = self._measurement_definition_row(
                active.measurement_rows,
                {"name": item.get("measurement_name", "")},
            )
            column = {"weight": 5, "valid": 6}.get(field_name)
            if column is not None:
                return self._manual_change_value_text(active.measurement_rows[index][column])
            if field_name == "median_deviation":
                values = _measurement_median_deviation_map(active)
                return self._manual_change_value_text(
                    values.get(str(item.get("measurement_name", "")), 0.0)
                )
            if field_name in {"status", "fixed_value"}:
                status, fixed_value = self._measurement_status_override(
                    active.measurement_rows[index]
                )
                return self._manual_change_value_text(
                    status if field_name == "status" else fixed_value
                )
            return None
        return None

    def _archive_manual_definition_changes_unlocked(self) -> Optional[Path]:
        if not self.manual_definition_changes_file.exists():
            return None
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        archived = self.runtime_dir / f"manual_overrides.stale.{timestamp}.json"
        try:
            self.manual_definition_changes_file.replace(archived)
        except OSError:
            self.manual_definition_changes_file.unlink(missing_ok=True)
            return None
        return archived

    def _source_definition_state_unlocked(
        self,
    ) -> Tuple[DefinitionSnapshot, EBook, EBook]:
        model_book = _load_book(self.source_files["model"])
        source_stat_book = _load_book(self.source_files["stat"])
        control_book = _load_book(
            self.source_files["control"]
            if self.source_files["control"].exists()
            else self.source_files["stat"]
        )
        source_stat_book, control_book = self._reconcile_source_dcp_controls_unlocked(
            model_book,
            source_stat_book,
            control_book,
        )
        dev_define_book = simu_loop._capability_define_book(
            model_book,
            self._legacy_dev_define_file(),
        )
        try:
            measurement_before, measurement_rows, measurement_after = parse_measurement_rows(
                self.source_files["meas"]
            )
        except Exception:
            measurement_before, measurement_rows, measurement_after = [], [], []
        measurement_rows, _added_measurements = _reconcile_hydrogen_inline_flow_measurements(
            model_book,
            measurement_rows,
        )
        snapshot = DefinitionSnapshot(
            revision=self.definition_snapshot.revision + 1,
            model_book=model_book,
            dev_define_book=dev_define_book,
            measurement_before=tuple(measurement_before),
            measurement_rows=tuple(tuple(row) for row in measurement_rows),
            measurement_after=tuple(measurement_after),
            measurement_median_deviations=self._read_source_measurement_median_deviations(
                measurement_rows
            ),
        )
        return snapshot, source_stat_book, control_book

    def _apply_manual_runtime_control_overrides_unlocked(
        self,
        items: Sequence[Mapping[str, Any]],
    ) -> None:
        for item in items:
            if item.get("kind") != "device":
                continue
            if item.get("effective") is False:
                continue
            field_name = str(item.get("field", "")).strip().casefold()
            block_name = str(item.get("block_name", "")).strip()
            row_key = item.get("row_key", {})
            if not isinstance(row_key, Mapping):
                continue
            dev_name = str(
                row_key.get("name", item.get("object_name", ""))
            ).strip()
            if not block_name or not dev_name:
                continue
            current_value = item.get("current_value", "")
            if field_name in RUNTIME_CONTROL_STATUS_FIELDS:
                for book in (self.source_stat_book, self.control_book):
                    self._upsert_runtime_status_value(
                        book,
                        block_name,
                        dev_name,
                        field_name,
                        current_value,
                    )
                continue
            set_type = self._runtime_control_set_type(block_name, field_name)
            if set_type is None:
                continue
            for book in (self.source_stat_book, self.control_book):
                self._upsert_runtime_setpoint_value(
                    book,
                    block_name,
                    dev_name,
                    set_type,
                    current_value,
                )

    def _apply_manual_measurement_status_overrides_unlocked(
        self,
        snapshot: DefinitionSnapshot,
        items: Sequence[Mapping[str, Any]],
    ) -> None:
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if item.get("kind") != "measurement":
                continue
            field_name = str(item.get("field", ""))
            if field_name not in {"status", "fixed_value"}:
                continue
            measurement_name = str(item.get("measurement_name", "")).strip()
            if measurement_name:
                grouped.setdefault(measurement_name, {})[field_name] = item.get(
                    "current_value",
                    "",
                )

        statuses: Dict[str, Dict[str, Any]] = {}
        for measurement_name, values in grouped.items():
            try:
                index, _record = self._measurement_definition_row(
                    snapshot.measurement_rows,
                    {"name": measurement_name},
                )
            except (KeyError, ValueError):
                continue
            default_status = _measurement_status_from_valid(
                snapshot.measurement_rows[index][6]
            )
            status = str(values.get("status", default_status)).strip().casefold()
            if status not in MEASUREMENT_STATUS_TOKENS:
                status = default_status
            fixed_value = _to_float(values.get("fixed_value"), None)
            statuses[measurement_name] = {
                "status": status,
                "fixed_value": fixed_value,
            }
        self.local_settings["measurement_statuses"] = statuses

    def _migrate_legacy_measurement_status_overrides_unlocked(self) -> bool:
        configured_statuses = self.local_settings.get("measurement_statuses", {})
        if not isinstance(configured_statuses, Mapping) or not configured_statuses:
            return False
        migrated = False
        existing_fields = {
            (
                str(item.get("measurement_name", "")),
                str(item.get("field", "")),
            )
            for item in self._manual_definition_changes.values()
            if item.get("kind") == "measurement"
        }
        rows = self.definition_snapshot.measurement_rows
        for measurement_name, configured in configured_statuses.items():
            if not isinstance(configured, Mapping):
                continue
            name = str(measurement_name).strip()
            if not name:
                continue
            try:
                index, _record = self._measurement_definition_row(
                    rows,
                    {"name": name},
                )
            except (KeyError, ValueError):
                continue
            before_row = list(rows[index])
            after_row = list(before_row)
            default_status = _measurement_status_from_valid(before_row[6])
            status = str(configured.get("status", default_status)).strip().casefold()
            if status not in MEASUREMENT_STATUS_TOKENS:
                status = default_status
            fixed_value = _to_float(configured.get("fixed_value"), None)
            after_row[6] = str(MEASUREMENT_STATUS_VALIDITY[status])
            changed_fields: List[str] = []
            if (name, "valid") not in existing_fields and not self._manual_change_values_equal(
                before_row[6],
                after_row[6],
            ):
                changed_fields.append("valid")
            if (name, "status") not in existing_fields and status != default_status:
                changed_fields.append("status")
            if (
                (name, "fixed_value") not in existing_fields
                and status == "fixed"
                and fixed_value is not None
            ):
                changed_fields.append("fixed_value")
            if not changed_fields:
                continue
            self._record_measurement_manual_changes_unlocked(
                before_row,
                after_row,
                changed_fields,
                persisted=False,
                persistence_error="正在迁移旧量测状态覆盖",
                before_status=default_status,
                before_fixed_value=None,
                after_status=status,
                after_fixed_value=fixed_value,
            )
            migrated = True

        # Measurement status edits now live exclusively in manual_overrides.json.
        # Keep unrelated runtime settings, but remove the legacy duplicate layer.
        self.local_settings["measurement_statuses"] = {}
        try:
            _write_json(self.settings_file, self.local_settings)
        except OSError:
            pass
        return migrated

    def _rebuild_effective_definitions_from_source_unlocked(
        self,
        *,
        materialize_controls: bool = True,
    ) -> DefinitionSnapshot:
        source_snapshot, source_stat_book, control_book = (
            self._source_definition_state_unlocked()
        )
        old_runtime_stat_book = self.runtime_stat_book
        self.source_stat_book = source_stat_book
        self.control_book = control_book
        items = list(self._manual_definition_changes.values())
        next_snapshot, _kinds = self._snapshot_with_manual_change_values_unlocked(
            source_snapshot,
            items,
        )
        self._apply_manual_runtime_control_overrides_unlocked(items)
        self._apply_manual_measurement_status_overrides_unlocked(next_snapshot, items)
        self._publish_definition_snapshot(next_snapshot)

        # Rebuild the effective control baseline while preserving the live SOC
        # rows.  Active automatic/manual commands are then layered on top.
        self.runtime_stat_book = old_runtime_stat_book
        self.runtime_stat_book = self._base_stat_book_for_controls()
        self._ensure_runtime_stat_book()
        if materialize_controls:
            self._materialize_active_control_commands(self.clock.absolute_minute)
            self._apply_device_faults(self.clock.minute, self.clock.absolute_minute)
        return next_snapshot

    def _load_manual_definition_changes(self) -> None:
        overlay_exists = self.manual_definition_changes_file.exists()
        payload = _read_json(self.manual_definition_changes_file, {})
        accepted_fingerprints: List[str] = []
        if isinstance(payload, Mapping):
            expected_fingerprint = str(payload.get("source_fingerprint", "")).strip()
            if expected_fingerprint:
                accepted_fingerprints.append(expected_fingerprint)
            raw_accepted = payload.get("accepted_source_fingerprints", [])
            if isinstance(raw_accepted, Sequence) and not isinstance(raw_accepted, (str, bytes)):
                accepted_fingerprints.extend(
                    str(fingerprint).strip()
                    for fingerprint in raw_accepted
                    if str(fingerprint).strip()
                )
        accepted_fingerprints = list(dict.fromkeys(accepted_fingerprints))
        current_fingerprint = self._manual_definition_source_fingerprint()
        source_definition_changed = bool(
            accepted_fingerprints and current_fingerprint not in accepted_fingerprints
        )
        model_matches = not isinstance(payload, Mapping) or str(
            payload.get("model_id", self.model_id)
        ).strip() in {"", self.model_id}
        if overlay_exists and (
            not isinstance(payload, Mapping)
            or not payload
            or not accepted_fingerprints
        ):
            self._manual_definition_changes = {}
            self._archive_manual_definition_changes_unlocked()
            return
        if isinstance(payload, Mapping) and payload and not model_matches:
            self._manual_definition_changes = {}
            self._archive_manual_definition_changes_unlocked()
            return
        items = payload.get("changes", []) if isinstance(payload, Mapping) else []
        loaded: Dict[str, Dict[str, Any]] = {}
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            for raw_item in items:
                if not isinstance(raw_item, Mapping):
                    continue
                item = dict(raw_item)
                change_id = str(item.get("id", "")).strip()
                if not change_id or item.get("kind") not in {"device", "measurement"} or not item.get("field"):
                    continue
                persisted = bool(item.get("persisted", False))
                item.setdefault("sync_status", "synced" if persisted else "failed")
                item.setdefault("last_sync_time", str(item.get("modified_at", "")))
                item.setdefault("last_sync_error", "" if persisted else "人工覆盖层尚未同步")
                item.setdefault("retry_count", 0)
                loaded[change_id] = item
        self._manual_definition_changes = loaded
        if source_definition_changed and self._manual_definition_changes:
            try:
                source_snapshot, _source_stat, _source_control = (
                    self._source_definition_state_unlocked()
                )
            except (KeyError, ValueError, OSError):
                source_snapshot = None
            if source_snapshot is not None:
                for item in self._manual_definition_changes.values():
                    try:
                        source_value = self._current_manual_change_value(
                            item,
                            snapshot=source_snapshot,
                        )
                    except (KeyError, ValueError):
                        source_value = None
                    if source_value is not None:
                        item["default_value"] = source_value
        migrated_legacy_statuses = self._migrate_legacy_measurement_status_overrides_unlocked()
        if not self._manual_definition_changes:
            return

        try:
            self._rebuild_effective_definitions_from_source_unlocked(
                materialize_controls=False,
            )
        except (KeyError, ValueError):
            self._manual_definition_changes = {}
            self._archive_manual_definition_changes_unlocked()
            self.reload_definition_state()
            return

        reconciled = migrated_legacy_statuses or source_definition_changed
        for change_id, item in list(self._manual_definition_changes.items()):
            if item.get("effective") is False:
                reconciled = True
                continue
            try:
                current_value = self._current_manual_change_value(item)
            except (KeyError, ValueError):
                current_value = None
            if current_value is None or not self._manual_change_values_equal(
                current_value,
                item.get("current_value", ""),
            ):
                self._manual_definition_changes.pop(change_id, None)
                reconciled = True
                continue
            if self._manual_change_values_equal(
                item.get("current_value", ""),
                item.get("default_value", ""),
            ):
                self._manual_definition_changes.pop(change_id, None)
                reconciled = True
                continue
            if not bool(item.get("persisted", False)) or item.get("sync_status") != "synced":
                self._set_manual_change_sync_state_unlocked(item, persisted=True)
                reconciled = True
        if reconciled:
            try:
                self._write_manual_definition_changes_unlocked()
            except OSError:
                pass

    def manual_definition_changes(self) -> Dict[str, Any]:
        with self.definition_update_lock:
            return self._manual_definition_changes_payload_unlocked()

    def _snapshot_with_manual_change_values_unlocked(
        self,
        current: DefinitionSnapshot,
        items: Sequence[Mapping[str, Any]],
    ) -> Tuple[DefinitionSnapshot, set[str]]:
        kinds = {str(item.get("kind", "")) for item in items}
        model_book = simu_loop._clone_ebook(current.model_book) if "device" in kinds else current.model_book
        measurement_rows = [list(row) for row in current.measurement_rows]
        measurement_median_deviations = _measurement_median_deviation_map(current)
        changed = False

        device_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for raw_item in items:
            if raw_item.get("kind") != "device":
                continue
            item = raw_item if isinstance(raw_item, dict) else dict(raw_item)
            block_name = str(item.get("block_name", ""))
            row_key = item.get("row_key", {})
            identity = json.dumps(row_key, ensure_ascii=False, sort_keys=True)
            device_groups.setdefault((block_name, identity), []).append(item)

        for (block_name, _identity), group in device_groups.items():
            try:
                block = model_book.data.get(block_name)
                if block is None:
                    raise ValueError(f"Unknown model block: {block_name}")
                row_key = group[0].get("row_key", {})
                if not isinstance(row_key, Mapping):
                    raise ValueError(
                        f"Invalid device identity for manual change: {group[0].get('id', '')}"
                    )
                row = self._definition_row(block, row_key)
                desired = {
                    str(item.get("field", "")): item.get("current_value", "")
                    for item in group
                }
                normalized = normalize_device_changes(
                    row,
                    desired,
                    allow_out_of_bounds_setpoints=not self.enforce_runtime_setpoint_bounds,
                )
            except (KeyError, ValueError) as exc:
                for item in group:
                    item["effective"] = False
                    item["application_status"] = "invalid"
                    item["application_error"] = str(exc)
                continue
            for item in group:
                item["effective"] = True
                item["application_status"] = "applied"
                item["application_error"] = ""
            changed = changed or any(
                not self._manual_change_values_equal(row.get(field_name, ""), value)
                for field_name, value in normalized.items()
            )
            row.update(normalized)

        measurement_groups: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if item.get("kind") != "measurement":
                continue
            if isinstance(item, dict):
                item["effective"] = True
                item["application_status"] = "applied"
                item["application_error"] = ""
            measurement_name = str(item.get("measurement_name", ""))
            measurement_groups.setdefault(measurement_name, {})[str(item.get("field", ""))] = item.get(
                "current_value",
                "",
            )
        for measurement_name, desired_values in measurement_groups.items():
            index, current_item = self._measurement_definition_row(
                measurement_rows,
                {"name": measurement_name},
            )
            current_item["median_deviation"] = measurement_median_deviations.get(
                measurement_name,
                0.0,
            )
            normalized = normalize_measurement_changes(current_item, desired_values)
            changed = changed or not self._manual_change_values_equal(
                measurement_rows[index][5],
                normalized["weight"],
            ) or not self._manual_change_values_equal(
                measurement_rows[index][6],
                normalized["valid"],
            ) or not self._manual_change_values_equal(
                measurement_median_deviations.get(measurement_name, 0.0),
                normalized["median_deviation"],
            )
            measurement_rows[index][5] = normalized["weight"]
            measurement_rows[index][6] = normalized["valid"]
            if normalized["median_deviation"] == 0.0:
                measurement_median_deviations.pop(measurement_name, None)
            else:
                measurement_median_deviations[measurement_name] = normalized["median_deviation"]

        if not changed:
            return current, kinds
        dev_define_book = (
            simu_loop._capability_define_book(model_book, self._legacy_dev_define_file())
            if "device" in kinds
            else current.dev_define_book
        )
        return DefinitionSnapshot(
            revision=current.revision + 1,
            model_book=model_book,
            dev_define_book=dev_define_book,
            measurement_before=current.measurement_before,
            measurement_rows=tuple(tuple(row) for row in measurement_rows),
            measurement_after=current.measurement_after,
            measurement_median_deviations=_normalized_measurement_median_deviation_pairs(
                measurement_median_deviations
            ),
        ), kinds

    def retry_manual_definition_changes(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            current = self.definition_snapshot
            require_definition_revision(payload, current.revision)
            raw_change_ids = payload.get("change_ids")
            if raw_change_ids is None:
                change_ids = [
                    change_id
                    for change_id, item in self._manual_definition_changes.items()
                    if not bool(item.get("persisted", False))
                ]
            else:
                if not isinstance(raw_change_ids, Sequence) or isinstance(raw_change_ids, (str, bytes)):
                    raise ValueError("change_ids must be an array")
                change_ids = list(
                    dict.fromkeys(
                        str(change_id).strip()
                        for change_id in raw_change_ids
                        if str(change_id).strip()
                    )
                )
            missing = [change_id for change_id in change_ids if change_id not in self._manual_definition_changes]
            if missing:
                raise ValueError(f"Unknown manual definition change: {missing[0]}")
            selected = [
                self._manual_definition_changes[change_id]
                for change_id in change_ids
                if not bool(self._manual_definition_changes[change_id].get("persisted", False))
            ]
            if not selected:
                result = self._manual_definition_changes_payload_unlocked()
                result.update(
                    {
                        "retried_count": 0,
                        "persisted_count": 0,
                        "memory_updated": False,
                        "persisted": True,
                        "change_record_persisted": True,
                    }
                )
                return result

            self._rebuild_effective_definitions_from_source_unlocked()
            original_changes = {
                change_id: dict(item)
                for change_id, item in self._manual_definition_changes.items()
            }
            persisted_count = 0
            for item in selected:
                change_id = str(item.get("id", ""))
                active_item = self._manual_definition_changes.get(change_id)
                if active_item is None:
                    continue
                self._set_manual_change_sync_state_unlocked(
                    active_item,
                    persisted=True,
                    increment_retry=True,
                )
                persisted_count += 1
                if self._manual_change_values_equal(
                    active_item.get("current_value", ""),
                    active_item.get("default_value", ""),
                ):
                    self._manual_definition_changes.pop(change_id, None)

            try:
                self._write_manual_definition_changes_unlocked()
            except OSError as exc:
                self._manual_definition_changes = original_changes
                error = f"人工覆盖层保存失败，请重试: {exc}"
                for item in selected:
                    active_item = self._manual_definition_changes.get(str(item.get("id", "")))
                    if active_item is not None:
                        self._set_manual_change_sync_state_unlocked(
                            active_item,
                            persisted=False,
                            error=error,
                            increment_retry=True,
                        )
                result = self._manual_definition_changes_payload_unlocked()
                result.update(
                    {
                        "retried_count": len(selected),
                        "persisted_count": 0,
                        "memory_updated": True,
                        "persisted": False,
                        "change_record_persisted": False,
                        "static_meta": self.static_meta(),
                        "warning": error,
                    }
                )
                return result

            result = self._manual_definition_changes_payload_unlocked()
            result.update(
                {
                    "retried_count": len(selected),
                    "persisted_count": persisted_count,
                    "memory_updated": True,
                    "persisted": True,
                    "change_record_persisted": True,
                    "static_meta": self.static_meta(),
                }
            )
            return result

    def _mark_manual_changes_persisted_unlocked(self, kind: str) -> None:
        for change_id, item in list(self._manual_definition_changes.items()):
            if item.get("kind") != kind:
                continue
            self._set_manual_change_sync_state_unlocked(item, persisted=True)
            if self._manual_change_values_equal(
                item.get("current_value", ""),
                item.get("default_value", ""),
            ):
                self._manual_definition_changes.pop(change_id, None)

    def _record_device_manual_changes_unlocked(
        self,
        block_name: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        changed_fields: Sequence[str],
        *,
        persisted: bool,
        persistence_error: str = "",
    ) -> None:
        row_key = {
            key: self._manual_change_value_text(after.get(key, ""))
            for key in ("idx", "name")
            if self._manual_change_value_text(after.get(key, "")).strip()
        }
        identity = {"block_name": block_name, **row_key}
        object_name = str(after.get("name", "")).strip() or f"{block_name}_{after.get('idx', '')}"
        now = _now_text()
        for field_name in changed_fields:
            change_id = self._manual_change_id("device", identity, field_name)
            existing = self._manual_definition_changes.get(change_id, {})
            default_value = self._manual_change_value_text(
                existing.get("default_value", before.get(field_name, ""))
            )
            current_value = self._manual_change_value_text(after.get(field_name, ""))
            if persisted and self._manual_change_values_equal(current_value, default_value):
                self._manual_definition_changes.pop(change_id, None)
                continue
            item = {
                **existing,
                "id": change_id,
                "kind": "device",
                "change_type": "设备参数",
                "object_type": block_name,
                "object_name": object_name,
                "object_id": str(after.get("idx", "")),
                "object_label": f"{block_name} · {object_name}",
                "block_name": block_name,
                "row_key": row_key,
                "field": field_name,
                "field_label": field_name,
                "default_value": default_value,
                "current_value": current_value,
                "modified_at": now,
                "source_file": "model.e",
            }
            self._set_manual_change_sync_state_unlocked(
                item,
                persisted=persisted,
                error=persistence_error,
            )
            self._manual_definition_changes[change_id] = item

    def _record_measurement_manual_changes_unlocked(
        self,
        before_row: Sequence[Any],
        after_row: Sequence[Any],
        changed_fields: Sequence[str],
        *,
        persisted: bool,
        persistence_error: str = "",
        before_status: Optional[str] = None,
        before_fixed_value: Any = None,
        before_median_deviation: Any = 0.0,
        after_status: Optional[str] = None,
        after_fixed_value: Any = None,
        after_median_deviation: Any = 0.0,
    ) -> None:
        after = _measurement_row_to_dict(after_row)
        measurement_name = str(after.get("name", ""))
        identity = {"measurement_name": measurement_name}
        object_type = str(after.get("dev_type", ""))
        object_name = str(after.get("dev_name", ""))
        raw_values = {
            "weight": (before_row[5], after_row[5]),
            "median_deviation": (
                before_median_deviation,
                after_median_deviation,
            ),
            "valid": (before_row[6], after_row[6]),
            "status": (
                before_status
                if before_status is not None
                else _measurement_status_from_valid(before_row[6]),
                after_status
                if after_status is not None
                else _measurement_status_from_valid(after_row[6]),
            ),
            "fixed_value": (before_fixed_value, after_fixed_value),
        }
        now = _now_text()
        for field_name in changed_fields:
            if field_name not in raw_values:
                continue
            default_raw, current_raw = raw_values[field_name]
            change_id = self._manual_change_id("measurement", identity, field_name)
            existing = self._manual_definition_changes.get(change_id, {})
            default_value = self._manual_change_value_text(existing.get("default_value", default_raw))
            current_value = self._manual_change_value_text(current_raw)
            if persisted and self._manual_change_values_equal(current_value, default_value):
                self._manual_definition_changes.pop(change_id, None)
                continue
            item = {
                **existing,
                "id": change_id,
                "kind": "measurement",
                "change_type": (
                    "量测参数"
                    if field_name in {"weight", "median_deviation"}
                    else "量测状态"
                ),
                "object_type": object_type,
                "object_name": object_name,
                "object_id": str(after.get("idx", "")),
                "object_label": f"{object_type}.{object_name} · {measurement_name}",
                "measurement_name": measurement_name,
                "measurement_type": str(after.get("meas_type", "")),
                "field": field_name,
                "field_label": {
                    "weight": "量测误差 / 权重",
                    "median_deviation": "中值偏差",
                    "valid": "量测有效性",
                    "status": "量测状态",
                    "fixed_value": "量测固定值",
                }[field_name],
                "default_value": default_value,
                "current_value": current_value,
                "modified_at": now,
                "source_file": (
                    DEFINITION_DEFAULTS_FILE
                    if field_name == "median_deviation"
                    else "meas.e"
                ),
            }
            self._set_manual_change_sync_state_unlocked(
                item,
                persisted=persisted,
                error=persistence_error,
            )
            if field_name == "weight":
                item["default_error_sigma"] = self._manual_change_sigma(default_value)
                item["current_error_sigma"] = self._manual_change_sigma(current_value)
            self._manual_definition_changes[change_id] = item

    @staticmethod
    def _merge_definition_warning(current: str, extra: str) -> str:
        return "；".join(text for text in (current, extra) if text)

    def _definition_update_result(
        self,
        snapshot: DefinitionSnapshot,
        record: Mapping[str, Any],
        *,
        persisted: bool,
        warning: str = "",
    ) -> Dict[str, Any]:
        result = {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "revision": snapshot.revision,
            "memory_updated": True,
            "persisted": persisted,
            "record": dict(record),
            "static_meta": self.static_meta(),
        }
        if warning:
            result["warning"] = warning
        return result

    @staticmethod
    def _runtime_control_set_type(block_name: str, field_name: str) -> Optional[str]:
        normalized_block = str(block_name or "").strip()
        normalized_field = str(field_name or "").strip().casefold()
        alias = RUNTIME_CONTROL_SETPOINT_ALIASES.get(
            (normalized_block, normalized_field)
        )
        if alias:
            return alias
        if normalized_field in RUNTIME_CONTROL_SETPOINT_FIELDS:
            return normalized_field
        if normalized_field.endswith("_set"):
            return normalized_field
        return None

    @staticmethod
    def _upsert_runtime_status_value(
        book: EBook,
        dev_type: str,
        dev_name: str,
        field_name: str,
        value: Any,
    ) -> None:
        normalized_field = str(field_name or "").strip().casefold()
        if normalized_field not in RUNTIME_CONTROL_STATUS_FIELDS:
            return
        block_name = "RunStat" if normalized_field == "run_stat" else "CbOpenStat"
        block = _ensure_block(book, block_name, STAT_HEADERS[block_name])
        row = _find_dev_row(block, dev_type, dev_name)
        if row is None:
            row = {
                "dev_type": dev_type,
                "dev_name": dev_name,
                normalized_field: "",
            }
            block.data.append(row)
        row[normalized_field] = _number_text(value)

    @staticmethod
    def _upsert_runtime_setpoint_value(
        book: EBook,
        dev_type: str,
        dev_name: str,
        set_type: str,
        value: Any,
    ) -> None:
        block = _ensure_block(book, "SetValue", STAT_HEADERS["SetValue"])
        row = _find_set_row(block, dev_type, dev_name, set_type)
        if row is None:
            row = {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "set_type": set_type,
                "set_value": "",
            }
            block.data.append(row)
        row["set_value"] = _number_text(value)

    def _sync_runtime_controls_from_device_changes_unlocked(
        self,
        block_name: str,
        row: Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        priority_override_keys: Optional[set[Tuple[str, str, str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        dev_type = str(block_name or "").strip()
        dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
        if not dev_type or not dev_name:
            return None

        requested: Dict[str, Any] = {
            "dev_type": dev_type,
            "dev_name": dev_name,
            "set_values": {},
        }
        changed = False
        for field_name, value in changes.items():
            normalized_field = str(field_name or "").strip().casefold()
            if normalized_field in RUNTIME_CONTROL_STATUS_FIELDS:
                for book in (self.source_stat_book, self.control_book):
                    self._upsert_runtime_status_value(
                        book,
                        dev_type,
                        dev_name,
                        normalized_field,
                        value,
                    )
                requested[normalized_field] = _json_scalar(value)
                changed = True
                continue

            set_type = self._runtime_control_set_type(dev_type, normalized_field)
            if set_type is None:
                continue
            for book in (self.source_stat_book, self.control_book):
                self._upsert_runtime_setpoint_value(
                    book,
                    dev_type,
                    dev_name,
                    set_type,
                    value,
                )
            requested["set_values"][set_type] = _json_scalar(value)
            changed = True

        if not changed:
            return None

        # The source books are the editable baseline. Rebuild the effective
        # runtime book so valid commands and active device faults keep their
        # existing precedence over that baseline.
        self._materialize_active_control_commands(
            self.clock.absolute_minute,
            additional_ui_overrides=priority_override_keys,
        )
        self._apply_device_faults(self.clock.minute, self.clock.absolute_minute)
        run_stats, cb_status, set_values, _soc_values = self._stat_maps()
        key = (dev_type, dev_name)
        effective: Dict[str, Any] = {
            "dev_type": dev_type,
            "dev_name": dev_name,
        }
        if "run_stat" in requested:
            effective["run_stat"] = _json_scalar(
                run_stats.get(key, requested["run_stat"])
            )
        if "status" in requested:
            effective["status"] = _json_scalar(
                cb_status.get(key, requested["status"])
            )
        requested_set_values = requested["set_values"]
        if requested_set_values:
            current_set_values = set_values.get(key, {})
            effective["set_values"] = {
                set_type: _json_scalar(
                    current_set_values.get(set_type, requested_value)
                )
                for set_type, requested_value in requested_set_values.items()
            }
        return effective

    def update_device_parameters(
        self,
        payload: Mapping[str, Any],
        *,
        allow_runtime_controls: bool = True,
    ) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            current = self.definition_snapshot
            require_definition_revision(payload, current.revision)
            model_book = simu_loop._clone_ebook(current.model_book)
            block_name = str(payload.get("block_name", "")).strip()
            if not block_name:
                raise ValueError("block_name is required")
            block = model_book.data.get(block_name)
            if block is None:
                raise ValueError(f"Unknown model block: {block_name}")
            row = self._definition_row(block, payload.get("row_key", {}))
            before_row = dict(row)
            changes = payload.get("changes", {})
            if not isinstance(changes, Mapping):
                raise ValueError("changes must be an object")
            if block_name in HYDROGEN_CONVERSION_BLOCKS and "control_type" in changes:
                changes = {
                    **changes,
                    "control_type": normalize_hydrogen_conversion_control_mode(
                        changes["control_type"]
                    ),
                }
            if not allow_runtime_controls:
                runtime_fields = [
                    str(field)
                    for field in changes
                    if str(field).strip().casefold() in RUNTIME_CONTROL_STATUS_FIELDS
                    or self._runtime_control_set_type(block_name, str(field)) is not None
                ]
                if runtime_fields:
                    raise ValueError(
                        "学员台设备参数入口禁止修改运行状态、开关状态和遥调设定值，"
                        "请使用遥控/遥调。"
                    )
            try:
                normalized_changes = normalize_device_changes(
                    row,
                    changes,
                    allow_out_of_bounds_setpoints=not self.enforce_runtime_setpoint_bounds,
                )
            except SafetyBoundaryError as exc:
                dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
                raise ValueError(
                    f"人工修改安全校验失败：{block_name}/{dev_name} 的修改超出允许范围"
                    f"（{exc}）；修改未生效，人工覆盖层、运行控制文件和仿真边界均未更新。"
                ) from exc
            if "p_set" in normalized_changes and self.enforce_runtime_setpoint_bounds:
                try:
                    hydrogen_safety = validate_hydrogen_power_setpoint_safety(
                        model_book,
                        block_name,
                        str(row.get("name", row.get("dev_name", ""))).strip(),
                        "p_set",
                        normalized_changes["p_set"],
                        clamp_to_bounds=True,
                    )
                    if hydrogen_safety and hydrogen_safety.get("clamped"):
                        normalized_changes["p_set"] = _number_text(
                            hydrogen_safety["p_set"]
                        )
                    prospective_row = {**row, **normalized_changes}
                    final_power, _bounds, _clamped = (
                        clamp_setpoint_safety_bounds(
                            prospective_row,
                            "p_set",
                            normalized_changes["p_set"],
                        )
                    )
                    normalized_changes["p_set"] = _number_text(final_power)
                except ValueError as exc:
                    dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
                    raise ValueError(
                        f"人工修改模型校验失败：{block_name}/{dev_name} 的跨域换算无法形成"
                        f"有效有限目标（{exc}）；修改未生效，人工覆盖层、运行控制文件和"
                        "仿真边界均未更新。"
                    ) from exc
            clamped_setpoint_details = []
            for field_name, normalized_value in normalized_changes.items():
                normalized_field = str(field_name).strip().casefold()
                if not (
                    normalized_field.endswith("_set")
                    or normalized_field in {"pv0", "qv0"}
                ):
                    continue
                requested_number = _to_float(changes.get(field_name), None)
                normalized_number = _to_float(normalized_value, None)
                if (
                    requested_number is not None
                    and normalized_number is not None
                    and not math.isclose(
                        requested_number,
                        normalized_number,
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                ):
                    clamped_setpoint_details.append(
                        f"{field_name} 请求值 {_number_text(requested_number)} 已限幅为 "
                        f"{_number_text(normalized_number)}"
                    )
            if clamped_setpoint_details:
                dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
                self._append_runtime_log(
                    "控制安全边界",
                    "人工遥调限幅",
                    "越界值已限幅并继续生效",
                    [
                        f"{block_name}/{dev_name}",
                        *clamped_setpoint_details,
                        "设备运行状态保持不变，限幅后的设定值继续写入运行控制边界。",
                    ],
                    level="warn",
                )
            row.update(normalized_changes)
            runtime_override_keys: set[Tuple[str, str, str, str]] = set()
            dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
            if dev_name:
                for field_name in normalized_changes:
                    normalized_field = str(field_name).strip().casefold()
                    if normalized_field in RUNTIME_CONTROL_STATUS_FIELDS:
                        runtime_override_keys.add(
                            ("remote_control", block_name, dev_name, normalized_field)
                        )
                        continue
                    set_type = self._runtime_control_set_type(block_name, normalized_field)
                    if set_type:
                        runtime_override_keys.add(
                            ("remote_adjustment", block_name, dev_name, set_type)
                        )
            dev_define_book = simu_loop._capability_define_book(
                model_book,
                self._legacy_dev_define_file(),
            )
            next_snapshot = DefinitionSnapshot(
                revision=current.revision + 1,
                model_book=model_book,
                dev_define_book=dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=current.measurement_rows,
                measurement_after=current.measurement_after,
                measurement_median_deviations=current.measurement_median_deviations,
            )
            self._publish_definition_snapshot(next_snapshot)

            self._record_device_manual_changes_unlocked(
                block_name,
                before_row,
                row,
                tuple(normalized_changes),
                persisted=False,
                persistence_error="等待人工覆盖层保存",
            )
            runtime_control = self._sync_runtime_controls_from_device_changes_unlocked(
                block_name,
                row,
                normalized_changes,
                priority_override_keys=runtime_override_keys,
            )
            persisted = False
            change_record_persisted = False
            runtime_control_persisted = runtime_control is None
            warning = ""
            try:
                self._write_ahead_manual_definition_changes_unlocked()
            except OSError as exc:
                persistence_error = f"人工覆盖层保存失败: {exc}"
                warning = f"后台定义已更新，但人工覆盖层保存失败，请重试: {exc}"
                self._record_device_manual_changes_unlocked(
                    block_name,
                    before_row,
                    row,
                    tuple(normalized_changes),
                    persisted=False,
                    persistence_error=persistence_error,
                )
            else:
                change_record_persisted = True
                pending_changes = {
                    change_id: dict(item)
                    for change_id, item in self._manual_definition_changes.items()
                }
                self._mark_manual_changes_persisted_unlocked("device")
                try:
                    self._write_manual_definition_changes_unlocked()
                except OSError as exc:
                    self._manual_definition_changes = pending_changes
                    warning = (
                        "人工覆盖层已保存当前值，但同步状态保存失败，请重试: "
                        f"{exc}"
                    )
                else:
                    persisted = True
                    runtime_control_persisted = True
            record = {
                header: _json_scalar(row.get(header, ""))
                for header in block.header_list
            }
            result = self._definition_update_result(
                next_snapshot,
                {
                    "block_name": block_name,
                    "row_key": {
                        "idx": record.get("idx", ""),
                        "name": record.get("name", ""),
                    },
                    **record,
                },
                persisted=persisted,
                warning=warning,
            )
            result["change_record_persisted"] = change_record_persisted
            if runtime_control is not None:
                result["runtime_control"] = runtime_control
                result["runtime_control_persisted"] = runtime_control_persisted
            return result

    def update_measurement_definition(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            current = self.definition_snapshot
            require_definition_revision(payload, current.revision)
            rows = [list(row) for row in current.measurement_rows]
            index, current_item = self._measurement_definition_row(rows, payload)
            before_row = list(rows[index])
            measurement_name = str(current_item.get("name", ""))
            median_deviations = _measurement_median_deviation_map(current)
            current_median_deviation = median_deviations.get(measurement_name, 0.0)
            changes = payload.get("changes", {})
            if not isinstance(changes, Mapping):
                raise ValueError("changes must be an object")
            current_with_status = dict(current_item)
            current_status, current_fixed_value = self._measurement_status_override(current_item)
            current_with_status["status"] = current_status
            current_with_status["fixed_value"] = current_fixed_value
            current_with_status["median_deviation"] = current_median_deviation
            normalized = normalize_measurement_changes(current_with_status, changes)
            rows[index][5] = normalized["weight"]
            rows[index][6] = normalized["valid"]
            if normalized["median_deviation"] == 0.0:
                median_deviations.pop(measurement_name, None)
            else:
                median_deviations[measurement_name] = normalized["median_deviation"]
            next_snapshot = DefinitionSnapshot(
                revision=current.revision + 1,
                model_book=current.model_book,
                dev_define_book=current.dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=tuple(tuple(row) for row in rows),
                measurement_after=current.measurement_after,
                measurement_median_deviations=_normalized_measurement_median_deviation_pairs(
                    median_deviations
                ),
            )
            self._publish_definition_snapshot(next_snapshot)

            changed_fields: List[str] = []
            if "weight" in changes or "error_sigma" in changes:
                changed_fields.append("weight")
            if "median_deviation" in changes:
                changed_fields.append("median_deviation")
            if "valid" in changes or "status" in changes:
                changed_fields.append("valid")
            if "status" in changes:
                changed_fields.append("status")
            if "fixed_value" in changes or (
                "status" in changes
                and (
                    current_fixed_value is not None
                    or normalized["fixed_value"] is not None
                )
            ):
                changed_fields.append("fixed_value")
            self._record_measurement_manual_changes_unlocked(
                before_row,
                rows[index],
                changed_fields,
                persisted=False,
                persistence_error="等待人工覆盖层保存",
                before_status=current_status,
                before_fixed_value=current_fixed_value,
                before_median_deviation=current_median_deviation,
                after_status=normalized["status"],
                after_fixed_value=normalized["fixed_value"],
                after_median_deviation=normalized["median_deviation"],
            )
            self._apply_manual_measurement_status_overrides_unlocked(
                next_snapshot,
                list(self._manual_definition_changes.values()),
            )
            persisted = False
            change_record_persisted = False
            warning = ""
            try:
                self._write_ahead_manual_definition_changes_unlocked()
            except OSError as exc:
                persistence_error = f"人工覆盖层保存失败: {exc}"
                warning = f"后台定义已更新，但人工覆盖层保存失败，请重试: {exc}"
                self._record_measurement_manual_changes_unlocked(
                    before_row,
                    rows[index],
                    changed_fields,
                    persisted=False,
                    persistence_error=persistence_error,
                    before_status=current_status,
                    before_fixed_value=current_fixed_value,
                    before_median_deviation=current_median_deviation,
                    after_status=normalized["status"],
                    after_fixed_value=normalized["fixed_value"],
                    after_median_deviation=normalized["median_deviation"],
                )
            else:
                change_record_persisted = True
                pending_changes = {
                    change_id: dict(item)
                    for change_id, item in self._manual_definition_changes.items()
                }
                self._mark_manual_changes_persisted_unlocked("measurement")
                try:
                    self._write_manual_definition_changes_unlocked()
                except OSError as exc:
                    self._manual_definition_changes = pending_changes
                    warning = (
                        "人工覆盖层已保存当前值，但同步状态保存失败，请重试: "
                        f"{exc}"
                    )
                else:
                    persisted = True
            record = _measurement_row_to_dict(rows[index])
            record["error_sigma"] = normalized["error_sigma"]
            record["median_deviation"] = normalized["median_deviation"]
            record["status"] = normalized["status"]
            record["fixed_value"] = normalized["fixed_value"]
            result = self._definition_update_result(
                next_snapshot,
                record,
                persisted=persisted,
                warning=warning,
            )
            result["change_record_persisted"] = change_record_persisted
            return result

    def reset_manual_definition_changes(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            current = self.definition_snapshot
            require_definition_revision(payload, current.revision)
            raw_change_ids = payload.get("change_ids", [])
            if not isinstance(raw_change_ids, Sequence) or isinstance(raw_change_ids, (str, bytes)):
                raise ValueError("change_ids must be an array")
            change_ids = list(
                dict.fromkeys(
                    str(change_id).strip()
                    for change_id in raw_change_ids
                    if str(change_id).strip()
                )
            )
            if not change_ids:
                raise ValueError("At least one manual change must be selected")
            missing = [change_id for change_id in change_ids if change_id not in self._manual_definition_changes]
            if missing:
                raise ValueError(f"Unknown manual definition change: {missing[0]}")
            # Measurement validity, status and fixed value form one effective
            # state.  Restoring one of them must not leave an impossible partial
            # override (for example fixed status without a fixed value).
            selected_ids = set(change_ids)
            selected_measurements = {
                str(item.get("measurement_name", ""))
                for change_id, item in self._manual_definition_changes.items()
                if change_id in selected_ids
                and item.get("kind") == "measurement"
                and item.get("field") in {"valid", "status", "fixed_value"}
            }
            for change_id, item in self._manual_definition_changes.items():
                if (
                    item.get("kind") == "measurement"
                    and str(item.get("measurement_name", "")) in selected_measurements
                    and item.get("field") in {"valid", "status", "fixed_value"}
                ):
                    selected_ids.add(change_id)
            change_ids = [
                change_id
                for change_id in self._manual_definition_changes
                if change_id in selected_ids
            ]
            selected = [
                dict(self._manual_definition_changes[change_id])
                for change_id in change_ids
            ]

            now = _now_text()
            for item in selected:
                active_item = self._manual_definition_changes[str(item.get("id", ""))]
                active_item["current_value"] = self._manual_change_value_text(
                    active_item.get("default_value", "")
                )
                active_item["modified_at"] = now
                self._set_manual_change_sync_state_unlocked(
                    active_item,
                    persisted=False,
                    error="等待人工覆盖层保存",
                )
                if active_item.get("field") == "weight":
                    active_item["current_error_sigma"] = self._manual_change_sigma(
                        active_item["current_value"]
                    )

            self._rebuild_effective_definitions_from_source_unlocked()
            try:
                self._write_ahead_manual_definition_changes_unlocked()
            except OSError as exc:
                error = f"后台定义已恢复，但人工覆盖层保存失败，请重试: {exc}"
                for item in selected:
                    active_item = self._manual_definition_changes.get(str(item.get("id", "")))
                    if active_item is not None:
                        self._set_manual_change_sync_state_unlocked(
                            active_item,
                            persisted=False,
                            error=error,
                        )
                result = self._manual_definition_changes_payload_unlocked()
                result.update(
                    {
                        "reset_count": len(selected),
                        "persisted_count": 0,
                        "memory_updated": True,
                        "persisted": False,
                        "change_record_persisted": False,
                        "reset_ids": change_ids,
                        "static_meta": self.static_meta(),
                        "warning": error,
                    }
                )
                return result

            pending_changes = {
                change_id: dict(item)
                for change_id, item in self._manual_definition_changes.items()
            }
            for change_id in change_ids:
                active_item = self._manual_definition_changes.get(change_id)
                if active_item is None:
                    continue
                self._set_manual_change_sync_state_unlocked(active_item, persisted=True)
                self._manual_definition_changes.pop(change_id, None)

            warning = ""
            persisted = True
            try:
                self._write_manual_definition_changes_unlocked()
            except OSError as exc:
                self._manual_definition_changes = pending_changes
                persisted = False
                warning = (
                    "默认值已写入人工覆盖层，但清理同步状态失败，请重试: "
                    f"{exc}"
                )

            result = self._manual_definition_changes_payload_unlocked()
            result.update(
                {
                    "reset_count": len(selected),
                    "persisted_count": len(selected) if persisted else 0,
                    "memory_updated": True,
                    "persisted": persisted,
                    "change_record_persisted": True,
                    "reset_ids": change_ids,
                    "static_meta": self.static_meta(),
                }
            )
            if warning:
                result["warning"] = warning
            return result

    def device_parameters(self) -> Dict[str, List[Dict[str, Any]]]:
        book = self.definition_snapshot.model_book
        parameter_blocks = (
            "ACWindGen",
            "DCWindGen",
            "ACPVGen",
            "DCPVGen",
            "ACStorageGen",
            "DCStorageGen",
            "ACDieselGen",
            "DCDieselGen",
        )
        return {
            name: [
                {key: _json_scalar(value) for key, value in row.items()}
                for row in getattr(block, "data", [])
            ]
            for name, block in book.data.items()
            if name in parameter_blocks
        }

    def _definition_book_blocks(
        self,
        path: Path,
        block_names: Optional[Sequence[str]] = None,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> Dict[str, Dict[str, Any]]:
        book = self._definition_book_for_path(path, definition_snapshot)
        selected = set(block_names or [])
        blocks: Dict[str, Dict[str, Any]] = {}
        for name, block in book.data.items():
            if selected and name not in selected:
                continue
            headers = list(getattr(block, "header_list", []) or [])
            rows = [
                {header: _json_scalar(row.get(header, "")) for header in headers}
                for row in getattr(block, "data", [])
            ]
            blocks[name] = {"headers": headers, "rows": rows}
        return blocks

    def _definition_book_for_path(
        self,
        path: Path,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> EBook:
        active_snapshot = definition_snapshot or self.definition_snapshot
        try:
            resolved = Path(path).resolve()
        except Exception:
            resolved = Path(path)
        path_by_book = (
            (self.source_files.get("model"), active_snapshot.model_book),
            (self.source_files.get("stat"), self.source_stat_book),
            (self.source_files.get("control"), self.control_book),
            (self.work_files.get("stat"), self.runtime_stat_book),
        )
        for candidate, book in path_by_book:
            if candidate is None:
                continue
            try:
                if Path(candidate).resolve() == resolved:
                    return book
            except Exception:
                continue
        return EBook({})

    def _control_definition_path(self) -> Path:
        for path in (self.source_files.get("control"), self.source_files.get("stat"), self.files["stat"]):
            if path and Path(path).exists():
                return Path(path)
        return self.files["stat"]

    def definitions(self, measurements: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None) -> Dict[str, Any]:
        definition_snapshot = self.definition_snapshot
        median_deviations = _measurement_median_deviation_map(definition_snapshot)
        measurement_rows = self._with_realtime_measurements(
            {
                "definitions": [
                    _measurement_definition_row_to_dict(row, median_deviations)
                    for row in definition_snapshot.measurement_rows
                ],
                "real": [],
                "scada": [],
            }
        )["definitions"]
        for row in measurement_rows:
            status, fixed_value = self._measurement_status_override(row)
            row["status"] = status
            row["fixed_value"] = fixed_value
            row["valid"] = MEASUREMENT_STATUS_VALIDITY.get(
                status,
                int(_to_float(row.get("valid"), 0) or 0),
            )
        return {
            "model": self._definition_book_blocks(
                self.files["model"],
                definition_snapshot=definition_snapshot,
            ),
            "measurement": measurement_rows,
            "control": self._definition_book_blocks(
                self._control_definition_path(),
                CONTROL_DEFINITION_BLOCKS,
                definition_snapshot=definition_snapshot,
            ),
        }

    def _stat_maps(
        self,
    ) -> Tuple[
        Dict[Tuple[str, str], Any],
        Dict[Tuple[str, str], Any],
        Dict[Tuple[str, str], dict],
        Dict[Tuple[str, str], float],
    ]:
        stat_book = self.runtime_stat_book
        run_stats: Dict[Tuple[str, str], Any] = {}
        cb_status: Dict[Tuple[str, str], Any] = {}
        set_values: Dict[Tuple[str, str], dict] = {}
        soc_values = self._runtime_storage_soc_values()
        for row in getattr(stat_book.data.get("RunStat"), "data", []):
            run_stats[(str(row.get("dev_type", "")), _dev_name(row))] = row.get("run_stat", "")
        for row in getattr(stat_book.data.get("CbOpenStat"), "data", []):
            cb_status[(str(row.get("dev_type", "")), _dev_name(row))] = row.get("status", "")
        for row in getattr(stat_book.data.get("SetValue"), "data", []):
            key = (str(row.get("dev_type", "")), _dev_name(row))
            set_values.setdefault(key, {})[str(row.get("set_type", ""))] = row.get("set_value", "")
        return run_stats, cb_status, set_values, soc_values

    def model_diagram(self) -> Dict[str, Any]:
        path = self.source_files.get("diagram", self.sim_dir / DIAGRAM_FILE_NAME)
        payload: Dict[str, Any] = {
            "present": False,
            "filename": DIAGRAM_FILE_NAME,
            "path": str(path),
            "svg": "",
            "updated_at": 0,
            "size": 0,
        }
        if not path.exists() or not path.is_file():
            return payload
        try:
            stat = path.stat()
            payload.update(
                {
                    "present": True,
                    "svg": path.read_text(encoding="utf-8-sig"),
                    "updated_at": stat.st_mtime,
                    "size": stat.st_size,
                }
            )
        except OSError as exc:
            payload["error"] = str(exc)
        except UnicodeDecodeError:
            payload["error"] = "diagram.svg is not valid UTF-8 text"
        return payload

    def model_info(self) -> Dict[str, Any]:
        return {
            "id": self.model_id,
            "name": self.model_name,
            "sim_dir": str(self.sim_dir),
            "runtime_dir": str(self.runtime_dir),
            "clock_state": self.clock.state,
        }

    def _path_static_signature(self, paths: Sequence[Path | str | None]) -> Dict[str, Any]:
        signatures: List[str] = []
        for index, raw_path in enumerate(paths):
            if raw_path is None:
                signatures.append(f"{index}:<none>:0:0:0")
                continue
            path = Path(raw_path)
            try:
                stat = path.stat()
            except OSError:
                signatures.append(f"{index}:{path.name}:0:0:0")
                continue
            signatures.append(f"{index}:{path.name}:1:{stat.st_size}:{stat.st_mtime_ns}")
        return {"signature": "|".join(signatures)}

    def static_meta(self) -> Dict[str, Any]:
        definition_revision = self.definition_snapshot.revision
        definition_paths = [
            self.source_files.get("model"),
            self.source_files.get("meas"),
            self.source_files.get("stat"),
            self.source_files.get("control"),
            self.source_files.get("weather"),
        ]
        definitions_meta = self._path_static_signature(definition_paths)
        definitions_meta["revision"] = definition_revision
        device_parameters_meta = self._path_static_signature([self.source_files.get("model")])
        device_parameters_meta["revision"] = definition_revision
        return {
            "files": self._path_static_signature(list(self.files.values())),
            "source_files": self._path_static_signature(list(self.source_files.values())),
            "work_files": self._path_static_signature(list(self.work_files.values())),
            "definitions": definitions_meta,
            "curves": self._path_static_signature([self.source_curves_file, self.curves_file]),
            "settings": self._path_static_signature([self.sim_dir / "local_settings.json", self.settings_file]),
            "device_parameters": device_parameters_meta,
            "diagram": self._path_static_signature([self.source_files.get("diagram")]),
        }

    def curve_boundary(self, absolute_minute: Optional[int | float] = None) -> Dict[str, Any]:
        target_minute = float(
            _to_float(
                self.clock.absolute_minute if absolute_minute is None else absolute_minute,
                0.0,
            )
            or 0.0
        )
        cache_key = (self._curve_revision, target_minute, id(self.curves))
        if (
            cache_key == self._curve_boundary_cache_key
            and self._curve_boundary_cache_value is not None
        ):
            return self._curve_boundary_cache_value

        curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        default_step = _simulation_mode_curve_step_minutes(curve_mode)
        default_point_count = _simulation_mode_point_count(curve_mode)
        step_minutes = float(_to_float(self.curves.get("time_step_minutes"), default_step) or default_step)
        period_minutes = _simulation_mode_duration_minutes(curve_mode)
        weather = self.curves.get("weather", [])
        if not isinstance(weather, Sequence) or isinstance(weather, (str, bytes)):
            weather = []
        point_count = int(_to_float(self.curves.get("point_count"), 0) or 0)
        if not point_count:
            point_count = len(weather)
        index = max(0, self._curve_point_index(target_minute, period_minutes) - 1)
        point = {
            key: self._interpolate_curve_series(
                weather,
                target_minute,
                key,
                default,
                period_minutes=period_minutes,
            )
            for key, default in self.weather_defaults.items()
            if key != "load_kw"
        }
        loads = self.curves.get("loads", {})
        load_total = 0.0
        load_count = 0
        if isinstance(loads, Mapping):
            for points in loads.values():
                if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                    continue
                value = self._interpolate_curve_series(
                    points,
                    target_minute,
                    "p_kw",
                    float("nan"),
                    period_minutes=period_minutes,
                )
                if value == value:
                    load_total += value
                    load_count += 1
        result = {
            "mode": curve_mode,
            "time_step_minutes": step_minutes,
            "point_count": point_count or default_point_count,
            "target_minute": target_minute,
            "index": index,
            "point": point,
            "load_total": load_total,
            "load_count": load_count,
        }
        self._curve_boundary_cache_key = cache_key
        self._curve_boundary_cache_value = result
        return result

    def snapshot(
        self,
        include_static: bool = True,
        runtime_log_limit: int = 300,
        *,
        include_runtime_logs: bool = True,
        include_measurements: bool = True,
        include_static_meta: bool = True,
        static_fields: Optional[Sequence[str]] = None,
        include_devices: bool = True,
        include_device_states: bool = True,
        include_commands: bool = True,
        include_command_history: bool = True,
    ) -> Dict[str, Any]:
        measurements: Dict[str, Any] = {}
        if include_measurements:
            compute_status = str(self.latest_compute.get("status", "") or "").lower()
            if compute_status in {"failed", "timeout"} and self.latest_measurements:
                measurements = {
                    str(channel): [dict(row) for row in rows]
                    for channel, rows in self.latest_measurements.items()
                }
            else:
                measurements = self.measurements()
                if "definitions" not in measurements:
                    definition_snapshot = self.definition_snapshot
                    median_deviations = _measurement_median_deviation_map(definition_snapshot)
                    measurements["definitions"] = [
                        _measurement_definition_row_to_dict(row, median_deviations)
                        for row in definition_snapshot.measurement_rows
                    ]
        try:
            log_limit = max(0, int(runtime_log_limit))
        except (TypeError, ValueError):
            log_limit = 300
        logs = self.runtime_logs[-log_limit:] if log_limit else []
        summary_measurements = measurements if include_measurements else (self.latest_measurements or {})
        snapshot = {
            "model": self.model_info(),
            "clock": self.clock.as_dict(),
            "measurement_clock": dict(self.latest_measurement_clock),
            "system_parameters": self.system_parameters(),
            "simulation_timing": self.simulation_timing(),
            "curve_boundary": self.curve_boundary(),
            "result": self.latest_result,
            "compute": dict(self.latest_compute),
            "summary": self._summary(summary_measurements),
            "power_summary": self._latest_power_summary(summary_measurements),
        }
        if include_static_meta:
            snapshot["static_meta"] = self.static_meta()
        if include_commands:
            recent_commands = self.command_history[-50:]
            recent_ids = {id(entry) for entry in recent_commands}
            active_commands = self._active_control_command_entries(self.clock.absolute_minute)
            effective_commands = self._effective_active_control_command_views(self.clock.absolute_minute)
            pinned_commands = [
                entry
                for entry in active_commands
                if _manual_command_holds_across_clock_lifecycle(entry) and id(entry) not in recent_ids
            ]
            pinned_ids = {id(entry) for entry in pinned_commands}
            pinned_commands.extend(
                entry
                for entry in effective_commands
                if id(entry) not in recent_ids and id(entry) not in pinned_ids
            )
            snapshot["commands"] = {
                "history": pinned_commands + recent_commands if include_command_history else [],
                "effective": effective_commands,
            }
        if include_devices:
            snapshot["devices"] = self.devices()
        if include_device_states:
            snapshot["device_states"] = self.device_states()
        if include_runtime_logs:
            snapshot["runtime_logs"] = logs
        if include_measurements:
            snapshot["measurements"] = measurements
        if include_static:
            requested_static_fields = set(SNAPSHOT_STATIC_FIELDS)
            if static_fields is not None:
                requested_static_fields = {
                    str(field)
                    for field in static_fields
                    if str(field) in SNAPSHOT_STATIC_FIELDS
                }
            if "definitions" in requested_static_fields and not include_measurements:
                measurements = self.measurements()
            if "files" in requested_static_fields:
                snapshot["files"] = {key: str(path) for key, path in self.files.items()}
            if "source_files" in requested_static_fields:
                snapshot["source_files"] = {key: str(path) for key, path in self.source_files.items()}
            if "work_files" in requested_static_fields:
                snapshot["work_files"] = {key: str(path) for key, path in self.work_files.items()}
            if "definitions" in requested_static_fields:
                snapshot["definitions"] = self.definitions(measurements)
            if "curves" in requested_static_fields:
                snapshot["curves"] = self.curves
            if "settings" in requested_static_fields:
                snapshot["settings"] = self.local_settings
            if "device_parameters" in requested_static_fields:
                snapshot["device_parameters"] = self.device_parameters()
            if "diagram" in requested_static_fields:
                snapshot["diagram"] = self.model_diagram()
        return snapshot

    def _summary(self, measurements: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
        scada = measurements.get("scada", [])
        valid = [item for item in scada if item.get("valid", 0) == 1]
        measurement_alarms = [
            item
            for item in scada
            if item.get("value") is not None and abs(float(item.get("value") or 0.0)) > 1e4
        ]
        compute_status = str(self.latest_compute.get("status", "") or "").strip().lower()
        power_flow_alarm_count = int(compute_status in {"failed", "timeout"})
        return {
            "scada_count": len(scada),
            "valid_scada_count": len(valid),
            "alarm_count": len(measurement_alarms) + power_flow_alarm_count,
            "measurement_alarm_count": len(measurement_alarms),
            "power_flow_alarm_count": power_flow_alarm_count,
            "command_count": len(self.command_history),
            "runtime_dir": str(self.runtime_dir),
            "model_id": self.model_id,
            "model_name": self.model_name,
        }


class MultiModelSimulator:
    """Owns independent simulator instances for multiple model cases."""

    def __init__(
        self,
        specs: Sequence[SimulationModelSpec | Mapping[str, Any]],
        runtime_dir: str | Path,
        kernel: Optional[Callable[[simu_loop.SimulationConfig], Optional[simu_loop.SimulationResult]]] = None,
        *,
        kernel_runner: Optional[Any] = None,
        period_seconds: float = 60.0,
        compute_interval_seconds: float = DEFAULT_COMPUTE_INTERVAL_SECONDS,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        models_root: str | Path | None = None,
        directory_backed: bool = False,
        runtime_role: str = "",
    ) -> None:
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        normalized_specs = self._unique_specs([self._normalize_spec(raw_spec) for raw_spec in specs])
        self.models_root = Path(models_root).resolve() if models_root else self._infer_models_root(normalized_specs)
        self.models_root.mkdir(parents=True, exist_ok=True)
        self.directory_backed = directory_backed
        self.runtime_role = str(runtime_role or "").strip().lower()
        self.clear_commands_on_start_and_reset = self.runtime_role == "simulator"
        self.enforce_runtime_setpoint_bounds = True
        self.kernel = kernel
        self.kernel_runner = kernel_runner
        self.period_seconds = period_seconds
        self.compute_interval_seconds = _compute_interval_seconds(compute_interval_seconds)
        self.noise_std = noise_std
        self.random_seed = random_seed
        self._services: Dict[str, PolarMicrogridSimulator] = {}
        self.lock = threading.RLock()
        self.default_model_id = ""
        self._directory_sync_interval_seconds = 1.0
        self._next_directory_sync_at = (
            time.monotonic() + self._directory_sync_interval_seconds
        )
        for spec in normalized_specs:
            if spec.model_id in self._services:
                raise ValueError(f"Duplicate simulation model id: {spec.model_id}")
            service = PolarMicrogridSimulator(
                sim_dir=spec.sim_dir,
                runtime_dir=self.runtime_dir / spec.model_id,
                kernel=kernel,
                kernel_runner=kernel_runner,
                period_seconds=period_seconds,
                compute_interval_seconds=self.compute_interval_seconds,
                noise_std=noise_std,
                random_seed=random_seed,
                model_id=spec.model_id,
                model_name=spec.name,
                clear_commands_on_start_and_reset=self.clear_commands_on_start_and_reset,
                enforce_runtime_setpoint_bounds=self.enforce_runtime_setpoint_bounds,
            )
            self._services[spec.model_id] = service
            if not self.default_model_id:
                self.default_model_id = spec.model_id
        if not self._services:
            raise ValueError("At least one simulation model is required")
        self.default_model_id = self._preferred_default_model_id(list(self._services), self.default_model_id)

    @staticmethod
    def _unique_specs(specs: Sequence[SimulationModelSpec]) -> List[SimulationModelSpec]:
        unique: List[SimulationModelSpec] = []
        seen_keys: set[str] = set()
        for spec in specs:
            keys = {_model_key(spec.model_id), _model_key(spec.name or spec.model_id)}
            if seen_keys.intersection(keys):
                continue
            unique.append(spec)
            seen_keys.update(keys)
        return unique

    @staticmethod
    def _infer_models_root(specs: Sequence[SimulationModelSpec]) -> Path:
        if not specs:
            return Path("models").resolve()
        parents = [Path(spec.sim_dir).resolve().parent for spec in specs]
        first = parents[0]
        if all(parent == first for parent in parents):
            return first
        return Path(specs[0].sim_dir).resolve().parent

    @staticmethod
    def _normalize_spec(raw_spec: SimulationModelSpec | Mapping[str, Any]) -> SimulationModelSpec:
        if isinstance(raw_spec, SimulationModelSpec):
            return raw_spec.normalized()
        model_id = raw_spec.get("id", raw_spec.get("model_id", raw_spec.get("name", "default")))
        sim_dir = raw_spec.get("sim_dir", raw_spec.get("path", raw_spec.get("dir", "")))
        name = str(raw_spec.get("label", raw_spec.get("display_name", raw_spec.get("name", model_id))))
        return SimulationModelSpec(str(model_id), Path(sim_dir), name).normalized()

    @classmethod
    def discover(
        cls,
        sim_dir: str | Path,
        runtime_dir: str | Path,
        kernel: Optional[Callable[[simu_loop.SimulationConfig], Optional[simu_loop.SimulationResult]]] = None,
        *,
        kernel_runner: Optional[Any] = None,
        period_seconds: float = 60.0,
        compute_interval_seconds: float = DEFAULT_COMPUTE_INTERVAL_SECONDS,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        models_dir: str | Path | None = None,
        runtime_role: str = "",
    ) -> "MultiModelSimulator":
        root = Path(sim_dir).resolve()
        models_root = Path(models_dir).resolve() if models_dir else root / "models"
        specs = cls._discover_specs(root, models_root)
        return cls(
            specs,
            runtime_dir=runtime_dir,
            kernel=kernel,
            kernel_runner=kernel_runner,
            period_seconds=period_seconds,
            compute_interval_seconds=compute_interval_seconds,
            noise_std=noise_std,
            random_seed=random_seed,
            models_root=models_root,
            directory_backed=True,
            runtime_role=runtime_role,
        )

    @staticmethod
    def _directory_specs(models_root: Path) -> List[SimulationModelSpec]:
        if not models_root.exists():
            return []
        return [
            SimulationModelSpec(child.name, child, child.name).normalized()
            for child in sorted(models_root.iterdir(), key=lambda path: path.name.casefold())
            if child.is_dir() and (child / "model.e").exists()
        ]

    @staticmethod
    def _preferred_default_model_id(model_ids: Sequence[str], fallback: str = "") -> str:
        for preferred in ("默认模型", "default"):
            for model_id in model_ids:
                if _model_key(model_id) == _model_key(preferred):
                    return model_id
        return fallback or (model_ids[0] if model_ids else "")

    @staticmethod
    def _discover_specs(root: Path, models_root: Path) -> List[SimulationModelSpec]:
        specs = MultiModelSimulator._directory_specs(models_root)
        if specs:
            return specs

        manifest = root / "models.json"
        if manifest.exists():
            payload = _read_json(manifest, [])
            items = payload.get("models", []) if isinstance(payload, Mapping) else payload
            specs = [
                SimulationModelSpec(
                    str(item.get("id", item.get("model_id", item.get("name", "default")))),
                    root / str(item.get("sim_dir", item.get("path", item.get("dir", ".")))),
                    str(item.get("label", item.get("name", item.get("id", "default")))),
                ).normalized()
                for item in items
                if isinstance(item, Mapping)
            ]
            if specs:
                return specs

        specs: List[SimulationModelSpec] = []
        if (root / "model.e").exists():
            specs.append(SimulationModelSpec("default", root, "默认模型").normalized())

        return specs or [SimulationModelSpec("default", root, "默认模型").normalized()]

    def _make_service(
        self,
        spec: SimulationModelSpec,
        *,
        clear_runtime: bool = False,
    ) -> PolarMicrogridSimulator:
        runtime_dir = self.runtime_dir / spec.model_id
        if clear_runtime:
            _clear_directory_contents(runtime_dir)
        return PolarMicrogridSimulator(
            sim_dir=spec.sim_dir,
            runtime_dir=runtime_dir,
            kernel=self.kernel,
            kernel_runner=self.kernel_runner,
            period_seconds=self.period_seconds,
            compute_interval_seconds=self.compute_interval_seconds,
            noise_std=self.noise_std,
            random_seed=self.random_seed,
            model_id=spec.model_id,
            model_name=spec.name,
            clear_commands_on_start_and_reset=self.clear_commands_on_start_and_reset,
            enforce_runtime_setpoint_bounds=self.enforce_runtime_setpoint_bounds,
        )

    @staticmethod
    def _retire_service_instance(service: PolarMicrogridSimulator) -> None:
        with service.lock:
            service._retire_service_instance_locked()

    def _sync_models_from_directory_locked(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._next_directory_sync_at:
            return
        specs = self._unique_specs(self._directory_specs(self.models_root))
        self._next_directory_sync_at = now + self._directory_sync_interval_seconds
        if not specs:
            return
        ordered_ids: List[str] = []
        for spec in specs:
            ordered_ids.append(spec.model_id)
            if spec.model_id not in self._services:
                self._services[spec.model_id] = self._make_service(spec, clear_runtime=True)
            else:
                self._services[spec.model_id].model_name = spec.name
        for model_id, service in list(self._services.items()):
            if model_id not in ordered_ids:
                self._retire_service_instance(service)
        self._services = {model_id: self._services[model_id] for model_id in ordered_ids}
        if self.default_model_id not in self._services:
            self.default_model_id = self._preferred_default_model_id(ordered_ids)

    def clone_model(self, source_model_id: Optional[str], new_model_id: Any) -> Dict[str, Any]:
        with self.lock:
            source = self.service_for(source_model_id)
            target_id = self.validate_new_model_name(new_model_id)
            target_dir = (self.models_root / target_id).resolve()
            try:
                target_dir.relative_to(self.models_root)
            except ValueError as exc:
                raise ValueError(f"模型名称无效: {new_model_id}") from exc
            if target_dir.exists():
                raise ValueError(f"模型文件夹已存在: {target_id}")

            source.clone_files_to(target_dir)
            service = self._make_service(
                SimulationModelSpec(target_id, target_dir, target_id).normalized(),
                clear_runtime=True,
            )
            self._services[target_id] = service
            self._append_manifest_model(target_id, target_dir)
            return service.model_info()

    def create_model_slot(self, new_model_id: Any) -> Dict[str, Any]:
        """Create an uninitialized trainee model slot without importing user files."""
        with self.lock:
            target_id = self.validate_new_model_name(new_model_id)
            target_dir = (self.models_root / target_id).resolve()
            runtime_dir = (self.runtime_dir / target_id).resolve()
            try:
                target_dir.relative_to(self.models_root.resolve())
                runtime_dir.relative_to(self.runtime_dir.resolve())
            except ValueError as exc:
                raise ValueError(f"模型名称无效: {new_model_id}") from exc

            target_dir.mkdir(parents=True, exist_ok=False)
            try:
                for file_name in ("model.e", "meas.e", "stat.e", "control.e", "weather.e", "curves.e"):
                    (target_dir / file_name).write_text("", encoding="utf-8")
                _write_json(
                    target_dir / "curves.json",
                    {
                        "mode": "day",
                        "time_step_minutes": 1,
                        "point_count": 0,
                        "weather": [],
                        "loads": {},
                    },
                )
                (target_dir / DIAGRAM_FILE_NAME).write_text(
                    (
                        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 480">'
                        '<rect width="800" height="480" fill="#f7fafb"/>'
                        '<text x="400" y="240" text-anchor="middle" fill="#60727a" font-size="24">'
                        "Model not initialized"
                        "</text></svg>"
                    ),
                    encoding="utf-8",
                )
                service = self._make_service(
                    SimulationModelSpec(target_id, target_dir, target_id).normalized(),
                    clear_runtime=True,
                )
            except Exception:
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                if runtime_dir.exists():
                    shutil.rmtree(runtime_dir)
                raise

            self._services[target_id] = service
            self._append_manifest_model(target_id, target_dir)
            return service.model_info()

    def delete_model(self, model_id: Any) -> Dict[str, Any]:
        target_id = _safe_model_id(model_id)
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked(force=True)
            service = self._services.get(target_id)
            if service is None:
                raise KeyError(f"Unknown simulation model: {model_id}")
            if len(self._services) <= 1:
                raise ValueError("至少需要保留一个模型")
            with service.lock:
                if service.trainee_receive_state().get("active"):
                    raise ValueError(f"模型正在接收中，无法删除: {target_id}")
                if service.clock.state != "stopped":
                    raise ValueError(f"模型正在运行中，无法删除: {target_id}")
                source_dir = Path(service.sim_dir).resolve()
                runtime_dir = Path(service.runtime_dir).resolve()
                removed = service.model_info()
                service._retire_service_instance_locked()
                self._services.pop(target_id, None)

            models_root = self.models_root.resolve()
            runtime_root = self.runtime_dir.resolve()
            try:
                source_dir.relative_to(models_root)
                runtime_dir.relative_to(runtime_root)
            except ValueError as exc:
                raise ValueError(f"模型目录无效，无法删除: {target_id}") from exc

            if source_dir.exists():
                shutil.rmtree(source_dir)
            if runtime_dir.exists():
                shutil.rmtree(runtime_dir)
            self._remove_manifest_model(target_id)

            if self.default_model_id == target_id:
                remaining_ids = list(self._services)
                self.default_model_id = self._preferred_default_model_id(remaining_ids, remaining_ids[0])
            return {
                **removed,
                "deleted": True,
                "active_model_id": self.default_model_id,
            }

    def validate_new_model_name(self, new_model_id: Any) -> str:
        target_id = _safe_model_id(new_model_id)
        target_keys = {_model_key(new_model_id), _model_key(target_id)}
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked(force=True)
            existing_keys = {
                key
                for existing_service in self._services.values()
                for key in (_model_key(existing_service.model_id), _model_key(existing_service.model_name))
            }
            if existing_keys.intersection(target_keys):
                raise ValueError(f"模型已存在: {target_id}")
            target_dir = (self.models_root / target_id).resolve()
            try:
                target_dir.relative_to(self.models_root)
            except ValueError as exc:
                raise ValueError(f"模型名称无效: {new_model_id}") from exc
            if target_dir.exists():
                raise ValueError(f"模型文件夹已存在: {target_id}")
        return target_id

    def _append_manifest_model(self, model_id: str, sim_dir: Path) -> None:
        manifest = self.models_root.parent / "models.json"
        if not manifest.exists():
            return
        payload = _read_json(manifest, {"models": []})
        is_mapping = isinstance(payload, Mapping)
        items = payload.get("models", []) if is_mapping else payload
        if not isinstance(items, list):
            items = []
        if any(isinstance(item, Mapping) and _safe_model_id(item.get("id", item.get("model_id", ""))) == model_id for item in items):
            return
        try:
            rel_dir = sim_dir.relative_to(self.models_root.parent).as_posix()
        except ValueError:
            rel_dir = str(sim_dir)
        items.append({"id": model_id, "name": model_id, "sim_dir": rel_dir})
        if is_mapping:
            payload = dict(payload)
            payload["models"] = items
        else:
            payload = items
        _write_json(manifest, payload)

    def _remove_manifest_model(self, model_id: str) -> None:
        manifest = self.models_root.parent / "models.json"
        if not manifest.exists():
            return
        payload = _read_json(manifest, {"models": []})
        is_mapping = isinstance(payload, Mapping)
        items = payload.get("models", []) if is_mapping else payload
        if not isinstance(items, list):
            return
        target_key = _model_key(model_id)
        next_items = [
            item
            for item in items
            if not (
                isinstance(item, Mapping)
                and _model_key(item.get("id", item.get("model_id", item.get("name", "")))) == target_key
            )
        ]
        if len(next_items) == len(items):
            return
        if is_mapping:
            payload = dict(payload)
            payload["models"] = next_items
        else:
            payload = next_items
        _write_json(manifest, payload)

    def service_for(self, model_id: Optional[str] = None) -> PolarMicrogridSimulator:
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked()
            target = _safe_model_id(model_id or self.default_model_id)
            service = self._services.get(target)
            if service is None and self.directory_backed:
                # Cache misses may be a newly added external model. Refresh
                # immediately without making hot lookups rescan the directory.
                self._sync_models_from_directory_locked(force=True)
                service = self._services.get(target)
        if service is None:
            raise KeyError(f"Unknown simulation model: {model_id}")
        return service

    def iter_services(self) -> List[PolarMicrogridSimulator]:
        with self.lock:
            return list(self._services.values())

    def close(self) -> None:
        runner = self.kernel_runner
        if runner is not None and callable(getattr(runner, "close", None)):
            runner.close()

    def models(self) -> List[Dict[str, Any]]:
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked(force=True)
            return [service.model_info() for service in self._services.values()]

    def trainee_receive_states(self) -> Dict[str, Dict[str, Any]]:
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked()
            return {model_id: service.trainee_receive_state() for model_id, service in self._services.items()}

    def snapshot(
        self,
        model_id: Optional[str] = None,
        include_static: bool = True,
        runtime_log_limit: int = 300,
        *,
        include_runtime_logs: bool = True,
        include_measurements: bool = True,
        include_static_meta: bool = True,
        static_fields: Optional[Sequence[str]] = None,
        include_devices: bool = True,
        include_device_states: bool = True,
        include_commands: bool = True,
        include_command_history: bool = True,
    ) -> Dict[str, Any]:
        return self.service_for(model_id).snapshot(
            include_static=include_static,
            runtime_log_limit=runtime_log_limit,
            include_runtime_logs=include_runtime_logs,
            include_measurements=include_measurements,
            include_static_meta=include_static_meta,
            static_fields=static_fields,
            include_devices=include_devices,
            include_device_states=include_device_states,
            include_commands=include_commands,
            include_command_history=include_command_history,
        )

    def measurements(self, model_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        return self.service_for(model_id).measurements()

    def measurement_delta(
        self,
        after_seq: int | float = 0,
        model_id: Optional[str] = None,
        *,
        compact: bool = False,
    ) -> Dict[str, Any]:
        return self.service_for(model_id).measurement_delta(after_seq=after_seq, compact=compact)

    def measurement_history(
        self,
        *,
        indices: Optional[Sequence[int]] = None,
        after_seq: int | float = 0,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.service_for(model_id).measurement_history(
            indices=indices,
            after_seq=after_seq,
        )

    def runtime_logs_delta(
        self,
        after_seq: int | float = 0,
        *,
        limit: int = 100,
        before_seq: Optional[int | float] = None,
        log_type: str = "",
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.service_for(model_id).runtime_logs_delta(
            after_seq=after_seq,
            limit=limit,
            before_seq=before_seq,
            log_type=log_type,
        )

    def devices(self, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.service_for(model_id).devices()

    def device_states(self, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.service_for(model_id).device_states()

    def device_runtime_frame(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).device_runtime_frame()

    def apply_student_commands(self, payload: Mapping[str, Any], source: str = "", model_id: Optional[str] = None) -> Dict[str, int]:
        return self.service_for(model_id).apply_student_commands(payload, source=source)

    def control_clock(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).control_clock(payload)

    def step(self, model_id: Optional[str] = None, advance_minutes: Optional[int] = None) -> Dict[str, Any]:
        return self.service_for(model_id).step(advance_minutes=advance_minutes)

    def set_curves(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).set_curves(payload)

    def curves_summary(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).curves_summary()

    def curves_series(self, keys: Sequence[str], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).curves_series(keys)

    def update_curve_series(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).update_curve_series(payload)

    def external_curves_query(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).external_curves_query(payload)

    def external_curves_update(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).external_curves_update(payload)

    def external_realtime_input_schema(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).external_realtime_input_schema()

    def apply_external_realtime_inputs(
        self,
        payload: Mapping[str, Any],
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.service_for(model_id).apply_external_realtime_inputs(payload)

    def set_local_settings(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, int]:
        return self.service_for(model_id).set_local_settings(payload)
