"""Periodic load-flow based simulator for SCADA measurement snapshots."""

from __future__ import annotations

import argparse
import contextlib
import io
import logging
import math
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


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
# Keep the WEB ``simu`` package ahead of the kernel package with the same name.
web_root = str(SIMU_DIR)
if web_root in sys.path:
    sys.path.remove(web_root)
sys.path.insert(0, web_root)

from efile_read import EBook
from update_meas_from_lf import (  # noqa: E402
    ANGLE_TYPES,
    MEAS_HEADER,
    VALUE_TYPES,
    Snapshot,
    _reconstruct_ac_ideal_edge_flows,
    _reconstruct_dc_ideal_edge_flows,
    format_number,
    parse_measurement_rows,
)
from ac_lf import ACPowerFlowCalc  # noqa: E402
from ac_model import ACPowerNetwork  # noqa: E402
from hybrid_lf import HybridPowerFlowCalc, _read_lf_network_from_file  # noqa: E402
from hybrid_lf import (  # noqa: E402
    _build_lf_network_from_hybrid_rows,
    _build_lf_network_from_single_ac_file,
    _build_lf_network_from_single_dc_file,
    _detect_lf_rows_kind,
    attach_multi_energy_context,
    build_multi_energy_context_from_rows,
)
from simu.device_roles import (  # noqa: E402
    converter_active_power_setpoint_field,
    converter_effective_control_types,
    converter_power_setpoint_fields,
)
from simu.model_semantics import (  # noqa: E402
    energy_coupling_control_bindings,
    grid_converter_keys,
    resolve_resource_reference,
    resource_aliases,
    structured_resources,
)


DEFAULT_MODEL_FILE = SIMU_DIR / "model.e"
DEFAULT_MEAS_FILE = SIMU_DIR / "meas.e"
DEFAULT_WEATHER_FILE = SIMU_DIR / "weather.e"
DEFAULT_DEV_STAT_FILE = SIMU_DIR / "stat.e"
DEFAULT_DEV_DEFINE_FILE: Optional[Path] = None
DEFAULT_YT_CTRL_FILE = SIMU_DIR / "yt_ctrl.e"
DEFAULT_REAL_FILE = SIMU_DIR / "real.e"
DEFAULT_SCADA_FILE = SIMU_DIR / "scada.e"
DEFAULT_LOG_DIR = ROOT_DIR / "log"
DEFAULT_PERIOD_SECONDS = 60.0
DEFAULT_STORAGE_CAPACITY_KWH = 50.0
DEFAULT_DC_EXPORT_EFFICIENCY = 0.98
HYDROGEN_STORAGE_STATE_BLOCK = "HydroStorageState"
HYDROGEN_STORAGE_STATE_HEADERS = (
    "dev_type",
    "idx",
    "name",
    "press",
    "flow",
    "gas_quantity",
    "soc",
)
StorageTarget = Tuple[str, dict, str, Optional[dict], int]
SIGNAL_MEASUREMENT_TYPES = {"RUN_STAT", "STATUS"}
GENERIC_CURRENT_BRANCH_TYPES = {
    "ACBranch",
    "ACTransformer",
    "ACSwitch",
    "ACBreak",
    "ACZeroBranch",
    "DCBranch",
    "DCSwitch",
    "DCBreak",
    "DCZeroBranch",
}
LOGGER = logging.getLogger("SimulationLoop")


@dataclass(frozen=True)
class MeasurementBinding:
    target_type: str
    target_name: str
    target_present: bool = False


@dataclass(frozen=True)
class SimulationConfig:
    model_file: Path
    meas_file: Path
    weather_file: Path
    dev_stat_file: Path
    real_file: Path
    scada_file: Path
    yt_ctrl_file: Path = DEFAULT_YT_CTRL_FILE
    dev_define_file: Optional[Path] = DEFAULT_DEV_DEFINE_FILE
    mode_file: Optional[Path] = None
    period_seconds: float = DEFAULT_PERIOD_SECONDS
    noise_std: Optional[float] = None
    random_seed: Optional[int] = None
    loop_count: Optional[int] = None
    log_file: Optional[Path] = None
    step_mode: bool = False
    write_output_files: bool = True
    model_book: Optional[EBook] = None
    meas_before: Optional[List[str]] = None
    meas_rows: Optional[List[List[str]]] = None
    meas_after: Optional[List[str]] = None
    weather_book: Optional[EBook] = None
    dev_stat_book: Optional[EBook] = None
    yt_ctrl_book: Optional[EBook] = None
    dev_define_book: Optional[EBook] = None
    mode_book: Optional[EBook] = None
    measurement_bindings: Optional[Tuple[MeasurementBinding, ...]] = None
    measurement_median_deviations: Optional[Mapping[str, float]] = None


@dataclass(frozen=True)
class SimulationResult:
    real_file: Path
    scada_file: Path
    updated: int
    missing: int
    overlay_updates: int
    solver_info: str
    model_book: Optional[EBook] = None
    measurement_definitions: Optional[List[List[str]]] = None
    real_rows: Optional[List[List[str]]] = None
    scada_rows: Optional[List[List[str]]] = None
    device_states: Optional[List[Dict[str, Any]]] = None


def default_config() -> SimulationConfig:
    return SimulationConfig(
        model_file=DEFAULT_MODEL_FILE,
        meas_file=DEFAULT_MEAS_FILE,
        weather_file=DEFAULT_WEATHER_FILE,
        dev_stat_file=DEFAULT_DEV_STAT_FILE,
        yt_ctrl_file=DEFAULT_YT_CTRL_FILE,
        dev_define_file=DEFAULT_DEV_DEFINE_FILE,
        mode_file=None,
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


_MODEL_BOOK_CACHE: Dict[Path, Tuple[Tuple[int, int], EBook]] = {}


def _file_signature(path: Path) -> Tuple[int, int]:
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def clear_model_book_cache(model_file: Optional[Path] = None) -> None:
    """Clear cached source model definitions after an explicit definition update."""
    if model_file is None:
        _MODEL_BOOK_CACHE.clear()
        return
    _MODEL_BOOK_CACHE.pop(Path(model_file).resolve(), None)


def _load_model_book_once(model_file: Path) -> EBook:
    model_file = Path(model_file).resolve()
    signature = _file_signature(model_file)
    cached = _MODEL_BOOK_CACHE.get(model_file)
    if cached is not None and cached[0] == signature:
        return cached[1]
    book = EBook(model_file)
    _MODEL_BOOK_CACHE[model_file] = (signature, book)
    return book


def _clone_ebook(book: EBook) -> EBook:
    clone = type(book).__new__(type(book))
    clone.data = {}
    if hasattr(book, "file_path"):
        clone.file_path = book.file_path
    for key, block in book.data.items():
        cloned_block = type(block)(block.name)
        cloned_block.header_list = list(block.header_list)
        cloned_block.data = [dict(row) for row in block.data]
        clone.data[key] = cloned_block
    return clone


def _ebook_to_efile_rows(book: EBook) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for key, block in book.data.items():
        table_name = str(getattr(block, "name", key))
        lv = 0
        if " lv " in table_name:
            table_key, lv_text = table_name.split(" lv ", 1)
            table_name = table_key
            try:
                lv = int(lv_text.strip().split("=", 1)[1])
            except (IndexError, ValueError):
                lv = 0
        header = list(block.header_list)
        serialized_rows = []
        for row in block.data:
            effective_row = row
            if table_name in {"ACDCConverter", "DCACConverter"}:
                ac_mode, dc_mode = converter_effective_control_types(row)
                if (
                    ac_mode != str(row.get("ac_control_type", "")).strip().upper()
                    or dc_mode != str(row.get("dc_control_type", "")).strip().upper()
                ):
                    effective_row = {
                        **row,
                        "ac_control_type": ac_mode,
                        "dc_control_type": dc_mode,
                    }
            serialized_rows.append(
                [str(effective_row.get(column, "")) for column in header]
            )
        rows[table_name] = {
            "table_name": table_name,
            "header_list": header,
            "rows": serialized_rows,
            "lv": lv,
        }
    return rows


def _ebook_to_dict_rows(book: EBook) -> Dict[str, List[Dict[str, str]]]:
    return {
        key: [{column: str(row.get(column, "")) for column in block.header_list} for row in block.data]
        for key, block in book.data.items()
    }


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


def apply_overlay_book(model_book: EBook, overlay_book: Optional[EBook]) -> int:
    if overlay_book is None:
        return 0
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


def _ensure_power_bound_columns(model_book: EBook, dev_type: str, row: dict) -> None:
    """Expose runtime p_min/p_max columns to the in-memory solver model.

    Older model E files omit optional generator bounds entirely.  The runtime
    SOC gate still needs to send dynamic bounds to the load-flow kernel, so
    add the optional columns to the cloned block without touching the source
    model file.  Non-storage rows in the same block remain unbounded because
    their newly added cells are left empty.
    """
    block = model_book.data.get(dev_type)
    if block is None:
        return
    for column in ("p_min", "p_max"):
        if column not in block.header_list:
            block.header_list.append(column)
        row.setdefault(column, "")


def _safe_float(value, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _numeric_from_text(value, default: Optional[float] = 0.0) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return default
    match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)
    if match is None:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def _ratio_from_text(value, default: Optional[float] = 0.0) -> Optional[float]:
    number = _numeric_from_text(value, default)
    if number is None:
        return default
    if isinstance(value, str) and "%" in value:
        return number / 100.0
    return number


def _storage_soc_ratio_from_text(value, default: Optional[float] = 0.0) -> Optional[float]:
    number = _ratio_from_text(value, default)
    if number is None:
        return default
    if not (isinstance(value, str) and "%" in value) and 2.0 < abs(number) <= 100.0:
        return number / 100.0
    return number


def _positive_numeric(value, default: Optional[float] = None) -> Optional[float]:
    number = _numeric_from_text(value, None)
    if number is None or number <= 0.0:
        return default
    return number


def _wind_rated_power_kw(row: Optional[dict], define: Optional[dict] = None, default: float = 10.0) -> float:
    source = row or {}
    capability = define or {}
    for value in (
        source.get("rated_capacity"),
        capability.get("rated_capacity"),
        capability.get("rated_power"),
        capability.get("p_max"),
        source.get("rated_power"),
        source.get("p_max"),
    ):
        rated = _positive_numeric(value, None)
        if rated is not None:
            return rated
    return float(default)


def _pv_rated_power_kw(row: Optional[dict], define: Optional[dict] = None, default: float = 0.0) -> float:
    source = row or {}
    capability = define or {}
    for value in (
        capability.get("rated_power"),
        capability.get("rated_capacity"),
        capability.get("p_max"),
        source.get("rated_capacity"),
        source.get("rated_power"),
        source.get("p_max"),
    ):
        rated = _positive_numeric(value, None)
        if rated is not None:
            return rated
    module_efficiency = _ratio_from_text(capability.get("module_efficiency"), None)
    array_area_m2 = _positive_numeric(capability.get("array_area"), None)
    reference_irradiance = _positive_numeric(
        capability.get("reference_irradiance"),
        1000.0,
    )
    if (
        module_efficiency is not None
        and module_efficiency > 0.0
        and array_area_m2 is not None
        and reference_irradiance is not None
    ):
        return module_efficiency * array_area_m2 * reference_irradiance / 1000.0
    return float(default)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _topology_node_alive_by_idx(grid: object) -> Dict[int, bool]:
    alive_by_idx: Dict[int, bool] = {}
    ppc = getattr(grid, "ppc", None)
    topology = ppc.get("_topology_arrays") if isinstance(ppc, Mapping) else None
    raw_node_ids = getattr(topology, "node_ids", None)
    raw_node_alive = getattr(topology, "node_alive_mask", None)
    node_ids = list(raw_node_ids) if raw_node_ids is not None else []
    node_alive = list(raw_node_alive) if raw_node_alive is not None else []
    for pos, node_id in enumerate(node_ids):
        if pos >= len(node_alive):
            break
        alive_by_idx[_safe_int(node_id)] = bool(node_alive[pos])

    for node in list(getattr(grid, "nodes", []) or []):
        idx = _safe_int(getattr(node, "idx", None), -1)
        if idx < 0 or idx in alive_by_idx:
            continue
        alive = getattr(node, "is_alive", None)
        if alive is None:
            island = getattr(node, "isl_obj", None)
            alive = getattr(island, "is_alive", None) if island is not None else None
        if alive is None and _safe_int(getattr(node, "run_stat", 1), 1) == 0:
            alive = False
        if alive is not None:
            alive_by_idx[idx] = bool(alive)
    return alive_by_idx


def _terminal_node_alive(node: object, alive_by_idx: Mapping[int, bool]) -> Optional[bool]:
    if node is None:
        return None
    idx = _safe_int(getattr(node, "idx", None), -1)
    if idx in alive_by_idx:
        return bool(alive_by_idx[idx])
    alive = getattr(node, "is_alive", None)
    if alive is not None:
        return bool(alive)
    island = getattr(node, "isl_obj", None)
    island_alive = getattr(island, "is_alive", None) if island is not None else None
    if island_alive is not None:
        return bool(island_alive) and _safe_int(getattr(node, "run_stat", 1), 1) == 1
    if _safe_int(getattr(node, "run_stat", 1), 1) == 0:
        return False
    return None


_BOUNDARY_DEVICE_TYPES = frozenset({"ACSwitch", "ACBreak", "DCSwitch", "DCBreak"})
# Descriptors are object attribute, model-row field, and topology domain. A
# missing object attribute means the device itself is the terminal node.
_DEVICE_TERMINAL_DESCRIPTORS = {
    "ACNode": ((None, "idx", "ac"),),
    "ACRealBs": (("node_obj", "node", "ac"),),
    "ACGenerator": (("node_obj", "node", "ac"),),
    "ACLoad": (("node_obj", "node", "ac"),),
    "ACShuntCompensator": (("node_obj", "node", "ac"),),
    "ACBranch": (("i_node_obj", "i_node", "ac"), ("j_node_obj", "j_node", "ac")),
    "ACTransformer": (("i_node_obj", "i_node", "ac"), ("j_node_obj", "j_node", "ac")),
    "ACThreeWindingTransformer": (
        ("i_node_obj", "i_node", "ac"),
        ("j_node_obj", "j_node", "ac"),
        ("k_node_obj", "k_node", "ac"),
    ),
    "ACZeroBranch": (("i_node_obj", "i_node", "ac"), ("j_node_obj", "j_node", "ac")),
    "ACSwitch": (("i_node_obj", "i_node", "ac"), ("j_node_obj", "j_node", "ac")),
    "ACBreak": (("i_node_obj", "i_node", "ac"), ("j_node_obj", "j_node", "ac")),
    "ACACConverter": (("i_node_obj", "i_node", "ac"), ("j_node_obj", "j_node", "ac")),
    "DCNode": ((None, "idx", "dc"),),
    "DCRealBs": (("node_obj", "node", "dc"),),
    "DCGenerator": (("node_obj", "node", "dc"),),
    "DCLoad": (("node_obj", "node", "dc"),),
    "DCBranch": (("i_node_obj", "i_node", "dc"), ("j_node_obj", "j_node", "dc")),
    "DCZeroBranch": (("i_node_obj", "i_node", "dc"), ("j_node_obj", "j_node", "dc")),
    "DCSwitch": (("i_node_obj", "i_node", "dc"), ("j_node_obj", "j_node", "dc")),
    "DCBreak": (("i_node_obj", "i_node", "dc"), ("j_node_obj", "j_node", "dc")),
    "DCDCConverter": (("i_node_obj", "i_node", "dc"), ("j_node_obj", "j_node", "dc")),
    "DCACConverter": (("ac_node_obj", "ac_node", "ac"), ("dc_node_obj", "dc_node", "dc")),
}


def _terminal_alive_map(
    domain: str,
    ac_node_alive: Mapping[int, bool],
    dc_node_alive: Mapping[int, bool],
) -> Mapping[int, bool]:
    return dc_node_alive if domain == "dc" else ac_node_alive


def _object_terminal_states(
    dev_type: str,
    device: object,
    ac_node_alive: Mapping[int, bool],
    dc_node_alive: Mapping[int, bool],
) -> List[Optional[bool]]:
    states = []
    for object_attr, _row_field, domain in _DEVICE_TERMINAL_DESCRIPTORS.get(dev_type, ()):
        node = device if object_attr is None else getattr(device, object_attr, None)
        states.append(
            _terminal_node_alive(
                node,
                _terminal_alive_map(domain, ac_node_alive, dc_node_alive),
            )
        )
    return states


def _model_terminal_states(
    dev_type: str,
    row: Mapping[str, object],
    ac_node_alive: Mapping[int, bool],
    dc_node_alive: Mapping[int, bool],
) -> List[Optional[bool]]:
    states = []
    for _object_attr, row_field, domain in _DEVICE_TERMINAL_DESCRIPTORS.get(dev_type, ()):
        alive_by_idx = _terminal_alive_map(domain, ac_node_alive, dc_node_alive)
        node_idx = _safe_int(row.get(row_field), -1)
        states.append(bool(alive_by_idx[node_idx]) if node_idx in alive_by_idx else None)
    return states


def _terminal_states_dead_island(
    dev_type: str,
    terminal_states: Sequence[Optional[bool]],
    fallback_alive: Optional[bool] = None,
) -> bool:
    if dev_type in _BOUNDARY_DEVICE_TYPES:
        # Do not infer a dead boundary unless every required endpoint is known dead.
        return bool(terminal_states) and all(state is False for state in terminal_states)
    if any(state is False for state in terminal_states):
        return True
    if terminal_states and all(state is True for state in terminal_states):
        return False
    return fallback_alive is False


def _device_dead_island(
    dev_type: str,
    device: object,
    ac_node_alive: Mapping[int, bool],
    dc_node_alive: Mapping[int, bool],
) -> bool:
    if _safe_int(getattr(device, "run_stat", 1), 1) != 1:
        return False
    terminal_states = _object_terminal_states(
        dev_type,
        device,
        ac_node_alive,
        dc_node_alive,
    )
    return _terminal_states_dead_island(
        dev_type,
        terminal_states,
        getattr(device, "is_alive", None),
    )


def collect_device_operating_states(
    snapshot: object,
    model_book: Optional[EBook] = None,
) -> List[Dict[str, Any]]:
    """Return compact run/dead-island states from one solved topology."""
    ac_grid = getattr(snapshot, "ac", None)
    dc_grid = getattr(snapshot, "dc", None)
    ac_node_alive = _topology_node_alive_by_idx(ac_grid) if ac_grid is not None else {}
    dc_node_alive = _topology_node_alive_by_idx(dc_grid) if dc_grid is not None else {}
    states: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add_device(dev_type: str, device: object, fallback_name: str = "") -> None:
        name = str(getattr(device, "name", fallback_name) or fallback_name).strip()
        if not dev_type or not name:
            return
        states[(dev_type, name)] = {
            "dev_type": dev_type,
            "dev_name": name,
            "run_stat": _safe_int(getattr(device, "run_stat", 1), 1),
            "dead_island": _device_dead_island(
                dev_type,
                device,
                ac_node_alive,
                dc_node_alive,
            ),
        }

    ac_specs = (
        ("ACNode", "nodes"),
        ("ACBranch", "branches"),
        ("ACTransformer", "transformers"),
        ("ACThreeWindingTransformer", "three_winding_transformers"),
        ("ACGenerator", "generators"),
        ("ACLoad", "loads"),
        ("ACShuntCompensator", "shunt_compensators"),
        ("ACZeroBranch", "zero_branches"),
        ("ACSwitch", "switches"),
        ("ACBreak", "breakers"),
    )
    dc_specs = (
        ("DCNode", "nodes"),
        ("DCBranch", "branches"),
        ("DCGenerator", "generators"),
        ("DCLoad", "loads"),
        ("DCZeroBranch", "zero_branches"),
        ("DCSwitch", "switches"),
        ("DCBreak", "breakers"),
        ("DCDCConverter", "dcdc_converters"),
    )
    for dev_type, attr in ac_specs:
        for device in list(getattr(ac_grid, attr, []) or []):
            add_device(dev_type, device)
    for dev_type, attr in dc_specs:
        for device in list(getattr(dc_grid, attr, []) or []):
            add_device(dev_type, device)

    for dev_type, devices in getattr(snapshot, "ac_devices", {}).items():
        for name, device in devices.items():
            add_device(str(dev_type), device, str(name))
    for dev_type, devices in getattr(snapshot, "dc_devices", {}).items():
        for name, device in devices.items():
            add_device(str(dev_type), device, str(name))
    for device in list(getattr(snapshot, "dcac_converters", []) or []):
        add_device("DCACConverter", device)
    for device in list(getattr(snapshot, "acac_converters", []) or []):
        add_device("ACACConverter", device)

    if model_book is not None:
        for dev_type, block in model_book.data.items():
            if "name" not in block.header_list or "run_stat" not in block.header_list:
                continue
            for row in block.data:
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                run_stat = _safe_int(row.get("run_stat", 1), 1)
                key = (str(dev_type), name)
                state = states.get(key, {
                    "dev_type": str(dev_type),
                    "dev_name": name,
                    "run_stat": run_stat,
                    "dead_island": False,
                })
                state["run_stat"] = run_stat
                if run_stat == 0:
                    state["dead_island"] = False
                elif key not in states:
                    state["dead_island"] = _terminal_states_dead_island(
                        str(dev_type),
                        _model_terminal_states(
                            str(dev_type),
                            row,
                            ac_node_alive,
                            dc_node_alive,
                        ),
                    )
                states[key] = state

    return [states[key] for key in sorted(states)]


def _clamp(value: float, lower: float, upper: float) -> float:
    if upper < lower:
        lower, upper = upper, lower
    return max(lower, min(upper, value))


def _efficiency_from_text(value, default: float = 1.0) -> float:
    number = _ratio_from_text(value, None)
    if number is None:
        return float(default)
    if number > 1.0:
        number /= 100.0
    return _clamp(float(number), 1e-9, 1.0)


def _efficiency_from_fields(row: Optional[Mapping[str, Any]], fields: Sequence[str], default: float = 1.0) -> float:
    if row is None:
        return float(default)
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return _efficiency_from_text(value, default)
    return float(default)


def _storage_efficiencies(define: Optional[Mapping[str, Any]]) -> Tuple[float, float]:
    shared = _efficiency_from_fields(
        define,
        (
            "charge_discharge_efficiency",
            "charge_discharge_eff",
            "round_trip_efficiency",
            "storage_efficiency",
            "efficiency",
            "eta",
        ),
        1.0,
    )
    charge_efficiency = _efficiency_from_fields(
        define,
        ("charge_efficiency", "charging_efficiency", "charge_eff", "eta_charge", "charge_eta"),
        shared,
    )
    discharge_efficiency = _efficiency_from_fields(
        define,
        (
            "discharge_efficiency",
            "discharging_efficiency",
            "dis_charge_efficiency",
            "discharge_eff",
            "eta_discharge",
            "discharge_eta",
        ),
        shared,
    )
    return charge_efficiency, discharge_efficiency


def _is_running_row(row: dict) -> bool:
    return _safe_int(row.get("run_stat", 1), 1) == 1


def _read_optional_book(file_path: Optional[Path]) -> EBook:
    if file_path is None:
        return EBook({})
    path = Path(file_path)
    return EBook(path) if path.exists() else EBook({})


def _weather_values_from_book(book: Optional[EBook]) -> Dict[str, float]:
    if book is None:
        return {}
    block = book.data.get("Weather")
    if block is None or not block.data:
        return {}
    row = block.data[0]
    if "name" in block.header_list and "value" in block.header_list:
        raw = {str(item.get("name")): item.get("value") for item in block.data}
    else:
        raw = row
    values: Dict[str, float] = {}
    for key in (
        "wind_speed_mps",
        "solar_irradiance_w_m2",
        "air_temp_c",
        "air_pressure_hpa",
        "humidity_pct",
        "load_kw",
    ):
        try:
            values[key] = float(raw[key])
        except (KeyError, TypeError, ValueError):
            pass
    if "time" in raw:
        time_minutes = _time_minutes(raw.get("time"))
        if time_minutes is not None:
            values["time_minutes"] = time_minutes
    return values


def _load_power_targets_from_book(book: Optional[EBook]) -> List[dict]:
    if book is None:
        return []
    block = book.data.get("LoadPower")
    if block is None:
        return []
    targets: List[dict] = []
    for row in block.data:
        dev_type = str(row.get("dev_type", "")).strip()
        dev_name = str(row.get("dev_name", "")).strip()
        p_kw = _safe_float(row.get("p_kw"), None)
        if dev_type not in {"ACLoad", "DCLoad"} or not dev_name or p_kw is None:
            continue
        targets.append({"dev_type": dev_type, "dev_name": dev_name, "p_kw": max(0.0, p_kw)})
    return targets


def _book_rows(book: EBook, table_name: str) -> List[dict]:
    block = book.data.get(table_name)
    return [] if block is None else list(block.data)


def _book_rows_by_idx(book: EBook, table_name: str) -> Dict[str, dict]:
    return {
        str(row.get("idx", "")): row
        for row in _book_rows(book, table_name)
        if str(row.get("idx", "")) != ""
    }


def _embedded_device_define_book(model_book: EBook) -> EBook:
    ac_generators = _book_rows_by_idx(model_book, "ACGenerator")
    dc_generators = _book_rows_by_idx(model_book, "DCGenerator")
    wind_rows: List[dict] = []
    pv_rows: List[dict] = []
    storage_rows: List[dict] = []
    diesel_rows: List[dict] = []

    for block_name, generators, generator_type, reference_field in (
        ("ACWindGen", ac_generators, "ACGenerator", "idx_acgenerator"),
        ("DCWindGen", dc_generators, "DCGenerator", "idx_dcgenerator"),
    ):
        for pos, row in enumerate(_sorted_rows(_book_rows(model_book, block_name)), start=1):
            source = generators.get(str(row.get(reference_field, "")))
            if source is None:
                continue
            source_name = str(source.get("name", "")).strip()
            if not source_name:
                continue
            rated = (
                _positive_numeric(source.get("rated_capacity"), None)
                or _positive_numeric(row.get("rated_power"), None)
                or _positive_numeric(source.get("p_max"), None)
                or _positive_numeric(source.get("rated_power"), None)
                or _positive_numeric(source.get("p_set"), None)
                or 10.0
            )
            wind_rows.append(
                {
                    "id": row.get("idx", pos),
                    "name": source_name,
                    "source_name": source_name,
                    "dev_type": generator_type,
                    "p_max": rated,
                    "p_min": 0,
                    "p_fur": 0,
                    "rated_power": rated,
                    "rated_wind_speed": _numeric_from_text(row.get("rated_wind_speed"), 15.0) or 15.0,
                    "cut_in_speed": _numeric_from_text(row.get("cut_in_wind_speed"), 5.0) or 5.0,
                    "cut_out_speed": _numeric_from_text(row.get("cut_out_wind_speed"), 30.0) or 30.0,
                }
            )

    for block_name, generators, generator_type, reference_field in (
        ("ACPVGen", ac_generators, "ACGenerator", "idx_acgenerator"),
        ("DCPVGen", dc_generators, "DCGenerator", "idx_dcgenerator"),
    ):
        for pos, row in enumerate(_sorted_rows(_book_rows(model_book, block_name)), start=1):
            source = generators.get(str(row.get(reference_field, "")))
            if source is None:
                continue
            source_name = str(source.get("name", "")).strip()
            if not source_name:
                continue
            rated = (
                _positive_numeric(row.get("rated_power"), None)
                or _positive_numeric(source.get("rated_capacity"), None)
            )
            if rated is None:
                efficiency = _efficiency_from_text(row.get("module_efficiency"), 0.2)
                area = _numeric_from_text(row.get("array_area"), 0.0) or 0.0
                rated = efficiency * area
            if rated <= 0.0:
                rated = (
                    _positive_numeric(source.get("p_max"), None)
                    or _positive_numeric(source.get("p_set"), None)
                    or 0.0
                )
            pv_rows.append(
                {
                    "id": row.get("idx", pos),
                    "name": source_name,
                    "source_name": source_name,
                    "dev_type": generator_type,
                    "p_max": rated,
                    "p_min": 0,
                    "p_fur": 0,
                    "rated_power": rated,
                    "temp_coefficient": _numeric_from_text(row.get("temp_coefficient"), 0.0) or 0.0,
                    "reference_irradiance": _numeric_from_text(row.get("reference_irradiance"), 1000.0) or 1000.0,
                    "reference_temperature": _numeric_from_text(row.get("reference_temperature"), 25.0) or 25.0,
                }
            )

    generator_rows_by_type = {
        "ACGenerator": ac_generators,
        "DCGenerator": dc_generators,
    }
    for block_name, generator_type, reference_field in (
        ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
        ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
    ):
        generators = generator_rows_by_type[generator_type]
        for pos, row in enumerate(_sorted_rows(_book_rows(model_book, block_name)), start=1):
            source = generators.get(str(row.get(reference_field, "")))
            if source is None:
                continue
            source_name = str(source.get("name", "")).strip()
            if not source_name:
                continue
            soc_max = _storage_soc_ratio_from_text(row.get("soc_upper_limit"), None)
            soc_cur = _storage_soc_ratio_from_text(row.get("state_of_charge"), None)
            storage_rows.append(
                {
                    "id": row.get("idx", pos),
                    "name": source_name,
                    "dev_type": generator_type,
                    "source_name": source_name,
                    "emva": _numeric_from_text(row.get("energy_capacity"), DEFAULT_STORAGE_CAPACITY_KWH) or DEFAULT_STORAGE_CAPACITY_KWH,
                    "soc_max": 1.0 if soc_max is None else soc_max,
                    "soc_min": _storage_soc_ratio_from_text(row.get("soc_lower_limit"), 0.0) or 0.0,
                    "soc_cur": 0.5 if soc_cur is None else soc_cur,
                    "charge_p_max": _numeric_from_text(row.get("max_charge_power"), 0.0) or 0.0,
                    "dis_charge_p_max": _numeric_from_text(row.get("max_discharge_power"), 0.0) or 0.0,
                    "charge_discharge_efficiency": _efficiency_from_text(row.get("charge_discharge_efficiency"), 1.0),
                }
            )

    diesel_seen: set[Tuple[str, str]] = set()
    for block_name, generators, generator_type, reference_field in (
        ("ACDieselGen", ac_generators, "ACGenerator", "idx_acgenerator"),
        ("DCDieselGen", dc_generators, "DCGenerator", "idx_dcgenerator"),
    ):
        for pos, parameter in enumerate(_sorted_rows(_book_rows(model_book, block_name)), start=1):
            source = generators.get(str(parameter.get(reference_field, "")))
            if source is None:
                continue
            name = str(source.get("name", "")).strip()
            key = (generator_type, name)
            if not name or key in diesel_seen:
                continue
            diesel_seen.add(key)
            p_max = (
                _positive_numeric(parameter.get("rated_power"), None)
                or _positive_numeric(parameter.get("p_max"), None)
                or _positive_numeric(source.get("rated_capacity"), None)
                or _positive_numeric(source.get("p_max"), None)
                or _positive_numeric(source.get("rated_power"), None)
                or _positive_numeric(source.get("p_set"), None)
                or 0.0
            )
            diesel_rows.append(
                {
                    "id": parameter.get("idx", pos),
                    "name": name,
                    "source_name": name,
                    "dev_type": generator_type,
                    "p_max": p_max,
                    "p_min": _numeric_from_text(parameter.get("p_min", source.get("p_min")), 0.0) or 0.0,
                }
            )

    return EBook(
        {
            "wind_generator": wind_rows,
            "pv_generator": pv_rows,
            "diesel_generator": diesel_rows,
            "estorage": storage_rows,
        }
    )


def _capability_define_book(model_book: EBook, dev_define_file: Optional[Path] = None) -> EBook:
    dev_define = _read_optional_book(dev_define_file)
    legacy_blocks = {"wind_generator", "pv_generator", "diesel_generator", "estorage", "load_curve_96", "load_temperature"}
    if any(name in dev_define.data for name in legacy_blocks):
        return dev_define
    embedded = _embedded_device_define_book(model_book)
    if any(getattr(block, "data", []) for block in embedded.data.values()):
        return embedded
    return dev_define


def _storage_soc_block(book: EBook):
    return book.data.get("StorageSoc") or book.data.get("StorageStatus")


def _storage_soc_rows(book: EBook) -> List[dict]:
    block = _storage_soc_block(book)
    return [] if block is None else list(block.data)


def _hydrogen_storage_state_block(book: EBook):
    return book.data.get(HYDROGEN_STORAGE_STATE_BLOCK)


def _hydrogen_storage_rows(model_book: EBook) -> List[dict]:
    block = model_book.data.get("HydroStorage")
    return [] if block is None else list(getattr(block, "data", []))


def _hydrogen_storage_initial_press(row: Mapping[str, Any]) -> Optional[float]:
    for field in ("press", "pressure"):
        value = _safe_float(row.get(field), None)
        if value is not None and math.isfinite(value):
            return float(value)
    return None


def _hydrogen_storage_water_volume(row: Mapping[str, Any]) -> Optional[float]:
    value = _safe_float(row.get("water_volume"), None)
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def _hydrogen_storage_initial_quantity(row: Mapping[str, Any]) -> Optional[float]:
    value = _safe_float(row.get("gas_quantity"), None)
    if value is not None and math.isfinite(value):
        return float(value)
    press = _hydrogen_storage_initial_press(row)
    water_volume = _hydrogen_storage_water_volume(row)
    if press is None or water_volume is None or water_volume <= 0.0:
        return None
    return press * water_volume / 0.1


def _hydrogen_storage_press_max(row: Mapping[str, Any]) -> Optional[float]:
    for field in ("press_max", "pressure_max"):
        value = _safe_float(row.get(field), None)
        if value is not None and math.isfinite(value):
            return float(value)
    return None


def _hydrogen_storage_soc(press: float, model_row: Mapping[str, Any]) -> Optional[float]:
    press_max = _hydrogen_storage_press_max(model_row)
    if press_max is None or press_max <= 0.0:
        return None
    return float(press) / press_max


def _hydrogen_storage_state_key(row: Mapping[str, Any]) -> Tuple[str, str]:
    name = str(row.get("name", row.get("dev_name", ""))).strip()
    if name:
        return ("name", name)
    return ("idx", str(row.get("idx", "")).strip())


def ensure_hydrogen_storage_state_rows_book(stat_book: EBook, model_book: EBook) -> int:
    model_rows = _hydrogen_storage_rows(model_book)
    if not model_rows:
        return 0
    block = _hydrogen_storage_state_block(stat_book)
    if block is None:
        template = EBook(
            {
                HYDROGEN_STORAGE_STATE_BLOCK: [
                    {header: "" for header in HYDROGEN_STORAGE_STATE_HEADERS}
                ]
            }
        )
        block = template.data[HYDROGEN_STORAGE_STATE_BLOCK]
        block.data.clear()
        stat_book.data[HYDROGEN_STORAGE_STATE_BLOCK] = block
    for header in HYDROGEN_STORAGE_STATE_HEADERS:
        if header not in block.header_list:
            block.header_list.append(header)

    existing = {
        _hydrogen_storage_state_key(row): row
        for row in block.data
        if any(str(row.get(field, "")).strip() for field in ("name", "dev_name", "idx"))
    }
    changed = 0
    for pos, model_row in enumerate(model_rows, start=1):
        key = _hydrogen_storage_state_key(model_row)
        state = existing.get(key)
        if state is None:
            state = {
                "dev_type": "HydroStorage",
                "idx": model_row.get("idx", pos),
                "name": model_row.get("name", ""),
                "press": "",
                "flow": "0",
                "gas_quantity": "",
                "soc": "",
            }
            block.data.append(state)
            existing[key] = state
            changed += 1
        changed += _set_row_value(state, "dev_type", "HydroStorage")
        changed += _set_row_value(state, "idx", model_row.get("idx", pos))
        changed += _set_row_value(state, "name", model_row.get("name", ""))
        if state.get("press", "") == "":
            initial_press = _hydrogen_storage_initial_press(model_row)
            if initial_press is not None:
                changed += _set_row_value(state, "press", format_number(initial_press))
        if state.get("flow", "") == "":
            changed += _set_row_value(state, "flow", "0")
        if state.get("gas_quantity", "") == "":
            initial_quantity = _hydrogen_storage_initial_quantity(model_row)
            if initial_quantity is not None:
                changed += _set_row_value(
                    state,
                    "gas_quantity",
                    format_number(initial_quantity),
                )
        if state.get("soc", "") == "":
            initial_press = _safe_float(state.get("press"), None)
            initial_soc = (
                _hydrogen_storage_soc(initial_press, model_row)
                if initial_press is not None
                else None
            )
            if initial_soc is not None:
                changed += _set_row_value(state, "soc", format_number(initial_soc))
    return changed


def hydrogen_storage_state_values_from_book(
    stat_book: Optional[EBook],
) -> Dict[object, Dict[str, float]]:
    if stat_book is None:
        return {}
    block = _hydrogen_storage_state_block(stat_book)
    result: Dict[object, Dict[str, float]] = {}
    for row in getattr(block, "data", []):
        name = str(row.get("name", row.get("dev_name", ""))).strip()
        if not name:
            continue
        values: Dict[str, float] = {}
        for field in ("press", "flow", "gas_quantity", "soc"):
            value = _safe_float(row.get(field), None)
            if value is not None and math.isfinite(value):
                values[field] = float(value)
        if not values:
            continue
        result[("HydroStorage", name)] = values
        result[name] = values
    return result


def apply_hydrogen_storage_state_book(model_book: EBook, stat_book: Optional[EBook]) -> int:
    state_values = hydrogen_storage_state_values_from_book(stat_book)
    changed = 0
    for row in _hydrogen_storage_rows(model_book):
        name = str(row.get("name", "")).strip()
        values = state_values.get(("HydroStorage", name))
        if values is None:
            continue
        for field in ("press", "flow", "gas_quantity", "soc"):
            if field in values:
                changed += _set_row_value(row, field, format_number(values[field]))
        if (
            "press" in values
            and str(row.get("control_type", "")).strip().upper() == "PRESSURE"
        ):
            changed += _set_row_value(
                row,
                "pressure_set",
                format_number(values["press"]),
            )
    return changed


def integrate_hydrogen_storage_state(
    *,
    press: float,
    gas_quantity: float,
    flow: float,
    period_seconds: float,
    water_volume: float,
) -> Tuple[float, float]:
    water_volume = float(water_volume)
    if not math.isfinite(water_volume) or water_volume <= 0.0:
        raise ValueError("HydroStorage water_volume must be greater than zero")
    period_hours = max(0.0, float(period_seconds)) / 3600.0
    quantity_delta = float(flow) * period_hours
    return (
        float(press) - quantity_delta / water_volume * 0.1,
        float(gas_quantity) - quantity_delta,
    )


def _snapshot_hydrogen_storage_flow_by_name(snapshot: Any) -> Dict[str, float]:
    fluid_results = getattr(snapshot, "fluid_results", {}) or {}
    hydro_result = (
        fluid_results.get("hydro")
        if isinstance(fluid_results, Mapping)
        else getattr(fluid_results, "hydro", None)
    )
    storages = getattr(hydro_result, "storages", {}) if hydro_result is not None else {}
    flows: Dict[str, float] = {}
    for name, result in getattr(storages, "items", lambda: ())():
        flow = _safe_float(getattr(result, "flow", None), None)
        if flow is not None and math.isfinite(flow):
            flows[str(name)] = float(flow)
    return flows


def update_hydrogen_storage_state_book(
    stat_book: EBook,
    model_book: EBook,
    period_seconds: float,
    *,
    snapshot: Any,
) -> int:
    changed = ensure_hydrogen_storage_state_rows_book(stat_book, model_book)
    block = _hydrogen_storage_state_block(stat_book)
    if block is None:
        return changed
    model_by_key = {
        _hydrogen_storage_state_key(row): row
        for row in _hydrogen_storage_rows(model_book)
    }
    flow_by_name = _snapshot_hydrogen_storage_flow_by_name(snapshot)
    period_hours = max(0.0, float(period_seconds)) / 3600.0
    for state in block.data:
        model_row = model_by_key.get(_hydrogen_storage_state_key(state))
        if model_row is None:
            continue
        name = str(model_row.get("name", "")).strip()
        flow = flow_by_name.get(name)
        if flow is None:
            if _safe_int(model_row.get("run_stat", 1), 1) == 0:
                changed += _set_row_value(state, "flow", "0")
            continue
        changed += _set_row_value(state, "flow", format_number(flow))
        gas_quantity = _safe_float(state.get("gas_quantity"), None)
        if gas_quantity is None:
            gas_quantity = _hydrogen_storage_initial_quantity(model_row)
        if gas_quantity is not None and math.isfinite(gas_quantity):
            changed += _set_row_value(
                state,
                "gas_quantity",
                format_number(float(gas_quantity) - flow * period_hours),
            )
        press = _safe_float(state.get("press"), None)
        if press is None:
            press = _hydrogen_storage_initial_press(model_row)
        water_volume = _hydrogen_storage_water_volume(model_row)
        if water_volume is None or water_volume <= 0.0:
            LOGGER.warning(
                "HydroStorage %s has invalid water_volume=%r; pressure integration skipped",
                name,
                model_row.get("water_volume"),
            )
            continue
        if press is None or not math.isfinite(press):
            LOGGER.warning(
                "HydroStorage %s has no valid initial press; pressure integration skipped",
                name,
            )
            continue
        next_press = float(press) - flow * period_hours / water_volume * 0.1
        changed += _set_row_value(state, "press", format_number(next_press))
        next_soc = _hydrogen_storage_soc(next_press, model_row)
        if next_soc is None:
            LOGGER.warning(
                "HydroStorage %s has invalid press_max=%r; SOC update skipped",
                name,
                model_row.get("press_max", model_row.get("pressure_max")),
            )
        else:
            changed += _set_row_value(state, "soc", format_number(next_soc))
    changed += apply_hydrogen_storage_state_book(model_book, stat_book)
    return changed


def reset_hydrogen_storage_state_book(stat_book: EBook, model_book: EBook) -> int:
    changed = ensure_hydrogen_storage_state_rows_book(stat_book, model_book)
    block = _hydrogen_storage_state_block(stat_book)
    if block is None:
        return changed
    model_by_key = {
        _hydrogen_storage_state_key(row): row
        for row in _hydrogen_storage_rows(model_book)
    }
    for state in block.data:
        model_row = model_by_key.get(_hydrogen_storage_state_key(state))
        if model_row is None:
            continue
        initial_press = _hydrogen_storage_initial_press(model_row)
        initial_quantity = _hydrogen_storage_initial_quantity(model_row)
        initial_soc = (
            _hydrogen_storage_soc(initial_press, model_row)
            if initial_press is not None
            else None
        )
        changed += _set_row_value(
            state,
            "press",
            "" if initial_press is None else format_number(initial_press),
        )
        changed += _set_row_value(state, "flow", "0")
        changed += _set_row_value(
            state,
            "gas_quantity",
            "" if initial_quantity is None else format_number(initial_quantity),
        )
        changed += _set_row_value(
            state,
            "soc",
            "" if initial_soc is None else format_number(initial_soc),
        )
    changed += apply_hydrogen_storage_state_book(model_book, stat_book)
    return changed


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


def _source_model_row(
    model_book: EBook,
    model_block: str,
    name: str,
    source_index: object = "",
) -> Optional[dict]:
    """Resolve an exact model row or one explicit parameter-table alias."""
    target = _model_row(model_book, model_block, name)
    if target is not None:
        return target
    index_text = str(source_index or "").strip()
    candidates = []
    for resource in structured_resources(model_book):
        if index_text and resource.source_index != index_text:
            continue
        if name and name not in resource_aliases(resource):
            continue
        candidates.append(resource.source)
    return candidates[0] if len(candidates) == 1 else None


def compile_measurement_bindings(
    measurement_rows: Sequence[Sequence[str]],
    model_book: Optional[EBook],
) -> Tuple[MeasurementBinding, ...]:
    if model_book is None:
        return tuple(
            MeasurementBinding(str(row[2]), str(row[3]), False)
            for row in measurement_rows
        )

    model_rows_by_key: Dict[Tuple[str, str], dict] = {}
    for block_name, block in model_book.data.items():
        for model_row in getattr(block, "data", []):
            name = str(model_row.get("name", ""))
            if name:
                model_rows_by_key[(str(block_name), name)] = model_row

    resources = structured_resources(model_book)
    resource_key_by_source_id = {
        id(resource.source): resource.device_key
        for resource in resources
    }
    alias_sources: Dict[str, Dict[int, dict]] = {}
    for resource in resources:
        for alias in resource_aliases(resource):
            alias_sources.setdefault(alias, {})[id(resource.source)] = resource.source

    bindings: List[MeasurementBinding] = []
    for row in measurement_rows:
        dev_type = str(row[2]) if len(row) > 2 else ""
        dev_name = str(row[3]) if len(row) > 3 else ""
        target = model_rows_by_key.get((dev_type, dev_name))
        if target is None:
            candidates = list(alias_sources.get(dev_name, {}).values())
            target = candidates[0] if len(candidates) == 1 else None
        target_key = resource_key_by_source_id.get(id(target)) if target is not None else None
        bindings.append(
            MeasurementBinding(
                target_type=target_key[0] if target_key is not None else dev_type,
                target_name=target_key[1] if target_key is not None else dev_name,
                target_present=target is not None,
            )
        )
    return tuple(bindings)


def _stat_dev_name(row: dict) -> str:
    return str(row.get("dev_name", row.get("name", "")))


def _is_converter_control_target(row: dict) -> bool:
    """Recognize a converter from its terminal/control structure."""
    return bool(
        ("ac_node" in row and "dc_node" in row)
        or "p_ac_set" in row
        or "p_dc_set" in row
    )


def _apply_setpoint_row(model_book: EBook, row: dict) -> int:
    dev_type = str(row.get("dev_type", ""))
    target = _source_model_row(
        model_book,
        dev_type,
        _stat_dev_name(row),
        row.get("idx", ""),
    )
    if target is None:
        return 0
    changed = 0
    if _is_converter_control_target(target):
        power_field = converter_active_power_setpoint_field(target) or "p_ac_set"
        mapping = {"p_set": power_field, "q_set": "q_ac_set", "v_set": "v_ac_set"}
    else:
        mapping = {"p_set": "p_set", "q_set": "q_set", "v_set": "v_set"}
    for src, dst in mapping.items():
        value = row.get(src, "")
        if value != "":
            changed += _set_row_value(target, dst, value)
    if row.get("run_stat", "") != "":
        changed += _set_row_value(target, "run_stat", row["run_stat"])
    return changed


def _set_value_target_column(dev_type: str, set_type: str, target: Optional[dict] = None) -> str:
    del dev_type
    target = target or {}
    if _is_converter_control_target(target):
        power_field = converter_active_power_setpoint_field(target or {}) or "p_ac_set"
        return {
            "p_set": power_field,
            "q_set": "q_ac_set",
            "v_set": "v_ac_set",
            "p_ac_set": "p_ac_set",
            "p_dc_set": "p_dc_set",
            "q_ac_set": "q_ac_set",
            "v_ac_set": "v_ac_set",
            "v_dc_set": "v_dc_set",
        }.get(set_type, set_type)
    if set_type == "p_set" and target.get("p_set") not in (None, "", "-"):
        return "p_set"
    if "pv0" in target or "qv0" in target:
        return {"p_set": "pv0", "q_set": "qv0", "pv0": "pv0", "qv0": "qv0"}.get(set_type, set_type)
    return set_type


def _apply_set_value_row(model_book: EBook, row: dict) -> int:
    dev_type = str(row.get("dev_type", ""))
    target = _source_model_row(
        model_book,
        dev_type,
        _stat_dev_name(row),
        row.get("idx", ""),
    )
    if target is None:
        return 0
    set_type = str(row.get("set_type", ""))
    if set_type == "":
        return 0
    value = row.get("set_value", "")
    if value == "":
        return 0
    target_column = _set_value_target_column(dev_type, set_type, target)
    return _set_row_value(target, target_column, value)


def _run_stat_by_name(stat_book: EBook) -> Dict[Tuple[str, str], str]:
    block = stat_book.data.get("RunStat")
    if block is None:
        return {}
    rows = {}
    for row in block.data:
        rows[(str(row.get("dev_type", "")), _stat_dev_name(row))] = str(row.get("run_stat", ""))
    return rows


def _apply_real_bus_node_constraints(model_book: EBook) -> int:
    changed = 0
    for real_bus_type, node_type in (("ACRealBs", "ACNode"), ("DCRealBs", "DCNode")):
        real_bus_block = model_book.data.get(real_bus_type)
        node_block = model_book.data.get(node_type)
        if real_bus_block is None:
            continue

        node_by_idx = (
            {
                _safe_int(row.get("idx"), -1): row
                for row in node_block.data
                if _safe_int(row.get("idx"), -1) >= 0
            }
            if node_block is not None
            else {}
        )
        all_busbars_running: Dict[int, bool] = {}
        for busbar in real_bus_block.data:
            node_idx = _safe_int(busbar.get("node"), -1)
            node = node_by_idx.get(node_idx)
            if node is None:
                LOGGER.warning(
                    "%s.%s references missing %s[%s]",
                    real_bus_type,
                    busbar.get("name", busbar.get("idx", "")),
                    node_type,
                    busbar.get("node", ""),
                )
                continue
            all_busbars_running[node_idx] = (
                all_busbars_running.get(node_idx, True)
                and _safe_int(busbar.get("run_stat", 1), 1) == 1
            )

        for node_idx, busbars_running in all_busbars_running.items():
            node = node_by_idx[node_idx]
            own_running = _safe_int(node.get("run_stat", 1), 1) == 1
            changed += _set_row_value(
                node,
                "run_stat",
                1 if own_running and busbars_running else 0,
            )
    return changed


def apply_dev_stat_file(model_book: EBook, dev_stat_file: Path) -> int:
    dev_stat_file = Path(dev_stat_file)
    if not dev_stat_file.exists():
        return 0
    return apply_dev_stat_book(model_book, EBook(dev_stat_file))


def apply_dev_stat_book(model_book: EBook, stat_book: EBook) -> int:
    run_stats = _run_stat_by_name(stat_book)
    changed = 0

    block = stat_book.data.get("RunStat")
    if block is not None:
        for row in block.data:
            target = _source_model_row(
                model_book,
                str(row.get("dev_type", "")),
                _stat_dev_name(row),
                row.get("idx", ""),
            )
            if target is not None and row.get("run_stat", "") != "":
                changed += _set_row_value(target, "run_stat", row.get("run_stat", ""))

    block = stat_book.data.get("DeviceRunStatus")
    if block is not None:
        for row in block.data:
            target = _source_model_row(
                model_book,
                str(row.get("dev_type", "")),
                _stat_dev_name(row),
                row.get("idx", ""),
            )
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
            if "pv0" in target or "qv0" in target:
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
        storage_targets = _storage_target_rows(model_book, EBook({}))
        for row in block.data:
            resolved = _storage_target_for_identity(row, storage_targets)
            if resolved is None:
                continue
            source_block, target, _name, _define, _pos = resolved
            run_stat = row.get("run_stat", "")
            if run_stat == "":
                run_stat = run_stats.get(
                    (source_block, str(target.get("name", ""))),
                    "",
                )
            if run_stat != "":
                changed += _set_row_value(target, "run_stat", run_stat)
    changed += _apply_real_bus_node_constraints(model_book)
    return changed


def apply_mode_file(model_book: EBook, mode_file: Optional[Path]) -> int:
    if mode_file is None:
        return 0
    mode_file = Path(mode_file)
    if not mode_file.exists():
        return 0
    return apply_mode_book(model_book, EBook(mode_file))


def apply_mode_book(model_book: EBook, mode_book: Optional[EBook]) -> int:
    if mode_book is None:
        return 0
    changed = 0
    for block_name in ("ControlMode", "DeviceMode", "Mode"):
        block = mode_book.data.get(block_name)
        if block is None:
            continue
        for row in block.data:
            dev_type = str(row.get("dev_type", row.get("type", "")))
            dev_name = _stat_dev_name(row)
            mode_value = str(row.get("mode", row.get("control_type", row.get("ctrl_mode", ""))))
            if not dev_type or not dev_name or not mode_value:
                continue
            target = _source_model_row(
                model_book,
                dev_type,
                dev_name,
                row.get("idx", ""),
            )
            if target is None:
                continue
            for column in ("control_type", "mode", "ctrl_mode"):
                if column in target:
                    changed += _set_row_value(target, column, mode_value)
                    break
    return changed


def _weather_values(weather_file: Path) -> Dict[str, float]:
    weather_file = Path(weather_file)
    if not weather_file.exists():
        return {}
    return _weather_values_from_book(EBook(weather_file))


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
    raw_pbase = _safe_float(row.get("pbase", 1.0), 1.0)
    raw_qbase = _safe_float(row.get("qbase", 1.0), 1.0)
    pbase = raw_pbase if raw_pbase is not None and raw_pbase > 0.0 else 1.0
    qbase = raw_qbase if raw_qbase is not None and raw_qbase > 0.0 else 0.0
    p = pbase * (_safe_float(row.get("pv0", 0.0), 0.0) or 0.0)
    q = qbase * (_safe_float(row.get("qv0", 0.0), 0.0) or 0.0)
    return p, q, pbase, qbase


def _load_write_base(row: dict, column: str) -> Tuple[float, int]:
    base = _safe_float(row.get(column, 1.0), 1.0)
    if base is None or base <= 0.0:
        return 1.0, _set_row_value(row, column, "1")
    return base, 0


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


def _coupled_electric_load_keys(model_book: EBook) -> set[Tuple[str, str]]:
    return {
        (
            str(binding.get("target_dev_type", "")),
            str(binding.get("target_dev_name", "")),
        )
        for bindings in energy_coupling_control_bindings(model_book).values()
        for binding in bindings
        if binding.get("set_type") == "p_set"
        and binding.get("target_dev_type") in {"ACLoad", "DCLoad"}
    }


def apply_load_model(model_book: EBook, dev_define: EBook, weather: Dict[str, float]) -> int:
    block = model_book.data.get("ACLoad")
    if block is None or not block.data:
        return 0
    if "load_kw" not in weather and "air_temp_c" not in weather and "time_minutes" not in weather:
        return 0

    weighted = []
    total_p = 0.0
    coupled_loads = _coupled_electric_load_keys(model_book)
    for pos, row in enumerate(_sorted_rows(block.data)):
        if ("ACLoad", str(row.get("name", ""))) in coupled_loads:
            continue
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
        pbase, base_changed = _load_write_base(row, "pbase")
        changed += base_changed
        qbase, base_changed = _load_write_base(row, "qbase")
        changed += base_changed
        changed += _set_row_value(row, "pv0", _format_power(p * scale / pbase))
        changed += _set_row_value(row, "qv0", _format_power(q * scale / qbase))
    return changed


def apply_load_power_targets(model_book: EBook, targets: Sequence[Mapping[str, object]]) -> int:
    """Apply per-device AC/DC load powers captured from the live curve editor."""

    changed = 0
    coupled_loads = _coupled_electric_load_keys(model_book)
    for target in targets:
        block_name = str(target.get("dev_type", "")).strip()
        load_name = str(target.get("dev_name", "")).strip()
        desired_p = _safe_float(target.get("p_kw"), None)
        if block_name not in {"ACLoad", "DCLoad"} or not load_name or desired_p is None:
            continue
        if (block_name, load_name) in coupled_loads:
            continue
        block = model_book.data.get(block_name)
        if block is None:
            continue
        row = next((item for item in block.data if str(item.get("name", "")) == load_name), None)
        if row is None:
            continue

        desired_p = max(0.0, desired_p)
        if block_name == "ACLoad":
            current_p, current_q, _pbase, _qbase = _load_power(row)
            reactive_ratio = current_q / current_p if abs(current_p) > 1e-12 else 0.0
            pbase, base_changed = _load_write_base(row, "pbase")
            changed += base_changed
            changed += _set_row_value(row, "pv0", _format_power(desired_p / pbase))
            qbase, base_changed = _load_write_base(row, "qbase")
            changed += base_changed
            changed += _set_row_value(row, "qv0", _format_power(desired_p * reactive_ratio / qbase))
        else:
            pbase, base_changed = _load_write_base(row, "pbase")
            changed += base_changed
            changed += _set_row_value(row, "pv0", _format_power(desired_p / pbase))
    return changed


def _target_rows(model_book: EBook, table_name: str) -> List[dict]:
    block = model_book.data.get(table_name)
    if block is None:
        return []
    return _sorted_rows(list(block.data))


def _renewable_target_rows(
    model_book: EBook,
    dev_define: EBook,
    define_table: str,
    model_tables: Sequence[str],
) -> List[Tuple[str, dict, Optional[dict], int]]:
    """Resolve capability targets only through model parameter references."""
    technology = {
        "wind_generator": "wind",
        "pv_generator": "pv",
        "diesel_generator": "diesel",
    }.get(define_table, "")
    if not technology:
        return []
    allowed_blocks = set(model_tables)
    return [
        (
            resource.source_block,
            resource.source,
            resource.parameter,
            position,
        )
        for position, resource in enumerate(structured_resources(model_book))
        if resource.technology == technology
        and resource.source_block in allowed_blocks
    ]


def _available_with_bounds(raw_available: float, define: Optional[dict]) -> float:
    if define is None:
        return max(0.0, raw_available)
    p_min = _safe_float(define.get("p_min", 0.0), 0.0) or 0.0
    p_max = _safe_float(define.get("p_max", raw_available), raw_available) or raw_available
    if raw_available <= 0.0:
        return 0.0
    return _clamp(raw_available, p_min, p_max)


def _limit_positive_setpoint(row: dict, column: str, available: float, has_active_control: bool) -> int:
    if not _is_running_row(row):
        return _set_row_value(row, column, "0")
    if not has_active_control:
        return _set_row_value(row, column, _format_power(available))
    command = _safe_float(row.get(column, 0.0), 0.0) or 0.0
    return _set_row_value(row, column, _format_power(_clamp(command, 0.0, available)))


def apply_wind_limits(
    model_book: EBook,
    dev_define: EBook,
    weather: Dict[str, float],
    active_power_controls: Optional[set[Tuple[str, str]]] = None,
) -> int:
    if "wind_speed_mps" not in weather:
        return 0
    rows = _renewable_target_rows(
        model_book,
        dev_define,
        "wind_generator",
        ("ACGenerator", "DCGenerator"),
    )
    changed = 0
    active_power_controls = active_power_controls or set()
    for table_name, row, define, _pos in rows:
        rated = _wind_rated_power_kw(row, define)
        rated_speed = _safe_float((define or {}).get("rated_wind_speed", 15.0), 15.0) or 15.0
        cut_in = _safe_float(
            (define or {}).get("cut_in_speed", (define or {}).get("cut_in_wind_speed", 5.0)),
            5.0,
        ) or 5.0
        cut_out = _safe_float(
            (define or {}).get("cut_out_speed", (define or {}).get("cut_out_wind_speed", 30.0)),
            30.0,
        ) or 30.0
        available = _available_with_bounds(wind_available_power(weather["wind_speed_mps"], rated, rated_speed, cut_in, cut_out), define)
        column = "p_ac_set" if "p_ac_set" in row else "p_set"
        target = (table_name, str(row.get("name", "")))
        changed += _limit_positive_setpoint(row, column, available, target in active_power_controls)
    return changed


def apply_pv_limits(
    model_book: EBook,
    dev_define: EBook,
    weather: Dict[str, float],
    active_power_controls: Optional[set[Tuple[str, str]]] = None,
) -> int:
    if "solar_irradiance_w_m2" not in weather:
        return 0
    rows = _renewable_target_rows(
        model_book,
        dev_define,
        "pv_generator",
        ("ACGenerator", "DCGenerator"),
    )
    changed = 0
    air_temp = weather.get("air_temp_c", 25.0)
    active_power_controls = active_power_controls or set()
    for table_name, row, define, _pos in rows:
        rated = _pv_rated_power_kw(row, define)
        temp_coef = _safe_float((define or {}).get("temp_coefficient", 0.0), 0.0) or 0.0
        ref_irrad = _safe_float((define or {}).get("reference_irradiance", 1000.0), 1000.0) or 1000.0
        ref_temp = _safe_float((define or {}).get("reference_temperature", 25.0), 25.0) or 25.0
        available = _available_with_bounds(
            pv_available_power(weather["solar_irradiance_w_m2"], air_temp, rated, temp_coef, ref_irrad, ref_temp),
            define,
        )
        target = (table_name, str(row.get("name", "")))
        changed += _limit_positive_setpoint(row, "p_set", available, target in active_power_controls)
    return changed


def apply_diesel_limits(model_book: EBook, dev_define: EBook) -> int:
    rows = _renewable_target_rows(
        model_book,
        dev_define,
        "diesel_generator",
        ("ACGenerator", "DCGenerator"),
    )
    changed = 0
    for _table_name, row, define, _pos in rows:
        if not _is_running_row(row):
            changed += _set_row_value(row, "p_set", "0")
            continue
        command = _safe_float(row.get("p_set", 0.0), 0.0) or 0.0
        p_min = _safe_float((define or {}).get("p_min", row.get("p_min")), None)
        p_max = _safe_float((define or {}).get("p_max", row.get("p_max")), None)
        if p_min is None or p_max is None or p_min < 0.0 or p_max < p_min:
            target = 0.0
        else:
            # An online diesel is either stopped through run_stat or operated
            # inside its declared stable-power interval.  A zero/negative P
            # request must not bypass the minimum stable generation limit.
            target = _clamp(command, p_min, p_max)
        changed += _set_row_value(row, "p_set", _format_power(target))
    return changed


def _storage_soc_by_name(dev_stat_file: Path) -> Tuple[Dict[str, dict], List[dict]]:
    stat_book = _read_optional_book(dev_stat_file)
    return _storage_soc_by_name_book(stat_book)


def _storage_soc_by_name_book(stat_book: EBook) -> Tuple[Dict[str, dict], List[dict]]:
    run_stat = _run_stat_by_name(stat_book)
    rows = []
    for row in _sorted_rows(_storage_soc_rows(stat_book)):
        item = dict(row)
        storage_name = str(item.get("name", item.get("dev_name", "")))
        item_type = str(item.get("dev_type", "")).strip()
        value = run_stat.get((item_type, storage_name))
        if value is not None and item.get("run_stat", "") == "":
            item["run_stat"] = value
        rows.append(item)
    by_name: Dict[str, dict] = {}
    ambiguous: set[str] = set()
    for row in rows:
        name = str(row.get("name", row.get("dev_name", "")))
        if name in ambiguous:
            continue
        if name in by_name:
            by_name.pop(name, None)
            ambiguous.add(name)
            continue
        by_name[name] = row
    return by_name, rows


def _storage_target_key(target: StorageTarget) -> Tuple[str, str]:
    source_block, row, _storage_name, _define, _pos = target
    return source_block, str(row.get("idx", "")).strip()


def _storage_target_for_identity(row: Mapping[str, object], targets: Sequence[StorageTarget]) -> Optional[StorageTarget]:
    source_block = str(row.get("dev_type", "")).strip()
    source_index = str(row.get("idx", "")).strip()
    name = str(row.get("name", row.get("dev_name", ""))).strip()
    if source_block and name:
        matches = [
            target
            for target in targets
            if _storage_target_key(target)[0] == source_block
            and name in _storage_target_lookup_names(target, targets)
        ]
        if len(matches) == 1:
            return matches[0]
    if source_block and source_index:
        matches = [
            target
            for target in targets
            if _storage_target_key(target) == (source_block, source_index)
        ]
        if len(matches) == 1:
            return matches[0]
    if source_index:
        matches = [
            target
            for target in targets
            if _storage_target_key(target)[1] == source_index
        ]
        if len(matches) == 1:
            return matches[0]
    if not name:
        return None
    matches = [
        target
        for target in targets
        if name in _storage_target_lookup_names(target, targets)
    ]
    return matches[0] if len(matches) == 1 else None


def _storage_target_lookup_names(
    target: StorageTarget,
    targets: Sequence[StorageTarget],
) -> List[str]:
    del targets
    _source_block, source, storage_name, define, _pos = target
    aliases = [str(source.get("name", "")).strip(), str(storage_name).strip()]
    for value in (define or {}).get("explicit_aliases", ()):  # type: ignore[union-attr]
        aliases.append(str(value or "").strip())
    return _unique_names(*aliases)


def _storage_status_for_target(
    target: StorageTarget,
    targets: Sequence[StorageTarget],
    status_by_name: Mapping[str, dict],
    status_rows: Sequence[dict],
) -> Optional[dict]:
    target_key = _storage_target_key(target)
    for status in status_rows:
        resolved = _storage_target_for_identity(status, targets)
        if resolved is not None and _storage_target_key(resolved) == target_key:
            return status
    return None


def _storage_target_rows(model_book: EBook, dev_define: EBook) -> List[StorageTarget]:
    """Return storage targets resolved only by AC/DC storage reference rows."""
    targets: List[StorageTarget] = []
    for position, resource in enumerate(structured_resources(model_book)):
        if resource.technology != "storage":
            continue
        parameter = dict(resource.parameter)
        soc_cur = _storage_soc_ratio_from_text(
            parameter.get("state_of_charge", parameter.get("soc_curr")),
            None,
        )
        soc_min = _storage_soc_ratio_from_text(
            parameter.get("soc_lower_limit", parameter.get("soc_min")),
            0.0,
        )
        soc_max = _storage_soc_ratio_from_text(
            parameter.get("soc_upper_limit", parameter.get("soc_max")),
            None,
        )
        define = {
            **parameter,
            "id": parameter.get("idx", position + 1),
            "name": resource.source_name,
            "source_name": resource.source_name,
            "source_block": resource.source_block,
            "source_idx": resource.source_index,
            "explicit_aliases": resource_aliases(resource),
            "soc_cur": 0.5 if soc_cur is None else soc_cur,
            "soc_min": 0.0 if soc_min is None else soc_min,
            "soc_max": 1.0 if soc_max is None else soc_max,
            "emva": _numeric_from_text(
                parameter.get("energy_capacity", parameter.get("emva")),
                DEFAULT_STORAGE_CAPACITY_KWH,
            ),
            "charge_p_max": _numeric_from_text(
                parameter.get("max_charge_power", parameter.get("charge_p_max")),
                0.0,
            ),
            "dis_charge_p_max": _numeric_from_text(
                parameter.get("max_discharge_power", parameter.get("dis_charge_p_max")),
                0.0,
            ),
            "charge_discharge_efficiency": _efficiency_from_text(
                parameter.get("charge_discharge_efficiency"),
                1.0,
            ),
        }
        targets.append(
            (
                resource.source_block,
                resource.source,
                resource.source_name,
                define,
                position,
            )
        )
    return targets


def _ensure_storage_soc_rows_book(stat_book: EBook, model_book: EBook, dev_define: EBook) -> int:
    targets = _storage_target_rows(model_book, dev_define)
    if not targets:
        return 0
    block = _storage_soc_block(stat_book)
    if block is None:
        template = EBook(
            {
                "StorageSoc": [
                    {"dev_type": "", "idx": "", "name": "", "soc_curr": ""}
                ]
            }
        )
        block = template.data["StorageSoc"]
        block.data.clear()
        stat_book.data["StorageSoc"] = block
    elif block.data:
        return 0

    status_by_name, status_rows = _storage_soc_by_name_book(stat_book)
    changed = 0
    for target in targets:
        if _storage_status_for_target(target, targets, status_by_name, status_rows) is not None:
            continue
        dev_type, source, _storage_name, define, pos = target
        initial_soc = _safe_float((define or {}).get("soc_cur"), None)
        if initial_soc is None:
            initial_soc = 0.5
        row = {
            "dev_type": dev_type,
            "idx": source.get("idx", (define or {}).get("id", pos + 1)),
            "name": source.get("name", ""),
            "soc_curr": format_number(initial_soc),
        }
        block.data.append(row)
        status_rows.append(dict(row))
        changed += 1
    return changed


def apply_storage_constraints(
    model_book: EBook,
    dev_stat_file: Path,
    dev_define: EBook,
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
) -> int:
    status_by_name, status_rows = _storage_soc_by_name(dev_stat_file)
    return apply_storage_constraints_book(model_book, status_by_name, status_rows, dev_define, period_seconds)


def apply_storage_constraints_book(
    model_book: EBook,
    status_by_name: Mapping[str, dict],
    status_rows: Sequence[dict],
    dev_define: EBook,
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
) -> int:
    changed = 0
    period_hours = max(0.0, float(period_seconds)) / 3600.0
    targets = _storage_target_rows(model_book, dev_define)
    for _dev_type, row, _storage_name, define, _pos in targets:
        target = (_dev_type, row, _storage_name, define, _pos)
        _ensure_power_bound_columns(model_book, _dev_type, row)
        status = _storage_status_for_target(target, targets, status_by_name, status_rows)
        run_stat = _safe_int((status or {}).get("run_stat", row.get("run_stat", 1)), 1)
        if run_stat != 1 or not _is_running_row(row):
            changed += _set_row_value(row, "p_min", _format_power(0.0))
            changed += _set_row_value(row, "p_max", _format_power(0.0))
            changed += _set_row_value(row, "p_set", "0")
            continue
        command = _safe_float(row.get("p_set", 0.0), 0.0) or 0.0
        soc = _safe_float((status or {}).get("soc_curr", (define or {}).get("soc_cur", 0.5)), 0.5)
        if soc is None:
            soc = 0.5
        soc_min = _safe_float((define or {}).get("soc_min", 0.0), 0.0) or 0.0
        soc_max = _safe_float((define or {}).get("soc_max", 1.0), None)
        if soc_max is None:
            soc_max = 1.0
        capacity = _safe_float((define or {}).get("emva", DEFAULT_STORAGE_CAPACITY_KWH), DEFAULT_STORAGE_CAPACITY_KWH)
        capacity = max(float(capacity if capacity is not None else DEFAULT_STORAGE_CAPACITY_KWH), 1e-9)
        charge_max = _safe_float((define or {}).get("charge_p_max", abs(command)), abs(command)) or 0.0
        discharge_max = _safe_float((define or {}).get("dis_charge_p_max", abs(command)), abs(command)) or 0.0
        charge_efficiency, discharge_efficiency = _storage_efficiencies(define)
        if period_hours > 0.0:
            discharge_soc_margin = max(0.0, float(soc) - soc_min)
            charge_soc_margin = max(0.0, soc_max - float(soc))
            discharge_max = min(discharge_max, discharge_soc_margin * capacity * discharge_efficiency / period_hours)
            charge_max = min(charge_max, charge_soc_margin * capacity / charge_efficiency / period_hours)
        # Keep the solver's instantaneous bounds consistent with the SOC gate.
        # Positive storage power is discharge and negative storage power is charge.
        if soc <= soc_min:
            discharge_max = 0.0
        if soc >= soc_max:
            charge_max = 0.0
        changed += _set_row_value(row, "p_min", _format_power(-max(0.0, charge_max)))
        changed += _set_row_value(row, "p_max", _format_power(max(0.0, discharge_max)))
        if command > 0.0:
            target = min(command, discharge_max)
        elif command < 0.0:
            target = max(command, -charge_max)
        else:
            target = 0.0
        changed += _set_row_value(row, "p_set", _format_power(target))
    return changed


def apply_acdc_limits(model_book: EBook) -> int:
    """Clamp explicit grid-intertie commands to declared bidirectional limits.

    ``p_ac_set`` is positive AC-to-DC; ``p_dc_set`` has the opposite sign and
    is positive DC-to-AC. Internal renewable/storage converters and converters
    without an explicit grid role are not automatic-dispatch actuators, so
    this pass leaves their setpoints untouched. An explicitly declared grid
    converter with invalid limits fails closed at zero.
    """
    changed = 0
    dispatchable_keys = grid_converter_keys(model_book)
    for converter_type in ("ACDCConverter", "DCACConverter"):
        for row in _target_rows(model_book, converter_type):
            if (converter_type, str(row.get("name", "")).strip()) not in dispatchable_keys:
                continue
            set_field = next(
                (
                    field
                    for field in converter_power_setpoint_fields(row)
                    if field in row
                ),
                "",
            )
            if not set_field:
                continue
            if not _is_running_row(row):
                changed += _set_row_value(row, set_field, "0")
                continue
            command = _safe_float(row.get(set_field, 0.0), 0.0) or 0.0
            if set_field == "p_dc_set":
                p_min = _safe_float(row.get("p_dc_min", row.get("dc_p_min")), None)
                p_max = _safe_float(row.get("p_dc_max", row.get("dc_p_max")), None)
                if p_min is None or p_max is None or p_min > p_max:
                    p_ac_min = _safe_float(
                        row.get("p_ac_min", row.get("ac_p_min")),
                        None,
                    )
                    p_ac_max = _safe_float(
                        row.get("p_ac_max", row.get("ac_p_max")),
                        None,
                    )
                    if (
                        p_ac_min is not None
                        and p_ac_max is not None
                        and p_ac_min <= p_ac_max
                    ):
                        p_min = -p_ac_max
                        p_max = -p_ac_min
            else:
                p_min = _safe_float(
                    row.get("p_ac_min", row.get("ac_p_min")),
                    None,
                )
                p_max = _safe_float(
                    row.get("p_ac_max", row.get("ac_p_max")),
                    None,
                )
            if p_min is None or p_max is None or p_min > p_max:
                target = 0.0
            else:
                target = _clamp(command, p_min, p_max)
            changed += _set_row_value(row, set_field, _format_power(target))
    return changed


def apply_dc_export_limits(
    model_book: EBook,
    dev_define: Optional[EBook] = None,
    efficiency: float = DEFAULT_DC_EXPORT_EFFICIENCY,
) -> int:
    """Compatibility entry point for the former one-way aggregate limiter."""
    del dev_define, efficiency
    return apply_acdc_limits(model_book)


def apply_device_capability_limits(
    model_book: EBook,
    weather_file: Path,
    dev_stat_file: Path,
    dev_define_file: Optional[Path],
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
    active_power_controls: Optional[set[Tuple[str, str]]] = None,
) -> int:
    dev_define = _capability_define_book(model_book, dev_define_file)
    if not dev_define.data:
        return 0
    weather = _weather_values(weather_file)
    stat_book = _read_optional_book(dev_stat_file)
    return apply_device_capability_limits_book(
        model_book,
        weather,
        stat_book,
        dev_define,
        period_seconds,
        active_power_controls,
    )


def apply_device_capability_limits_book(
    model_book: EBook,
    weather: Mapping[str, float],
    stat_book: EBook,
    dev_define: EBook,
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
    active_power_controls: Optional[set[Tuple[str, str]]] = None,
    *,
    apply_load_curves: bool = True,
) -> int:
    if not dev_define.data:
        return 0
    weather_values = dict(weather)
    _ensure_storage_soc_rows_book(stat_book, model_book, dev_define)
    status_by_name, status_rows = _storage_soc_by_name_book(stat_book)
    changed = 0
    if apply_load_curves:
        changed += apply_load_model(model_book, dev_define, weather_values)
    changed += apply_wind_limits(model_book, dev_define, weather_values, active_power_controls)
    changed += apply_pv_limits(model_book, dev_define, weather_values, active_power_controls)
    changed += apply_diesel_limits(model_book, dev_define)
    changed += apply_storage_constraints_book(model_book, status_by_name, status_rows, dev_define, period_seconds)
    changed += apply_acdc_limits(model_book)
    return changed


def apply_weather_file(model_book: EBook, weather_file: Path, dev_define_file: Optional[Path] = None) -> int:
    values = _weather_values(weather_file)
    dev_define = _capability_define_book(model_book, dev_define_file)
    return apply_weather_book(model_book, values, dev_define)


def apply_weather_book(
    model_book: EBook,
    values: Mapping[str, float],
    dev_define: Optional[EBook] = None,
    *,
    apply_load_curves: bool = True,
) -> int:
    if not values:
        return 0
    dev_define = dev_define or EBook({})
    values = dict(values)
    if dev_define.data:
        changed = 0
        if apply_load_curves:
            changed += apply_load_model(model_book, dev_define, values)
        changed += apply_wind_limits(model_book, dev_define, values)
        changed += apply_pv_limits(model_book, dev_define, values)
        return changed
    changed = apply_wind_limits(model_book, dev_define, values)
    changed += apply_pv_limits(model_book, dev_define, values)

    if apply_load_curves and "load_kw" in values:
        block = model_book.data.get("ACLoad")
        if block is not None and block.data:
            base_loads = []
            total = 0.0
            coupled_loads = _coupled_electric_load_keys(model_book)
            for row in block.data:
                if ("ACLoad", str(row.get("name", ""))) in coupled_loads:
                    continue
                p, q, _pbase, _qbase = _load_power(row)
                base_loads.append((row, p, q))
                total += p
            if total > 0.0:
                for row, p, q in base_loads:
                    new_p = values["load_kw"] * p / total
                    new_q = values["load_kw"] * q / total
                    pbase, base_changed = _load_write_base(row, "pbase")
                    changed += base_changed
                    qbase, base_changed = _load_write_base(row, "qbase")
                    changed += base_changed
                    changed += _set_row_value(row, "pv0", format_number(new_p / pbase))
                    changed += _set_row_value(row, "qv0", format_number(new_q / qbase))
    return changed


def _active_power_control_targets(yt_ctrl_file: Path) -> set[Tuple[str, str]]:
    yt_ctrl_file = Path(yt_ctrl_file)
    if not yt_ctrl_file.exists():
        return set()
    return _active_power_control_targets_book(EBook(yt_ctrl_file))


def _active_power_control_targets_book(ctrl_book: Optional[EBook]) -> set[Tuple[str, str]]:
    if ctrl_book is None:
        return set()
    targets: set[Tuple[str, str]] = set()
    block = ctrl_book.data.get("SetValue")
    if block is not None:
        for row in block.data:
            if str(row.get("set_type", "")) not in ("p_set", "p_ac_set", "p_dc_set"):
                continue
            if row.get("set_value", "") == "":
                continue
            targets.add((str(row.get("dev_type", "")), _stat_dev_name(row)))
    for table_name in ("GeneratorSetpoint", "ConverterSetpoint"):
        block = ctrl_book.data.get(table_name)
        if block is None:
            continue
        for row in block.data:
            if all(
                row.get(field, "") == ""
                for field in ("p_set", "p_ac_set", "p_dc_set")
            ):
                continue
            targets.add((str(row.get("dev_type", "")), _stat_dev_name(row)))
    return targets


def apply_yt_ctrl_file(model_book: EBook, yt_ctrl_file: Path) -> int:
    yt_ctrl_file = Path(yt_ctrl_file)
    if not yt_ctrl_file.exists():
        return 0
    return apply_yt_ctrl_book(model_book, EBook(yt_ctrl_file))


def apply_yt_ctrl_book(model_book: EBook, ctrl_book: Optional[EBook]) -> int:
    if ctrl_book is None:
        return 0
    changed = 0
    block = ctrl_book.data.get("SetValue")
    if block is not None:
        for row in block.data:
            changed += _apply_set_value_row(model_book, row)
    storage_targets = _storage_target_rows(model_book, EBook({}))
    for table_name in ("GeneratorSetpoint", "StorageSoc", "StorageStatus"):
        block = ctrl_book.data.get(table_name)
        if block is None:
            continue
        for row in block.data:
            if table_name in ("StorageSoc", "StorageStatus"):
                resolved = _storage_target_for_identity(row, storage_targets)
                if resolved is not None and row.get("p_set", "") != "":
                    changed += _set_row_value(resolved[1], "p_set", row["p_set"])
            else:
                changed += _apply_setpoint_row(model_book, row)
    changed += apply_overlay_book(model_book, ctrl_book)
    return changed


def update_storage_soc(
    dev_stat_file: Path,
    model_book: EBook,
    period_seconds: float,
    dev_define_file: Optional[Path] = None,
    snapshot=None,
) -> int:
    dev_stat_file = Path(dev_stat_file)
    if not dev_stat_file.exists():
        return 0
    stat_book = EBook(dev_stat_file)
    dev_define = _capability_define_book(model_book, dev_define_file)
    changed = update_storage_soc_book(stat_book, model_book, period_seconds, dev_define, snapshot=snapshot)
    if changed:
        write_ebook_aligned(stat_book, dev_stat_file)
    return changed


def update_hydrogen_storage_state(
    dev_stat_file: Path,
    model_book: EBook,
    period_seconds: float,
    *,
    snapshot: Any,
) -> int:
    dev_stat_file = Path(dev_stat_file)
    stat_book = EBook(dev_stat_file) if dev_stat_file.exists() else EBook({})
    changed = update_hydrogen_storage_state_book(
        stat_book,
        model_book,
        period_seconds,
        snapshot=snapshot,
    )
    if changed:
        write_ebook_aligned(stat_book, dev_stat_file)
    return changed


def _unique_names(*names: str) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            continue
        result.append(name)
        seen.add(name)
    return result


def _storage_power_lookup(
    powers: Mapping[object, float],
    target: StorageTarget,
    targets: Sequence[StorageTarget],
) -> Optional[float]:
    dev_type = target[0]
    lookup_names = _storage_target_lookup_names(target, targets)
    for name in lookup_names:
        key = (dev_type, name)
        if key in powers:
            return powers[key]
    for name in lookup_names:
        if name not in powers:
            continue
        resolved = _storage_target_for_identity({"dev_type": "", "name": name}, targets)
        if resolved is not None and _storage_target_key(resolved) == _storage_target_key(target):
            return powers[name]
    return None


def _snapshot_device_state_by_key(snapshot) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Return operating states carried by this solved snapshot only."""
    states: Dict[Tuple[str, str], Dict[str, Any]] = {}
    ac_grid = getattr(snapshot, "ac", None)
    dc_grid = getattr(snapshot, "dc", None)
    ac_node_alive = _topology_node_alive_by_idx(ac_grid) if ac_grid is not None else {}
    dc_node_alive = _topology_node_alive_by_idx(dc_grid) if dc_grid is not None else {}

    def add_device(dev_type: str, device: object, fallback_name: str = "") -> None:
        dev_name = str(getattr(device, "name", fallback_name) or fallback_name)
        if not dev_name:
            return
        states[(dev_type, dev_name)] = {
            "dev_type": dev_type,
            "dev_name": dev_name,
            "run_stat": _safe_int(getattr(device, "run_stat", 1), 1),
            "dead_island": (
                getattr(device, "dead_island", None) is True
                or _device_dead_island(
                    dev_type,
                    device,
                    ac_node_alive,
                    dc_node_alive,
                )
            ),
        }

    for dev_type, grid in (("ACGenerator", ac_grid), ("DCGenerator", dc_grid)):
        for device in list(getattr(grid, "generators", []) or []):
            add_device(dev_type, device)
    for devices_by_type in (
        getattr(snapshot, "ac_devices", {}) or {},
        getattr(snapshot, "dc_devices", {}) or {},
    ):
        for dev_type, devices in devices_by_type.items():
            for fallback_name, device in devices.items():
                add_device(str(dev_type), device, str(fallback_name))
    explicit_states = getattr(snapshot, "device_states", None)
    if isinstance(explicit_states, Mapping):
        explicit_rows = list(explicit_states.values())
    else:
        explicit_rows = list(explicit_states or [])
    for row in explicit_rows:
        if not isinstance(row, Mapping):
            continue
        dev_type = str(row.get("dev_type", ""))
        dev_name = str(row.get("dev_name", row.get("name", "")))
        if dev_type and dev_name:
            states[(dev_type, dev_name)] = dict(row)
    return states


def _snapshot_storage_power_by_name(snapshot, model_book: EBook, dev_define: EBook) -> Dict[object, float]:
    if snapshot is None:
        return {}
    powers: Dict[object, float] = {}
    states = _snapshot_device_state_by_key(snapshot)
    value_reader = getattr(snapshot, "value", None)
    targets = _storage_target_rows(model_book, dev_define)
    for target in targets:
        dev_type, row, _storage_name, _define, _pos = target
        row_name = str(row.get("name", ""))
        actual_power: Optional[float] = None
        state = states.get((dev_type, row_name))
        if (
            state is None
            or _safe_int(state.get("run_stat", 0), 0) != 1
            or state.get("dead_island") is True
        ):
            actual_power = 0.0
        else:
            if callable(value_reader):
                try:
                    value = value_reader(dev_type, row_name, "P_GEN")
                except Exception:
                    value = None
                number = _safe_float(value, None)
                if number is not None and math.isfinite(number):
                    actual_power = number
            if actual_power is None:
                actual_power = 0.0
        powers[(dev_type, row_name)] = actual_power
    return powers


def _storage_internal_power_for_soc(terminal_power: float, charge_efficiency: float, discharge_efficiency: float) -> float:
    if terminal_power > 0.0:
        return terminal_power / max(discharge_efficiency, 1e-9)
    if terminal_power < 0.0:
        return terminal_power * charge_efficiency
    return 0.0


def update_storage_soc_book(
    stat_book: EBook,
    model_book: EBook,
    period_seconds: float,
    dev_define: EBook,
    storage_power_by_name: Optional[Mapping[object, float]] = None,
    snapshot=None,
) -> int:
    changed = _ensure_storage_soc_rows_book(stat_book, model_book, dev_define)
    block = _storage_soc_block(stat_book)
    if block is None:
        return changed
    actual_storage_power = dict(storage_power_by_name or {})
    if snapshot is not None:
        actual_storage_power.update(_snapshot_storage_power_by_name(snapshot, model_book, dev_define))
    targets = _storage_target_rows(model_book, dev_define)
    for row in _sorted_rows(block.data):
        target = _storage_target_for_identity(row, targets)
        if target is None:
            continue
        _dev_type, source, _storage_name, define, _pos = target
        try:
            soc = float(row.get("soc_curr", 0.5))
        except (TypeError, ValueError):
            continue
        actual_power = _storage_power_lookup(actual_storage_power, target, targets)
        if actual_power is None:
            try:
                actual_power = float(source.get("p_set", 0.0))
            except (TypeError, ValueError):
                continue
        capacity = _safe_float((define or {}).get("emva", DEFAULT_STORAGE_CAPACITY_KWH), DEFAULT_STORAGE_CAPACITY_KWH) or DEFAULT_STORAGE_CAPACITY_KWH
        charge_efficiency, discharge_efficiency = _storage_efficiencies(define)
        soc_power = _storage_internal_power_for_soc(actual_power, charge_efficiency, discharge_efficiency)
        next_soc = soc - soc_power * float(period_seconds) / 3600.0 / max(capacity, 1e-9)
        changed += _set_row_value(row, "soc_curr", format_number(next_soc))
    return changed


def apply_realtime_inputs(
    model_file: Path,
    weather_file: Path,
    dev_stat_file: Path,
    yt_ctrl_file: Path,
    dev_define_file_or_work_dir: Optional[Path],
    work_dir: Optional[Path] = None,
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
    mode_file: Optional[Path] = None,
) -> Tuple[Optional[Path], int, EBook]:
    if work_dir is None:
        dev_define_file = None
        if dev_define_file_or_work_dir is None:
            work_dir = Path(model_file).parent / ".simu_loop_work"
        else:
            work_dir = Path(dev_define_file_or_work_dir)
    else:
        dev_define_file = Path(dev_define_file_or_work_dir) if dev_define_file_or_work_dir is not None else None
    model_book = _clone_ebook(_load_model_book_once(model_file))
    active_power_controls = _active_power_control_targets(yt_ctrl_file)
    changed = 0
    changed += apply_dev_stat_file(model_book, dev_stat_file)
    stat_book = EBook(dev_stat_file) if Path(dev_stat_file).exists() else EBook({})
    changed += ensure_hydrogen_storage_state_rows_book(stat_book, model_book)
    changed += apply_hydrogen_storage_state_book(model_book, stat_book)
    changed += apply_mode_file(model_book, mode_file)
    changed += apply_weather_file(model_book, weather_file, dev_define_file)
    changed += apply_yt_ctrl_file(model_book, yt_ctrl_file)
    changed += apply_device_capability_limits(
        model_book,
        weather_file,
        dev_stat_file,
        dev_define_file,
        period_seconds,
        active_power_controls,
    )
    return None, changed, model_book


def apply_realtime_input_books(
    source_model_book: EBook,
    weather_book: Optional[EBook],
    dev_stat_book: Optional[EBook],
    yt_ctrl_book: Optional[EBook],
    dev_define_book: Optional[EBook],
    period_seconds: float = DEFAULT_PERIOD_SECONDS,
    mode_book: Optional[EBook] = None,
) -> Tuple[int, EBook, EBook, Dict[str, float]]:
    """Apply one runtime boundary snapshot to a cloned model book in memory."""
    model_book = _clone_ebook(source_model_book)
    stat_book = dev_stat_book or EBook({})
    ctrl_book = yt_ctrl_book or EBook({})
    weather_values = _weather_values_from_book(weather_book)
    load_power_targets = _load_power_targets_from_book(weather_book)
    dev_define = dev_define_book or _capability_define_book(model_book, None)
    active_power_controls = _active_power_control_targets_book(ctrl_book)
    changed = 0
    changed += apply_dev_stat_book(model_book, stat_book)
    changed += ensure_hydrogen_storage_state_rows_book(stat_book, model_book)
    changed += apply_hydrogen_storage_state_book(model_book, stat_book)
    changed += apply_mode_book(model_book, mode_book)
    changed += apply_weather_book(
        model_book,
        weather_values,
        dev_define,
        apply_load_curves=not load_power_targets,
    )
    changed += apply_load_power_targets(model_book, load_power_targets)
    changed += apply_yt_ctrl_book(model_book, ctrl_book)
    changed += apply_device_capability_limits_book(
        model_book,
        weather_values,
        stat_book,
        dev_define,
        period_seconds,
        active_power_controls,
        apply_load_curves=not load_power_targets,
    )
    return changed, model_book, dev_define, weather_values


def solve_ac_snapshot(e_file: Path) -> Tuple[Snapshot, str]:
    network = ACPowerNetwork()
    network.read_from_file(e_file)
    network.topo()
    calc = ACPowerFlowCalc(network)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = calc.run()
    if rc != 0 or not calc.converged:
        raise RuntimeError(f"AC load flow failed for {e_file}: rc={rc}, iter={calc.iterations}, normF={calc.normF:.3e}")
    _reconstruct_ac_ideal_edge_flows(network)
    return Snapshot(network, ac_grid=network), f"iter={calc.iterations}, normF={calc.normF:.3e}"


def solve_ac_snapshot_from_book(model_book: EBook, source: Optional[Path] = None) -> Tuple[Snapshot, str]:
    source_path = Path(source or getattr(model_book, "file_path", "memory_model.e"))
    network = ACPowerNetwork()
    network.source = str(source_path)
    network.read_from_model(_ebook_to_efile_rows(model_book))
    network.topo()
    calc = ACPowerFlowCalc(network)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = calc.run()
    if rc != 0 or not calc.converged:
        raise RuntimeError(
            f"AC load flow failed for in-memory model {source_path}: "
            f"rc={rc}, iter={calc.iterations}, normF={calc.normF:.3e}"
        )
    _reconstruct_ac_ideal_edge_flows(network)
    snapshot = Snapshot(network, ac_grid=network)
    _add_zero_impedance_devices_from_book(snapshot, model_book)
    _link_snapshot_terminal_objects(snapshot)
    return snapshot, f"iter={calc.iterations}, normF={calc.normF:.3e}"


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
    _reconstruct_ac_ideal_edge_flows(
        network.ac,
        network.dcac_converters,
        network.acac_converters,
    )
    _reconstruct_dc_ideal_edge_flows(
        network.dc,
        network.dcac_converters,
    )
    snapshot = Snapshot(
        network,
        ac_grid=network.ac,
        dc_grid=network.dc,
        dcac_converters=network.dcac_converters,
        acac_converters=network.acac_converters,
    )
    snapshot.fluid_results = dict(
        getattr(getattr(calc, "lf_result", None), "fluid", {}) or {}
    )
    snapshot.coupling_results = list(getattr(calc, "coupling_results", ()) or ())
    _add_zero_impedance_devices_from_file(snapshot, e_file)
    _link_snapshot_terminal_objects(snapshot)
    return snapshot, f"iter={calc.iterations}, normF={calc.normF:.3e}"


def _read_lf_network_from_book(model_book: EBook, source: Path) -> object:
    rows = _ebook_to_efile_rows(model_book)
    file_kind = _detect_lf_rows_kind(rows)
    if file_kind == "ac":
        network = _build_lf_network_from_single_ac_file(source, rows)
    elif file_kind == "dc":
        network = _build_lf_network_from_single_dc_file(source, rows)
    else:
        network = _build_lf_network_from_hybrid_rows(source, rows)
    context = build_multi_energy_context_from_rows(rows, source=source)
    return attach_multi_energy_context(network, context)


def solve_hybrid_snapshot_from_book(model_book: EBook, source: Optional[Path] = None) -> Tuple[Snapshot, str]:
    source_path = Path(source or getattr(model_book, "file_path", "memory_model.e"))
    network = _read_lf_network_from_book(model_book, source_path)
    calc = HybridPowerFlowCalc(network, verbose=False)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = calc.run()
    if rc != 0 or not calc.converged:
        raise RuntimeError(
            f"Hybrid load flow failed for in-memory model {source_path}: "
            f"rc={rc}, iter={calc.iterations}, normF={calc.normF:.3e}"
        )
    _reconstruct_ac_ideal_edge_flows(
        network.ac,
        network.dcac_converters,
        network.acac_converters,
    )
    _reconstruct_dc_ideal_edge_flows(
        network.dc,
        network.dcac_converters,
    )
    snapshot = Snapshot(
        network,
        ac_grid=network.ac,
        dc_grid=network.dc,
        dcac_converters=network.dcac_converters,
        acac_converters=network.acac_converters,
    )
    snapshot.fluid_results = dict(
        getattr(getattr(calc, "lf_result", None), "fluid", {}) or {}
    )
    snapshot.coupling_results = list(getattr(calc, "coupling_results", ()) or ())
    _add_zero_impedance_devices_from_book(snapshot, model_book)
    _link_snapshot_terminal_objects(snapshot)
    return snapshot, f"iter={calc.iterations}, normF={calc.normF:.3e}"


def _add_zero_impedance_devices_from_file(snapshot: Snapshot, e_file: Path) -> None:
    _add_zero_impedance_devices_from_book(snapshot, EBook(e_file))


def _add_zero_impedance_devices_from_book(snapshot: Snapshot, book: EBook) -> None:
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


def _storage_soc_values(
    dev_stat_file: Optional[Path],
    model_book: Optional[EBook] = None,
) -> Dict[object, float]:
    if dev_stat_file is None:
        return {}
    path = Path(dev_stat_file)
    if not path.exists():
        return {}
    try:
        book = EBook(path)
    except Exception:
        return {}
    return _storage_soc_values_from_book(book, model_book)


def _storage_soc_values_from_book(
    book: Optional[EBook],
    model_book: Optional[EBook] = None,
) -> Dict[object, float]:
    if book is None:
        return {}
    storage_resources = [
        resource
        for resource in structured_resources(model_book)
        if resource.technology == "storage"
    ] if model_book is not None else []
    values: Dict[object, float] = {}
    for row in _storage_soc_rows(book):
        dev_type = str(row.get("dev_type", "")).strip()
        name = str(row.get("name", row.get("dev_name", "")))
        soc = _safe_float(row.get("soc_curr", row.get("soc", "")), None)
        if soc is None:
            continue
        if dev_type and name:
            values[(dev_type, name)] = soc
        resource_key = resolve_resource_reference(storage_resources, row)
        if resource_key is not None:
            values[resource_key] = soc
    return values


def _signal_measurement_values(dev_stat_file: Optional[Path]) -> Dict[Tuple[str, str, str], float]:
    if dev_stat_file is None:
        return {}
    path = Path(dev_stat_file)
    if not path.exists():
        return {}
    try:
        book = EBook(path)
    except Exception:
        return {}
    return _signal_measurement_values_from_book(book)


def _signal_measurement_values_from_book(book: Optional[EBook]) -> Dict[Tuple[str, str, str], float]:
    if book is None:
        return {}
    values: Dict[Tuple[str, str, str], float] = {}
    signal_blocks = (
        ("RunStat", "run_stat", "RUN_STAT"),
        ("DeviceRunStatus", "run_stat", "RUN_STAT"),
        ("CbOpenStat", "status", "STATUS"),
        ("SwitchBreakerStatus", "status", "STATUS"),
    )
    for block_name, value_column, meas_type in signal_blocks:
        block = book.data.get(block_name)
        if block is None:
            continue
        for item in block.data:
            dev_type = str(item.get("dev_type", ""))
            dev_name = _stat_dev_name(item)
            if not dev_type or not dev_name:
                continue
            value = _safe_float(item.get(value_column, ""), None)
            if value is not None:
                values[(dev_type, dev_name, meas_type)] = value
    return values


def _effective_signal_measurement_values(
    signal_values: Optional[Mapping[Tuple[str, str, str], float]],
    device_states: Optional[Sequence[Mapping[str, Any]]],
) -> Dict[Tuple[str, str, str], float]:
    """Overlay topology availability without changing administrative run state."""
    values = dict(signal_values or {})
    for state in device_states or ():
        if state.get("dead_island") is not True:
            continue
        dev_type = str(state.get("dev_type", "")).strip()
        dev_name = str(state.get("dev_name", state.get("name", ""))).strip()
        if dev_type and dev_name:
            values[(dev_type, dev_name, "RUN_STAT")] = 0.0
    return values


def _weather_measurement_value(meas_type: str, weather: Optional[Dict[str, float]]) -> Optional[float]:
    if weather is None:
        return None
    return {
        "WIND_SPEED": weather.get("wind_speed_mps"),
        "AIR_TEMP": weather.get("air_temp_c"),
        "HUMIDITY": weather.get("humidity_pct"),
        "AIR_PRESSURE": weather.get("air_pressure_hpa"),
        "SOLAR_IRRADIANCE": weather.get("solar_irradiance_w_m2"),
    }.get(meas_type)


def _fluid_endpoint_measurement_value(
    snapshot,
    dev_type: str,
    dev_name: str,
    meas_type: str,
) -> Optional[float]:
    domain = "hydro" if str(dev_type).startswith("Hydro") else ""
    result = (getattr(snapshot, "fluid_results", {}) or {}).get(domain)
    if result is None:
        return None
    collection_name = {
        "HydroSource": "sources",
        "HydroLoad": "loads",
        "HydroStorage": "storages",
    }.get(dev_type)
    if collection_name is None:
        return None
    item = (getattr(result, collection_name, {}) or {}).get(dev_name)
    if item is None:
        return None
    field = {
        "FLOW": "flow",
        "PRESS": "pressure",
        "PRESSURE": "pressure",
    }.get(str(meas_type).upper())
    if field is None:
        return None
    value = _safe_float(getattr(item, field, None), None)
    return value if value is not None and math.isfinite(value) else None


def _hydrogen_conversion_measurement_value(
    snapshot,
    dev_type: str,
    dev_name: str,
    meas_type: str,
) -> Optional[float]:
    for result in getattr(snapshot, "coupling_results", ()) or ():
        if (
            str(getattr(result, "table_name", "")) != dev_type
            or str(getattr(result, "name", "")) != dev_name
        ):
            continue
        coupling = getattr(result, "coupling", None)
        if coupling is None:
            return None
        terminals = (
            (getattr(coupling, "t1", None), getattr(result, "t1_value", None)),
            (getattr(coupling, "t2", None), getattr(result, "t2_value", None)),
        )
        if str(meas_type).upper() == "P":
            value = next(
                (
                    _safe_float(endpoint_value, None)
                    for terminal, endpoint_value in terminals
                    if getattr(terminal, "domain", "") in {"ac", "dc"}
                ),
                None,
            )
            if value is None:
                return None
            converter = getattr(snapshot, "power_to_file", None)
            return float(converter(value)) if callable(converter) else value
        if str(meas_type).upper() == "FLOW":
            return next(
                (
                    _safe_float(endpoint_value, None)
                    for terminal, endpoint_value in terminals
                    if getattr(terminal, "domain", "") == "hydro"
                ),
                None,
            )
        return None
    return None


def _measurement_value(
    snapshot,
    row: Sequence[str],
    storage_soc: Optional[Mapping[object, float]] = None,
    weather: Optional[Dict[str, float]] = None,
    signal_values: Optional[Dict[Tuple[str, str, str], float]] = None,
    model_book: Optional[EBook] = None,
    binding: Optional[MeasurementBinding] = None,
    hydrogen_storage_state: Optional[Mapping[object, Mapping[str, float]]] = None,
) -> Optional[float]:
    dev_type, dev_name, meas_type = row[2], row[3], row[4].upper()
    if meas_type in SIGNAL_MEASUREMENT_TYPES:
        return None if signal_values is None else signal_values.get((dev_type, dev_name, meas_type))
    if dev_type == "Environment" and dev_name == "weather":
        return _weather_measurement_value(meas_type, weather)
    if dev_type in {"HydroSource", "HydroLoad"}:
        return _fluid_endpoint_measurement_value(
            snapshot,
            dev_type,
            dev_name,
            meas_type,
        )
    if dev_type in {"AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"}:
        return _hydrogen_conversion_measurement_value(
            snapshot,
            dev_type,
            dev_name,
            meas_type,
        )
    target_present = False
    if binding is not None:
        target_type = binding.target_type
        target_name = binding.target_name
        target_present = binding.target_present
    else:
        target = (
            _source_model_row(model_book, dev_type, dev_name)
            if model_book is not None
            else None
        )
        target_type = dev_type
        target_name = dev_name
        target_present = target is not None
        if target is not None:
            resolved = [
                resource.device_key
                for resource in structured_resources(model_book)
                if resource.source is target
            ]
            if len(resolved) == 1:
                target_type, target_name = resolved[0]
            elif _model_row(model_book, dev_type, dev_name) is not None:
                target_type, target_name = dev_type, dev_name
    if dev_type == "HydroStorage" or target_type == "HydroStorage":
        field = {
            "PRESS": "press",
            "PRESSURE": "press",
            "FLOW": "flow",
            "GAS_QUANTITY": "gas_quantity",
            "SOC": "soc",
        }.get(meas_type)
        if field is not None and hydrogen_storage_state is not None:
            for key in (
                (dev_type, dev_name),
                (target_type, target_name),
                dev_name,
                target_name,
            ):
                values = hydrogen_storage_state.get(key)
                if values is not None and field in values:
                    return values[field]
            return None
    if meas_type == "I" and target_type in GENERIC_CURRENT_BRANCH_TYPES:
        for terminal_meas_type in ("I_FROM", "I_TO"):
            value = snapshot.value(target_type, target_name, terminal_meas_type)
            number = _safe_float(value, None)
            if number is not None:
                return number
        return None
    if meas_type == "SOC":
        if storage_soc is None:
            return None
        for key in (
            (dev_type, dev_name),
            (target_type, target_name),
            dev_name,
            target_name,
        ):
            if key in storage_soc:
                return storage_soc[key]
        return None
    if target_type == "ACBreak":
        dev = snapshot.ac_devices.get("ACBreak", {}).get(target_name)
        return None if dev is None else snapshot._ac_zero_value(dev, meas_type)
    if target_type == "DCBreak":
        dev = snapshot.dc_devices.get("DCBreak", {}).get(target_name)
        return None if dev is None else snapshot._dc_zero_value(dev, meas_type)
    if target_present and meas_type in {"P", "Q", "V", "I"}:
        suffix = "GEN" if target_type in {"ACGenerator", "DCGenerator"} else ""
        target_meas_type = f"{meas_type}_{suffix}" if suffix else meas_type
        value = snapshot.value(target_type, target_name, target_meas_type)
        if value is not None:
            return value
    value = snapshot.value(target_type, target_name, meas_type)
    if value is None and (meas_type in VALUE_TYPES or meas_type in ANGLE_TYPES):
        return None
    return value


def build_real_rows(
    meas_file: Path,
    snapshot,
    dev_stat_file: Optional[Path] = None,
    weather_file: Optional[Path] = None,
    device_states: Optional[Sequence[Mapping[str, Any]]] = None,
    model_book: Optional[EBook] = None,
) -> Tuple[List[str], List[List[str]], List[str], int, int]:
    before, rows, after = parse_measurement_rows(meas_file)
    storage_soc = _storage_soc_values(dev_stat_file, model_book)
    hydrogen_storage_state = hydrogen_storage_state_values_from_book(
        EBook(dev_stat_file) if dev_stat_file is not None and Path(dev_stat_file).exists() else None
    )
    weather = _weather_values(weather_file) if weather_file is not None else None
    signal_values = _effective_signal_measurement_values(
        _signal_measurement_values(dev_stat_file),
        device_states,
    )
    return build_real_rows_from_data(
        rows,
        snapshot,
        storage_soc,
        weather,
        signal_values,
        before,
        after,
        model_book=model_book,
        hydrogen_storage_state=hydrogen_storage_state,
    )


def build_real_rows_from_data(
    measurement_rows: Sequence[Sequence[str]],
    snapshot,
    storage_soc: Optional[Mapping[object, float]] = None,
    weather: Optional[Dict[str, float]] = None,
    signal_values: Optional[Dict[Tuple[str, str, str], float]] = None,
    before: Optional[Sequence[str]] = None,
    after: Optional[Sequence[str]] = None,
    *,
    model_book: Optional[EBook] = None,
    measurement_bindings: Optional[Sequence[MeasurementBinding]] = None,
    hydrogen_storage_state: Optional[Mapping[object, Mapping[str, float]]] = None,
) -> Tuple[List[str], List[List[str]], List[str], int, int]:
    rows = []
    for source_row in measurement_rows:
        row = [str(cell) for cell in source_row]
        if len(row) < len(MEAS_HEADER):
            row.extend("" for _ in range(len(MEAS_HEADER) - len(row)))
        rows.append(row[: len(MEAS_HEADER)])
    updated = 0
    missing = 0
    bindings = tuple(measurement_bindings or compile_measurement_bindings(rows, model_book))
    if len(bindings) != len(rows):
        raise ValueError("Measurement binding count does not match measurement rows")
    for row, binding in zip(rows, bindings):
        value = _measurement_value(
            snapshot,
            row,
            storage_soc,
            weather,
            signal_values,
            model_book,
            binding,
            hydrogen_storage_state,
        )
        if value is None:
            missing += 1
            continue
        row[7] = format_number(float(value))
        updated += 1
    return list(before or []), rows, list(after or []), updated, missing


def _measurement_rows_from_book(book: Optional[EBook]) -> Tuple[List[str], List[List[str]], List[str]]:
    if book is None:
        return [], [], []
    block = book.data.get("Measurement")
    if block is None:
        return [], [], []
    rows = [
        [str(row.get(header, "")) for header in MEAS_HEADER]
        for row in getattr(block, "data", [])
    ]
    return [], rows, []


def _row_noise_sigma(row: Sequence[str], noise_std: Optional[float]) -> float:
    if noise_std is not None:
        return max(0.0, float(noise_std))
    try:
        weight = float(row[5])
    except (TypeError, ValueError):
        return 0.0
    if weight <= 0.0:
        return 0.0
    sigma = 1.0 / math.sqrt(weight)
    meas_type = str(row[4]).upper() if len(row) > 4 else ""
    value = _safe_float(row[7], None) if len(row) > 7 else None
    if meas_type == "SOC" and value is not None and abs(value) <= 2.0:
        # SOC definitions moved from percentage points to a 0-1 ratio. Keep
        # existing measurement weights equivalent in the normalized unit.
        sigma /= 100.0
    return sigma


def add_noise_to_rows(
    rows: Sequence[Sequence[str]],
    noise_std: Optional[float],
    rng: random.Random,
    median_deviations: Optional[Mapping[str, float]] = None,
) -> List[List[str]]:
    noisy_rows: List[List[str]] = []
    configured_deviations = median_deviations or {}
    for source_row in rows:
        row = list(source_row)
        meas_type = str(row[4]).upper() if len(row) > 4 else ""
        if meas_type in SIGNAL_MEASUREMENT_TYPES:
            noisy_rows.append(row)
            continue
        sigma = _row_noise_sigma(row, noise_std)
        measurement_name = str(row[1]).strip() if len(row) > 1 else ""
        try:
            median_deviation = float(configured_deviations.get(measurement_name, 0.0))
        except (TypeError, ValueError):
            median_deviation = 0.0
        if not math.isfinite(median_deviation):
            median_deviation = 0.0
        if sigma > 0.0 or median_deviation != 0.0 or meas_type == "SOC":
            try:
                value = float(row[7])
                if sigma > 0.0 or median_deviation != 0.0:
                    value += rng.gauss(median_deviation, sigma)
                row[7] = format_number(value)
            except (IndexError, TypeError, ValueError):
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


def _config_uses_memory_runtime(config: SimulationConfig) -> bool:
    return any(
        value is not None
        for value in (
            config.model_book,
            config.meas_rows,
            config.weather_book,
            config.dev_stat_book,
            config.yt_ctrl_book,
            config.dev_define_book,
            config.mode_book,
        )
    )


def _solve_snapshot_from_book(
    solver: Callable[[object], Tuple[object, str]],
    model_book: EBook,
    source: Path,
) -> Tuple[object, str]:
    if solver is solve_hybrid_snapshot:
        return solve_hybrid_snapshot_from_book(model_book, source)
    if solver is solve_ac_snapshot:
        return solve_ac_snapshot_from_book(model_book, source)
    if solver is solve_hybrid_snapshot_from_book or solver is solve_ac_snapshot_from_book:
        return solver(model_book, source)
    return solver(_ebook_to_dict_rows(model_book))


def run_once(
    config: SimulationConfig,
    solver: Callable[[object], Tuple[object, str]] = solve_hybrid_snapshot,
    rng: Optional[random.Random] = None,
) -> SimulationResult:
    rng = rng or random.Random(config.random_seed)
    if _config_uses_memory_runtime(config):
        source_model_book = config.model_book if config.model_book is not None else _load_model_book_once(config.model_file)
        meas_before = list(config.meas_before or [])
        if config.meas_rows is None:
            book_before, meas_rows, book_after = _measurement_rows_from_book(EBook(config.meas_file) if config.meas_file.exists() else None)
            meas_before = meas_before or book_before
            meas_after = list(config.meas_after or book_after)
        else:
            meas_rows = [list(row) for row in config.meas_rows]
            meas_after = list(config.meas_after or [])
        stat_book = config.dev_stat_book or _read_optional_book(config.dev_stat_file)
        weather_book = config.weather_book or _read_optional_book(config.weather_file)
        ctrl_book = config.yt_ctrl_book or _read_optional_book(config.yt_ctrl_file)
        if config.mode_book is not None:
            mode_book = config.mode_book
        elif config.mode_file is not None and Path(config.mode_file).exists():
            mode_book = EBook(config.mode_file)
        else:
            mode_book = None
        dev_define_book = config.dev_define_book
        if dev_define_book is None and config.dev_define_file is not None:
            dev_define_book = _read_optional_book(config.dev_define_file)

        overlay_updates, model_book, dev_define, weather_values = apply_realtime_input_books(
            source_model_book,
            weather_book,
            stat_book,
            ctrl_book,
            dev_define_book,
            config.period_seconds,
            mode_book,
        )
        snapshot, solver_info = _solve_snapshot_from_book(solver, model_book, config.model_file)
        soc_updates = update_storage_soc_book(stat_book, model_book, config.period_seconds, dev_define, snapshot=snapshot)
        storage_soc = _storage_soc_values_from_book(stat_book, model_book)
        hydrogen_updates = update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            config.period_seconds,
            snapshot=snapshot,
        )
        hydrogen_storage_state = hydrogen_storage_state_values_from_book(stat_book)
        device_states = collect_device_operating_states(snapshot, model_book)
        signal_values = _effective_signal_measurement_values(
            _signal_measurement_values_from_book(stat_book),
            device_states,
        )
        before, real_rows, after, updated, missing = build_real_rows_from_data(
            meas_rows,
            snapshot,
            storage_soc,
            weather_values,
            signal_values,
            meas_before,
            meas_after,
            model_book=model_book,
            measurement_bindings=config.measurement_bindings,
            hydrogen_storage_state=hydrogen_storage_state,
        )
        scada_rows = add_noise_to_rows(
            real_rows,
            config.noise_std,
            rng,
            config.measurement_median_deviations,
        )
        if config.write_output_files:
            write_measurement_snapshot(config.real_file, before, real_rows, after)
            write_measurement_snapshot(config.scada_file, before, scada_rows, after)
        return SimulationResult(
            real_file=config.real_file,
            scada_file=config.scada_file,
            updated=updated,
            missing=missing,
            overlay_updates=overlay_updates + soc_updates + hydrogen_updates,
            solver_info=solver_info,
            model_book=model_book,
            measurement_definitions=[list(row) for row in meas_rows],
            real_rows=real_rows,
            scada_rows=scada_rows,
            device_states=device_states,
        )

    work_dir = config.real_file.parent / ".simu_loop_work"
    _model_file, overlay_updates, model_book = apply_realtime_inputs(
        config.model_file,
        config.weather_file,
        config.dev_stat_file,
        config.yt_ctrl_file,
        config.dev_define_file,
        work_dir,
        config.period_seconds,
        config.mode_file,
    )
    snapshot, solver_info = _solve_snapshot_from_book(solver, model_book, config.model_file)
    soc_updates = update_storage_soc(config.dev_stat_file, model_book, config.period_seconds, config.dev_define_file, snapshot=snapshot)
    hydrogen_updates = update_hydrogen_storage_state(
        config.dev_stat_file,
        model_book,
        config.period_seconds,
        snapshot=snapshot,
    )
    device_states = collect_device_operating_states(snapshot, model_book)

    before, real_rows, after, updated, missing = build_real_rows(
        config.meas_file,
        snapshot,
        config.dev_stat_file,
        config.weather_file,
        device_states,
        model_book,
    )
    scada_rows = add_noise_to_rows(
        real_rows,
        config.noise_std,
        rng,
        config.measurement_median_deviations,
    )
    if config.write_output_files:
        write_measurement_snapshot(config.real_file, before, real_rows, after)
        write_measurement_snapshot(config.scada_file, before, scada_rows, after)
    return SimulationResult(
        real_file=config.real_file,
        scada_file=config.scada_file,
        updated=updated,
        missing=missing,
        overlay_updates=overlay_updates + soc_updates + hydrogen_updates,
        solver_info=solver_info,
        model_book=model_book,
        measurement_definitions=[list(row) for row in real_rows],
        real_rows=real_rows,
        scada_rows=scada_rows,
        device_states=device_states,
    )


def simulate_once(
    model_file: Optional[Path] = None,
    meas_file: Optional[Path] = None,
    weather_file: Optional[Path] = None,
    dev_stat_file: Optional[Path] = None,
    yt_ctrl_file: Optional[Path] = None,
    dev_define_file: Optional[Path] = None,
    mode_file: Optional[Path] = None,
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
        dev_define_file=Path(dev_define_file).resolve() if dev_define_file is not None else defaults.dev_define_file,
        mode_file=Path(mode_file).resolve() if mode_file is not None else defaults.mode_file,
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
        default=None,
        help="Optional legacy device parameter E file. If omitted, device parameters are read from model.e blocks.",
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
        dev_define_file=Path(args.dev_define).resolve() if args.dev_define else None,
        mode_file=None,
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
