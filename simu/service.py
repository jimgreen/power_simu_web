"""Service layer for the polar microgrid time-series simulation system.

The service deliberately keeps the web/API layer thin.  It owns the runtime
copies of the E files, projects curve/settings/trainee-command overlays into
those files, calls the existing load-flow kernel, and exposes JSON snapshots
that both the simulator console and trainee console can poll.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import threading
import time
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


WEATHER_HEADER = (
    "time",
    "wind_speed_mps",
    "air_temp_c",
    "air_pressure_hpa",
    "solar_irradiance_w_m2",
    "humidity_pct",
    "load_kw",
)

MEAS_HEADER = ("idx", "name", "dev_type", "dev_name", "meas_type", "weight", "valid", "value")

DEFAULT_WEATHER = {
    "wind_speed_mps": 12.0,
    "air_temp_c": -18.0,
    "air_pressure_hpa": 960.0,
    "solar_irradiance_w_m2": 0.0,
    "humidity_pct": 72.0,
    "load_kw": 100.0,
}

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

STAT_HEADERS = {
    "RunStat": ("dev_type", "dev_name", "run_stat"),
    "CbOpenStat": ("dev_type", "dev_name", "status"),
    "SetValue": ("dev_type", "dev_name", "set_type", "set_value"),
    "StorageSoc": ("dev_type", "idx", "name", "soc_curr"),
}

SOURCE_DEFINITION_FILES = ("model.e", "meas.e", "stat.e", "control.e", "weather.e", "curves.e")
LEGACY_RUNTIME_DEFINITION_FILES = SOURCE_DEFINITION_FILES + ("device.e",)
CONTROL_DEFINITION_BLOCKS = ("RunStat", "CbOpenStat", "SetValue", "StorageSoc")
CLOCK_SPEED_LEVELS = (1.0, 5.0, 15.0, 30.0, 60.0)
DEFAULT_CONTROL_VALID_MINUTES = 5.0
DEFAULT_COMPUTE_INTERVAL_SECONDS = 1.0
DEFAULT_STORAGE_INITIAL_SOC = 0.5
LOG_DECIMAL_PATTERN = re.compile(r"(?<![\w:])[-+]?\d+\.\d+(?:e[-+]?\d+)?(?![\w:])", re.IGNORECASE)


@dataclass
class ClockState:
    state: str = "stopped"
    minute: int = 0
    absolute_minute: int = 0
    speed: float = 1.0
    step_minutes: int = 1
    run_id: int = 0
    step_count: int = 0
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "minute": self.minute,
            "absolute_minute": self.absolute_minute,
            "speed": self.speed,
            "step_minutes": self.step_minutes,
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


def _align_minute_to_step(minute: int | float, step_minutes: int | float) -> int:
    step = max(1, int(step_minutes))
    value = max(0, int(minute))
    remainder = value % step
    return value if remainder == 0 else value + step - remainder


def _effective_clock_step(step_minutes: int | float, speed: int | float) -> int:
    return max(1, int(round(float(step_minutes) * float(speed))))


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
    soc = _to_float(value, default)
    if soc is None or not math.isfinite(soc):
        soc = default
    return min(1.0, max(0.0, float(soc)))


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


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_model_id(value: Any) -> str:
    text = str(value or "default").strip()
    cleaned = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in text)
    return cleaned.strip("_") or "default"


def _model_key(value: Any) -> str:
    return _safe_model_id(value).casefold()


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


def _active_window(
    item: Mapping[str, Any],
    minute: int,
    absolute_minute: Optional[int | float] = None,
    curve_mode: str = "day",
) -> bool:
    if str(curve_mode or "day").lower() == "year":
        absolute = float(minute if absolute_minute is None else absolute_minute)
        current_day = int(absolute // 1440) % 365 + 1
        start = min(365, max(1, int(_to_float(item.get("start_day", 1), 1) or 1)))
        clear_value = item.get("clear_day", item.get("end_day"))
        if clear_value in (None, ""):
            return current_day >= start
        clear = min(365, max(1, int(_to_float(clear_value, 365) or 365)))
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


def _has_cancel_command_payload(payload: Mapping[str, Any]) -> bool:
    for key in ("cancel_commands", "cancelCommands", "cancel_items", "cancelItems", "cancel_names", "cancelNames"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) > 0:
            return True
    action = str(payload.get("action", payload.get("operation", "")) or "").strip().casefold()
    if action in {"cancel", "cancel_command", "cancel_commands", "取消", "取消指令"}:
        return True
    return bool(payload.get("cancel") is True and any(key in payload for key in ("name", "names", "commands", "items", "controls")))


def _manual_command_holds_across_clock_lifecycle(entry_or_payload: Mapping[str, Any], source: Any = "") -> bool:
    if bool(entry_or_payload.get("manual_hold", entry_or_payload.get("hold_until_cancelled", False))):
        return True
    payload = entry_or_payload.get("payload") if isinstance(entry_or_payload.get("payload"), Mapping) else entry_or_payload
    if isinstance(payload, Mapping) and isinstance(payload.get("strategy"), Mapping):
        return False
    text = str(source or entry_or_payload.get("source", "") or "").strip().casefold()
    if "renewable" in text or "strategy" in text:
        return False
    return text in {"trainee-ui", "student-ui"} or text.startswith("trainee-ui-") or text.startswith("student-ui-") or "人工" in text


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
    default: float,
    *,
    period_minutes: float = 1440.0,
) -> float:
    pairs = []
    for point in points:
        value = _to_float(point.get(key), None)
        if value is None:
            continue
        pairs.append((float(point.get("minute", 0)) % period_minutes, value))
    if not pairs:
        return default
    pairs.sort(key=lambda item: item[0])
    m = float(minute % period_minutes)
    if len(pairs) == 1:
        return pairs[0][1]
    if m < pairs[0][0]:
        prev_m, prev_v = pairs[-1][0] - period_minutes, pairs[-1][1]
        next_m, next_v = pairs[0]
    else:
        prev_m, prev_v = pairs[-1]
        next_m, next_v = pairs[0][0] + period_minutes, pairs[0][1]
        for idx in range(len(pairs) - 1):
            left_m, left_v = pairs[idx]
            right_m, right_v = pairs[idx + 1]
            if left_m <= m <= right_m:
                prev_m, prev_v = left_m, left_v
                next_m, next_v = right_m, right_v
                break
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


def _measurement_dict_to_row(item: Mapping[str, Any]) -> List[str]:
    return [str(item.get(key, "")) for key in MEAS_HEADER]


class PolarMicrogridSimulator:
    """Runtime service for simulator and trainee web consoles."""

    def __init__(
        self,
        sim_dir: str | Path,
        runtime_dir: str | Path,
        kernel: Optional[Callable[[simu_loop.SimulationConfig], Optional[simu_loop.SimulationResult]]] = None,
        *,
        period_seconds: float = 60.0,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        compute_interval_seconds: float = DEFAULT_COMPUTE_INTERVAL_SECONDS,
        model_id: str = "default",
        model_name: str = "",
    ) -> None:
        self.sim_dir = Path(sim_dir).resolve()
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.model_id = _safe_model_id(model_id)
        self.model_name = model_name or self.model_id
        self.kernel = kernel or simu_loop.run_once
        self.period_seconds = float(period_seconds)
        self.compute_interval_seconds = _compute_interval_seconds(compute_interval_seconds)
        self.storage_initial_soc = DEFAULT_STORAGE_INITIAL_SOC
        self.noise_std = noise_std
        self.random_seed = random_seed
        self.clock = ClockState()
        self.lock = threading.RLock()
        self.command_history: List[Dict[str, Any]] = []
        self.runtime_logs: List[Dict[str, Any]] = []
        self._runtime_log_seq = 0
        self._last_command_response_index = 0
        self.latest_result: Dict[str, Any] = {}
        self.latest_measurements: Dict[str, Any] = {}
        self.latest_model_book: Optional[EBook] = None
        self.source_model_book = EBook({})
        self.source_stat_book = EBook({})
        self.control_book = EBook({})
        self.weather_book = EBook({})
        self.dev_define_book = EBook({})
        self.runtime_stat_book = EBook({})
        self.yt_ctrl_book = EBook({})
        self.mode_book: Optional[EBook] = None
        self.measurement_before: List[str] = []
        self.measurement_rows: List[List[str]] = []
        self.measurement_after: List[str] = []
        self.latest_real_rows: List[List[str]] = []
        self.latest_scada_rows: List[List[str]] = []
        self._fault_restore: Dict[Tuple[str, str, str], str] = {}
        self._last_scada_values: Dict[str, float] = {}

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
        }
        self.curves_file = self.runtime_dir / "curves.json"
        self.source_curves_file = self.source_files["curves"]
        self.settings_file = self.runtime_dir / "local_settings.json"
        self.commands_file = self.runtime_dir / "commands.json"
        self.runtime_logs_file = self.runtime_dir / "runtime_logs.json"

        self._copy_runtime_inputs()
        self.weather_defaults = self._read_weather_defaults()
        self.reload_definition_state()
        self.ensure_weather_measurements_in_definition_files()
        self.reload_definition_state()
        self.curves = self._read_curves()
        self.clock.step_minutes = max(1, int(_to_float(self.curves.get("time_step_minutes"), 1) or 1))
        self.local_settings = self._read_local_settings()
        self._apply_stored_system_parameters()
        self.command_history = self._read_command_history()
        self._last_command_response_index = len(self.command_history)
        self.runtime_logs = self._read_runtime_logs()
        self._runtime_log_seq = max((int(_to_float(item.get("seq"), 0) or 0) for item in self.runtime_logs), default=0)
        self.reload_definition_state()
        self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)

    def reload_definition_state(self) -> None:
        """Load source definition E files into the live calculation state."""
        self.source_model_book = _load_book(self.source_files["model"])
        self.source_stat_book = _load_book(self.source_files["stat"])
        self.control_book = _load_book(
            self.source_files["control"] if self.source_files["control"].exists() else self.source_files["stat"]
        )
        self.weather_book = _load_book(
            self.source_files["weather"] if self.source_files["weather"].exists() else self.work_files["weather"]
        )
        self.dev_define_book = simu_loop._capability_define_book(self.source_model_book, self._legacy_dev_define_file())
        try:
            self.measurement_before, self.measurement_rows, self.measurement_after = parse_measurement_rows(
                self.source_files["meas"]
            )
        except Exception:
            self.measurement_before, self.measurement_rows, self.measurement_after = [], [], []
        self.runtime_stat_book = self._base_stat_book_for_controls()
        self._ensure_runtime_stat_book()
        self.yt_ctrl_book = _make_book({"SetValue": (STAT_HEADERS["SetValue"], [])})
        self.mode_book = None
        self.latest_model_book = None
        self.latest_real_rows = []
        self.latest_scada_rows = []
        self.latest_measurements = {
            "definitions": [_measurement_row_to_dict(row) for row in self.measurement_rows],
            "real": [],
            "scada": [],
        }

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
        default = {"mode": "day", "time_step_minutes": 1, "weather": [], "loads": {}}
        source_curves = _read_json(self.source_curves_file, default) if self.source_curves_file.exists() else default
        return _read_json(self.curves_file, source_curves)

    def _read_local_settings(self) -> Dict[str, Any]:
        default = {"device_faults": [], "measurement_faults": [], "modes": [], "system_parameters": {}}
        if self.settings_file.exists():
            settings = _read_json(self.settings_file, default)
        else:
            source_settings_file = self.sim_dir / "local_settings.json"
            settings = _read_json(source_settings_file, default) if source_settings_file.exists() else default
        return dict(settings) if isinstance(settings, Mapping) else dict(default)

    def _read_runtime_logs(self) -> List[Dict[str, Any]]:
        items = _read_json(self.runtime_logs_file, [])
        if not isinstance(items, list):
            return []
        return [item for item in items[-500:] if isinstance(item, dict)]

    def _write_runtime_logs(self) -> None:
        _write_json(self.runtime_logs_file, self.runtime_logs[-500:])

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

    def _read_command_history(self) -> List[Dict[str, Any]]:
        items = _read_json(self.commands_file, [])
        if not isinstance(items, list):
            return []
        history = [item for item in items[-200:] if isinstance(item, dict)]
        changed = self._repair_legacy_cancel_command_entries(history)
        if changed:
            _write_json(self.commands_file, history[-200:])
        return history

    def _write_command_history(self) -> None:
        _write_json(self.commands_file, self.command_history[-200:])

    def _apply_stored_system_parameters(self) -> None:
        params = self.local_settings.get("system_parameters", {})
        if not isinstance(params, Mapping):
            return
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

    def system_parameters(self) -> Dict[str, Any]:
        return {
            "clock_speed": _nearest_clock_speed(self.clock.speed),
            "compute_interval_seconds": self.compute_interval_seconds,
            "storage_initial_soc": self.storage_initial_soc,
            "clock_step_minutes": max(1, int(self.clock.step_minutes)),
            "effective_step_minutes": _effective_clock_step(self.clock.step_minutes, self.clock.speed),
        }

    def set_system_parameters(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
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
                    f"储能SOC初始值 {format_number(self.storage_initial_soc)}",
                    f"有效推进步长 {effective_step} min",
                ],
                level="ok",
                simu_time=minute_to_time(self.clock.minute),
            )
            return {"system_parameters": self.system_parameters(), "clock": self.clock.as_dict()}

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
            if self.curves:
                _write_json(target_dir / "curves.json", self.curves)

    def _read_weather_defaults(self) -> Dict[str, float]:
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

    def _base_stat_book_for_controls(self) -> EBook:
        book = simu_loop._clone_ebook(self.source_stat_book)
        for name, headers in STAT_HEADERS.items():
            _ensure_block(book, name, headers)

        runtime_book = self.runtime_stat_book
        runtime_storage = runtime_book.data.get("StorageSoc") or runtime_book.data.get("StorageStatus")
        if runtime_storage is not None:
            storage_block = _ensure_block(book, "StorageSoc", STAT_HEADERS["StorageSoc"])
            storage_block.data = self._merge_runtime_storage_soc(storage_block.data, runtime_storage.data)
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
        if not self._command_entry_has_accepted_controls(item):
            return False
        current = float(absolute_minute)
        manual_hold = _manual_command_holds_across_clock_lifecycle(item)
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

    def _command_entry_has_accepted_controls(self, item: Mapping[str, Any]) -> bool:
        if not isinstance(item, Mapping) or not item.get("eligible_source") or item.get("cancelled"):
            return False
        accepted = item.get("accepted", {})
        if not isinstance(accepted, Mapping):
            return False
        accepted_count = int(_to_float(accepted.get("run_status"), 0) or 0) + int(_to_float(accepted.get("set_values"), 0) or 0)
        return accepted_count > 0

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
        active: List[Mapping[str, Any]] = []
        for item in self.command_history:
            if self._command_entry_is_active(item, absolute_minute, current_run_id):
                active.append(item)
        return active

    def _materialize_active_control_commands(self, absolute_minute: int | float, *, persist: bool = False) -> Dict[str, int]:
        book = self._base_stat_book_for_controls()
        run_block = _ensure_block(book, "RunStat", STAT_HEADERS["RunStat"])
        cb_block = _ensure_block(book, "CbOpenStat", STAT_HEADERS["CbOpenStat"])
        set_block = _ensure_block(book, "SetValue", STAT_HEADERS["SetValue"])
        active_entries = self._active_control_command_entries(absolute_minute)
        applied_run = 0
        applied_set = 0
        active_set_rows: List[Dict[str, Any]] = []

        for command in active_entries:
            normalized = command.get("normalized", {})
            run_items = normalized.get("run_status", []) if isinstance(normalized, Mapping) else []
            set_items = normalized.get("set_values", []) if isinstance(normalized, Mapping) else []
            if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
                for item in run_items:
                    if not isinstance(item, Mapping):
                        continue
                    dev_type = str(item.get("dev_type", ""))
                    dev_name = str(item.get("dev_name", ""))
                    if not dev_type or not dev_name:
                        continue
                    row = _find_dev_row(run_block, dev_type, dev_name)
                    if row is None:
                        row = {"dev_type": dev_type, "dev_name": dev_name, "run_stat": ""}
                        run_block.data.append(row)
                    if item.get("run_stat", "") != "":
                        row["run_stat"] = _number_text(item.get("run_stat"))
                        applied_run += 1
                    if "status" in item:
                        cb_row = _find_dev_row(cb_block, dev_type, dev_name)
                        if cb_row is None:
                            cb_row = {"dev_type": dev_type, "dev_name": dev_name, "status": ""}
                            cb_block.data.append(cb_row)
                        cb_row["status"] = _number_text(item.get("status"))
            if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
                for item in set_items:
                    if not isinstance(item, Mapping):
                        continue
                    dev_type = str(item.get("dev_type", ""))
                    dev_name = str(item.get("dev_name", ""))
                    set_type = str(item.get("set_type", ""))
                    if not dev_type or not dev_name or not set_type:
                        continue
                    row = _find_set_row(set_block, dev_type, dev_name, set_type)
                    if row is None:
                        row = {"dev_type": dev_type, "dev_name": dev_name, "set_type": set_type, "set_value": ""}
                        set_block.data.append(row)
                    row["set_value"] = _number_text(item.get("set_value", ""))
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
        return {"active_commands": len(active_entries), "run_status": applied_run, "set_values": applied_set}

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
            name = raw_name or f"{dev_type}.{dev_name}.{set_type}"
            return ("remote_adjustment", dev_type, dev_name, set_type), name
        field_name = "status" if control_type == "status" else "run_stat"
        name = raw_name or f"{dev_type}.{dev_name}.{field_name}"
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

    def cancel_student_commands(self, payload: Mapping[str, Any], source: str = "") -> Dict[str, Any]:
        with self.lock:
            source = source or str(payload.get("source", ""))
            eligible_source = _is_trainee_command_source(source)
            targets = self._cancel_command_targets(payload)
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
            }
            cancel_entry = {
                "time": received_wall_time,
                "received_wall_time": received_wall_time,
                "received_simu_time": received_simu_time,
                "received_absolute_minute": current,
                "run_id": int(self.clock.run_id),
                "source": source,
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
            self.command_history.append(cancel_entry)
            drop_count = max(0, len(self.command_history) - 200)
            if drop_count:
                self.command_history = self.command_history[drop_count:]
                self._last_command_response_index = max(0, self._last_command_response_index - drop_count)
            self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            self._write_command_history()
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

    def _make_config(self, period_seconds: Optional[float] = None) -> simu_loop.SimulationConfig:
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
            model_book=self.source_model_book,
            meas_before=list(self.measurement_before),
            meas_rows=[list(row) for row in self.measurement_rows],
            meas_after=list(self.measurement_after),
            weather_book=self.weather_book,
            dev_stat_book=self.runtime_stat_book,
            yt_ctrl_book=self.yt_ctrl_book,
            dev_define_book=self.dev_define_book,
            mode_book=self.mode_book,
        )

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
        self._runtime_log_seq += 1
        self.runtime_logs.append(
            {
                "seq": self._runtime_log_seq,
                "wall_time": _now_text(),
                "simu_time": simu_time or minute_to_time(self.clock.minute),
                "type": log_type,
                "target": target,
                "result": result,
                "detail": _format_log_detail(detail),
                "level": level,
            }
        )
        self.runtime_logs = self.runtime_logs[-500:]
        self._write_runtime_logs()

    def clear_runtime_logs(self) -> Dict[str, int]:
        count = len(self.runtime_logs)
        self.runtime_logs = []
        self._runtime_log_seq = 0
        self._write_runtime_logs()
        return {"cleared": count}

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
        expires_at_absolute_minute: float,
    ) -> List[str]:
        valid_for = max(0.0, expires_at_absolute_minute - issued_absolute_minute)
        lines = [
            f"来源 {source}",
            (
                f"来源校验 {'学员台有效来源' if eligible_source else '非学员台来源，忽略为无效控制'}，"
                f"有效期 {format_number(valid_for)} min，截止累计分钟 {format_number(expires_at_absolute_minute)}"
            ),
            f"接受投退 {accepted.get('run_status', 0)} 条，设值 {accepted.get('set_values', 0)} 条，忽略 {accepted.get('ignored', 0)} 条",
        ]
        run_preview = []
        for item in run_items:
            if not isinstance(item, Mapping):
                continue
            dev_type = str(item.get("dev_type", item.get("type", "")))
            dev_name = str(item.get("dev_name", item.get("name", "")))
            run_stat = item.get("run_stat", item.get("running", item.get("value", "")))
            if isinstance(run_stat, bool):
                run_stat = 1 if run_stat else 0
            if dev_type and dev_name:
                run_preview.append(f"{dev_type}.{dev_name}={_number_text(run_stat)}")
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
        step = max(1.0, _to_float(self.curves.get("time_step_minutes"), 1.0) or 1.0)
        return int((target_minute % period_minutes) // step) + 1

    def _append_environment_load_log(
        self,
        minute: int,
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
                f"环境 风速 {row.get('wind_speed_mps', '')} m/s，光照 {row.get('solar_irradiance_w_m2', '')} W/m2，"
                f"气温 {row.get('air_temp_c', '')} ℃，气压 {row.get('air_pressure_hpa', '')} hPa，湿度 {row.get('humidity_pct', '')} %"
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

    def _load_flow_input_model_book(self) -> Optional[EBook]:
        if self.latest_model_book is not None:
            return self.latest_model_book
        return self.source_model_book

    def _renewable_limit_boundary_lines(self) -> List[str]:
        weather = simu_loop._weather_values_from_book(self.weather_book)
        model_book = self._load_flow_input_model_book()
        if model_book is None:
            return ["新能源限值 未读取到潮流输入模型"]
        device_book = self.dev_define_book
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
                ("ACGenerator",),
                ("wt", "wind"),
            ):
                rated = simu_loop._safe_float((define or {}).get("rated_power", (define or {}).get("p_max", 10.0)), 10.0) or 10.0
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
                ("DCGenerator",),
                ("pv", "solar"),
            ):
                rated = simu_loop._safe_float((define or {}).get("rated_power", (define or {}).get("p_max", row.get("p_set", 0.0))), 0.0) or 0.0
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

        return [
            (
                f"新能源限值 风电 {wind_count} 台，可用 {format_number(wind_available_total)} kW，执行 {format_number(wind_execute_total)} kW；"
                f"光伏 {pv_count} 台，可用 {format_number(pv_available_total)} kW，执行 {format_number(pv_execute_total)} kW"
            )
        ]

    def _input_boundary_lines(
        self,
        minute: int,
        absolute_minute: int,
        clock_advance: int,
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
            f"风速 {_number_text(weather.get('wind_speed_mps', ''))} m/s，"
            f"辐照 {_number_text(weather.get('solar_irradiance_w_m2', ''))} W/m2，"
            f"气温 {_number_text(weather.get('air_temp_c', ''))} ℃，"
            f"负荷 {_number_text(weather.get('load_kw', ''))} kW"
            if weather
            else "未读取到 Weather 块"
        )
        return [
            (
                f"仿真边界 时刻 {minute_to_time(minute)}，日内分钟 {minute}，累计分钟 {absolute_minute}，"
                f"本步推进 {clock_advance} min，等效计算周期 {format_number(period_seconds)} s"
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

    def _device_category_names(self) -> Dict[str, set[str]]:
        categories = {
            "wind": set(),
            "pv": set(),
            "diesel": set(),
            "load": set(),
            "storage": set(),
        }
        model_book = self.source_model_book
        capability_book = self.dev_define_book
        for category, block_name in {
            "wind": "wind_generator",
            "pv": "pv_generator",
            "diesel": "diesel_generator",
            "storage": "estorage",
        }.items():
            block = capability_book.data.get(block_name)
            if block is None:
                continue
            for row in block.data:
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                categories[category].add(name)
                if category == "storage":
                    categories[category].add(f"{name}_vsrc")
        for row in getattr(model_book.data.get("ACLoad"), "data", []):
            name = str(row.get("name", "")).strip()
            if name:
                categories["load"].add(name)
        return categories

    def _measurement_power_category(
        self,
        dev_type: str,
        dev_name: str,
        category_names: Mapping[str, set[str]],
    ) -> str:
        lower_name = dev_name.casefold()
        storage_names = category_names["storage"]
        wind_names = category_names["wind"]
        pv_names = category_names["pv"]
        diesel_names = category_names["diesel"]
        load_names = category_names["load"]
        if dev_type in ("ESS", "Storage"):
            return "storage"
        if dev_type == "DCGenerator" and (
            dev_name in storage_names or (not storage_names and lower_name.startswith("ess"))
        ):
            return "storage"
        if dev_type == "ACGenerator" and (
            dev_name in wind_names or (not wind_names and lower_name.startswith(("wt", "wind")))
        ):
            return "wind"
        if dev_type == "DCGenerator" and (
            dev_name in pv_names or (not pv_names and lower_name.startswith(("pv", "solar")))
        ):
            return "pv"
        if dev_type == "ACGenerator" and (
            dev_name in diesel_names or (not diesel_names and ("diesel" in lower_name or "柴" in dev_name))
        ):
            return "diesel"
        if dev_type.endswith("Load") and (
            dev_name in load_names or (not load_names and ("load" in lower_name or "负荷" in dev_name))
        ):
            return "load"
        return ""

    def _canonical_power_device_name(self, category: str, dev_name: str) -> str:
        if category == "storage" and dev_name.endswith("_vsrc"):
            return dev_name.removesuffix("_vsrc")
        return dev_name

    def _preferred_power_value(self, category: str, values: Mapping[str, float]) -> Optional[float]:
        preferences = {
            "wind": ("P_AC", "P_DC", "P_GEN", "P", "P_FROM", "P_TO"),
            "pv": ("P_TO", "P_FROM", "P_GEN", "P", "P_DC", "P_AC"),
            "diesel": ("P_GEN", "P", "P_AC", "P_TO", "P_FROM"),
            "load": ("P_LOAD", "P", "P_AC", "P_TO", "P_FROM"),
            "storage": ("P", "P_GEN", "P_FROM", "P_TO"),
        }
        for meas_type in preferences.get(category, ("P",)):
            if meas_type in values:
                return values[meas_type]
        return None

    def _power_flow_summary_lines(self, real_measurements: Sequence[Mapping[str, Any]]) -> List[str]:
        category_names = self._device_category_names()
        power_by_device: Dict[Tuple[str, str], Dict[str, float]] = {}
        soc_by_storage: Dict[str, float] = {}

        for item in real_measurements:
            if int(_to_float(item.get("valid"), 1) or 0) != 1:
                continue
            dev_type = str(item.get("dev_type", ""))
            dev_name = str(item.get("dev_name", ""))
            meas_type = str(item.get("meas_type", "")).upper()
            value = _to_float(item.get("value"), None)
            if not dev_type or not dev_name or meas_type == "" or value is None:
                continue
            category = self._measurement_power_category(dev_type, dev_name, category_names)
            if category == "storage" and meas_type == "SOC":
                soc_by_storage[self._canonical_power_device_name(category, dev_name)] = value
                continue
            if not meas_type.startswith("P"):
                continue
            if not category:
                continue
            device_key = (category, self._canonical_power_device_name(category, dev_name))
            power_by_device.setdefault(device_key, {})[meas_type] = value

        totals = {"wind": 0.0, "pv": 0.0, "diesel": 0.0, "load": 0.0}
        counts = {"wind": 0, "pv": 0, "diesel": 0, "load": 0, "storage": 0}
        storage_generation = 0.0
        storage_charge = 0.0
        for (category, _dev_name), values in power_by_device.items():
            power = self._preferred_power_value(category, values)
            if power is None:
                continue
            counts[category] += 1
            if category == "storage":
                if power >= 0.0:
                    storage_generation += power
                else:
                    storage_charge += -power
            else:
                totals[category] += abs(power)

        soc_values = list(soc_by_storage.values())
        soc_average = sum(soc_values) / len(soc_values) if soc_values else None
        soc_total = sum(soc_values)
        soc_text = (
            f"储能SOC 平均 {format_number(soc_average * 100.0)}%，储能总SOC {format_number(soc_total)}，台数 {len(soc_values)}"
            if soc_average is not None
            else "储能SOC 平均 --，储能总SOC --，台数 0"
        )
        generation_total = totals["wind"] + totals["pv"] + totals["diesel"] + storage_generation
        consumption_total = totals["load"] + storage_charge
        power_difference = generation_total - consumption_total
        return [
            (
                f"分类统计 风力发电总功率 {format_number(totals['wind'])} kW（{counts['wind']} 台），"
                f"光伏发电总功率 {format_number(totals['pv'])} kW（{counts['pv']} 台）"
            ),
            (
                f"分类统计 柴油发电总功率 {format_number(totals['diesel'])} kW（{counts['diesel']} 台），"
                f"负荷用电总功率 {format_number(totals['load'])} kW（{counts['load']} 个）"
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
        minute: int,
        absolute_minute: int,
        clock_advance: int,
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
        minute: int,
        absolute_minute: int,
        clock_advance: int,
        period_seconds: float,
    ) -> None:
        simu_time = minute_to_time(minute)
        result = self._power_flow_failure_result(error)
        detail = [
            (
                f"计算失败 时刻 {simu_time}，累计分钟 {absolute_minute}，推进 {clock_advance} min，"
                f"仿真周期 {format_number(period_seconds)} s"
            ),
            f"失败类型 {result}，异常 {type(error).__name__}: {error}",
            "处理措施 本轮潮流结果未写入，仿真时钟不推进；时钟保护逻辑将切换为暂停状态",
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
            normalized_run_items = self._normalize_run_command_items(run_sequence)
            normalized_set_items = self._normalize_set_command_items(set_sequence)
            eligible_source = _is_trainee_command_source(source)
            issued_absolute_minute = float(self.clock.absolute_minute)
            received_wall_time = _now_text()
            received_simu_time = minute_to_time(self.clock.minute)
            expires_at_absolute_minute = _command_expires_at(payload, None, issued_absolute_minute)
            accepted_run = len(normalized_run_items) if eligible_source else 0
            accepted_set = len(normalized_set_items) if eligible_source else 0
            ignored = 0 if eligible_source else len(normalized_run_items) + len(normalized_set_items)
            accepted = {"run_status": accepted_run, "set_values": accepted_set, "ignored": ignored}
            manual_hold = _manual_command_holds_across_clock_lifecycle(payload, source)
            command_entry = {
                "time": received_wall_time,
                "received_wall_time": received_wall_time,
                "received_simu_time": received_simu_time,
                "received_absolute_minute": issued_absolute_minute,
                "run_id": int(self.clock.run_id),
                "source": source,
                "eligible_source": eligible_source,
                "manual_hold": manual_hold,
                "issued_absolute_minute": issued_absolute_minute,
                "expires_at_absolute_minute": expires_at_absolute_minute,
                "valid_for_minutes": max(0.0, expires_at_absolute_minute - issued_absolute_minute),
                "accepted": accepted,
                "normalized": {
                    "run_status": normalized_run_items if eligible_source else [],
                    "set_values": normalized_set_items if eligible_source else [],
                },
                "payload": json.loads(json.dumps(payload, ensure_ascii=False, default=str)),
            }
            self.command_history.append(command_entry)
            drop_count = max(0, len(self.command_history) - 200)
            if drop_count:
                self.command_history = self.command_history[drop_count:]
                self._last_command_response_index = max(0, self._last_command_response_index - drop_count)
            self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            self._write_command_history()
            self._append_runtime_log(
                "控制指令",
                "学员台 /api/student/commands",
                "接受成功" if accepted_run or accepted_set else "无有效指令",
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
            item_dev_type = str(item.get("dev_type", item.get("type", "")))
            item_dev_name = str(item.get("dev_name", item.get("name", "")))
            if item_dev_type == "Storage" and item_dev_name:
                item = {
                    **dict(item),
                    "dev_type": "ESS",
                    "dev_name": item_dev_name,
                }
            if "set_type" in item:
                expanded.append(dict(item))
                continue
            for key in ("p_set", "q_set", "v_set", "p_ac_set", "q_ac_set", "v_ac_set"):
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
        with self.lock:
            mode = str(payload.get("mode", self.curves.get("mode", "day")) or "day").lower()
            if mode not in ("day", "year"):
                mode = "day"
            current_mode = str(self.curves.get("mode", "day") or "day").lower()
            if mode != current_mode and self.clock.state != "stopped":
                raise ValueError("仿真运行过程中不能切换仿真模式，请先停止仿真")
            default_step = 60 if mode == "year" else 1
            time_step_minutes = int(_to_float(payload.get("time_step_minutes"), default_step) or default_step)
            point_count = int(_to_float(payload.get("point_count"), 8760 if mode == "year" else 1440) or 0)
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
            self.curves = {
                "mode": mode,
                "time_step_minutes": time_step_minutes,
                "point_count": point_count or len(weather_points),
                "weather": weather_points,
                "loads": loads,
            }
            self.clock.step_minutes = max(1, time_step_minutes)
            self.clock.absolute_minute = _align_minute_to_step(
                self.clock.absolute_minute,
                _effective_clock_step(self.clock.step_minutes, self.clock.speed),
            )
            self.clock.minute = self.clock.absolute_minute % 1440
            self.clock.updated_at = time.time()
            _write_json(self.curves_file, self.curves)
            return {"weather_points": len(weather_points), "load_devices": len(loads), "mode": mode}

    def set_local_settings(self, payload: Mapping[str, Any]) -> Dict[str, int]:
        with self.lock:
            aliases = {
                "device_faults": ("device_faults", "deviceFaults", "faults"),
                "measurement_faults": ("measurement_faults", "measurementFaults", "meas_faults"),
                "modes": ("modes", "device_modes", "deviceModes"),
            }
            for target_key, names in aliases.items():
                for name in names:
                    if name in payload:
                        value = payload.get(name) or []
                        self.local_settings[target_key] = list(value) if isinstance(value, Sequence) else []
                        break
            _write_json(self.settings_file, self.local_settings)
            return {
                "device_faults": len(self.local_settings.get("device_faults", [])),
                "measurement_faults": len(self.local_settings.get("measurement_faults", [])),
                "modes": len(self.local_settings.get("modes", [])),
            }

    def control_clock(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            action = str(payload.get("action", "")).lower()
            previous_state = self.clock.state
            if "step_minutes" in payload:
                self.clock.step_minutes = max(1, int(_to_float(payload.get("step_minutes"), 1) or 1))
            if "minute" in payload:
                minute = int(_to_float(payload.get("minute"), self.clock.minute) or 0)
                self.clock.absolute_minute = minute
                self.clock.minute = minute % 1440
            if "speed" in payload:
                self.clock.speed = _nearest_clock_speed(payload.get("speed"))
            should_reset_storage_soc = False
            if action == "start":
                if previous_state == "stopped":
                    self.clock.run_id += 1
                    should_reset_storage_soc = True
                self.clock.state = "running"
            elif action == "pause":
                self.clock.state = "paused"
            elif action == "stop":
                self.clock.state = "stopped"
                self.clock.absolute_minute = 0
                self.clock.minute = 0
                self.clock.step_count = 0
                should_reset_storage_soc = True
            elif action in ("faster", "speed_up"):
                self.clock.speed = _next_clock_speed(self.clock.speed)
            elif action in ("slower", "speed_down"):
                self.clock.speed = _previous_clock_speed(self.clock.speed)
            effective_step = _effective_clock_step(self.clock.step_minutes, self.clock.speed)
            self.clock.absolute_minute = _align_minute_to_step(self.clock.absolute_minute, effective_step)
            self.clock.minute = self.clock.absolute_minute % 1440
            if should_reset_storage_soc:
                self._reset_storage_soc_to_initial()
            if action in ("start", "stop"):
                self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            if action == "step":
                return self.step(advance_minutes=effective_step)["clock"]
            self.clock.updated_at = time.time()
            return self.clock.as_dict()

    def step(self, advance_minutes: Optional[int] = None) -> Dict[str, Any]:
        with self.lock:
            step_minutes = max(1, int(self.clock.step_minutes))
            clock_advance = step_minutes if advance_minutes is None else max(1, int(advance_minutes))
            self.clock.absolute_minute = _align_minute_to_step(self.clock.absolute_minute, clock_advance)
            self.clock.minute = self.clock.absolute_minute % 1440
            period_seconds = self.period_seconds * clock_advance / step_minutes
            minute = self.clock.minute
            absolute_minute = self.clock.absolute_minute
            self._prepare_runtime_inputs(minute, absolute_minute)
            config = self._make_config(period_seconds=period_seconds)
            try:
                kernel_result = self.kernel(config)
            except Exception as exc:
                self.latest_result = {
                    "solver_info": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                self._append_power_flow_failure_log(exc, minute, absolute_minute, clock_advance, period_seconds)
                self.clock.updated_at = time.time()
                raise
            self.latest_model_book = getattr(kernel_result, "model_book", None)
            self._store_kernel_measurement_rows(kernel_result)
            self._apply_measurement_faults(minute, absolute_minute)
            self.latest_measurements = self.measurements()
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
            self.clock.absolute_minute += clock_advance
            self.clock.minute = self.clock.absolute_minute % 1440
            self.clock.step_count += 1
            self.clock.updated_at = time.time()
            return self.snapshot()

    def _store_kernel_measurement_rows(self, result: Optional[simu_loop.SimulationResult]) -> None:
        if result is None:
            return
        real_rows = getattr(result, "real_rows", None)
        scada_rows = getattr(result, "scada_rows", None)
        if real_rows is not None:
            self.latest_real_rows = [list(row) for row in real_rows]
        if scada_rows is not None:
            self.latest_scada_rows = [list(row) for row in scada_rows]

    def _prepare_runtime_inputs(self, minute: int, absolute_minute: int) -> None:
        self._write_current_weather(minute, absolute_minute)
        self._materialize_active_control_commands(absolute_minute)
        self._apply_device_faults(minute, absolute_minute)
        self._write_modes_file()

    def _write_current_weather(self, minute: int, absolute_minute: int | float | None = None) -> None:
        curve_mode = str(self.curves.get("mode", "day") or "day").lower()
        period_minutes = 365.0 * 24.0 * 60.0 if curve_mode == "year" else 1440.0
        target_minute = absolute_minute if curve_mode == "year" and absolute_minute is not None else minute
        row = {"time": minute_to_time(minute)}
        for key, default in self.weather_defaults.items():
            row[key] = _number_text(
                _interpolate(self.curves.get("weather", []), target_minute, key, default, period_minutes=period_minutes)
            )
        load_total = 0.0
        load_seen = False
        loads = self.curves.get("loads", {})
        load_details: List[Tuple[str, float]] = []
        if isinstance(loads, Mapping):
            for load_name, points in loads.items():
                value = _interpolate(points, target_minute, "p_kw", float("nan"), period_minutes=period_minutes)
                if value == value:
                    load_total += value
                    load_seen = True
                    load_details.append((str(load_name), value))
        row["load_kw"] = _number_text(load_total if load_seen else self.weather_defaults.get("load_kw", 0.0))
        self._write_weather_row(row)
        self._append_environment_load_log(
            minute,
            float(target_minute),
            period_minutes,
            row,
            load_details,
            load_seen=load_seen,
        )

    def _write_weather_row(self, row: Mapping[str, Any]) -> None:
        clean = {header: row.get(header, "") for header in WEATHER_HEADER}
        self.weather_book = _make_book({"Weather": (WEATHER_HEADER, [clean])})

    def _apply_device_faults(self, minute: int, absolute_minute: int) -> None:
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

    def _apply_measurement_faults(self, minute: int, absolute_minute: int) -> None:
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
        for offset, (weather_key, name_suffix, meas_type) in enumerate(WEATHER_MEASUREMENTS):
            value = _to_float(weather.get(weather_key), _to_float(DEFAULT_WEATHER.get(weather_key), 0.0))
            rows.append(
                {
                    "idx": start_idx + offset,
                    "name": f"weather_{name_suffix}",
                    "dev_type": "Environment",
                    "dev_name": "weather",
                    "meas_type": meas_type,
                    "weight": 1.0,
                    "valid": 1,
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
        return values

    def _signal_measurement_rows(self, start_idx: int) -> List[Dict[str, Any]]:
        values = self._current_signal_values()
        rows: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str, str]] = set()
        for book in (self.control_book, self.source_stat_book, self.runtime_stat_book):
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
                            "name": f"{dev_type}.{dev_name}.{name_suffix}",
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
            meas_type: _to_float(weather.get(weather_key), _to_float(DEFAULT_WEATHER.get(weather_key), 0.0)) or 0.0
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
                if meas_type in weather_values:
                    row["value"] = weather_values[meas_type]
                row.setdefault("valid", 1)
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
        definitions = [_measurement_row_to_dict(row) for row in self.measurement_rows]
        real = [_measurement_row_to_dict(row) for row in self.latest_real_rows]
        scada = [_measurement_row_to_dict(row) for row in self.latest_scada_rows]
        measurements = self._with_realtime_measurements({"definitions": definitions, "real": real, "scada": scada})
        for item in measurements["scada"]:
            self._last_scada_values[
                f"{item['name']}|{item['dev_type']}|{item['dev_name']}|{item['meas_type']}"
            ] = item.get("value", 0.0) or 0.0
        return measurements

    def _read_measurement_file(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            _before, rows, _after = parse_measurement_rows(path)
        except Exception:
            return []
        return [_measurement_row_to_dict(row) for row in rows]

    def devices(self) -> List[Dict[str, Any]]:
        model_book = self.source_model_book
        run_stats, cb_status, set_values, soc_values = self._stat_maps()
        devices: List[Dict[str, Any]] = []
        device_blocks = (
            "ACGenerator",
            "DCGenerator",
            "ACLoad",
            "DCLoad",
            "DCDCConverter",
            "DCACConverter",
            "ACACConverter",
            "ACBreak",
            "DCBreak",
            "ACSwitch",
            "DCSwitch",
        )
        for dev_type in device_blocks:
            block = model_book.data.get(dev_type)
            if block is None:
                continue
            for row in block.data:
                name = str(row.get("name", ""))
                key = (dev_type, name)
                set_types = []
                for column in ("p_set", "q_set", "v_set", "p_ac_set", "q_ac_set", "v_ac_set", "pv0", "qv0"):
                    if column in block.header_list:
                        set_types.append(column)
                devices.append(
                    {
                        "dev_type": dev_type,
                        "dev_name": name,
                        "run_stat": int(_to_float(run_stats.get(key, row.get("run_stat", 1)), 1) or 0),
                        "status": int(_to_float(cb_status.get(key, row.get("status", 1)), 1) or 0),
                        "mode": row.get("control_type", row.get("mode", "")),
                        "set_types": set_types,
                        "set_values": set_values.get(key, {}),
                        "raw": {header: row.get(header, "") for header in block.header_list},
                    }
                )
        devices_by_key = {
            (str(device.get("dev_type", "")), str(device.get("dev_name", ""))): device
            for device in devices
        }
        storage_raw: Dict[str, Dict[str, Any]] = {}
        capability_book = self.dev_define_book
        storage_block = capability_book.data.get("estorage")
        for row in getattr(storage_block, "data", []):
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            storage_raw[name] = {header: row.get(header, "") for header in storage_block.header_list}
            soc_values.setdefault(
                name,
                _to_float(row.get("soc_curr", row.get("soc_cur", row.get("soc", 0.0))), 0.0) or 0.0,
            )
            for key in (("DCGenerator", name), ("DCGenerator", f"{name}_vsrc")):
                device = devices_by_key.get(key)
                if device is None:
                    continue
                device["soc_curr"] = soc_values[name]
                device["raw"] = dict(device.get("raw", {})) | storage_raw[name] | {"soc_curr": soc_values[name]}
                for set_type in ("p_set", "v_set"):
                    if set_type not in device["set_types"]:
                        device["set_types"].append(set_type)
        for (dev_type, dev_name), _run_stat in run_stats.items():
            if dev_type in ("ESS", "Storage") and dev_name:
                soc_values.setdefault(dev_name, 0.0)
        for name, soc in soc_values.items():
            if ("DCGenerator", name) in devices_by_key or ("DCGenerator", f"{name}_vsrc") in devices_by_key:
                continue
            storage_set_values = set_values.get(("ESS", name), set_values.get(("DCGenerator", f"{name}_vsrc"), {}))
            devices.append(
                {
                    "dev_type": "ESS",
                    "dev_name": name,
                    "run_stat": int(_to_float(run_stats.get(("ESS", name), 1), 1) or 0),
                    "status": 1,
                    "mode": "PH",
                    "set_types": ["p_set", "v_set"],
                    "set_values": storage_set_values,
                    "soc_curr": soc,
                    "raw": storage_raw.get(name, {}) | {"soc_curr": soc},
                }
            )
        return devices

    def _api_time_payload(self) -> Dict[str, Any]:
        return {
            "time": minute_to_time(self.clock.minute),
            "simu_time": minute_to_time(self.clock.minute),
            "absolute_minute": self.clock.absolute_minute,
            "wall_time": _now_text(),
        }

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
                        "name": f"{dev_type}.{dev_name}.run_stat",
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
                        "name": f"{dev_type}.{dev_name}.status",
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

    def latest_telemetry_values(self) -> Dict[str, Any]:
        """Return compact latest remote measurements and status points for external clients."""
        time_payload = self._api_time_payload()
        items = [
            self._compact_external_value_item(item, time_payload, include_valid=True)
            for item in self._latest_telemetry_items()
        ]
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            **time_payload,
            "items": items,
            "values": {item["name"]: item.get("value") for item in items},
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
            "model_id": self.model_id,
            "model_name": self.model_name,
            **time_payload,
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

    def _command_entry_time_info(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        absolute_minute = _to_float(entry.get("received_absolute_minute", entry.get("issued_absolute_minute")), None)
        return {
            "wall_time": entry.get("received_wall_time", entry.get("time", "")) or "--",
            "simu_time": entry.get("received_simu_time") or (minute_to_time(absolute_minute) if absolute_minute is not None else "--"),
            "absolute_minute": absolute_minute,
            "expires_at_absolute_minute": _to_float(entry.get("expires_at_absolute_minute"), None),
            "source": entry.get("source", ""),
        }

    def _latest_active_control_update(
        self,
        command_kind: str,
        dev_type: str,
        dev_name: str,
        field_name: str,
    ) -> Dict[str, Any]:
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
        return {"wall_time": "--", "simu_time": "--", "absolute_minute": None, "expires_at_absolute_minute": None, "source": "", "active": False}

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
                    "name": f"{dev_type}.{dev_name}.run_stat",
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
                    "name": f"{dev_type}.{dev_name}.status",
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
                    "name": f"{dev_type}.{dev_name}.{set_type}",
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
                }
            )

        return items

    def latest_control_values(self) -> Dict[str, Any]:
        """Return compact current remote-control and remote-adjustment values for external clients."""
        time_payload = self._api_time_payload()
        items = [
            self._compact_external_value_item(item, time_payload, include_active=True)
            for item in self._latest_control_value_items()
        ]
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            **time_payload,
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
                resolved_items.append({"name": raw_name or f"{dev_type}.{dev_name}.{set_type}", "value": _json_scalar(value)})
                continue
            field_name = "status" if control_type == "status" else "run_stat"
            run_row: Dict[str, Any] = {"dev_type": dev_type, "dev_name": dev_name}
            run_row[field_name] = value
            run_items.append(run_row)
            resolved_items.append({"name": raw_name or f"{dev_type}.{dev_name}.{field_name}", "value": _json_scalar(value)})

        return {"run_status": run_items, "set_values": set_items, "resolved_items": resolved_items}

    def apply_external_control_values(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if _has_cancel_command_payload(payload):
            source = str(payload.get("source") or "trainee-external-api")
            if not _is_trainee_command_source(source):
                source = f"trainee-{source}"
            result = self.cancel_student_commands(payload | {"source": source}, source=source)
            time_payload = self._api_time_payload()
            return {
                "model_id": self.model_id,
                "model_name": self.model_name,
                **time_payload,
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
            "model_id": self.model_id,
            "model_name": self.model_name,
            **time_payload,
            "accepted": {
                "remote_controls": result.get("run_status", 0),
                "remote_adjustments": result.get("set_values", 0),
                "ignored": result.get("ignored", 0),
            },
            "updated_items": updated_items,
            "control_values": self.latest_control_values(),
        }

    def device_parameters(self) -> Dict[str, List[Dict[str, Any]]]:
        book = self.source_model_book
        parameter_blocks = ("ACWindGen", "DCPVGen", "DCStorageGen")
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
    ) -> Dict[str, Dict[str, Any]]:
        book = self._definition_book_for_path(path)
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

    def _definition_book_for_path(self, path: Path) -> EBook:
        try:
            resolved = Path(path).resolve()
        except Exception:
            resolved = Path(path)
        path_by_book = (
            (self.source_files.get("model"), self.source_model_book),
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
        measurement_rows = list((measurements or {}).get("definitions", []))
        if not measurement_rows:
            measurement_rows = self._with_realtime_measurements(
                {"definitions": [_measurement_row_to_dict(row) for row in self.measurement_rows], "real": [], "scada": []}
            )["definitions"]
        return {
            "model": self._definition_book_blocks(self.files["model"]),
            "measurement": measurement_rows,
            "control": self._definition_book_blocks(
                self._control_definition_path(),
                CONTROL_DEFINITION_BLOCKS,
            ),
        }

    def _stat_maps(self) -> Tuple[Dict[Tuple[str, str], Any], Dict[Tuple[str, str], Any], Dict[Tuple[str, str], dict], Dict[str, float]]:
        stat_book = self.runtime_stat_book
        run_stats: Dict[Tuple[str, str], Any] = {}
        cb_status: Dict[Tuple[str, str], Any] = {}
        set_values: Dict[Tuple[str, str], dict] = {}
        soc_values: Dict[str, float] = {}
        for row in getattr(stat_book.data.get("RunStat"), "data", []):
            run_stats[(str(row.get("dev_type", "")), _dev_name(row))] = row.get("run_stat", "")
        for row in getattr(stat_book.data.get("CbOpenStat"), "data", []):
            cb_status[(str(row.get("dev_type", "")), _dev_name(row))] = row.get("status", "")
        for row in getattr(stat_book.data.get("SetValue"), "data", []):
            key = (str(row.get("dev_type", "")), _dev_name(row))
            set_values.setdefault(key, {})[str(row.get("set_type", ""))] = row.get("set_value", "")
        storage_block = stat_book.data.get("StorageSoc") or stat_book.data.get("StorageStatus")
        for row in getattr(storage_block, "data", []):
            name = str(row.get("name", row.get("dev_name", "")))
            soc_values[name] = _to_float(row.get("soc_curr", row.get("soc", 0.0)), 0.0) or 0.0
        return run_stats, cb_status, set_values, soc_values

    def model_info(self) -> Dict[str, Any]:
        return {
            "id": self.model_id,
            "name": self.model_name,
            "sim_dir": str(self.sim_dir),
            "runtime_dir": str(self.runtime_dir),
            "clock_state": self.clock.state,
        }

    def snapshot(self) -> Dict[str, Any]:
        measurements = dict(self.latest_measurements or self.measurements())
        if "definitions" not in measurements:
            measurements["definitions"] = [_measurement_row_to_dict(row) for row in self.measurement_rows]
        measurements = self._with_realtime_measurements(measurements)
        return {
            "model": self.model_info(),
            "clock": self.clock.as_dict(),
            "files": {key: str(path) for key, path in self.files.items()},
            "source_files": {key: str(path) for key, path in self.source_files.items()},
            "work_files": {key: str(path) for key, path in self.work_files.items()},
            "definitions": self.definitions(measurements),
            "curves": self.curves,
            "settings": self.local_settings,
            "system_parameters": self.system_parameters(),
            "commands": {"history": self.command_history[-50:]},
            "runtime_logs": self.runtime_logs[-300:],
            "devices": self.devices(),
            "device_parameters": self.device_parameters(),
            "measurements": measurements,
            "result": self.latest_result,
            "summary": self._summary(measurements),
        }

    def _summary(self, measurements: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
        scada = measurements.get("scada", [])
        valid = [item for item in scada if item.get("valid", 0) == 1]
        alarms = [
            item
            for item in scada
            if item.get("value") is not None and abs(float(item.get("value") or 0.0)) > 1e4
        ]
        return {
            "scada_count": len(scada),
            "valid_scada_count": len(valid),
            "alarm_count": len(alarms),
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
        period_seconds: float = 60.0,
        compute_interval_seconds: float = DEFAULT_COMPUTE_INTERVAL_SECONDS,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        models_root: str | Path | None = None,
        directory_backed: bool = False,
    ) -> None:
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        normalized_specs = self._unique_specs([self._normalize_spec(raw_spec) for raw_spec in specs])
        self.models_root = Path(models_root).resolve() if models_root else self._infer_models_root(normalized_specs)
        self.models_root.mkdir(parents=True, exist_ok=True)
        self.directory_backed = directory_backed
        self.kernel = kernel
        self.period_seconds = period_seconds
        self.compute_interval_seconds = _compute_interval_seconds(compute_interval_seconds)
        self.noise_std = noise_std
        self.random_seed = random_seed
        self._services: Dict[str, PolarMicrogridSimulator] = {}
        self.lock = threading.RLock()
        self.default_model_id = ""
        for spec in normalized_specs:
            if spec.model_id in self._services:
                raise ValueError(f"Duplicate simulation model id: {spec.model_id}")
            service = PolarMicrogridSimulator(
                sim_dir=spec.sim_dir,
                runtime_dir=self.runtime_dir / spec.model_id,
                kernel=kernel,
                period_seconds=period_seconds,
                compute_interval_seconds=self.compute_interval_seconds,
                noise_std=noise_std,
                random_seed=random_seed,
                model_id=spec.model_id,
                model_name=spec.name,
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
        period_seconds: float = 60.0,
        compute_interval_seconds: float = DEFAULT_COMPUTE_INTERVAL_SECONDS,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        models_dir: str | Path | None = None,
    ) -> "MultiModelSimulator":
        root = Path(sim_dir).resolve()
        models_root = Path(models_dir).resolve() if models_dir else root / "models"
        specs = cls._discover_specs(root, models_root)
        return cls(
            specs,
            runtime_dir=runtime_dir,
            kernel=kernel,
            period_seconds=period_seconds,
            compute_interval_seconds=compute_interval_seconds,
            noise_std=noise_std,
            random_seed=random_seed,
            models_root=models_root,
            directory_backed=True,
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

    def _make_service(self, spec: SimulationModelSpec) -> PolarMicrogridSimulator:
        return PolarMicrogridSimulator(
            sim_dir=spec.sim_dir,
            runtime_dir=self.runtime_dir / spec.model_id,
            kernel=self.kernel,
            period_seconds=self.period_seconds,
            compute_interval_seconds=self.compute_interval_seconds,
            noise_std=self.noise_std,
            random_seed=self.random_seed,
            model_id=spec.model_id,
            model_name=spec.name,
        )

    def _sync_models_from_directory_locked(self) -> None:
        specs = self._unique_specs(self._directory_specs(self.models_root))
        if not specs:
            return
        ordered_ids: List[str] = []
        for spec in specs:
            ordered_ids.append(spec.model_id)
            if spec.model_id not in self._services:
                self._services[spec.model_id] = self._make_service(spec)
            else:
                self._services[spec.model_id].model_name = spec.name
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
            service = PolarMicrogridSimulator(
                sim_dir=target_dir,
                runtime_dir=self.runtime_dir / target_id,
                kernel=self.kernel,
                period_seconds=self.period_seconds,
                compute_interval_seconds=self.compute_interval_seconds,
                noise_std=self.noise_std,
                random_seed=self.random_seed,
                model_id=target_id,
                model_name=target_id,
            )
            with source.lock:
                service.command_history = [
                    json.loads(json.dumps(item, ensure_ascii=False, default=str)) for item in source.command_history[-200:]
                ]
                service._write_command_history()
                service.latest_result = json.loads(json.dumps(source.latest_result, ensure_ascii=False, default=str))
                service.latest_measurements = json.loads(
                    json.dumps(source.latest_measurements, ensure_ascii=False, default=str)
                )
            self._services[target_id] = service
            self._append_manifest_model(target_id, target_dir)
            return service.model_info()

    def delete_model(self, model_id: Any) -> Dict[str, Any]:
        target_id = _safe_model_id(model_id)
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked()
            service = self._services.get(target_id)
            if service is None:
                raise KeyError(f"Unknown simulation model: {model_id}")
            if len(self._services) <= 1:
                raise ValueError("至少需要保留一个模型")
            if service.clock.state != "stopped":
                raise ValueError(f"模型正在运行中，无法删除: {target_id}")

            source_dir = Path(service.sim_dir).resolve()
            runtime_dir = Path(service.runtime_dir).resolve()
            models_root = self.models_root.resolve()
            runtime_root = self.runtime_dir.resolve()
            try:
                source_dir.relative_to(models_root)
                runtime_dir.relative_to(runtime_root)
            except ValueError as exc:
                raise ValueError(f"模型目录无效，无法删除: {target_id}") from exc

            removed = service.model_info()
            self._services.pop(target_id, None)
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
                self._sync_models_from_directory_locked()
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
        if service is None:
            raise KeyError(f"Unknown simulation model: {model_id}")
        return service

    def iter_services(self) -> List[PolarMicrogridSimulator]:
        with self.lock:
            return list(self._services.values())

    def models(self) -> List[Dict[str, Any]]:
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked()
            return [service.model_info() for service in self._services.values()]

    def snapshot(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).snapshot()

    def measurements(self, model_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        return self.service_for(model_id).measurements()

    def devices(self, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.service_for(model_id).devices()

    def apply_student_commands(self, payload: Mapping[str, Any], source: str = "", model_id: Optional[str] = None) -> Dict[str, int]:
        return self.service_for(model_id).apply_student_commands(payload, source=source)

    def control_clock(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).control_clock(payload)

    def step(self, model_id: Optional[str] = None, advance_minutes: Optional[int] = None) -> Dict[str, Any]:
        return self.service_for(model_id).step(advance_minutes=advance_minutes)

    def set_curves(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).set_curves(payload)

    def set_local_settings(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, int]:
        return self.service_for(model_id).set_local_settings(payload)
