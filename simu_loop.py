"""Periodic load-flow based simulator for SCADA measurement snapshots."""

from __future__ import annotations

import argparse
import contextlib
import io
import logging
import math
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Sequence, Tuple


def _find_project_root() -> Path:
    for path in Path(__file__).resolve().parents:
        if (path / "pyproject.toml").exists():
            return path
        if (path / "simu").exists() and (path / "model.e").exists():
            return path
    return Path(__file__).resolve().parent


ROOT_DIR = _find_project_root()
SIMU_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = ROOT_DIR / "src" / "hybrid_power_system_analysis"
SCRIPTS_DIR = ROOT_DIR / "scripts"
if not PACKAGE_DIR.exists():
    legacy_root = ROOT_DIR.parent / "elec_power_flow" / "hybrid_power_system_analysis"
    legacy_package = legacy_root / "src" / "hybrid_power_system_analysis"
    if legacy_package.exists():
        PACKAGE_DIR = legacy_package
        SCRIPTS_DIR = legacy_root / "scripts"
for path in (PACKAGE_DIR, PACKAGE_DIR / "lfcore", PACKAGE_DIR / "model", SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from efile_read import EBook
from update_meas_from_lf import (  # noqa: E402
    ANGLE_TYPES,
    MEAS_HEADER,
    VALUE_TYPES,
    Snapshot,
    format_number,
    parse_measurement_rows,
)
from ac_lf import ACPowerFlowCalc  # noqa: E402
from ac_model import ACPowerNetwork  # noqa: E402
from hybrid_lf import HybridPowerFlowCalc, _read_lf_network_from_file  # noqa: E402


DEFAULT_MODEL_FILE = SIMU_DIR / "model.e"
DEFAULT_MEAS_FILE = SIMU_DIR / "meas.e"
DEFAULT_WEATHER_FILE = SIMU_DIR / "weather.e"
DEFAULT_DEV_STAT_FILE = SIMU_DIR / "stat.e"
DEFAULT_DEV_DEFINE_FILE = SIMU_DIR / "device.e"
DEFAULT_YT_CTRL_FILE = SIMU_DIR / "yt_ctrl.e"
DEFAULT_REAL_FILE = SIMU_DIR / "real.e"
DEFAULT_SCADA_FILE = SIMU_DIR / "scada.e"
DEFAULT_LOG_DIR = ROOT_DIR / "log"
DEFAULT_PERIOD_SECONDS = 60.0
DEFAULT_STORAGE_CAPACITY_KWH = 50.0


@dataclass(frozen=True)
class SimulationConfig:
    model_file: Path
    meas_file: Path
    weather_file: Path
    dev_stat_file: Path
    real_file: Path
    scada_file: Path
    yt_ctrl_file: Path = DEFAULT_YT_CTRL_FILE
    dev_define_file: Path = DEFAULT_DEV_DEFINE_FILE
    period_seconds: float = DEFAULT_PERIOD_SECONDS
    noise_std: Optional[float] = None
    random_seed: Optional[int] = None
    loop_count: Optional[int] = None
    log_file: Optional[Path] = None
    step_mode: bool = False


@dataclass(frozen=True)
class SimulationResult:
    real_file: Path
    scada_file: Path
    updated: int
    missing: int
    overlay_updates: int
    solver_info: str


def default_config() -> SimulationConfig:
    return SimulationConfig(
        model_file=DEFAULT_MODEL_FILE,
        meas_file=DEFAULT_MEAS_FILE,
        weather_file=DEFAULT_WEATHER_FILE,
        dev_stat_file=DEFAULT_DEV_STAT_FILE,
        yt_ctrl_file=DEFAULT_YT_CTRL_FILE,
        dev_define_file=DEFAULT_DEV_DEFINE_FILE,
        real_file=DEFAULT_REAL_FILE,
        scada_file=DEFAULT_SCADA_FILE,
        log_file=_default_log_file(),
        step_mode=False,
    )


def _default_log_file() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_LOG_DIR / f"simu_loop_{timestamp}.log"


def setup_logger(log_file: Path) -> logging.Logger:
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("SimulationLoop")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def write_ebook_aligned(book: EBook, file_path: Path) -> None:
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    for block in book.data.values():
        header = list(block.header_list)
        widths = [len(name) for name in header]
        for row in block.data:
            for idx, name in enumerate(header):
                widths[idx] = max(widths[idx], len(str(row.get(name, ""))))
        parts.append(f"<{block.name}>\n")
        parts.append("@ " + "  ".join(f"{header[idx]:<{widths[idx]}}" for idx in range(len(header))).rstrip() + "\n")
        for row in block.data:
            parts.append("# " + "  ".join(f"{str(row.get(name, '')):<{widths[idx]}}" for idx, name in enumerate(header)).rstrip() + "\n")
        parts.append(f"</{block.name}>\n")
    file_path.write_text("".join(parts), encoding="utf-8")


def _row_key(row) -> Tuple[Optional[str], Optional[str]]:
    name = row.get("name")
    idx = row.get("idx")
    return (None if name in (None, "") else str(name), None if idx in (None, "") else str(idx))


def _find_target_row(rows, overlay_row):
    name, idx = _row_key(overlay_row)
    if name is not None:
        for row in rows:
            if str(row.get("name", "")) == name:
                return row
    if idx is not None:
        for row in rows:
            if str(row.get("idx", "")) == idx:
                return row
    return None


def apply_overlay_file(model_book: EBook, overlay_file: Path) -> int:
    """Apply matching rows from weather/dev-control E files onto a model book.

    A block is applied only when the model has the same block name.  Rows match
    by ``name`` first, then by ``idx``.  Only columns already present in the
    model block are overwritten, so auxiliary weather blocks can coexist with
    the simulator without breaking the base network model.
    """
    overlay_file = Path(overlay_file)
    if not overlay_file.exists():
        return 0

    overlay_book = EBook(overlay_file)
    changed = 0
    for table_name, overlay_block in overlay_book.data.items():
        model_block = model_book.data.get(table_name)
        if model_block is None:
            continue
        writable_columns = set(model_block.header_list) - {"idx", "name"}
        if not writable_columns:
            continue
        for overlay_row in overlay_block.data:
            target_row = _find_target_row(model_block.data, overlay_row)
            if target_row is None:
                continue
            for column in overlay_block.header_list:
                if column not in writable_columns:
                    continue
                new_value = overlay_row[column]
                if str(target_row.get(column, "")) != str(new_value):
                    target_row[column] = new_value
                    changed += 1
    return changed


def _rows_by_name(block) -> Dict[str, dict]:
    return {str(row.get("name", "")): row for row in block.data}


def _set_row_value(row: dict, column: str, value) -> int:
    if column not in row:
        return 0
    text = str(value)
    if str(row.get(column, "")) == text:
        return 0
    row[column] = text
    return 1


def _safe_float(value, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    if upper < lower:
        lower, upper = upper, lower
    return max(lower, min(upper, value))


def _is_running_row(row: dict) -> bool:
    return _safe_int(row.get("run_stat", 1), 1) == 1


def _read_optional_book(file_path: Optional[Path]) -> EBook:
    if file_path is None:
        return EBook({})
    path = Path(file_path)
    return EBook(path) if path.exists() else EBook({})


def _book_rows(book: EBook, table_name: str) -> List[dict]:
    block = book.data.get(table_name)
    return [] if block is None else list(block.data)


def _storage_soc_block(book: EBook):
    return book.data.get("StorageSoc") or book.data.get("StorageStatus")


def _storage_soc_rows(book: EBook) -> List[dict]:
    block = _storage_soc_block(book)
    return [] if block is None else list(block.data)


def _row_order_key(row: dict) -> Tuple[int, str]:
    for key in ("idx", "id"):
        if row.get(key, "") != "":
            return (_safe_int(row.get(key), 0), str(row.get("name", "")))
    return (0, str(row.get("name", "")))


def _sorted_rows(rows: Sequence[dict]) -> List[dict]:
    return sorted(rows, key=_row_order_key)


def _define_row_by_position(dev_define: EBook, table_name: str, pos: int) -> Optional[dict]:
    rows = _sorted_rows(_book_rows(dev_define, table_name))
    if 0 <= pos < len(rows):
        return rows[pos]
    return None


def _define_row_by_name_or_position(dev_define: EBook, table_name: str, name: str, pos: int) -> Optional[dict]:
    rows = _sorted_rows(_book_rows(dev_define, table_name))
    for row in rows:
        if str(row.get("name", "")) == str(name):
            return row
    if 0 <= pos < len(rows):
        return rows[pos]
    return None


def _format_power(value: float) -> str:
    return format_number(float(value))


def _model_row(model_book: EBook, dev_type: str, name: str) -> Optional[dict]:
    block = model_book.data.get(dev_type)
    if block is None:
        return None
    return _rows_by_name(block).get(str(name))


def _stat_dev_name(row: dict) -> str:
    return str(row.get("dev_name", row.get("name", "")))


def _apply_setpoint_row(model_book: EBook, row: dict) -> int:
    dev_type = str(row.get("dev_type", ""))
    target = _model_row(model_book, dev_type, _stat_dev_name(row))
    if target is None:
        return 0
    changed = 0
    if dev_type == "DCACConverter":
        mapping = {"p_set": "p_ac_set", "q_set": "q_ac_set", "v_set": "v_ac_set"}
    else:
        mapping = {"p_set": "p_set", "q_set": "q_set", "v_set": "v_set"}
    for src, dst in mapping.items():
        value = row.get(src, "")
        if value != "":
            changed += _set_row_value(target, dst, value)
    if row.get("run_stat", "") != "":
        changed += _set_row_value(target, "run_stat", row["run_stat"])
    return changed


def _set_value_target_column(dev_type: str, set_type: str) -> str:
    if dev_type == "DCACConverter":
        return {
            "p_set": "p_ac_set",
            "q_set": "q_ac_set",
            "v_set": "v_ac_set",
            "p_ac_set": "p_ac_set",
            "q_ac_set": "q_ac_set",
            "v_ac_set": "v_ac_set",
        }.get(set_type, set_type)
    if dev_type == "ACLoad":
        return {"p_set": "pv0", "q_set": "qv0", "pv0": "pv0", "qv0": "qv0"}.get(set_type, set_type)
    return set_type


def _apply_set_value_row(model_book: EBook, row: dict) -> int:
    dev_type = str(row.get("dev_type", ""))
    target = _model_row(model_book, dev_type, _stat_dev_name(row))
    if target is None:
        return 0
    set_type = str(row.get("set_type", ""))
    if set_type == "":
        return 0
    value = row.get("set_value", "")
    if value == "":
        return 0
    return _set_row_value(target, _set_value_target_column(dev_type, set_type), value)


def _run_stat_by_name(stat_book: EBook) -> Dict[Tuple[str, str], str]:
    block = stat_book.data.get("RunStat")
    if block is None:
        return {}
    rows = {}
    for row in block.data:
        rows[(str(row.get("dev_type", "")), _stat_dev_name(row))] = str(row.get("run_stat", ""))
    return rows


def apply_dev_stat_file(model_book: EBook, dev_stat_file: Path) -> int:
    dev_stat_file = Path(dev_stat_file)
    if not dev_stat_file.exists():
        return 0
    stat_book = EBook(dev_stat_file)
    run_stats = _run_stat_by_name(stat_book)
    changed = 0

    block = stat_book.data.get("RunStat")
    if block is not None:
        for row in block.data:
            target = _model_row(model_book, row.get("dev_type", ""), _stat_dev_name(row))
            if target is not None and row.get("run_stat", "") != "":
                changed += _set_row_value(target, "run_stat", row.get("run_stat", ""))

    block = stat_book.data.get("DeviceRunStatus")
    if block is not None:
        for row in block.data:
            target = _model_row(model_book, row.get("dev_type", ""), _stat_dev_name(row))
            if target is not None and row.get("run_stat", "") != "":
                changed += _set_row_value(target, "run_stat", row.get("run_stat", ""))

    for table_name in ("CbOpenStat", "SwitchBreakerStatus"):
        block = stat_book.data.get(table_name)
        if block is not None:
            for row in block.data:
                target = _model_row(model_book, row.get("dev_type", ""), _stat_dev_name(row))
                if target is not None:
                    if row.get("run_stat", "") != "":
                        changed += _set_row_value(target, "run_stat", row.get("run_stat", ""))
                    if row.get("status", "") != "":
                        changed += _set_row_value(target, "status", row.get("status", ""))

    block = stat_book.data.get("SetValue")
    if block is not None:
        for row in block.data:
            changed += _apply_set_value_row(model_book, row)

    block = stat_book.data.get("GeneratorSetpoint")
    if block is not None:
        for row in block.data:
            changed += _apply_setpoint_row(model_book, row)

    block = stat_book.data.get("ConverterSetpoint")
    if block is not None:
        for row in block.data:
            changed += _apply_setpoint_row(model_book, row)

    block = stat_book.data.get("LoadSetpoint")
    if block is not None:
        for row in block.data:
            target = _model_row(model_book, row.get("dev_type", ""), _stat_dev_name(row))
            if target is None:
                continue
            if row.get("run_stat", "") != "":
                changed += _set_row_value(target, "run_stat", row.get("run_stat", ""))
            if str(row.get("dev_type", "")) == "ACLoad":
                if row.get("p_set", "") != "":
                    changed += _set_row_value(target, "pv0", row.get("p_set", ""))
                if row.get("q_set", "") != "":
                    changed += _set_row_value(target, "qv0", row.get("q_set", ""))
            else:
                if row.get("p_set", "") != "":
                    changed += _set_row_value(target, "p_set", row.get("p_set", ""))
                if row.get("q_set", "") != "":
                    changed += _set_row_value(target, "q_set", row.get("q_set", ""))

    block = _storage_soc_block(stat_book)
    if block is not None:
        for row in block.data:
            storage_name = str(row.get("name", row.get("dev_name", "")))
            target = _model_row(model_book, "DCDCConverter", f"{storage_name}_dcdc")
            if target is not None:
                run_stat = row.get("run_stat", "")
                if run_stat == "":
                    run_stat = run_stats.get(("ESS", storage_name), run_stats.get(("DCDCConverter", f"{storage_name}_dcdc"), ""))
                if run_stat != "":
                    changed += _set_row_value(target, "run_stat", run_stat)
    return changed


def _weather_values(weather_file: Path) -> Dict[str, float]:
    weather_file = Path(weather_file)
    if not weather_file.exists():
        return {}
    book = EBook(weather_file)
    block = book.data.get("Weather")
    if block is None or not block.data:
        return {}
    row = block.data[0]
    if "name" in block.header_list and "value" in block.header_list:
        raw = {str(item.get("name")): item.get("value") for item in block.data}
    else:
        raw = row
    values = {}
    for key in ("wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c", "load_kw"):
        try:
            values[key] = float(raw[key])
        except (KeyError, TypeError, ValueError):
            pass
    if "time" in raw:
        time_minutes = _time_minutes(raw.get("time"))
        if time_minutes is not None:
            values["time_minutes"] = time_minutes
    return values


def _time_minutes(value) -> Optional[float]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if ":" in text:
        parts = text.split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            second = float(parts[2]) if len(parts) > 2 else 0.0
        except (TypeError, ValueError):
            return None
        return (hour % 24) * 60.0 + minute + second / 60.0
    try:
        numeric = float(text)
    except (TypeError, ValueError):
        return None
    return numeric % 1440.0


def _wind_power_kw(speed: float, rated_power: float = 10.0) -> float:
    return wind_available_power(speed, rated_power=rated_power)


def wind_available_power(
    speed: float,
    rated_power: float = 10.0,
    rated_wind_speed: float = 15.0,
    cut_in_speed: float = 5.0,
    cut_out_speed: float = 30.0,
) -> float:
    speed = max(0.0, float(speed))
    rated_power = max(0.0, float(rated_power))
    rated_wind_speed = max(float(rated_wind_speed), float(cut_in_speed) + 1e-9)
    if speed < cut_in_speed or speed >= cut_out_speed:
        return 0.0
    if speed >= rated_wind_speed:
        return rated_power
    return rated_power * ((speed - cut_in_speed) / (rated_wind_speed - cut_in_speed)) ** 3


def pv_available_power(
    irradiance: float,
    air_temp: float,
    rated_power: float,
    temp_coefficient: float = 0.0,
    reference_irradiance: float = 1000.0,
    reference_temperature: float = 25.0,
) -> float:
    irradiance = max(0.0, float(irradiance))
    reference_irradiance = max(float(reference_irradiance), 1e-9)
    raw = float(rated_power) * irradiance / reference_irradiance
    raw *= 1.0 + float(temp_coefficient) * (float(air_temp) - float(reference_temperature))
    return max(0.0, raw)


def _load_power(row: dict) -> Tuple[float, float, float, float]:
    pbase = _safe_float(row.get("pbase", 1.0), 1.0) or 1.0
    qbase = _safe_float(row.get("qbase", 1.0), 1.0) or 1.0
    p = pbase * (_safe_float(row.get("pv0", 0.0), 0.0) or 0.0)
    q = qbase * (_safe_float(row.get("qv0", 0.0), 0.0) or 0.0)
    return p, q, pbase, qbase


def _load_curve_column_names(point: int) -> Tuple[str, ...]:
    minute = (point - 1) * 15
    hour = minute // 60
    minute_in_hour = minute % 60
    return (
        f"p{point:03d}",
        f"p{point}",
        f"t{point:03d}",
        f"t{hour:02d}{minute_in_hour:02d}",
        f"p{hour:02d}{minute_in_hour:02d}",
    )


def _load_curve_factor(dev_define: EBook, load_name: str, pos: int, weather: Dict[str, float]) -> float:
    row = _define_row_by_name_or_position(dev_define, "load_curve_96", load_name, pos)
    if row is None:
        return 1.0
    if "time_minutes" not in weather:
        return 1.0
    point = int(float(weather["time_minutes"]) // 15.0) % 96 + 1
    for column in _load_curve_column_names(point):
        if column in row:
            return max(0.0, _safe_float(row.get(column), 1.0) or 0.0)
    return 1.0


def _load_temperature_row(dev_define: EBook, load_name: str, pos: int) -> Optional[dict]:
    row = _define_row_by_name_or_position(dev_define, "load_temperature", load_name, pos)
    if row is not None:
        return row
    return _define_row_by_name_or_position(dev_define, "energyconsumer", load_name, pos)


def apply_load_model(model_book: EBook, dev_define: EBook, weather: Dict[str, float]) -> int:
    block = model_book.data.get("ACLoad")
    if block is None or not block.data:
        return 0
    if "load_kw" not in weather and "air_temp_c" not in weather and "time_minutes" not in weather:
        return 0

    weighted = []
    total_p = 0.0
    for pos, row in enumerate(_sorted_rows(block.data)):
        p, q, pbase, qbase = _load_power(row)
        load_name = str(row.get("name", ""))
        curve_scale = _load_curve_factor(dev_define, load_name, pos, weather)
        define = _load_temperature_row(dev_define, load_name, pos)
        temp_scale = 1.0
        if define is not None and "air_temp_c" in weather:
            temp_base = _safe_float(define.get("temp_base", weather["air_temp_c"]), weather["air_temp_c"]) or weather["air_temp_c"]
            temp_factor = _safe_float(define.get("temp_factor", 0.0), 0.0) or 0.0
            temp_scale = max(0.0, 1.0 + temp_factor * (weather["air_temp_c"] - temp_base))
        p *= curve_scale
        q *= curve_scale
        p *= temp_scale
        q *= temp_scale
        weighted.append((row, p, q, pbase, qbase))
        total_p += p

    if total_p <= 0.0:
        return 0
    target_total = weather.get("load_kw", total_p)
    scale = target_total / total_p
    changed = 0
    for row, p, q, pbase, qbase in weighted:
        changed += _set_row_value(row, "pv0", _format_power(p * scale / pbase))
        changed += _set_row_value(row, "qv0", _format_power(q * scale / qbase))
    return changed


def _target_rows(model_book: EBook, table_name: str, prefix: Optional[str] = None, contains: Optional[str] = None) -> List[dict]:
    block = model_book.data.get(table_name)
    if block is None:
        return []
    rows = []
    for row in block.data:
        name = str(row.get("name", ""))
        lower_name = name.lower()
        if prefix is not None and not lower_name.startswith(prefix.lower()):
            continue
        if contains is not None and contains.lower() not in lower_name:
            continue
        rows.append(row)
    return _sorted_rows(rows)


def _available_with_bounds(raw_available: float, define: Optional[dict]) -> float:
    if define is None:
        return max(0.0, raw_available)
    p_min = _safe_float(define.get("p_min", 0.0), 0.0) or 0.0
    p_max = _safe_float(define.get("p_max", raw_available), raw_available) or raw_available
    if raw_available <= 0.0:
        return 0.0
    return _clamp(raw_available, p_min, p_max)


def _limit_positive_setpoint(row: dict, column: str, available: float) -> int:
    if not _is_running_row(row):
        return _set_row_value(row, column, "0")
    command = _safe_float(row.get(column, 0.0), 0.0) or 0.0
    return _set_row_value(row, column, _format_power(_clamp(command, 0.0, available)))


def apply_wind_limits(model_book: EBook, dev_define: EBook, weather: Dict[str, float]) -> int:
    if "wind_speed_mps" not in weather:
        return 0
    rows = _target_rows(model_book, "DCACConverter", prefix="wt")
    if not rows:
        rows = _target_rows(model_book, "ACGenerator", prefix="wt")
    changed = 0
    for pos, row in enumerate(rows):
        define = _define_row_by_position(dev_define, "wind_generator", pos)
        rated = _safe_float((define or {}).get("rated_power", (define or {}).get("p_max", 10.0)), 10.0) or 10.0
        rated_speed = _safe_float((define or {}).get("rated_wind_speed", 15.0), 15.0) or 15.0
        cut_in = _safe_float((define or {}).get("cut_in_speed", 5.0), 5.0) or 5.0
        cut_out = _safe_float((define or {}).get("cut_out_speed", 30.0), 30.0) or 30.0
        available = _available_with_bounds(wind_available_power(weather["wind_speed_mps"], rated, rated_speed, cut_in, cut_out), define)
        column = "p_ac_set" if "p_ac_set" in row else "p_set"
        changed += _limit_positive_setpoint(row, column, available)
    return changed


def apply_pv_limits(model_book: EBook, dev_define: EBook, weather: Dict[str, float]) -> int:
    if "solar_irradiance_w_m2" not in weather:
        return 0
    rows = _target_rows(model_book, "DCDCConverter", prefix="pv")
    if not rows:
        rows = _target_rows(model_book, "DCGenerator", prefix="pv")
    changed = 0
    air_temp = weather.get("air_temp_c", 25.0)
    for pos, row in enumerate(rows):
        define = _define_row_by_position(dev_define, "pv_generator", pos)
        rated = _safe_float((define or {}).get("rated_power", (define or {}).get("p_max", row.get("p_set", 0.0))), 0.0) or 0.0
        temp_coef = _safe_float((define or {}).get("temp_coefficient", 0.0), 0.0) or 0.0
        ref_irrad = _safe_float((define or {}).get("reference_irradiance", 1000.0), 1000.0) or 1000.0
        ref_temp = _safe_float((define or {}).get("reference_temperature", 25.0), 25.0) or 25.0
        available = _available_with_bounds(
            pv_available_power(weather["solar_irradiance_w_m2"], air_temp, rated, temp_coef, ref_irrad, ref_temp),
            define,
        )
        changed += _limit_positive_setpoint(row, "p_set", available)
    return changed


def apply_diesel_limits(model_book: EBook, dev_define: EBook) -> int:
    rows = _target_rows(model_book, "ACGenerator", contains="diesel")
    changed = 0
    for pos, row in enumerate(rows):
        define = _define_row_by_position(dev_define, "diesel_generator", pos)
        if not _is_running_row(row):
            changed += _set_row_value(row, "p_set", "0")
            continue
        command = _safe_float(row.get("p_set", 0.0), 0.0) or 0.0
        if command <= 0.0:
            target = 0.0
        else:
            p_min = _safe_float((define or {}).get("p_min", 0.0), 0.0) or 0.0
            p_max = _safe_float((define or {}).get("p_max", command), command) or command
            target = _clamp(command, p_min, p_max)
        changed += _set_row_value(row, "p_set", _format_power(target))
    return changed


def _storage_soc_by_name(dev_stat_file: Path) -> Tuple[Dict[str, dict], List[dict]]:
    stat_book = _read_optional_book(dev_stat_file)
    run_stat = _run_stat_by_name(stat_book)
    rows = []
    for row in _sorted_rows(_storage_soc_rows(stat_book)):
        item = dict(row)
        storage_name = str(item.get("name", item.get("dev_name", "")))
        value = run_stat.get(("ESS", storage_name), run_stat.get(("DCDCConverter", f"{storage_name}_dcdc")))
        if value is not None and item.get("run_stat", "") == "":
            item["run_stat"] = value
        rows.append(item)
    return {str(row.get("name", "")): row for row in rows}, rows


def _storage_define_for(dev_define: EBook, storage_name: str, pos: int) -> Optional[dict]:
    rows = _sorted_rows(_book_rows(dev_define, "estorage"))
    for row in rows:
        if str(row.get("name", "")) == storage_name:
            return row
    if 0 <= pos < len(rows):
        return rows[pos]
    return None


def apply_storage_constraints(
    model_book: EBook,
    dev_stat_file: Path,
    dev_define: EBook,
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
) -> int:
    rows = _target_rows(model_book, "DCDCConverter", prefix="ess")
    status_by_name, status_rows = _storage_soc_by_name(dev_stat_file)
    changed = 0
    period_hours = max(0.0, float(period_seconds)) / 3600.0
    for pos, row in enumerate(rows):
        storage_name = str(row.get("name", "")).removesuffix("_dcdc")
        status = status_by_name.get(storage_name)
        if status is None and pos < len(status_rows):
            status = status_rows[pos]
        define = _storage_define_for(dev_define, storage_name, pos)
        run_stat = _safe_int((status or {}).get("run_stat", row.get("run_stat", 1)), 1)
        if run_stat != 1 or not _is_running_row(row):
            changed += _set_row_value(row, "p_set", "0")
            continue
        command = _safe_float(row.get("p_set", 0.0), 0.0) or 0.0
        soc = _safe_float((status or {}).get("soc_curr", (define or {}).get("soc_cur", 0.5)), 0.5)
        if soc is None:
            soc = 0.5
        soc_min = _safe_float((define or {}).get("soc_min", 0.0), 0.0) or 0.0
        soc_max = _safe_float((define or {}).get("soc_max", 1.0), 1.0) or 1.0
        capacity = _safe_float((define or {}).get("emva", DEFAULT_STORAGE_CAPACITY_KWH), DEFAULT_STORAGE_CAPACITY_KWH)
        capacity = max(float(capacity if capacity is not None else DEFAULT_STORAGE_CAPACITY_KWH), 1e-9)
        charge_max = _safe_float((define or {}).get("charge_p_max", abs(command)), abs(command)) or 0.0
        discharge_max = _safe_float((define or {}).get("dis_charge_p_max", abs(command)), abs(command)) or 0.0
        if period_hours > 0.0:
            discharge_soc_margin = max(0.0, float(soc) - soc_min)
            charge_soc_margin = max(0.0, soc_max - float(soc))
            discharge_max = min(discharge_max, discharge_soc_margin * capacity / period_hours)
            charge_max = min(charge_max, charge_soc_margin * capacity / period_hours)
        if command > 0.0:
            target = 0.0 if soc <= soc_min else min(command, discharge_max)
        elif command < 0.0:
            target = 0.0 if soc >= soc_max else max(command, -charge_max)
        else:
            target = 0.0
        changed += _set_row_value(row, "p_set", _format_power(target))
    return changed


def apply_device_capability_limits(
    model_book: EBook,
    weather_file: Path,
    dev_stat_file: Path,
    dev_define_file: Optional[Path],
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
) -> int:
    dev_define = _read_optional_book(dev_define_file)
    if not dev_define.data:
        return 0
    weather = _weather_values(weather_file)
    changed = 0
    changed += apply_load_model(model_book, dev_define, weather)
    changed += apply_wind_limits(model_book, dev_define, weather)
    changed += apply_pv_limits(model_book, dev_define, weather)
    changed += apply_diesel_limits(model_book, dev_define)
    changed += apply_storage_constraints(model_book, dev_stat_file, dev_define, period_seconds)
    return changed


def apply_weather_file(model_book: EBook, weather_file: Path, dev_define_file: Optional[Path] = None) -> int:
    values = _weather_values(weather_file)
    if not values:
        return 0
    dev_define = _read_optional_book(dev_define_file)
    if dev_define.data:
        changed = 0
        changed += apply_load_model(model_book, dev_define, values)
        changed += apply_wind_limits(model_book, dev_define, values)
        changed += apply_pv_limits(model_book, dev_define, values)
        return changed
    changed = 0

    if "wind_speed_mps" in values:
        wind_kw = format_number(_wind_power_kw(values["wind_speed_mps"]))
        block = model_book.data.get("DCACConverter")
        if block is not None:
            for row in block.data:
                if str(row.get("name", "")).startswith("wt"):
                    changed += _set_row_value(row, "p_ac_set", wind_kw)

    if "solar_irradiance_w_m2" in values:
        scale = max(0.0, min(1.0, values["solar_irradiance_w_m2"] / 1000.0))
        block = model_book.data.get("DCDCConverter")
        if block is not None:
            for row in block.data:
                if str(row.get("name", "")).startswith("pv"):
                    try:
                        rated = float(row.get("p_set", 0.0))
                    except (TypeError, ValueError):
                        rated = 0.0
                    changed += _set_row_value(row, "p_set", format_number(rated * scale))

    if "load_kw" in values:
        block = model_book.data.get("ACLoad")
        if block is not None and block.data:
            base_loads = []
            total = 0.0
            for row in block.data:
                try:
                    p = float(row.get("pbase", 1.0)) * float(row.get("pv0", 0.0))
                    q = float(row.get("qbase", 1.0)) * float(row.get("qv0", 0.0))
                except (TypeError, ValueError):
                    p, q = 0.0, 0.0
                base_loads.append((row, p, q))
                total += p
            if total > 0.0:
                for row, p, q in base_loads:
                    new_p = values["load_kw"] * p / total
                    new_q = values["load_kw"] * q / total
                    changed += _set_row_value(row, "pv0", format_number(new_p))
                    changed += _set_row_value(row, "qv0", format_number(new_q))
    return changed


def apply_yt_ctrl_file(model_book: EBook, yt_ctrl_file: Path) -> int:
    yt_ctrl_file = Path(yt_ctrl_file)
    if not yt_ctrl_file.exists():
        return 0
    ctrl_book = EBook(yt_ctrl_file)
    changed = 0
    for table_name in ("GeneratorSetpoint", "StorageSoc", "StorageStatus"):
        block = ctrl_book.data.get(table_name)
        if block is None:
            continue
        for row in block.data:
            if table_name in ("StorageSoc", "StorageStatus"):
                ess_name = str(row.get("name", ""))
                target = _model_row(model_book, "DCDCConverter", f"{ess_name}_dcdc")
                if target is not None and row.get("p_set", "") != "":
                    changed += _set_row_value(target, "p_set", row["p_set"])
            else:
                changed += _apply_setpoint_row(model_book, row)
    changed += apply_overlay_file(model_book, yt_ctrl_file)
    return changed


def update_storage_soc(
    dev_stat_file: Path,
    model_book: EBook,
    period_seconds: float,
    dev_define_file: Optional[Path] = None,
) -> int:
    dev_stat_file = Path(dev_stat_file)
    if not dev_stat_file.exists():
        return 0
    stat_book = EBook(dev_stat_file)
    block = _storage_soc_block(stat_book)
    if block is None:
        return 0
    dcdc = model_book.data.get("DCDCConverter")
    dcdc_by_name = _rows_by_name(dcdc) if dcdc is not None else {}
    dev_define = _read_optional_book(dev_define_file)
    changed = 0
    for pos, row in enumerate(_sorted_rows(block.data)):
        ess_name = str(row.get("name", ""))
        source = dcdc_by_name.get(f"{ess_name}_dcdc")
        if source is None:
            continue
        try:
            soc = float(row.get("soc_curr", 0.5))
            p_set = float(source.get("p_set", 0.0))
        except (TypeError, ValueError):
            continue
        define = _storage_define_for(dev_define, ess_name, pos)
        capacity = _safe_float((define or {}).get("emva", DEFAULT_STORAGE_CAPACITY_KWH), DEFAULT_STORAGE_CAPACITY_KWH) or DEFAULT_STORAGE_CAPACITY_KWH
        soc_min = _safe_float((define or {}).get("soc_min", 0.0), 0.0) or 0.0
        soc_max = _safe_float((define or {}).get("soc_max", 1.0), 1.0) or 1.0
        next_soc = soc - p_set * float(period_seconds) / 3600.0 / max(capacity, 1e-9)
        next_soc = _clamp(next_soc, soc_min, soc_max)
        changed += _set_row_value(row, "soc_curr", format_number(next_soc))
    if changed:
        write_ebook_aligned(stat_book, dev_stat_file)
    return changed


def apply_realtime_inputs(
    model_file: Path,
    weather_file: Path,
    dev_stat_file: Path,
    yt_ctrl_file: Path,
    dev_define_file_or_work_dir: Path,
    work_dir: Optional[Path] = None,
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
) -> Tuple[Path, int, EBook]:
    if work_dir is None:
        dev_define_file = None
        work_dir = Path(dev_define_file_or_work_dir)
    else:
        dev_define_file = Path(dev_define_file_or_work_dir)
    model_book = EBook(model_file)
    changed = 0
    changed += apply_dev_stat_file(model_book, dev_stat_file)
    changed += apply_weather_file(model_book, weather_file, dev_define_file)
    changed += apply_yt_ctrl_file(model_book, yt_ctrl_file)
    changed += apply_device_capability_limits(model_book, weather_file, dev_stat_file, dev_define_file, period_seconds)
    work_dir.mkdir(parents=True, exist_ok=True)
    merged_model = work_dir / "merged_model.e"
    write_ebook_aligned(model_book, merged_model)
    return merged_model, changed, model_book


def solve_ac_snapshot(e_file: Path) -> Tuple[Snapshot, str]:
    network = ACPowerNetwork()
    network.read_from_file(e_file)
    network.topo()
    calc = ACPowerFlowCalc(network)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = calc.run()
    if rc != 0 or not calc.converged:
        raise RuntimeError(f"AC load flow failed for {e_file}: rc={rc}, iter={calc.iterations}, normF={calc.normF:.3e}")
    return Snapshot(network, ac_grid=network), f"iter={calc.iterations}, normF={calc.normF:.3e}"


def solve_hybrid_snapshot(e_file: Path) -> Tuple[Snapshot, str]:
    network = _read_lf_network_from_file(e_file)
    calc = HybridPowerFlowCalc(network, verbose=False)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = calc.run()
    if rc != 0 or not calc.converged:
        raise RuntimeError(
            f"Hybrid load flow failed for {e_file}: rc={rc}, "
            f"iter={calc.iterations}, normF={calc.normF:.3e}"
        )
    snapshot = Snapshot(
        network,
        ac_grid=network.ac,
        dc_grid=network.dc,
        dcac_converters=network.dcac_converters,
        acac_converters=network.acac_converters,
    )
    _add_zero_impedance_devices_from_file(snapshot, e_file)
    _link_snapshot_terminal_objects(snapshot)
    return snapshot, f"iter={calc.iterations}, normF={calc.normF:.3e}"


def _add_zero_impedance_devices_from_file(snapshot: Snapshot, e_file: Path) -> None:
    book = EBook(e_file)
    specs = (
        ("ACSwitch", snapshot.ac_devices, ("p", "q", "current")),
        ("ACBreak", snapshot.ac_devices, ("p", "q", "current")),
        ("DCSwitch", snapshot.dc_devices, ("p", "current")),
        ("DCBreak", snapshot.dc_devices, ("p", "current")),
    )
    for table_name, target, value_fields in specs:
        block = book.data.get(table_name)
        if block is None:
            continue
        devices = target.setdefault(table_name, {})
        for row in block.data:
            name = str(row.get("name", ""))
            if name in devices:
                continue
            values = {
                "idx": int(row.get("idx", 0)),
                "name": name,
                "i_node": int(row.get("i_node", 0)),
                "j_node": int(row.get("j_node", 0)),
                "status": int(row.get("status", 1)),
                "run_stat": int(row.get("run_stat", 1)),
            }
            values.update({field: 0.0 for field in value_fields})
            devices[name] = SimpleNamespace(**values)


def _link_snapshot_terminal_objects(snapshot: Snapshot) -> None:
    if "ACBreak" not in snapshot.ac_devices:
        snapshot.ac_devices["ACBreak"] = snapshot._by_name(getattr(snapshot.ac, "breakers", []))
    if "DCBreak" not in snapshot.dc_devices:
        snapshot.dc_devices["DCBreak"] = snapshot._by_name(getattr(snapshot.dc, "breakers", []))

    for device_type in ("ACBranch", "ACTransformer", "ACSwitch", "ACZeroBranch", "ACBreak"):
        for dev in snapshot.ac_devices.get(device_type, {}).values():
            if getattr(dev, "i_node_obj", None) is None:
                dev.i_node_obj = snapshot.ac_nodes_by_idx.get(getattr(dev, "i_node", None))
            if getattr(dev, "j_node_obj", None) is None:
                dev.j_node_obj = snapshot.ac_nodes_by_idx.get(getattr(dev, "j_node", None))
    for device_type in ("ACGenerator", "ACLoad"):
        for dev in snapshot.ac_devices.get(device_type, {}).values():
            if getattr(dev, "node_obj", None) is None:
                dev.node_obj = snapshot.ac_nodes_by_idx.get(getattr(dev, "node", None))

    for device_type in ("DCBranch", "DCSwitch", "DCZeroBranch", "DCBreak", "DCDCConverter"):
        for dev in snapshot.dc_devices.get(device_type, {}).values():
            if getattr(dev, "i_node_obj", None) is None:
                dev.i_node_obj = snapshot.dc_nodes_by_idx.get(getattr(dev, "i_node", None))
            if getattr(dev, "j_node_obj", None) is None:
                dev.j_node_obj = snapshot.dc_nodes_by_idx.get(getattr(dev, "j_node", None))
    for device_type in ("DCGenerator", "DCLoad"):
        for dev in snapshot.dc_devices.get(device_type, {}).values():
            if getattr(dev, "node_obj", None) is None:
                dev.node_obj = snapshot.dc_nodes_by_idx.get(getattr(dev, "node", None))
    for dev in snapshot.dcac_by_name.values():
        if getattr(dev, "ac_node_obj", None) is None:
            dev.ac_node_obj = snapshot.ac_nodes_by_idx.get(getattr(dev, "ac_node", None))
        if getattr(dev, "dc_node_obj", None) is None:
            dev.dc_node_obj = snapshot.dc_nodes_by_idx.get(getattr(dev, "dc_node", None))


def _storage_soc_values(dev_stat_file: Optional[Path]) -> Dict[str, float]:
    if dev_stat_file is None:
        return {}
    path = Path(dev_stat_file)
    if not path.exists():
        return {}
    try:
        book = EBook(path)
    except Exception:
        return {}
    values: Dict[str, float] = {}
    for row in _storage_soc_rows(book):
        name = str(row.get("name", row.get("dev_name", "")))
        if not name:
            continue
        soc = _safe_float(row.get("soc_curr", row.get("soc", "")), None)
        if soc is not None:
            values[name] = soc
    return values


def _measurement_value(snapshot, row: Sequence[str], storage_soc: Optional[Dict[str, float]] = None) -> Optional[float]:
    dev_type, dev_name, meas_type = row[2], row[3], row[4].upper()
    if dev_type in ("ESS", "Storage"):
        if meas_type == "SOC":
            return None if storage_soc is None else storage_soc.get(dev_name)
        dcdc_name = f"{dev_name}_dcdc"
        if meas_type == "P":
            return snapshot.value("DCDCConverter", dcdc_name, "P_FROM")
        if meas_type == "Q":
            return 0.0
        if meas_type == "V":
            return snapshot.value("DCDCConverter", dcdc_name, "V_FROM")
        if meas_type == "I":
            return snapshot.value("DCDCConverter", dcdc_name, "I_FROM")
    if dev_type == "ACBreak":
        dev = snapshot.ac_devices.get("ACBreak", {}).get(dev_name)
        return None if dev is None else snapshot._ac_zero_value(dev, meas_type)
    if dev_type == "DCBreak":
        dev = snapshot.dc_devices.get("DCBreak", {}).get(dev_name)
        return None if dev is None else snapshot._dc_zero_value(dev, meas_type)
    value = snapshot.value(dev_type, dev_name, meas_type)
    if value is None and (meas_type in VALUE_TYPES or meas_type in ANGLE_TYPES):
        return None
    return value


def build_real_rows(
    meas_file: Path,
    snapshot,
    dev_stat_file: Optional[Path] = None,
) -> Tuple[List[str], List[List[str]], List[str], int, int]:
    before, rows, after = parse_measurement_rows(meas_file)
    storage_soc = _storage_soc_values(dev_stat_file)
    updated = 0
    missing = 0
    for row in rows:
        value = _measurement_value(snapshot, row, storage_soc)
        if value is None:
            missing += 1
            continue
        row[7] = format_number(float(value))
        updated += 1
    return before, rows, after, updated, missing


def _row_noise_sigma(row: Sequence[str], noise_std: Optional[float]) -> float:
    if noise_std is not None:
        return max(0.0, float(noise_std))
    try:
        weight = float(row[5])
    except (TypeError, ValueError):
        return 0.0
    if weight <= 0.0:
        return 0.0
    return 1.0 / math.sqrt(weight)


def add_noise_to_rows(rows: Sequence[Sequence[str]], noise_std: Optional[float], rng: random.Random) -> List[List[str]]:
    noisy_rows: List[List[str]] = []
    for source_row in rows:
        row = list(source_row)
        sigma = _row_noise_sigma(row, noise_std)
        if sigma > 0.0:
            try:
                row[7] = format_number(float(row[7]) + rng.gauss(0.0, sigma))
            except (TypeError, ValueError):
                pass
        noisy_rows.append(row)
    return noisy_rows


def render_measurement_snapshot_aligned(before: Sequence[str], rows: Sequence[Sequence[str]], after: Sequence[str]) -> str:
    widths = [len(header) for header in MEAS_HEADER]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(str(cell)))

    parts: List[str] = []
    parts.extend(line + "\n" for line in before if line)
    parts.append("<Measurement>\n")
    parts.append("@ " + "  ".join(f"{MEAS_HEADER[idx]:<{widths[idx]}}" for idx in range(len(MEAS_HEADER))).rstrip() + "\n")
    for row in rows:
        parts.append("# " + "  ".join(f"{str(cell):<{widths[idx]}}" for idx, cell in enumerate(row)).rstrip() + "\n")
    parts.append("</Measurement>\n")
    parts.extend(line + "\n" for line in after if line)
    return "".join(parts)


def write_measurement_snapshot(path: Path, before: Sequence[str], rows: Sequence[Sequence[str]], after: Sequence[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_measurement_snapshot_aligned(before, rows, after), encoding="utf-8")


def run_once(
    config: SimulationConfig,
    solver: Callable[[Path], Tuple[object, str]] = solve_hybrid_snapshot,
    rng: Optional[random.Random] = None,
) -> SimulationResult:
    rng = rng or random.Random(config.random_seed)
    work_dir = config.real_file.parent / ".simu_loop_work"
    model_file, overlay_updates, model_book = apply_realtime_inputs(
        config.model_file,
        config.weather_file,
        config.dev_stat_file,
        config.yt_ctrl_file,
        config.dev_define_file,
        work_dir,
        config.period_seconds,
    )
    snapshot, solver_info = solver(model_file)
    soc_updates = update_storage_soc(config.dev_stat_file, model_book, config.period_seconds, config.dev_define_file)

    before, real_rows, after, updated, missing = build_real_rows(config.meas_file, snapshot, config.dev_stat_file)
    write_measurement_snapshot(config.real_file, before, real_rows, after)
    scada_rows = add_noise_to_rows(real_rows, config.noise_std, rng)
    write_measurement_snapshot(config.scada_file, before, scada_rows, after)
    return SimulationResult(
        real_file=config.real_file,
        scada_file=config.scada_file,
        updated=updated,
        missing=missing,
        overlay_updates=overlay_updates + soc_updates,
        solver_info=solver_info,
    )


def simulate_once(
    model_file: Optional[Path] = None,
    meas_file: Optional[Path] = None,
    weather_file: Optional[Path] = None,
    dev_stat_file: Optional[Path] = None,
    yt_ctrl_file: Optional[Path] = None,
    dev_define_file: Optional[Path] = None,
    real_file: Optional[Path] = None,
    scada_file: Optional[Path] = None,
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
    noise_std: Optional[float] = None,
    random_seed: Optional[int] = None,
    solver: Callable[[Path], Tuple[object, str]] = solve_hybrid_snapshot,
) -> SimulationResult:
    defaults = default_config()
    config = SimulationConfig(
        model_file=Path(model_file or defaults.model_file).resolve(),
        meas_file=Path(meas_file or defaults.meas_file).resolve(),
        weather_file=Path(weather_file or defaults.weather_file).resolve(),
        dev_stat_file=Path(dev_stat_file or defaults.dev_stat_file).resolve(),
        yt_ctrl_file=Path(yt_ctrl_file or defaults.yt_ctrl_file).resolve(),
        dev_define_file=Path(dev_define_file or defaults.dev_define_file).resolve(),
        real_file=Path(real_file or defaults.real_file).resolve(),
        scada_file=Path(scada_file or defaults.scada_file).resolve(),
        period_seconds=period_seconds,
        noise_std=noise_std,
        random_seed=random_seed,
        loop_count=1,
        log_file=defaults.log_file,
        step_mode=False,
    )
    return run_once(config, solver=solver)


def _result_message(cycle: int, result: SimulationResult) -> str:
    return (
        f"第 {cycle} 轮仿真完成: updated={result.updated}, missing={result.missing}, "
        f"overlays={result.overlay_updates}, {result.solver_info}, "
        f"real={result.real_file}, scada={result.scada_file}"
    )


def run_loop(
    config: SimulationConfig,
    logger: Optional[logging.Logger] = None,
    run_once_func: Callable[..., SimulationResult] = run_once,
) -> int:
    logger = logger or setup_logger(config.log_file or _default_log_file())
    rng = random.Random(config.random_seed)
    count = 0
    logger.info(
        "仿真循环启动 model=%s meas=%s weather=%s dev_stat=%s dev_define=%s yt_ctrl=%s real=%s scada=%s period=%s noise_std=%s count=%s seed=%s step_mode=%s",
        config.model_file,
        config.meas_file,
        config.weather_file,
        config.dev_stat_file,
        config.dev_define_file,
        config.yt_ctrl_file,
        config.real_file,
        config.scada_file,
        config.period_seconds,
        config.noise_std,
        config.loop_count,
        config.random_seed,
        config.step_mode,
    )
    if config.step_mode:
        if config.loop_count is None:
            logger.error("步进模式需要指定有限 count")
            return 1
        for cycle in range(1, int(config.loop_count) + 1):
            try:
                result = run_once_func(config, rng=rng)
            except Exception:
                logger.exception("第 %s 轮仿真失败", cycle)
                return 1
            logger.info(_result_message(cycle, result))
            count += 1
        logger.info("步进模式仿真结束，共完成 %s 步", count)
        return 0
    while config.loop_count is None or count < config.loop_count:
        started = time.monotonic()
        try:
            result = run_once_func(config, rng=rng)
        except Exception:
            logger.exception("第 %s 轮仿真失败", count + 1)
            return 1
        logger.info(_result_message(count + 1, result))
        count += 1
        if config.loop_count is not None and count >= config.loop_count:
            break
        sleep_seconds = max(0.0, float(config.period_seconds) - (time.monotonic() - started))
        logger.info("等待 %.3f 秒后进入下一轮仿真", sleep_seconds)
        time.sleep(sleep_seconds)
    logger.info("仿真循环结束，共完成 %s 轮", count)
    return 0


def parse_args(argv: Sequence[str]) -> SimulationConfig:
    defaults = default_config()
    parser = argparse.ArgumentParser(description="Run periodic station hybrid load-flow simulation and write real/scada E files.")
    parser.add_argument("--model", default=str(defaults.model_file), help="Network model E file, default: simu/model.e.")
    parser.add_argument("--meas", default=str(defaults.meas_file), help="Measurement definition E file, default: simu/meas.e.")
    parser.add_argument("--weather", default=str(defaults.weather_file), help="Realtime weather E overlay file.")
    parser.add_argument("--dev-stat", default=str(defaults.dev_stat_file), help="Device status E file, default: simu/stat.e.")
    parser.add_argument(
        "--device",
        "--dev-define",
        dest="dev_define",
        default=str(defaults.dev_define_file),
        help="Wind/PV/storage/diesel/load device parameter E file, default: simu/device.e.",
    )
    parser.add_argument("--yt-ctrl", default=str(defaults.yt_ctrl_file), help="Remote control E file.")
    parser.add_argument("--real", default=str(defaults.real_file), help="Output real-value E file.")
    parser.add_argument("--scada", default=str(defaults.scada_file), help="Output noisy SCADA E file.")
    parser.add_argument("--period", type=float, default=defaults.period_seconds, help="Loop period in seconds.")
    parser.add_argument("--noise-std", type=float, default=None, help="Absolute Gaussian noise sigma. If omitted, use 1/sqrt(weight).")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible SCADA noise.")
    parser.add_argument("--log", default=str(defaults.log_file), help="Simulation log file.")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument("--count", type=int, default=None, help="Run a fixed number of cycles and exit.")
    parser.add_argument("--step-mode", action="store_true", help="Run fixed steps without sleeping; requires --count or --once.")
    args = parser.parse_args(argv)
    loop_count = 1 if args.once else args.count
    return SimulationConfig(
        model_file=Path(args.model).resolve(),
        meas_file=Path(args.meas).resolve(),
        weather_file=Path(args.weather).resolve(),
        dev_stat_file=Path(args.dev_stat).resolve(),
        dev_define_file=Path(args.dev_define).resolve(),
        yt_ctrl_file=Path(args.yt_ctrl).resolve(),
        real_file=Path(args.real).resolve(),
        scada_file=Path(args.scada).resolve(),
        period_seconds=args.period,
        noise_std=args.noise_std,
        random_seed=args.seed,
        loop_count=loop_count,
        log_file=Path(args.log).resolve() if args.log else None,
        step_mode=args.step_mode,
    )


def main(argv: Sequence[str]) -> int:
    config = parse_args(argv)
    return run_loop(config)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
