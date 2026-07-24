"""Service layer for the polar microgrid time-series simulation system.

The service deliberately keeps the web/API layer thin.  It owns the runtime
copies of the E files, projects curve/settings/trainee-command overlays into
those files, calls the existing load-flow kernel, and exposes JSON snapshots
that both the simulator console and trainee console can poll.
"""

from __future__ import annotations

import json
import math
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

STAT_HEADERS = {
    "RunStat": ("dev_type", "dev_name", "run_stat"),
    "CbOpenStat": ("dev_type", "dev_name", "status"),
    "SetValue": ("dev_type", "dev_name", "set_type", "set_value"),
    "StorageSoc": ("dev_type", "idx", "name", "soc_curr"),
}

INPUT_FILES = ("model.e", "meas.e", "stat.e", "weather.e", "device.e", "yt_ctrl.e")
CLONE_FILES = INPUT_FILES + ("real.e", "scada.e", "curves.json", "local_settings.json", "commands.json")
CLOCK_SPEED_LEVELS = (1.0, 5.0, 15.0, 30.0, 60.0)
DEFAULT_CONTROL_VALID_MINUTES = 5.0


@dataclass
class ClockState:
    state: str = "stopped"
    minute: int = 0
    absolute_minute: int = 0
    speed: float = 1.0
    step_minutes: int = 1
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "minute": self.minute,
            "absolute_minute": self.absolute_minute,
            "speed": self.speed,
            "step_minutes": self.step_minutes,
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


def _active_window(item: Mapping[str, Any], minute: int) -> bool:
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
        self.noise_std = noise_std
        self.random_seed = random_seed
        self.clock = ClockState()
        self.lock = threading.RLock()
        self.command_history: List[Dict[str, Any]] = []
        self.runtime_logs: List[Dict[str, Any]] = []
        self._runtime_log_seq = 0
        self._last_command_response_index = 0
        self.latest_result: Dict[str, Any] = {}
        self.latest_measurements: Dict[str, Any] = {"real": [], "scada": []}
        self._fault_restore: Dict[Tuple[str, str, str], str] = {}
        self._last_scada_values: Dict[str, float] = {}

        self.files = {
            "model": self.runtime_dir / "model.e",
            "meas": self.runtime_dir / "meas.e",
            "stat": self.runtime_dir / "stat.e",
            "weather": self.runtime_dir / "weather.e",
            "device": self.runtime_dir / "device.e",
            "yt_ctrl": self.runtime_dir / "yt_ctrl.e",
            "real": self.runtime_dir / "real.e",
            "scada": self.runtime_dir / "scada.e",
        }
        self.curves_file = self.runtime_dir / "curves.json"
        self.settings_file = self.runtime_dir / "local_settings.json"
        self.commands_file = self.runtime_dir / "commands.json"

        self._copy_runtime_inputs()
        self.weather_defaults = self._read_weather_defaults()
        self.curves = _read_json(self.curves_file, {"mode": "day", "time_step_minutes": 1, "weather": [], "loads": {}})
        self.local_settings = _read_json(
            self.settings_file,
            {"device_faults": [], "measurement_faults": [], "modes": []},
        )
        self.command_history = self._read_command_history()
        self._last_command_response_index = len(self.command_history)
        self._ensure_stat_file()

    def _copy_runtime_inputs(self) -> None:
        for name in CLONE_FILES:
            source = self.sim_dir / name
            target = self.runtime_dir / name
            if source.exists():
                shutil.copy2(source, target)
        if not self.files["weather"].exists():
            self._write_weather_row(DEFAULT_WEATHER | {"time": minute_to_time(0)})

    def _read_command_history(self) -> List[Dict[str, Any]]:
        items = _read_json(self.commands_file, [])
        if not isinstance(items, list):
            return []
        return [item for item in items[-200:] if isinstance(item, dict)]

    def _write_command_history(self) -> None:
        _write_json(self.commands_file, self.command_history[-200:])

    def clone_files_to(self, target_dir: Path) -> None:
        with self.lock:
            _write_json(self.curves_file, self.curves)
            _write_json(self.settings_file, self.local_settings)
            self._write_command_history()
            target_dir.mkdir(parents=True, exist_ok=False)
            for name in CLONE_FILES:
                source = self.runtime_dir / name
                if not source.exists():
                    source = self.sim_dir / name
                if source.exists():
                    shutil.copy2(source, target_dir / name)

    def _read_weather_defaults(self) -> Dict[str, float]:
        values = dict(DEFAULT_WEATHER)
        path = self.files["weather"]
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

    def _ensure_stat_file(self) -> None:
        book = _load_book(self.files["stat"])
        changed = False
        for name, headers in STAT_HEADERS.items():
            if name not in book.data:
                changed = True
            _ensure_block(book, name, headers)
        if changed or not self.files["stat"].exists():
            simu_loop.write_ebook_aligned(book, self.files["stat"])

    def _base_stat_book_for_controls(self) -> EBook:
        source_stat = self.sim_dir / "stat.e"
        book = _load_book(source_stat if source_stat.exists() else self.files["stat"])
        for name, headers in STAT_HEADERS.items():
            _ensure_block(book, name, headers)

        runtime_book = _load_book(self.files["stat"])
        runtime_storage = runtime_book.data.get("StorageSoc") or runtime_book.data.get("StorageStatus")
        if runtime_storage is not None:
            storage_block = _ensure_block(book, "StorageSoc", STAT_HEADERS["StorageSoc"])
            storage_block.data = [
                {header: row.get(header, "") for header in storage_block.header_list}
                for row in runtime_storage.data
            ]
        return book

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

    def _active_control_command_entries(self, absolute_minute: int | float) -> List[Mapping[str, Any]]:
        current = float(absolute_minute)
        active: List[Mapping[str, Any]] = []
        for item in self.command_history:
            if not isinstance(item, Mapping) or not item.get("eligible_source"):
                continue
            accepted = item.get("accepted", {})
            if not isinstance(accepted, Mapping):
                continue
            if int(_to_float(accepted.get("run_status"), 0) or 0) + int(_to_float(accepted.get("set_values"), 0) or 0) <= 0:
                continue
            issued = _to_float(item.get("issued_absolute_minute"), None)
            expires = _to_float(item.get("expires_at_absolute_minute"), None)
            if issued is None or expires is None:
                continue
            if issued <= current < expires:
                active.append(item)
        return active

    def _materialize_active_control_commands(self, absolute_minute: int | float) -> Dict[str, int]:
        book = self._base_stat_book_for_controls()
        run_block = _ensure_block(book, "RunStat", STAT_HEADERS["RunStat"])
        cb_block = _ensure_block(book, "CbOpenStat", STAT_HEADERS["CbOpenStat"])
        set_block = _ensure_block(book, "SetValue", STAT_HEADERS["SetValue"])
        active_entries = self._active_control_command_entries(absolute_minute)
        applied_run = 0
        applied_set = 0

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

        simu_loop.write_ebook_aligned(book, self.files["stat"])
        return {"active_commands": len(active_entries), "run_status": applied_run, "set_values": applied_set}

    def _make_config(self, period_seconds: Optional[float] = None) -> simu_loop.SimulationConfig:
        return simu_loop.SimulationConfig(
            model_file=self.files["model"],
            meas_file=self.files["meas"],
            weather_file=self.files["weather"],
            dev_stat_file=self.files["stat"],
            dev_define_file=self.files["device"],
            yt_ctrl_file=self.files["yt_ctrl"],
            real_file=self.files["real"],
            scada_file=self.files["scada"],
            period_seconds=self.period_seconds if period_seconds is None else period_seconds,
            noise_std=self.noise_std,
            random_seed=self.random_seed,
            loop_count=1,
            log_file=None,
            step_mode=True,
        )

    def _append_runtime_log(
        self,
        log_type: str,
        target: str,
        result: str,
        detail: Any = "",
        *,
        level: str = "info",
        sim_time: Optional[str] = None,
    ) -> None:
        self._runtime_log_seq += 1
        self.runtime_logs.append(
            {
                "seq": self._runtime_log_seq,
                "wall_time": _now_text(),
                "sim_time": sim_time or minute_to_time(self.clock.minute),
                "type": log_type,
                "target": target,
                "result": result,
                "detail": detail,
                "level": level,
            }
        )
        self.runtime_logs = self.runtime_logs[-500:]

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
            lines.append("已登记为有效控制指令，并已按当前有效期物化到 stat.e，等待下一轮潮流计算响应")
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
        detail.append("本轮 real.e 与 scada.e 已刷新")
        return detail

    def _collect_command_response_lines(self, result: Mapping[str, Any]) -> List[str]:
        if self._last_command_response_index >= len(self.command_history):
            active = self._active_control_command_entries(self.clock.absolute_minute)
            return [
                f"控制响应 本轮无新增学员台控制指令；当前有效控制指令 {len(active)} 条，按有效期物化后的 stat.e / yt_ctrl.e 输入边界开展潮流计算"
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
            "已写入 weather.e，并作为本轮负荷、新能源限值计算输入",
        ]
        self._append_runtime_log(
            "环境/负荷",
            "weather.e / curves.json",
            "逐点读取",
            detail,
            level="ok" if load_seen else "warn",
            sim_time=minute_to_time(minute),
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
        try:
            book = _load_book(self.files["weather"])
        except Exception:
            return values
        block = book.data.get("Weather")
        if block is None or not block.data:
            return values
        row = block.data[0]
        return {header: row.get(header, "") for header in block.header_list}

    def _input_boundary_lines(
        self,
        minute: int,
        absolute_minute: int,
        clock_advance: int,
        period_seconds: float,
    ) -> List[str]:
        weather = self._weather_boundary_values()
        stat_book = _load_book(self.files["stat"])
        run_rows = list(getattr(stat_book.data.get("RunStat"), "data", []))
        cb_rows = list(getattr(stat_book.data.get("CbOpenStat"), "data", []))
        set_rows = list(getattr(stat_book.data.get("SetValue"), "data", []))
        soc_block = stat_book.data.get("StorageSoc") or stat_book.data.get("StorageStatus")
        soc_rows = list(getattr(soc_block, "data", []))

        run_off = [
            f"{row.get('dev_type', '')}.{_dev_name(row)}={_number_text(row.get('run_stat', ''))}"
            for row in run_rows
            if int(_to_float(row.get("run_stat"), 1) or 0) == 0
        ]
        cb_zero = [
            f"{row.get('dev_type', '')}.{_dev_name(row)}={_number_text(row.get('status', ''))}"
            for row in cb_rows
            if int(_to_float(row.get("status"), 1) or 0) == 0
        ]
        set_values = [
            f"{row.get('dev_type', '')}.{_dev_name(row)}.{row.get('set_type', '')}={_number_text(row.get('set_value', ''))}"
            for row in set_rows
        ]
        soc_values = [
            f"{row.get('dev_type', 'ESS')}.{row.get('name', row.get('dev_name', ''))}={_number_text(row.get('soc_curr', row.get('soc', '')))}"
            for row in soc_rows
        ]
        run_on = len(run_rows) - len(run_off)
        cb_one = len(cb_rows) - len(cb_zero)
        weather_text = "，".join(
            f"{key}={weather.get(key, '')}"
            for key in WEATHER_HEADER
            if key in weather
        ) or "未读取到 Weather 块"
        return [
            (
                "输入文件 "
                f"model={self.files['model'].name}，meas={self.files['meas'].name}，stat={self.files['stat'].name}，"
                f"weather={self.files['weather'].name}，device={self.files['device'].name}，yt_ctrl={self.files['yt_ctrl'].name}"
            ),
            (
                f"仿真边界 时刻 {minute_to_time(minute)}，日内分钟 {minute}，累计分钟 {absolute_minute}，"
                f"本步推进 {clock_advance} min，等效计算周期 {format_number(period_seconds)} s"
            ),
            f"天气/负荷边界 {weather_text}",
            f"RunStat 投入 {run_on}/{len(run_rows)}，退出 {len(run_off)}：{self._short_list(run_off)}",
            f"CbOpenStat status=1 {cb_one}/{len(cb_rows)}，status=0 {len(cb_zero)}：{self._short_list(cb_zero)}",
            f"SetValue {len(set_rows)} 条：{self._short_list(set_values, 36)}",
            f"StorageSoc {len(soc_rows)} 条：{self._short_list(soc_values, 36)}",
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
        try:
            book = _load_book(self.files["device"])
        except Exception:
            return categories
        for category, block_names in {
            "wind": ("wind_generator",),
            "pv": ("pv_generator",),
            "diesel": ("diesel_generator",),
            "load": ("load_curve_96", "load_temperature"),
            "storage": ("estorage",),
        }.items():
            for block_name in block_names:
                block = book.data.get(block_name)
                if block is None:
                    continue
                for row in block.data:
                    name = str(row.get("name", "")).strip()
                    if not name:
                        continue
                    categories[category].add(name)
                    if category == "storage":
                        categories[category].add(f"{name}_dcdc")
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
        if dev_name in storage_names or (not storage_names and (dev_type in ("ESS", "Storage") or lower_name.startswith("ess"))):
            return "storage"
        if dev_name in wind_names or (not wind_names and lower_name.startswith(("wt", "wind"))):
            return "wind"
        if dev_name in pv_names or (not pv_names and lower_name.startswith(("pv", "solar"))):
            return "pv"
        if dev_name in diesel_names or (not diesel_names and ("diesel" in lower_name or "柴" in dev_name)):
            return "diesel"
        if dev_name in load_names or (not load_names and (dev_type.endswith("Load") or "load" in lower_name or "负荷" in dev_name)):
            return "load"
        return ""

    def _canonical_power_device_name(self, category: str, dev_name: str) -> str:
        if category == "storage" and dev_name.endswith("_dcdc"):
            return dev_name.removesuffix("_dcdc")
        return dev_name

    def _preferred_power_value(self, category: str, values: Mapping[str, float]) -> Optional[float]:
        preferences = {
            "wind": ("P_AC", "P_DC", "P_GEN", "P", "P_FROM", "P_TO"),
            "pv": ("P_TO", "P_FROM", "P_GEN", "P", "P_DC", "P_AC"),
            "diesel": ("P_GEN", "P", "P_AC", "P_TO", "P_FROM"),
            "load": ("P_LOAD", "P", "P_AC", "P_TO", "P_FROM"),
            "storage": ("P", "P_FROM", "P_TO"),
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
        detail = [
            *self._compact_command_response_lines(command_response_lines),
            (
                f"计算摘要 时刻 {minute_to_time(minute)}，累计分钟 {absolute_minute}，推进 {clock_advance} min，"
                f"求解器 {result.get('solver_info', 'not-run')}，"
                f"真值量测 {len(real_measurements)} 条，更新 {result.get('updated', 0)} 条，"
                f"缺失 {result.get('missing', 0)} 条，叠加修正 {result.get('overlay_updates', 0)} 条"
            ),
            *self._power_flow_summary_lines(real_measurements),
        ]
        self._append_runtime_log(
            "潮流计算/控制响应",
            "model.e / stat.e / weather.e / real.e",
            "完成" if int(_to_float(result.get("missing"), 0) or 0) == 0 else "有缺失",
            detail,
            level="ok" if int(_to_float(result.get("missing"), 0) or 0) == 0 else "warn",
            sim_time=minute_to_time(minute),
        )

    def apply_student_commands(self, payload: Mapping[str, Any], source: str = "") -> Dict[str, int]:
        with self.lock:
            run_items = payload.get("run_status", payload.get("runStatus", [])) or []
            set_items = payload.get("set_values", payload.get("setValues", payload.get("setpoints", []))) or []
            run_sequence = list(run_items) if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)) else []
            set_sequence = list(set_items) if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)) else []
            normalized_run_items = self._normalize_run_command_items(run_sequence)
            normalized_set_items = self._normalize_set_command_items(set_sequence)
            eligible_source = _is_trainee_command_source(source)
            issued_absolute_minute = float(self.clock.absolute_minute)
            expires_at_absolute_minute = _command_expires_at(payload, None, issued_absolute_minute)
            accepted_run = len(normalized_run_items) if eligible_source else 0
            accepted_set = len(normalized_set_items) if eligible_source else 0
            ignored = 0 if eligible_source else len(normalized_run_items) + len(normalized_set_items)
            accepted = {"run_status": accepted_run, "set_values": accepted_set, "ignored": ignored}
            command_entry = {
                "time": _now_text(),
                "source": source,
                "eligible_source": eligible_source,
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
            self._materialize_active_control_commands(self.clock.absolute_minute)
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
            if item_dev_type == "ESS" and item_dev_name:
                item = {
                    **dict(item),
                    "dev_type": "DCDCConverter",
                    "dev_name": f"{item_dev_name}_dcdc",
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
            if "step_minutes" in payload:
                self.clock.step_minutes = max(1, int(_to_float(payload.get("step_minutes"), 1) or 1))
            if "minute" in payload:
                minute = int(_to_float(payload.get("minute"), self.clock.minute) or 0)
                self.clock.absolute_minute = minute
                self.clock.minute = minute % 1440
            if "speed" in payload:
                self.clock.speed = _nearest_clock_speed(payload.get("speed"))
            if action == "start":
                self.clock.state = "running"
            elif action == "pause":
                self.clock.state = "paused"
            elif action == "stop":
                self.clock.state = "stopped"
                self.clock.absolute_minute = 0
                self.clock.minute = 0
                self.clock.speed = CLOCK_SPEED_LEVELS[0]
            elif action in ("faster", "speed_up"):
                self.clock.speed = _next_clock_speed(self.clock.speed)
            elif action in ("slower", "speed_down"):
                self.clock.speed = _previous_clock_speed(self.clock.speed)
            elif action == "step":
                return self.step()["clock"]
            self.clock.updated_at = time.time()
            return self.clock.as_dict()

    def step(self, advance_minutes: Optional[int] = None) -> Dict[str, Any]:
        with self.lock:
            step_minutes = max(1, int(self.clock.step_minutes))
            clock_advance = step_minutes if advance_minutes is None else max(1, int(advance_minutes))
            period_seconds = self.period_seconds * clock_advance / step_minutes
            minute = self.clock.minute
            absolute_minute = self.clock.absolute_minute
            self._prepare_runtime_inputs(minute, absolute_minute)
            config = self._make_config(period_seconds=period_seconds)
            kernel_result = self.kernel(config)
            self._apply_measurement_faults(minute)
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
            self.clock.updated_at = time.time()
            return self.snapshot()

    def _prepare_runtime_inputs(self, minute: int, absolute_minute: int) -> None:
        self._write_current_weather(minute, absolute_minute)
        self._materialize_active_control_commands(absolute_minute)
        self._apply_device_faults(minute)
        self._apply_modes_to_model()

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
        book = _make_book({"Weather": (WEATHER_HEADER, [clean])})
        simu_loop.write_ebook_aligned(book, self.files["weather"])

    def _apply_device_faults(self, minute: int) -> None:
        book = _load_book(self.files["stat"])
        run_block = _ensure_block(book, "RunStat", STAT_HEADERS["RunStat"])
        cb_block = _ensure_block(book, "CbOpenStat", STAT_HEADERS["CbOpenStat"])
        active_keys: set[Tuple[str, str, str]] = set()

        for fault in self.local_settings.get("device_faults", []):
            if not isinstance(fault, Mapping) or not _active_window(fault, minute):
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

        simu_loop.write_ebook_aligned(book, self.files["stat"])

    def _apply_modes_to_model(self) -> None:
        modes = self.local_settings.get("modes", [])
        if not modes or not self.files["model"].exists():
            return
        book = EBook(self.files["model"])
        changed = False
        for mode in modes:
            if not isinstance(mode, Mapping):
                continue
            dev_type = str(mode.get("dev_type", mode.get("type", "")))
            dev_name = str(mode.get("dev_name", mode.get("name", "")))
            mode_value = str(mode.get("mode", mode.get("control_type", "")))
            if not dev_type or not dev_name or not mode_value:
                continue
            block = book.data.get(dev_type)
            if block is None:
                continue
            target = None
            for row in block.data:
                if str(row.get("name", "")) == dev_name:
                    target = row
                    break
            if target is None:
                continue
            for column in ("control_type", "mode", "ctrl_mode"):
                if column in block.header_list:
                    target[column] = mode_value
                    changed = True
                    break
        if changed:
            simu_loop.write_ebook_aligned(book, self.files["model"])

    def _apply_measurement_faults(self, minute: int) -> None:
        faults = [fault for fault in self.local_settings.get("measurement_faults", []) if isinstance(fault, Mapping)]
        active_faults = [fault for fault in faults if _active_window(fault, minute)]
        if not active_faults or not self.files["scada"].exists():
            return
        before, rows, after = parse_measurement_rows(self.files["scada"])
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
            simu_loop.write_measurement_snapshot(self.files["scada"], before, rows, after)

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

    def measurements(self) -> Dict[str, List[Dict[str, Any]]]:
        definitions = self._read_measurement_file(self.files["meas"])
        real = self._read_measurement_file(self.files["real"])
        scada = self._read_measurement_file(self.files["scada"])
        for item in scada:
            self._last_scada_values[
                f"{item['name']}|{item['dev_type']}|{item['dev_name']}|{item['meas_type']}"
            ] = item.get("value", 0.0) or 0.0
        return {"definitions": definitions, "real": real, "scada": scada}

    def _read_measurement_file(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            _before, rows, _after = parse_measurement_rows(path)
        except Exception:
            return []
        return [_measurement_row_to_dict(row) for row in rows]

    def devices(self) -> List[Dict[str, Any]]:
        if not self.files["model"].exists():
            return []
        try:
            model_book = EBook(self.files["model"])
        except Exception:
            return []
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
        for name, soc in soc_values.items():
            dcdc_set_values = set_values.get(("DCDCConverter", f"{name}_dcdc"), {})
            devices.append(
                {
                    "dev_type": "ESS",
                    "dev_name": name,
                    "run_stat": int(_to_float(run_stats.get(("ESS", name), 1), 1) or 0),
                    "status": 1,
                    "mode": "PH",
                    "set_types": ["p_set", "v_set"],
                    "set_values": dcdc_set_values,
                    "soc_curr": soc,
                    "raw": {"soc_curr": soc},
                }
            )
        return devices

    def device_parameters(self) -> Dict[str, List[Dict[str, Any]]]:
        try:
            book = _load_book(self.files["device"])
        except Exception:
            return {}
        return {
            name: [
                {key: _json_scalar(value) for key, value in row.items()}
                for row in getattr(block, "data", [])
            ]
            for name, block in book.data.items()
        }

    def _stat_maps(self) -> Tuple[Dict[Tuple[str, str], Any], Dict[Tuple[str, str], Any], Dict[Tuple[str, str], dict], Dict[str, float]]:
        stat_book = _load_book(self.files["stat"])
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
        }

    def snapshot(self) -> Dict[str, Any]:
        measurements = dict(self.latest_measurements or self.measurements())
        if "definitions" not in measurements:
            measurements["definitions"] = self._read_measurement_file(self.files["meas"])
        return {
            "model": self.model_info(),
            "clock": self.clock.as_dict(),
            "files": {key: str(path) for key, path in self.files.items()},
            "curves": self.curves,
            "settings": self.local_settings,
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
            self.default_model_id = ordered_ids[0]

    def clone_model(self, source_model_id: Optional[str], new_model_id: Any) -> Dict[str, Any]:
        with self.lock:
            source = self.service_for(source_model_id)
            target_id = _safe_model_id(new_model_id)
            target_keys = {_model_key(new_model_id), _model_key(target_id)}
            existing_keys = {
                key
                for service in self._services.values()
                for key in (_model_key(service.model_id), _model_key(service.model_name))
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

            source.clone_files_to(target_dir)
            service = PolarMicrogridSimulator(
                sim_dir=target_dir,
                runtime_dir=self.runtime_dir / target_id,
                kernel=self.kernel,
                period_seconds=self.period_seconds,
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
