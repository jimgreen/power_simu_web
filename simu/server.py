"""HTTP server for the polar microgrid simulator and trainee consoles."""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import gzip
import hashlib
import html
import json
import math
import mimetypes
import os
import re
import shutil
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

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
    from .device_roles import converter_power_setpoint_fields
except ImportError:  # pragma: no cover - direct module execution.
    from simu.device_roles import converter_power_setpoint_fields

try:
    from .command_frame import command_payload_signature
except ImportError:  # pragma: no cover - direct module execution.
    from simu.command_frame import command_payload_signature

try:
    from .device_runtime_frame import (
        compact_device_runtime_frame,
        compact_device_runtime_supplement_frame,
    )
except ImportError:  # pragma: no cover - direct module execution.
    from simu.device_runtime_frame import (
        compact_device_runtime_frame,
        compact_device_runtime_supplement_frame,
    )

try:
    from .definition_editing import (
        DefinitionRevisionConflict,
        canonical_ratio_parameter_text,
        is_ratio_parameter_field,
        is_soc_parameter_field,
        render_ebook_aligned,
    )
    from .point_names import automatic_point_name
    from .service import (
        DEFAULT_WEATHER,
        DEFINITION_DEFAULTS_FILE,
        DIAGRAM_FILE_NAME,
        MEAS_HEADER,
        SIGNAL_MEASUREMENTS,
        STAT_HEADERS,
        UNKNOWN_WEATHER_VALUE,
        WEATHER_HEADER,
        WEATHER_MEASUREMENTS,
        MultiModelSimulator,
        PolarMicrogridSimulator,
        ServiceInstanceRetiredError,
        _safe_model_id as _service_model_id,
        _to_float,
    )
    from .renewable_control import (
        TraineeRenewableControlLifecycleError,
        TraineeRenewableControlManager,
    )
    from .simulator_cluster import SimulatorClusterManager
    from .simulator_proxy import make_simulator_proxy_server
    from .trainee_exchange import TraineeExchangeLifecycleError, TraineeRealtimeExchange
    from .trainee_data_policy import (
        project_trainee_interstation_snapshot,
        strip_trainee_remote_details_from_snapshot,
        strip_trainee_truth_from_measurement_delta,
        strip_trainee_truth_from_measurement_history,
        strip_trainee_truth_from_measurements,
        strip_trainee_truth_from_snapshot,
    )
except ImportError:  # pragma: no cover - legacy package compatibility.
    from hybrid_power_system_analysis.polar_microgrid_sim.definition_editing import (
        DefinitionRevisionConflict,
        canonical_ratio_parameter_text,
        is_ratio_parameter_field,
        is_soc_parameter_field,
        render_ebook_aligned,
    )
    from hybrid_power_system_analysis.polar_microgrid_sim.point_names import automatic_point_name
    from hybrid_power_system_analysis.polar_microgrid_sim.service import (
        DEFAULT_WEATHER,
        DEFINITION_DEFAULTS_FILE,
        DIAGRAM_FILE_NAME,
        MEAS_HEADER,
        SIGNAL_MEASUREMENTS,
        STAT_HEADERS,
        UNKNOWN_WEATHER_VALUE,
        WEATHER_HEADER,
        WEATHER_MEASUREMENTS,
        MultiModelSimulator,
        PolarMicrogridSimulator,
        ServiceInstanceRetiredError,
        _safe_model_id as _service_model_id,
        _to_float,
    )
    from renewable_control import (
        TraineeRenewableControlLifecycleError,
        TraineeRenewableControlManager,
    )
    from simulator_cluster import SimulatorClusterManager
    from simulator_proxy import make_simulator_proxy_server
    from trainee_exchange import TraineeExchangeLifecycleError, TraineeRealtimeExchange
    from trainee_data_policy import (
        project_trainee_interstation_snapshot,
        strip_trainee_remote_details_from_snapshot,
        strip_trainee_truth_from_measurement_delta,
        strip_trainee_truth_from_measurement_history,
        strip_trainee_truth_from_measurements,
        strip_trainee_truth_from_snapshot,
    )

try:
    import simu_loop  # type: ignore
except ImportError:  # pragma: no cover - legacy package compatibility.
    from hybrid_power_system_analysis.simu import simu_loop

from simu.model_semantics import energy_coupling_control_bindings
from simu.source_curves import source_curve_catalog, source_curve_identity


PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
CLOCK_BASE_INTERVAL_SECONDS = 1.0
ROLE_MODEL_DIRS = {
    "simulator": ("models", "simulator"),
    "trainee": ("models", "trainee"),
}
CONTROL_DEFINITION_BLOCKS = {"RunStat", "CbOpenStat", "SetValue", "StorageSoc"}
DEFINITION_EDIT_PATHS = {
    "/api/definitions/device-parameters",
    "/api/definitions/measurement",
    "/api/definitions/manual-changes/reset",
    "/api/definitions/manual-changes/retry",
}
MANUAL_DEFINITION_CHANGES_PATH = "/api/definitions/manual-changes"
LOCAL_DEFINITION_PATHS = DEFINITION_EDIT_PATHS | {MANUAL_DEFINITION_CHANGES_PATH}
LOCAL_RUNTIME_SETTINGS_PATH = "/api/runtime-settings"
SIMULATOR_COMMAND_DELETE_PATH = "/api/simulator/commands/delete"
TRAINEE_LOCAL_GET_PATHS = {
    "/api/health",
    "/api/config",
    "/api/models",
    "/api/snapshot",
    "/api/runtime-logs",
    "/api/measurements",
    "/api/measurements/delta",
    "/api/measurement-history",
    "/api/devices",
    "/api/device-states",
    "/api/curves",
    "/api/curves/summary",
    "/api/curves/series",
    "/api/settings",
    "/api/export-definitions",
}

PROCESS_STARTED_MONOTONIC = time.monotonic()


def _current_process_memory() -> dict[str, Optional[float]]:
    working_set_bytes: Optional[int] = None
    private_bytes: Optional[int] = None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCountersEx(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCountersEx),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            counters = ProcessMemoryCountersEx()
            counters.cb = ctypes.sizeof(counters)
            process = kernel32.GetCurrentProcess()
            if psapi.GetProcessMemoryInfo(
                process,
                ctypes.byref(counters),
                counters.cb,
            ):
                working_set_bytes = int(counters.WorkingSetSize)
                private_bytes = int(counters.PrivateUsage)
        except (AttributeError, OSError, TypeError, ValueError):
            pass
    divisor = 1024.0 * 1024.0
    return {
        "working_set_mb": round(working_set_bytes / divisor, 3) if working_set_bytes is not None else None,
        "private_mb": round(private_bytes / divisor, 3) if private_bytes is not None else None,
    }


def _process_health_payload() -> dict[str, Any]:
    try:
        from . import NUMERIC_THREAD_ENV_NAMES
    except ImportError:  # pragma: no cover - direct module execution.
        from simu import NUMERIC_THREAD_ENV_NAMES

    return {
        "pid": os.getpid(),
        "uptime_seconds": round(max(0.0, time.monotonic() - PROCESS_STARTED_MONOTONIC), 3),
        "cpu_seconds": round(time.process_time(), 3),
        "python_threads": threading.active_count(),
        "logical_processors": os.cpu_count() or 1,
        **_current_process_memory(),
        "numeric_thread_limit": int(os.environ.get("POWER_SIMU_NUMERIC_THREADS", "1") or 1),
        "numeric_thread_limits": {
            name: str(os.environ.get(name, ""))
            for name in NUMERIC_THREAD_ENV_NAMES
        },
    }
TRAINEE_LOCAL_POST_PATHS = {
    "/api/models/create",
    "/api/models/update-definitions",
    "/api/models/clone",
    "/api/models/delete",
    "/api/models/import-definitions",
}

def _role_models_base_dir(sim_dir: Path, role: str) -> Path:
    parts = ROLE_MODEL_DIRS.get(role.lower(), ("models", role.lower()))
    return sim_dir.joinpath(*parts)


def _default_models_dir(sim_dir: Path, role: str) -> Path:
    """Keep simulator and trainee model sources physically separate by default."""
    return _role_models_base_dir(sim_dir, role) / "source"


def _default_runtime_dir(sim_dir: Path, role: str) -> Path:
    return _role_models_base_dir(sim_dir, role) / "runtime"


def _definition_file_path(service: PolarMicrogridSimulator, file_key: str, file_name: str) -> Path:
    source_files = getattr(service, "source_files", {})
    source_path = Path(source_files.get(file_key, service.sim_dir / file_name))
    if source_path.exists():
        return source_path
    runtime_path = Path(service.files.get(file_key, service.runtime_dir / file_name))
    if runtime_path.exists():
        return runtime_path
    return source_path


def _book_from_text(text: str) -> EBook:
    book = EBook({})
    block: Optional[EBlock] = None
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("<") and line.endswith(">"):
            if line.startswith("</"):
                if block is not None:
                    book.data[block.name] = block
                block = None
            else:
                block = EBlock(line[1:-1])
            continue
        if block is None:
            raise ValueError(f"Invalid E file row before block at line {line_no}")
        if line.startswith("@"):
            block.header_list = line[1:].split()
        elif line.startswith("#"):
            block.AddRow(line[1:].split())
        else:
            raise ValueError(f"Invalid E file row at line {line_no}: {line}")
    return book


def _merge_control_definition(stat_path: Path, control_text: str, model_text: str = "") -> None:
    stat_book = EBook(stat_path) if stat_path.exists() else EBook({})
    control_book = _book_from_text(control_text)
    found = False
    for block_name in CONTROL_DEFINITION_BLOCKS:
        block = control_book.data.get(block_name)
        if block is not None:
            stat_book.data[block_name] = block
            found = True
        elif block_name != "StorageSoc":
            stat_book.data.pop(block_name, None)
    if not found:
        raise ValueError("control.e must contain at least one control block")
    if control_book.data.get("StorageSoc") is None:
        stat_book.data.pop("StorageSoc", None)
        if model_text:
            storage_rows = _storage_source_rows(_book_from_text(model_text))
            if storage_rows:
                storage_block = EBlock("StorageSoc")
                storage_block.header_list = ["dev_type", "idx", "name", "soc_curr"]
                for row in storage_rows:
                    storage_block.AddRow(
                        [
                            str(row.get("dev_type", "")),
                            str(row.get("idx", "")),
                            str(row.get("name", "")),
                            str(row.get("soc_curr", 0.5)),
                        ]
                    )
                stat_book.data["StorageSoc"] = storage_block
    simu_loop.write_ebook_aligned(stat_book, stat_path)


def _extract_efile_blocks(text: str, names: set[str]) -> str:
    parts: list[str] = []
    capturing = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("<") and stripped.endswith(">") and not stripped.startswith("</"):
            block_name = stripped[1:-1]
            capturing = block_name in names
        if capturing:
            parts.append(line)
        if stripped.startswith("</") and stripped.endswith(">"):
            capturing = False
    return "".join(parts)


def _definition_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def _definition_number(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return number


def _aligned_efile_text(blocks: Mapping[str, tuple[list[str], list[Mapping[str, Any]]]]) -> str:
    parts: list[str] = []
    for block_name, (headers, rows) in blocks.items():
        widths = [len(header) for header in headers]
        normalized_rows = []
        for row in rows:
            normalized = [_definition_cell(row.get(header, "")) for header in headers]
            normalized_rows.append(normalized)
            widths = [max(width, len(value)) for width, value in zip(widths, normalized)]
        parts.append(f"<{block_name}>\n")
        parts.append("@ " + "  ".join(f"{header:<{widths[idx]}}" for idx, header in enumerate(headers)).rstrip() + "\n")
        for row in normalized_rows:
            parts.append("# " + "  ".join(f"{value:<{widths[idx]}}" for idx, value in enumerate(row)).rstrip() + "\n")
        parts.append(f"</{block_name}>\n")
    return "".join(parts)


def _curve_definition_text(curves: Mapping[str, Any]) -> str:
    mode = str(curves.get("mode", "day") or "day")
    time_step_minutes = curves.get("time_step_minutes", "")
    weather = curves.get("weather", [])
    loads = curves.get("loads", {})
    sources = curves.get("sources", [])
    point_count = curves.get("point_count", len(weather) if isinstance(weather, list) else "")

    info_rows = [
        {
            "mode": mode,
            "time_step_minutes": time_step_minutes,
            "point_count": point_count,
        }
    ]
    env_rows: list[Mapping[str, Any]] = []
    if isinstance(weather, list):
        for idx, point in enumerate(weather, start=1):
            if isinstance(point, Mapping):
                env_rows.append(
                    {
                        "idx": idx,
                        "minute": point.get("minute", idx - 1),
                        "wind_speed_mps": point.get("wind_speed_mps", ""),
                        "air_temp_c": point.get("air_temp_c", ""),
                        "air_pressure_hpa": point.get("air_pressure_hpa", ""),
                        "solar_irradiance_w_m2": point.get("solar_irradiance_w_m2", ""),
                        "humidity_pct": point.get("humidity_pct", ""),
                    }
                )

    load_rows: list[Mapping[str, Any]] = []
    if isinstance(loads, Mapping):
        for load_name, points in loads.items():
            if not isinstance(points, list):
                continue
            for idx, point in enumerate(points, start=1):
                if isinstance(point, Mapping):
                    load_rows.append(
                        {
                            "idx": idx,
                            "load_name": load_name,
                            "minute": point.get("minute", idx - 1),
                            "p_kw": point.get("p_kw", ""),
                        }
                    )

    source_rows: list[Mapping[str, Any]] = []
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            points = source.get("points", [])
            if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                continue
            for idx, point in enumerate(points, start=1):
                if not isinstance(point, Mapping):
                    continue
                source_rows.append(
                    {
                        "idx": idx,
                        "dev_type": source.get("dev_type", ""),
                        "dev_name": source.get("dev_name", source.get("name", "")),
                        "set_type": source.get("set_type", ""),
                        "family": source.get("family", ""),
                        "unit": source.get("unit", ""),
                        "minute": point.get("minute", idx - 1),
                        "value": point.get("value", point.get("set_value", "")),
                    }
                )

    return _aligned_efile_text(
        {
            "CurveInfo": (["mode", "time_step_minutes", "point_count"], info_rows),
            "EnvironmentCurve": (
                [
                    "idx",
                    "minute",
                    "wind_speed_mps",
                    "air_temp_c",
                    "air_pressure_hpa",
                    "solar_irradiance_w_m2",
                    "humidity_pct",
                ],
                env_rows,
            ),
            "LoadCurve": (["idx", "load_name", "minute", "p_kw"], load_rows),
            "SourceCurve": (
                ["idx", "dev_type", "dev_name", "set_type", "family", "unit", "minute", "value"],
                source_rows,
            ),
        }
    )


def _curves_from_definition_text(text: str) -> Mapping[str, Any]:
    book = _book_from_text(text)
    info_block = book.data.get("CurveInfo")
    info = info_block.data[0] if info_block is not None and info_block.data else {}
    payload: dict[str, Any] = {
        "mode": str(info.get("mode", "day") or "day"),
        "time_step_minutes": _definition_number(info.get("time_step_minutes", 1)),
        "point_count": _definition_number(info.get("point_count", 0)),
        "weather": [],
        "loads": {},
        "sources": [],
    }

    env_block = book.data.get("EnvironmentCurve")
    if env_block is not None:
        weather_rows = []
        for row in env_block.data:
            weather_rows.append(
                {
                    "minute": _definition_number(row.get("minute", "")),
                    "wind_speed_mps": _definition_number(row.get("wind_speed_mps", "")),
                    "air_temp_c": _definition_number(row.get("air_temp_c", "")),
                    "air_pressure_hpa": _definition_number(row.get("air_pressure_hpa", "")),
                    "solar_irradiance_w_m2": _definition_number(row.get("solar_irradiance_w_m2", "")),
                    "humidity_pct": _definition_number(row.get("humidity_pct", "")),
                }
            )
        payload["weather"] = weather_rows

    load_block = book.data.get("LoadCurve")
    loads: dict[str, list[Mapping[str, Any]]] = {}
    if load_block is not None:
        for row in load_block.data:
            load_name = str(row.get("load_name", "")).strip()
            if not load_name:
                continue
            loads.setdefault(load_name, []).append(
                {
                    "minute": _definition_number(row.get("minute", "")),
                    "p_kw": _definition_number(row.get("p_kw", "")),
                }
            )
    payload["loads"] = loads
    source_block = book.data.get("SourceCurve")
    sources: dict[tuple[str, str, str], dict[str, Any]] = {}
    if source_block is not None:
        for row in source_block.data:
            identity = (
                str(row.get("dev_type", "")).strip(),
                str(row.get("dev_name", "")).strip(),
                str(row.get("set_type", "")).strip(),
            )
            if not all(identity):
                continue
            source = sources.setdefault(
                identity,
                {
                    "dev_type": identity[0],
                    "dev_name": identity[1],
                    "name": identity[1],
                    "set_type": identity[2],
                    "family": str(row.get("family", "")).strip(),
                    "unit": str(row.get("unit", "")).strip(),
                    "points": [],
                },
            )
            source["points"].append(
                {
                    "minute": _definition_number(row.get("minute", "")),
                    "value": _definition_number(row.get("value", "")),
                }
            )
    payload["sources"] = list(sources.values())
    if not payload["point_count"]:
        payload["point_count"] = len(payload["weather"])
    return payload


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _decode_uploaded_definition_text(data: bytes, description: str = "model.e") -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{description} 文件编码无法识别，请保存为 UTF-8 或 GB18030 编码")


def _read_zip_text(archive: zipfile.ZipFile, entry_name: str, required: bool = True) -> Optional[str]:
    try:
        data = archive.read(entry_name)
    except KeyError:
        if required:
            raise ValueError(f"Definition archive is missing {entry_name}") from None
        return None
    return _decode_uploaded_definition_text(data, entry_name)


def _normalize_diagram_svg_text(svg_text: Optional[str]) -> Optional[str]:
    if svg_text is None:
        return None
    text = str(svg_text).lstrip("\ufeff")
    if not text.strip():
        return None
    text = re.sub(
        r'^(\s*<\?xml\b[^>]*?\bencoding\s*=\s*)(["\'])([^"\']+)(\2)',
        lambda match: f'{match.group(1)}{match.group(2)}UTF-8{match.group(2)}',
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    lower = text.lower()
    if "<svg" not in lower:
        raise ValueError("SVG图形文件必须包含 <svg> 根图形内容")
    if "<script" in lower or "javascript:" in lower or re.search(r"\son[a-z0-9_-]+\s*=", text, re.IGNORECASE):
        raise ValueError("SVG图形文件不能包含脚本、事件属性或 javascript 链接")
    return text


def _decode_optional_svg_payload(payload: Mapping[str, Any]) -> Optional[str]:
    data_base64 = str(payload.get("diagram_svg_base64", payload.get("svg_base64", "")) or "")
    if not data_base64:
        return None
    try:
        data = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("SVG图形文件 Base64 数据无效") from exc
    return _decode_uploaded_definition_text(data, "SVG图形")


def _write_model_diagram(target_dir: Path, diagram_svg_text: Optional[str], *, remove_when_absent: bool = False) -> bool:
    path = target_dir / DIAGRAM_FILE_NAME
    normalized = _normalize_diagram_svg_text(diagram_svg_text)
    if normalized is None:
        if remove_when_absent and path.exists() and path.is_file():
            path.unlink()
        return False
    path.write_text(normalized, encoding="utf-8", newline="")
    return True


def _fallback_definition_diagram_svg(service: PolarMicrogridSimulator) -> str:
    model_id = html.escape(str(getattr(service, "model_id", "model") or "model"))
    model_name = html.escape(str(getattr(service, "model_name", model_id) or model_id))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" data-model-diagram="fallback" '
        'width="960" height="540" viewBox="0 0 960 540">'
        '<rect width="960" height="540" fill="#f8fafc"/>'
        '<rect x="220" y="190" width="520" height="160" rx="12" fill="#ffffff" stroke="#94a3b8" stroke-width="2"/>'
        '<text x="480" y="250" text-anchor="middle" font-family="Arial, sans-serif" '
        'font-size="28" fill="#0f172a">'
        f"{model_name}"
        "</text>"
        '<text x="480" y="295" text-anchor="middle" font-family="Arial, sans-serif" '
        'font-size="18" fill="#475569">'
        f"{model_id} · diagram.svg"
        "</text>"
        "</svg>"
    )


MODEL_DEVICE_BLOCKS = {
    "ACNode",
    "DCNode",
    "ACRealBs",
    "DCRealBs",
    "ACBranch",
    "DCBranch",
    "ACZeroBranch",
    "DCZeroBranch",
    "ACSwitch",
    "DCSwitch",
    "ACBreak",
    "DCBreak",
    "ACLoad",
    "DCLoad",
    "ACGenerator",
    "DCGenerator",
    "DCDCConverter",
    "DCACConverter",
    "ACACConverter",
}
SET_VALUE_COLUMN_MAP = {
    "ACGenerator": (("p_set", "p_set"), ("q_set", "q_set"), ("v_set", "v_set")),
    "DCGenerator": (("p_set", "p_set"), ("v_set", "v_set"), ("i_set", "i_set")),
    "DCDCConverter": (("p_set", "p_set"), ("i_set", "i_set"), ("v_set", "v_set")),
    "DCACConverter": (
        ("p_ac_set", "p_ac_set"),
        ("p_dc_set", "p_dc_set"),
        ("q_ac_set", "q_ac_set"),
        ("v_ac_set", "v_ac_set"),
        ("v_dc_set", "v_dc_set"),
    ),
    "ACACConverter": (
        ("p_set", "p_set"),
        ("q_set", "q_set"),
        ("v_set", "v_set"),
        ("p_from_set", "p_from_set"),
        ("q_from_set", "q_from_set"),
        ("v_from_set", "v_from_set"),
        ("p_to_set", "p_to_set"),
        ("q_to_set", "q_to_set"),
        ("v_to_set", "v_to_set"),
    ),
    "ACLoad": (
        ("p_set", "p_set"),
        ("p_set", "pv0"),
        ("q_set", "q_set"),
        ("q_set", "qv0"),
    ),
    "DCLoad": (("p_set", "p_set"), ("p_set", "pv0"), ("v_set", "v_set"), ("i_set", "i_set")),
    "HydroSource": (("flow_set", "flow_set"),),
    "HydroLoad": (("flow_set", "flow_set"),),
    "HeatSource": (("flow_set", "flow_set"),),
}
MEASUREMENT_TYPE_MAP = {
    "ACNode": ("V", "ANGLE"),
    "DCNode": ("V",),
    "ACGenerator": ("P_GEN", "Q_GEN", "V_GEN", "I_GEN"),
    "DCGenerator": ("P_GEN", "V_GEN", "I_GEN"),
    "ACLoad": ("P_LOAD", "Q_LOAD", "V_LOAD", "I_LOAD"),
    "DCLoad": ("P_LOAD", "V_LOAD", "I_LOAD"),
    "HydroSource": ("flow", "pressure"),
    "HydroLoad": ("flow", "pressure"),
    "HydroPipe": ("flow",),
    "HydroValve": ("flow",),
    "HydroCompressor": ("flow",),
    "HydroPressRegulator": ("flow",),
    "HydroStopValve": ("flow",),
    "ACBranch": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "ACTransformer": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "ACZeroBranch": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "ACSwitch": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "ACBreak": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "DCBranch": ("P_FROM", "P_TO", "I"),
    "DCZeroBranch": ("P_FROM", "P_TO", "I"),
    "DCSwitch": ("P_FROM", "P_TO", "I"),
    "DCBreak": ("P_FROM", "P_TO", "I"),
    "DCDCConverter": ("P_FROM", "V_FROM", "I_FROM", "P_TO", "V_TO", "I_TO"),
    "DCACConverter": ("P_DC", "V_DC", "I_DC", "P_AC", "Q_AC", "V_AC", "I_AC"),
    "ACACConverter": ("P_FROM", "Q_FROM", "V_FROM", "I_FROM", "P_TO", "Q_TO", "V_TO", "I_TO"),
    "HydroStorage": ("pressure", "flow", "gas_quantity", "soc"),
}
STORAGE_PARAMETER_SPECS = (
    ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
    ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
)
CONVERTER_MODEL_BLOCKS = ("DCACConverter", "DCDCConverter", "ACACConverter")
AMBIGUOUS_CONVERTER_RUNTIME_FIELDS = frozenset({"p", "q", "u", "i"})


def _rows(book: EBook, block_name: str) -> list[dict]:
    block = book.data.get(block_name)
    return [] if block is None else list(block.data)


def _ebook_from_blocks(blocks: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]]) -> EBook:
    book = EBook({})
    for block_name, (headers, rows) in blocks.items():
        block = EBlock(block_name)
        block.header_list = list(headers)
        block.data = [{header: row.get(header, "") for header in headers} for row in rows]
        book.data[block_name] = block
    return book


def _remove_ambiguous_converter_runtime_fields(model_book: EBook) -> int:
    removed = 0
    for block_name in CONVERTER_MODEL_BLOCKS:
        block = model_book.data.get(block_name)
        if block is None:
            continue
        headers = [
            field
            for field in getattr(block, "header_list", [])
            if str(field).strip().casefold() not in AMBIGUOUS_CONVERTER_RUNTIME_FIELDS
        ]
        removed += len(getattr(block, "header_list", [])) - len(headers)
        block.header_list = headers
        block.data = [
            {field: row.get(field, "") for field in headers}
            for row in getattr(block, "data", [])
        ]
    return removed


def _row_name(row: Mapping[str, Any]) -> str:
    return str(row.get("name", row.get("dev_name", ""))).strip()


def _numeric(value: Any, default: float = 0.0) -> float:
    number = _to_float(value, None)
    if number is None:
        text = str(value or "")
        if text.endswith("%"):
            number = _to_float(text[:-1], None)
            return default if number is None else float(number) / 100.0
        return default
    return float(number)


def _storage_soc_value(value: Any, default: float = 0.5) -> float:
    text = str(value or "").strip()
    raw_value = text.replace("%", "").strip() if "%" in text else value
    number = _to_float(raw_value, None)
    if number is None:
        return default
    if "%" in text or 2.0 < abs(number) <= 100.0:
        return number / 100.0
    return number


def _first_present(row: Mapping[str, Any], columns: Sequence[str], default: Any = "") -> Any:
    for column in columns:
        if column in row and row.get(column, "") != "":
            return row.get(column)
    return default


def _model_book_has_power_model(book: EBook) -> bool:
    return any(name in MODEL_DEVICE_BLOCKS and getattr(block, "data", []) for name, block in book.data.items())


def _validate_dcac_converter_schema(model_book: EBook) -> None:
    block = model_book.data.get("DCACConverter")
    if block is None or not getattr(block, "data", []):
        return
    headers = set(getattr(block, "header_list", []))
    if "control_type" in headers:
        raise ValueError(
            "DCACConverter 已取消 control_type，请使用 ac_control_type 和 dc_control_type"
        )
    required = {"ac_control_type", "dc_control_type", "p_ac_set", "p_dc_set"}
    missing = sorted(required - headers)
    if missing:
        raise ValueError(
            f"DCACConverter 缺少必需字段: {', '.join(missing)}"
        )


_REQUIRED_POWER_MODEL_FIELDS = {
    "ACRealBs": {"node"},
    "DCRealBs": {"node"},
    "ACGenerator": {"node", "control_type", "p_set", "q_set", "v_set"},
    "DCGenerator": {"node", "control_type", "p_set", "v_set", "i_set"},
}

_SAFE_DEFAULT_MODEL_FIELDS = {
    "ACRealBs": {"u", "f"},
    "DCRealBs": {"u", "i"},
    "ACBranch": {"p", "q", "i"},
    "ACZeroBranch": {"p", "q", "i"},
    "ACSwitch": {"p", "q", "i"},
    "ACBreak": {"p", "q", "i"},
    "DCBranch": {"p", "u", "i"},
    "DCZeroBranch": {"p", "i"},
    "DCSwitch": {"p", "i"},
    "DCBreak": {"p", "i"},
    "ACGenerator": {"p", "q", "u", "i"},
    "DCGenerator": {"p", "u", "i"},
    "ACLoad": {"p_set", "p", "q", "u", "i"},
    "DCLoad": {"p_set", "p", "u", "i"},
    "DCDCConverter": {"p_set", "i_set", "v_set"},
    "DCACConverter": {
        "p_ac_set",
        "p_dc_set",
        "q_ac_set",
        "i_dc_set",
        "v_ac_set",
        "v_dc_set",
    },
}

_SVG_REQUIRED_MODEL_BLOCKS = {
    "ACRealBs",
    "DCRealBs",
    "ACBranch",
    "DCBranch",
    "ACZeroBranch",
    "DCZeroBranch",
    "ACSwitch",
    "DCSwitch",
    "ACBreak",
    "DCBreak",
    "ACLoad",
    "DCLoad",
    "ACGenerator",
    "DCGenerator",
    "DCDCConverter",
    "DCACConverter",
    "ACACConverter",
    "AcE2Hydro",
    "DcE2Hydro",
    "Hydro2AcE",
    "Hydro2DcE",
    "HydroSource",
    "HydroLoad",
    "HydroPipe",
    "HydroValve",
    "HydroCompressor",
    "HydroPressRegulator",
    "HydroStopValve",
    "HydroStorage",
}


class ModelPreflightError(ValueError):
    """A failed, non-mutating model import validation."""

    def __init__(self, validation: Mapping[str, Any]) -> None:
        self.validation = dict(validation)
        super().__init__(str(self.validation.get("summary") or "模型预校核未通过"))


def _xml_local_name(value: Any) -> str:
    return str(value or "").rsplit("}", 1)[-1]


def _diagram_svg_inventory(svg_text: Optional[str]) -> Mapping[str, Any]:
    normalized = _normalize_diagram_svg_text(svg_text)
    if normalized is None:
        return {"svg": None, "devices": [], "edge_device_ids": []}
    try:
        root = ET.fromstring(normalized)
    except ET.ParseError as exc:
        raise ValueError(f"SVG图形 XML 解析失败: {exc}") from exc
    if _xml_local_name(root.tag).casefold() != "svg":
        raise ValueError("SVG图形文件的根元素必须是 <svg>")
    if str(root.attrib.get("data-model-diagram", "")).strip().casefold() == "fallback":
        return {"svg": None, "devices": [], "edge_device_ids": []}

    devices: list[dict[str, str]] = []
    edge_device_ids: list[str] = []
    for element in root.iter():
        attributes = {
            _xml_local_name(key): str(value or "").strip()
            for key, value in element.attrib.items()
        }
        for field in ("source-dev-id", "target-dev-id"):
            value = attributes.get(field, "")
            if value:
                edge_device_ids.append(value)
        tag = _xml_local_name(element.tag).casefold()
        # ``dev`` is a measurement-overlay reference such as ``ACGenerator-31``;
        # it is not a device type and must not be counted as another SVG device.
        explicit_type = attributes.get("dev-type", attributes.get("device-type", ""))
        device_id = attributes.get("dev-id", "")
        if tag != "use" and (tag != "g" or not device_id):
            continue
        if not device_id and tag == "use":
            candidate_id = attributes.get("id", "")
            if "-" in candidate_id and not candidate_id.startswith(("label_", "measure_")):
                device_id = candidate_id
        if not device_id:
            continue
        devices.append(
            {
                "dev_id": device_id,
                "dev_type": explicit_type,
                "idx": attributes.get("idx", ""),
                "name": attributes.get("name", ""),
                "node": attributes.get("node", ""),
            }
        )
    return {
        "svg": normalized,
        "devices": devices,
        "edge_device_ids": sorted(set(edge_device_ids)),
    }


def _resolve_svg_devices(model_book: EBook, inventory: Mapping[str, Any]) -> list[dict[str, str]]:
    block_names = {
        str(name)
        for name in model_book.data
    } | set(_SVG_REQUIRED_MODEL_BLOCKS)
    resolved: list[dict[str, str]] = []
    for source in inventory.get("devices", []):
        if not isinstance(source, Mapping):
            continue
        item = {str(key): str(value or "").strip() for key, value in source.items()}
        dev_type = item.get("dev_type", "")
        dev_id = item.get("dev_id", "")
        idx = item.get("idx", "")
        if not dev_type and dev_id:
            for block_name in sorted(block_names, key=len, reverse=True):
                prefix = f"{block_name}-"
                if dev_id.startswith(prefix):
                    dev_type = block_name
                    if not idx:
                        idx = dev_id[len(prefix):]
                    break
        item["dev_type"] = dev_type
        item["idx"] = idx
        resolved.append(item)
    return resolved


def _preflight_number_text(value: float) -> str:
    text = format(float(value), ".15g")
    return "0" if text in {"-0", "-0.0"} else text


def _bounded_zero_default(row: Mapping[str, Any], minimum_field: str, maximum_field: str) -> str:
    lower = _to_float(row.get(minimum_field), None)
    upper = _to_float(row.get(maximum_field), None)
    value = 0.0
    if lower is not None:
        value = max(value, float(lower))
    if upper is not None:
        value = min(value, float(upper))
    return _preflight_number_text(value)


def _node_base_voltage(model_book: EBook, domain: str, node_idx: Any) -> Optional[float]:
    normalized_idx = str(node_idx or "").strip()
    node_block = model_book.data.get(f"{domain}Node")
    if normalized_idx and node_block is not None:
        for node_row in getattr(node_block, "data", []):
            if str(node_row.get("idx", "")).strip() != normalized_idx:
                continue
            voltage = _to_float(node_row.get("vbase", node_row.get("voltage")), None)
            if voltage is not None and float(voltage) > 0.0:
                return float(voltage)
    return None


def _connected_node_voltage(
    model_book: EBook,
    block_name: str,
    row: Mapping[str, Any],
    field: str = "v_set",
) -> Optional[float]:
    candidates: list[tuple[str, Any]] = []
    if field == "v_ac_set":
        candidates.append(("AC", row.get("ac_node")))
    elif field == "v_dc_set":
        candidates.append(("DC", row.get("dc_node")))
    elif block_name == "DCDCConverter":
        candidates.extend(("DC", row.get(key)) for key in ("i_node", "j_node"))
    elif block_name.startswith("AC"):
        candidates.append(("AC", row.get("node", row.get("i_node"))))
    else:
        candidates.append(("DC", row.get("node", row.get("i_node"))))
    for domain, node_idx in candidates:
        voltage = _node_base_voltage(model_book, domain, node_idx)
        if voltage is not None:
            return voltage
    rated = _to_float(row.get("rated_voltage"), None)
    return float(rated) if rated is not None and float(rated) > 0.0 else None


def _safe_model_field_default(
    model_book: EBook,
    block_name: str,
    row: Mapping[str, Any],
    field: str,
) -> tuple[Optional[str], str]:
    if field in {"v_set", "v_ac_set", "v_dc_set", "u"}:
        voltage = _connected_node_voltage(model_book, block_name, row, field)
        if voltage is not None:
            return _preflight_number_text(voltage), "额定电压或连接节点基准电压"
        if field == "u":
            return "0", "运行量初值"
        return None, ""
    if field == "p_set" and block_name in {"ACLoad", "DCLoad"}:
        pbase = _to_float(row.get("pbase"), None)
        if pbase is not None:
            # ACLoad/DCLoad expose p_set as the writable alias of pbase.  Copying
            # pbase preserves the original ZIP load pbase*pv0 operating point.
            return _preflight_number_text(float(pbase)), "静态负荷模型 pbase"
        return _bounded_zero_default(row, "p_min", "p_max"), "功率上下限内的零值"
    if field in {"p_set", "p_ac_set", "p_dc_set"}:
        minimum_field = "p_min"
        maximum_field = "p_max"
        if field == "p_ac_set":
            minimum_field, maximum_field = "ac_p_min", "ac_p_max"
        elif field == "p_dc_set":
            minimum_field, maximum_field = "dc_p_min", "dc_p_max"
        return _bounded_zero_default(row, minimum_field, maximum_field), "功率上下限内的零值"
    if field in {"q_set", "q_ac_set"}:
        minimum_field, maximum_field = ("q_min", "q_max")
        if field == "q_ac_set":
            minimum_field, maximum_field = ("ac_q_min", "ac_q_max")
        return _bounded_zero_default(row, minimum_field, maximum_field), "无功上下限内的零值"
    if field in {"i_set", "i_dc_set"}:
        minimum_field, maximum_field = ("i_min", "i_max")
        if field == "i_dc_set":
            minimum_field, maximum_field = ("dc_i_min", "dc_i_max")
        return _bounded_zero_default(row, minimum_field, maximum_field), "电流上下限内的零值"
    if field == "f":
        return "50", "交流额定频率"
    if field in {"p", "q", "i"}:
        return "0", "运行量初值"
    return None, ""


def _repair_power_model_schema(
    model_book: EBook,
    svg_devices: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Fill only deterministic defaults; ambiguous topology/control stays invalid."""

    repairs: list[dict[str, str]] = []
    resolved_svg = _resolve_svg_devices(model_book, {"devices": list(svg_devices)})

    def svg_row(block_name: str, row: Mapping[str, Any]) -> Optional[Mapping[str, str]]:
        idx = str(row.get("idx", "")).strip()
        name = str(row.get("name", "")).strip()
        matches = [
            item
            for item in resolved_svg
            if item.get("dev_type") == block_name
            and (
                (idx and item.get("idx") == idx)
                or (name and item.get("name") == name)
            )
        ]
        if len(matches) != 1:
            return None
        match = matches[0]
        svg_name = str(match.get("name", "")).strip()
        return match if not svg_name or not name or svg_name == name else None

    candidate_blocks = set(_REQUIRED_POWER_MODEL_FIELDS) | set(_SAFE_DEFAULT_MODEL_FIELDS)
    for block_name in sorted(candidate_blocks):
        candidate_fields = (
            set(_REQUIRED_POWER_MODEL_FIELDS.get(block_name, set()))
            | set(_SAFE_DEFAULT_MODEL_FIELDS.get(block_name, set()))
        )
        block = model_book.data.get(block_name)
        if block is None or not getattr(block, "data", []):
            continue
        headers = list(getattr(block, "header_list", []))
        for field in sorted(candidate_fields):
            field_was_missing = field not in headers
            repaired_any = False
            for row in block.data:
                if str(row.get(field, "")).strip():
                    continue
                replacement: Optional[str] = None
                source = ""
                if field == "node":
                    diagram_row = svg_row(block_name, row)
                    svg_node = str((diagram_row or {}).get("node", "")).strip()
                    if svg_node:
                        replacement = svg_node
                        source = "SVG设备节点"
                else:
                    replacement, source = _safe_model_field_default(
                        model_book,
                        block_name,
                        row,
                        field,
                    )
                if replacement is None:
                    continue
                row[field] = replacement
                repaired_any = True
                repairs.append(
                    {
                        "block": block_name,
                        "device": str(row.get("name", row.get("idx", ""))).strip(),
                        "field": field,
                        "value": replacement,
                        "source": source,
                    }
                )
            if field_was_missing and repaired_any:
                headers.append(field)
        block.header_list = headers
    return repairs


def _validate_power_model_schema(model_book: EBook) -> None:
    """Reject definitions that silently remove a bus anchor or generator control."""

    issues: list[str] = []
    for block_name in sorted(_SVG_REQUIRED_MODEL_BLOCKS):
        block = model_book.data.get(block_name)
        if block is None or not getattr(block, "data", []):
            continue
        headers = {
            str(field).strip()
            for field in getattr(block, "header_list", [])
            if str(field).strip()
        }
        missing_identity_fields = sorted({"idx", "name"} - headers)
        if missing_identity_fields:
            issues.append(
                f"{block_name} 缺少设备身份字段: {', '.join(missing_identity_fields)}"
            )
        seen_indices: set[str] = set()
        seen_names: set[str] = set()
        for position, row in enumerate(getattr(block, "data", []), start=1):
            idx = str(row.get("idx", "")).strip()
            name = str(row.get("name", "")).strip()
            if not idx:
                issues.append(f"{block_name} 第 {position} 行的稳定索引 idx 为空")
            elif idx in seen_indices:
                issues.append(f"{block_name} 的稳定索引 idx={idx} 重复")
            else:
                seen_indices.add(idx)
            if not name:
                issues.append(f"{block_name} 第 {position} 行的设备名称 name 为空")
            elif name in seen_names:
                issues.append(f"{block_name} 的设备名称 name={name} 重复")
            else:
                seen_names.add(name)
    for block_name, required_fields in _REQUIRED_POWER_MODEL_FIELDS.items():
        block = model_book.data.get(block_name)
        if block is None or not getattr(block, "data", []):
            continue
        headers = {
            str(field).strip()
            for field in getattr(block, "header_list", [])
            if str(field).strip()
        }
        missing = sorted(required_fields - headers)
        if missing:
            issues.append(f"{block_name} 缺少必需字段: {', '.join(missing)}")
        for row in getattr(block, "data", []):
            device = str(row.get("name", row.get("idx", ""))).strip() or "未命名设备"
            empty = sorted(
                field
                for field in required_fields & headers
                if not str(row.get(field, "")).strip()
            )
            if empty:
                issues.append(f"{block_name}/{device} 的必需字段为空: {', '.join(empty)}")
    if issues:
        raise ValueError(
            "model.e 关键潮流字段不完整："
            + "；".join(issues)
            + "。已拒绝更新，以免对应电网被静默判为死岛。"
        )


def _expected_svg_model_rows(model_book: EBook) -> list[tuple[str, str, str]]:
    coupled_endpoints = {
        (
            str(binding.get("target_dev_type", "")).strip(),
            str(binding.get("target_dev_name", "")).strip(),
        )
        for bindings in energy_coupling_control_bindings(model_book).values()
        for binding in bindings
    }
    expected: list[tuple[str, str, str]] = []
    for block_name in sorted(_SVG_REQUIRED_MODEL_BLOCKS):
        block = model_book.data.get(block_name)
        for row in [] if block is None else getattr(block, "data", []):
            idx = str(row.get("idx", "")).strip()
            name = str(row.get("name", "")).strip()
            if not idx or not name or (block_name, name) in coupled_endpoints:
                continue
            expected.append((block_name, idx, name))
    return expected


def _diagram_model_match_result(
    model_book: EBook,
    inventory: Mapping[str, Any],
) -> Mapping[str, Any]:
    if inventory.get("svg") is None:
        return {
            "id": "diagram",
            "label": "E/SVG 匹配性",
            "status": "warning",
            "message": "未提供 SVG 图形，已跳过 E/SVG 匹配性校验。",
            "details": {
                "missing_in_svg": [],
                "unknown_in_model": [],
                "name_mismatches": [],
                "dangling_edges": [],
                "identity_issues": [],
                "duplicate_devices": [],
            },
        }

    expected = _expected_svg_model_rows(model_book)
    by_type_idx = {(block, idx): name for block, idx, name in expected}
    all_model_rows = {
        (str(block_name), str(row.get("idx", "")).strip()): str(row.get("name", "")).strip()
        for block_name, block in model_book.data.items()
        for row in getattr(block, "data", [])
        if str(row.get("idx", "")).strip()
    }
    resolved = _resolve_svg_devices(model_book, inventory)
    matched: set[tuple[str, str]] = set()
    unknown: list[str] = []
    name_mismatches: list[str] = []
    identity_issues: list[str] = []
    svg_device_ids: set[str] = set()
    svg_identity_counts: dict[tuple[str, str], int] = {}
    for item in resolved:
        block_name = str(item.get("dev_type", "")).strip()
        idx = str(item.get("idx", "")).strip()
        name = str(item.get("name", "")).strip()
        dev_id = str(item.get("dev_id", "")).strip()
        if dev_id:
            svg_device_ids.add(dev_id)
        if block_name and idx:
            identity = (block_name, idx)
            svg_identity_counts[identity] = svg_identity_counts.get(identity, 0) + 1
        if not block_name or not idx or not name:
            missing_fields = [
                field
                for field, value in (("dev_type", block_name), ("idx", idx), ("name", name))
                if not value
            ]
            identity_issues.append(
                f"{dev_id or '--'} 缺少 {', '.join(missing_fields)}"
            )
            continue
        model_name = all_model_rows.get((block_name, idx))
        if model_name is None:
            unknown.append(dev_id or f"{block_name}/{name or idx or '--'}")
            continue
        if name and model_name and name != model_name:
            name_mismatches.append(
                f"{block_name}-{idx}: SVG={name}, E={model_name}"
            )
            continue
        if (block_name, idx) in by_type_idx:
            matched.add((block_name, idx))

    missing = [
        f"{block_name}-{idx}/{name}"
        for block_name, idx, name in expected
        if (block_name, idx) not in matched
    ]
    dangling_edges = [
        device_id
        for device_id in inventory.get("edge_device_ids", [])
        if str(device_id) not in svg_device_ids
    ]
    duplicate_devices = [
        f"{block_name}-{idx} 出现 {count} 次"
        for (block_name, idx), count in sorted(svg_identity_counts.items())
        if count > 1
    ]
    details = {
        "expected_device_count": len(expected),
        "svg_device_count": len(resolved),
        "matched_device_count": len(matched),
        "missing_in_svg": missing,
        "unknown_in_model": sorted(set(unknown)),
        "name_mismatches": sorted(set(name_mismatches)),
        "dangling_edges": sorted(set(dangling_edges)),
        "identity_issues": sorted(set(identity_issues)),
        "duplicate_devices": duplicate_devices,
    }
    mismatch_count = sum(
        len(details[key])
        for key in (
            "missing_in_svg",
            "unknown_in_model",
            "name_mismatches",
            "dangling_edges",
            "identity_issues",
            "duplicate_devices",
        )
    )
    if mismatch_count:
        summary_parts = []
        if missing:
            summary_parts.append(f"E 中有 {len(missing)} 台设备未出现在 SVG")
        if unknown:
            summary_parts.append(f"SVG 中有 {len(set(unknown))} 台设备无法在 E 中定位")
        if name_mismatches:
            summary_parts.append(f"有 {len(set(name_mismatches))} 台设备名称不一致")
        if dangling_edges:
            summary_parts.append(f"有 {len(set(dangling_edges))} 个连线端点未绑定图元")
        if identity_issues:
            summary_parts.append(f"有 {len(set(identity_issues))} 个 SVG 图元身份字段不完整")
        if duplicate_devices:
            summary_parts.append(f"有 {len(duplicate_devices)} 个 SVG 设备稳定索引重复")
        return {
            "id": "diagram",
            "label": "E/SVG 匹配性",
            "status": "failed",
            "message": "；".join(summary_parts) + "。",
            "details": details,
        }
    return {
        "id": "diagram",
        "label": "E/SVG 匹配性",
        "status": "passed",
        "message": f"E 与 SVG 的 {len(expected)} 台可视设备身份、索引和名称一致。",
        "details": details,
    }


def _repair_fixed_boundaries(model_book: EBook) -> list[dict]:
    return simu_loop.repair_fixed_boundary_setpoints(model_book)


_FIXED_BOUNDARY_CONTROL_FIELD_ALIASES = {
    "pressure_set": {"pressure_set", "p_set"},
    "supply_temperature_set": {"supply_temperature_set", "supply_temperature"},
    "return_temperature_set": {"return_temperature_set", "return_temperature"},
    "enthalpy_set": {"enthalpy_set", "h_set"},
}


def _repair_fixed_boundary_control_rows(model_book: EBook, control_book: EBook) -> list[dict]:
    """Repair invalid effective boundaries introduced by persisted SetValue rows."""
    set_block = control_book.data.get("SetValue")
    if set_block is None or not getattr(set_block, "data", []):
        return []

    effective_book = copy.deepcopy(model_book)

    run_block = control_book.data.get("RunStat")
    for run_row in [] if run_block is None else getattr(run_block, "data", []):
        dev_type = str(run_row.get("dev_type", "")).strip()
        dev_name = str(run_row.get("dev_name", "")).strip()
        block = effective_book.data.get(dev_type)
        if block is None:
            continue
        targets = [row for row in block.data if _row_name(row) == dev_name]
        if len(targets) == 1:
            targets[0]["run_stat"] = run_row.get("run_stat", "")

    applied_rows: dict[tuple[str, str, str], list[dict]] = {}
    for control_row in set_block.data:
        dev_type = str(control_row.get("dev_type", "")).strip()
        dev_name = str(control_row.get("dev_name", "")).strip()
        set_type = str(control_row.get("set_type", "")).strip()
        block = effective_book.data.get(dev_type)
        if not dev_type or not dev_name or not set_type or block is None:
            continue
        targets = [row for row in block.data if _row_name(row) == dev_name]
        if len(targets) != 1:
            continue
        targets[0][set_type] = control_row.get("set_value", "")
        applied_rows.setdefault((dev_type, dev_name, set_type), []).append(control_row)

    corrections = _repair_fixed_boundaries(effective_book)
    for item in corrections:
        dev_type = str(item["device_type"])
        dev_name = str(item["name"])
        field = str(item["field"])
        set_types = _FIXED_BOUNDARY_CONTROL_FIELD_ALIASES.get(field, {field})
        for set_type in set_types:
            for control_row in applied_rows.get((dev_type, dev_name, set_type), ()):
                control_row["set_value"] = format(item["replacement"], ".15g")
    return corrections


def _ensure_dcac_dcp_control_rows(model_book: EBook, control_book: EBook) -> None:
    _validate_dcac_converter_schema(model_book)
    _repair_fixed_boundaries(model_book)
    converter_block = model_book.data.get("DCACConverter")
    converter_rows = [] if converter_block is None else list(getattr(converter_block, "data", []))
    if not converter_rows:
        return

    set_block = control_book.data.get("SetValue")
    if set_block is None:
        set_block = EBlock("SetValue")
        set_block.header_list = list(STAT_HEADERS["SetValue"])
        set_block.data = []
        control_book.data["SetValue"] = set_block
    required_headers = set(STAT_HEADERS["SetValue"])
    missing_headers = sorted(required_headers - set(getattr(set_block, "header_list", [])))
    if missing_headers:
        raise ValueError(
            f"control.e SetValue 缺少必需字段: {', '.join(missing_headers)}"
        )

    rows = list(getattr(set_block, "data", []))
    for converter in converter_rows:
        name = _row_name(converter)
        if not name:
            raise ValueError("DCACConverter 存在缺少 name 的设备")
        matches = [
            row
            for row in rows
            if str(row.get("dev_type", "")).strip() == "DCACConverter"
            and str(row.get("dev_name", "")).strip() == name
            and str(row.get("set_type", "")).strip() == "p_dc_set"
        ]
        if len(matches) > 1:
            raise ValueError(
                f"control.e 中 DCACConverter.{name}.p_dc_set 遥调定义重复"
            )
        if matches:
            continue
        row = {
            "dev_type": "DCACConverter",
            "dev_name": name,
            "set_type": "p_dc_set",
            "set_value": converter.get("p_dc_set", 0),
        }
        set_block.data.append(row)
        rows.append(row)


def _storage_source_rows(model_book: EBook) -> list[dict]:
    storage_rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for block_name, generator_type, index_field in STORAGE_PARAMETER_SPECS:
        generators = {
            str(row.get("idx", "")): row
            for row in _rows(model_book, generator_type)
            if str(row.get("idx", ""))
        }
        for pos, row in enumerate(_rows(model_book, block_name), start=1):
            source = generators.get(str(row.get(index_field, "")))
            if source is None:
                continue
            name = _row_name(source)
            key = (generator_type, name)
            if not name or key in seen:
                continue
            storage_rows.append(
                {
                    "dev_type": generator_type,
                    "idx": source.get("idx", row.get("idx", pos)),
                    "name": name,
                    "soc_curr": _storage_soc_value(
                        _first_present(row, ("state_of_charge", "soc_curr", "soc_cur", "soc"), 0.5),
                        0.5,
                    ),
                }
            )
            seen.add(key)

    return storage_rows


def _generated_control_blocks(model_book: EBook) -> Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]]:
    _repair_fixed_boundaries(model_book)
    run_rows: list[dict[str, Any]] = []
    cb_rows: list[dict[str, Any]] = []
    set_rows: list[dict[str, Any]] = []
    set_row_keys: set[tuple[str, str, str]] = set()

    for block_name, block in model_book.data.items():
        headers = set(getattr(block, "header_list", []))
        for row in getattr(block, "data", []):
            name = _row_name(row)
            if not name:
                continue
            active_converter_power_field = ""
            if block_name == "DCACConverter":
                active_converter_power_field = next(
                    (
                        field
                        for field in converter_power_setpoint_fields(row)
                        if field in row
                    ),
                    "",
                )
            if "run_stat" in headers:
                run_rows.append(
                    {
                        "dev_type": block_name,
                        "dev_name": name,
                        "run_stat": row.get("run_stat", 1),
                    }
                )
            if "status" in headers:
                cb_rows.append(
                    {
                        "dev_type": block_name,
                        "dev_name": name,
                        "status": row.get("status", 1),
                    }
                )
            for set_type, source_column in SET_VALUE_COLUMN_MAP.get(block_name, ()):
                if (
                    block_name == "DCACConverter"
                    and set_type in {"p_ac_set", "p_set"}
                    and set_type != active_converter_power_field
                ):
                    continue
                if source_column in row:
                    source_value = row.get(source_column, 0)
                else:
                    continue
                if block_name in {"ACLoad", "DCLoad"} and source_column == "pv0":
                    source_value = _numeric(row.get("pbase"), 1.0) * _numeric(source_value, 0.0)
                elif block_name == "ACLoad" and source_column == "qv0":
                    source_value = _numeric(row.get("qbase"), 1.0) * _numeric(source_value, 0.0)
                if source_value in (None, "", "-"):
                    continue
                set_row_key = (block_name, name, set_type)
                if set_row_key in set_row_keys:
                    continue
                set_row_keys.add(set_row_key)
                set_rows.append(
                    {
                        "dev_type": block_name,
                        "dev_name": name,
                        "set_type": set_type,
                        "set_value": source_value,
                    }
                )

    blocks: dict[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]] = {
        "RunStat": (STAT_HEADERS["RunStat"], run_rows),
        "SetValue": (STAT_HEADERS["SetValue"], set_rows),
    }
    if cb_rows:
        blocks["CbOpenStat"] = (STAT_HEADERS["CbOpenStat"], cb_rows)
    storage_rows = _storage_source_rows(model_book)
    if storage_rows:
        blocks["StorageSoc"] = (STAT_HEADERS["StorageSoc"], storage_rows)
    hydrogen_state_book = EBook({})
    simu_loop.ensure_hydrogen_storage_state_rows_book(hydrogen_state_book, model_book)
    hydrogen_state = hydrogen_state_book.data.get(simu_loop.HYDROGEN_STORAGE_STATE_BLOCK)
    if hydrogen_state is not None and hydrogen_state.data:
        blocks[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK] = (
            simu_loop.HYDROGEN_STORAGE_STATE_HEADERS,
            list(hydrogen_state.data),
        )
    return blocks


def _generated_measurement_book(
    model_book: EBook,
    control_blocks: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]],
) -> EBook:
    rows: list[dict[str, Any]] = []
    name_counts: dict[str, int] = {}
    storage_rows = list(control_blocks.get("StorageSoc", ((), ()))[1])
    storage_by_key = {
        (str(row.get("dev_type", "")), str(row.get("name", ""))): row
        for row in storage_rows
    }
    storage_names = set(storage_by_key)
    measured_storage_keys: set[tuple[str, str]] = set()

    def add(
        dev_type: str,
        dev_name: str,
        meas_type: str,
        *,
        weight: float = 10000.0,
        value: Any = 0.0,
        valid: int = 1,
    ) -> None:
        if not dev_name:
            return
        base_name = automatic_point_name(dev_type, dev_name, meas_type)
        count = name_counts.get(base_name, 0)
        name_counts[base_name] = count + 1
        name = base_name if count == 0 else f"{base_name}.{count + 1}"
        rows.append(
            {
                "idx": len(rows) + 1,
                "name": name,
                "dev_type": dev_type,
                "dev_name": dev_name,
                "meas_type": meas_type,
                "weight": weight,
                "valid": valid,
                "value": value,
            }
        )

    for block_name, meas_types in MEASUREMENT_TYPE_MAP.items():
        for row in _rows(model_book, block_name):
            name = _row_name(row)
            if not name:
                continue
            for meas_type in meas_types:
                add(block_name, name, meas_type)
            storage_key = (block_name, name)
            if storage_key in storage_names:
                add(block_name, name, "SOC", value=storage_by_key[storage_key].get("soc_curr", 0.5))
                measured_storage_keys.add(storage_key)

    for storage_key, storage_row in storage_by_key.items():
        if storage_key in measured_storage_keys:
            continue
        add(
            storage_key[0],
            storage_key[1],
            "SOC",
            value=storage_row.get("soc_curr", 0.5),
        )

    for weather_key, _name_suffix, meas_type in WEATHER_MEASUREMENTS:
        value = _to_float(DEFAULT_WEATHER.get(weather_key), None)
        add(
            "Environment",
            "weather",
            meas_type,
            weight=1.0,
            value=value if value is not None else 0.0,
            valid=1 if value is not None else 0,
        )

    for block_name, value_column, meas_type, _name_suffix in SIGNAL_MEASUREMENTS:
        for row in control_blocks.get(block_name, ((), ()))[1]:
            add(
                str(row.get("dev_type", "")),
                str(row.get("dev_name", "")),
                meas_type,
                weight=1.0,
                value=row.get(value_column, 1),
            )

    return _ebook_from_blocks({"Measurement": (MEAS_HEADER, rows)})


def _generated_weather_book() -> EBook:
    row = {
        **{key: UNKNOWN_WEATHER_VALUE if value is None else value for key, value in DEFAULT_WEATHER.items()},
        "time": "00:00:00",
    }
    return _ebook_from_blocks({"Weather": (WEATHER_HEADER, [row])})


def _load_base_kw(row: Mapping[str, Any], block_name: str) -> float:
    if block_name == "ACLoad":
        pbase = _numeric(row.get("pbase"), 0.0)
        pv0 = _numeric(row.get("pv0", row.get("p_set", row.get("p", 0.0))), 0.0)
        if pbase not in (0.0, 1.0) and pv0:
            return max(0.0, pbase * pv0)
        return max(0.0, pv0 or pbase or _numeric(row.get("p_set"), 0.0))
    return max(0.0, _numeric(_first_present(row, ("p_set", "p", "p0", "p_kw"), 0.0), 0.0))


def _load_curve_sources(model_book: EBook) -> list[tuple[str, float]]:
    sources: list[tuple[str, float]] = []
    coupled_loads = {
        (
            str(binding.get("target_dev_type", "")),
            str(binding.get("target_dev_name", "")),
        )
        for bindings in energy_coupling_control_bindings(model_book).values()
        for binding in bindings
        if binding.get("set_type") == "p_set"
        and binding.get("target_dev_type") in {"ACLoad", "DCLoad"}
    }
    for block_name in ("ACLoad", "DCLoad"):
        for row in _rows(model_book, block_name):
            name = _row_name(row)
            if name and (block_name, name) not in coupled_loads:
                sources.append((name, _load_base_kw(row, block_name) or DEFAULT_WEATHER["load_kw"]))
    return sources


def _generated_curves_payload(model_book: EBook) -> dict[str, Any]:
    point_count = 1440
    load_sources = _load_curve_sources(model_book)
    weather: list[dict[str, Any]] = []
    loads: dict[str, list[dict[str, Any]]] = {name: [] for name, _base in load_sources}
    for minute in range(point_count):
        day_angle = 2.0 * math.pi * minute / point_count
        solar_shape = max(0.0, math.sin(math.pi * (minute - 360) / 720.0))
        wind_speed = max(0.0, min(50.0, 14.0 + 8.0 * math.sin(day_angle - 0.9) + 3.0 * math.sin(4.0 * day_angle)))
        air_temp = -20.0 + 7.0 * math.sin(day_angle - math.pi / 2.0)
        weather.append(
            {
                "minute": minute,
                "wind_speed_mps": round(wind_speed, 3),
                "air_temp_c": round(air_temp, 3),
                "air_pressure_hpa": round(960.0 + 4.0 * math.sin(day_angle + 0.5), 3),
                "solar_irradiance_w_m2": round(720.0 * solar_shape, 3),
                "humidity_pct": round(72.0 + 8.0 * math.sin(day_angle + 1.2), 3),
            }
        )
        load_shape = 0.88 + 0.12 * math.sin(day_angle - 1.1) + (0.16 if 1020 <= minute <= 1320 else 0.0)
        for name, base_kw in load_sources:
            loads.setdefault(name, []).append({"minute": minute, "p_kw": round(max(0.0, base_kw * load_shape), 3)})
    return {
        "mode": "day",
        "time_step_minutes": 1,
        "point_count": point_count,
        "weather": weather,
        "loads": loads,
        "sources": [
            {**item, "points": [{"minute": 0.0, "value": item["default_value"]}]}
            for item in source_curve_catalog(model_book)
        ],
    }


def _generated_model_artifacts(
    model_text: str,
    *,
    svg_devices: Sequence[Mapping[str, Any]] = (),
    allow_schema_repairs: bool = False,
    schema_repairs: Optional[list[dict[str, str]]] = None,
) -> Mapping[str, Any]:
    if not str(model_text or "").strip():
        raise ValueError("model.e 不能为空")
    model_book = _book_from_text(model_text)
    _remove_ambiguous_converter_runtime_fields(model_book)
    for block in model_book.data.values():
        for field in getattr(block, "header_list", []):
            if not is_ratio_parameter_field(field):
                continue
            allow_out_of_range = is_soc_parameter_field(field) and str(field).casefold() in {
                "state_of_charge",
                "soc",
                "soc_curr",
                "soc_cur",
            }
            for row in getattr(block, "data", []):
                if row.get(field, "") == "":
                    continue
                row[field] = canonical_ratio_parameter_text(
                    field,
                    row[field],
                    legacy_percent_points=True,
                    allow_out_of_range=allow_out_of_range,
                )
    if not _model_book_has_power_model(model_book):
        raise ValueError("model.e 中未找到可识别的电网模型设备块")
    if allow_schema_repairs:
        repairs = _repair_power_model_schema(model_book, svg_devices)
        if schema_repairs is not None:
            schema_repairs.extend(repairs)
    _validate_power_model_schema(model_book)
    _validate_dcac_converter_schema(model_book)
    _repair_fixed_boundaries(model_book)

    control_blocks = _generated_control_blocks(model_book)
    return {
        "model_book": model_book,
        "stat_book": _ebook_from_blocks(control_blocks),
        "control_book": _ebook_from_blocks(control_blocks),
        "meas_book": _generated_measurement_book(model_book, control_blocks),
        "weather_book": _generated_weather_book(),
        "curves_payload": _generated_curves_payload(model_book),
    }


def _preflight_model_import(
    model_text: str,
    *,
    diagram_svg_text: Optional[str] = None,
    source_label: str = "model.e",
) -> Mapping[str, Any]:
    """Validate and solve an uploaded model without touching its target folder."""

    started = time.perf_counter()
    schema_repairs: list[dict[str, str]] = []
    inventory: Mapping[str, Any]
    diagram_parse_error = ""
    try:
        inventory = _diagram_svg_inventory(diagram_svg_text)
    except ValueError as exc:
        inventory = {"svg": diagram_svg_text, "devices": [], "edge_device_ids": []}
        diagram_parse_error = str(exc)

    artifacts: Optional[Mapping[str, Any]] = None
    schema_error = ""
    try:
        artifacts = _generated_model_artifacts(
            model_text,
            svg_devices=inventory.get("devices", []),
            allow_schema_repairs=True,
            schema_repairs=schema_repairs,
        )
        schema_check: Mapping[str, Any] = {
            "id": "schema",
            "label": "必要字段",
            "status": "repaired" if schema_repairs else "passed",
            "message": (
                f"已自动补齐 {len(schema_repairs)} 个可确定的必要字段默认值。"
                if schema_repairs
                else "必要字段完整，无需自动补值。"
            ),
            "repairs": schema_repairs,
        }
    except (ValueError, OSError) as exc:
        schema_error = str(exc)
        schema_check = {
            "id": "schema",
            "label": "必要字段",
            "status": "failed",
            "message": schema_error,
            "repairs": schema_repairs,
        }

    if diagram_parse_error:
        diagram_check: Mapping[str, Any] = {
            "id": "diagram",
            "label": "E/SVG 匹配性",
            "status": "failed",
            "message": diagram_parse_error,
            "details": {
                "missing_in_svg": [],
                    "unknown_in_model": [],
                    "name_mismatches": [],
                    "dangling_edges": [],
                    "identity_issues": [],
                    "duplicate_devices": [],
            },
        }
    elif artifacts is None:
        diagram_check = {
            "id": "diagram",
            "label": "E/SVG 匹配性",
            "status": "blocked",
            "message": "E 文件必要字段校验失败，无法继续核对 SVG 设备身份。",
            "details": {
                "missing_in_svg": [],
                "unknown_in_model": [],
                "name_mismatches": [],
                "dangling_edges": [],
                "identity_issues": [],
                "duplicate_devices": [],
            },
        }
    else:
        diagram_check = _diagram_model_match_result(artifacts["model_book"], inventory)

    if artifacts is None:
        power_flow_check: Mapping[str, Any] = {
            "id": "power_flow",
            "label": "单次潮流",
            "status": "blocked",
            "message": "E 文件必要字段校验失败，未执行潮流计算。",
            "solver_info": "",
        }
    else:
        power_flow_started = time.perf_counter()
        try:
            _snapshot, solver_info = simu_loop.solve_hybrid_snapshot_from_book(
                copy.deepcopy(artifacts["model_book"]),
                Path(Path(str(source_label or "model.e")).name or "model.e"),
            )
            power_flow_check = {
                "id": "power_flow",
                "label": "单次潮流",
                "status": "passed",
                "message": f"潮流计算收敛：{solver_info}",
                "solver_info": solver_info,
                "duration_ms": round((time.perf_counter() - power_flow_started) * 1000.0, 3),
            }
        except Exception as exc:
            power_flow_check = {
                "id": "power_flow",
                "label": "单次潮流",
                "status": "failed",
                "message": f"潮流计算不收敛或无法建立网络：{exc}",
                "solver_info": str(exc),
                "duration_ms": round((time.perf_counter() - power_flow_started) * 1000.0, 3),
            }

    checks = [power_flow_check, schema_check, diagram_check]
    failed_checks = [
        item
        for item in checks
        if item.get("status") in {"failed", "blocked"}
    ]
    ok = not failed_checks
    signature_source = (
        str(model_text or "")
        + "\0"
        + str(inventory.get("svg") or diagram_svg_text or "")
    ).encode("utf-8", errors="replace")
    if ok:
        summary = (
            "模型预校核通过：必要字段、E/SVG 匹配性和单次潮流均满足加载条件。"
            if inventory.get("svg") is not None
            else "模型预校核通过：必要字段和单次潮流满足加载条件；未提供 SVG，匹配性校验已跳过。"
        )
    else:
        failed_labels = "、".join(str(item.get("label") or item.get("id")) for item in failed_checks)
        summary = f"模型预校核未通过：{failed_labels}。模型文件未写入。"
    validation = {
        "ok": ok,
        "status": "passed" if ok else "failed",
        "summary": summary,
        "source": str(source_label or "model.e"),
        "checks": checks,
        "repairs": schema_repairs,
        "signature": hashlib.sha256(signature_source).hexdigest(),
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }
    if not ok:
        raise ModelPreflightError(validation)
    assert artifacts is not None
    return {
        "artifacts": artifacts,
        "diagram_svg_text": inventory.get("svg"),
        "validation": validation,
    }


def _merge_generated_curves_payload(
    existing_payload: Mapping[str, Any],
    generated_payload: Mapping[str, Any],
) -> dict[str, Any]:
    merged = copy.deepcopy(dict(existing_payload))
    for key, value in generated_payload.items():
        if key not in {"loads", "sources"} and key not in merged:
            merged[key] = copy.deepcopy(value)

    existing_loads = existing_payload.get("loads", {})
    generated_loads = generated_payload.get("loads", {})
    existing_loads = existing_loads if isinstance(existing_loads, Mapping) else {}
    generated_loads = generated_loads if isinstance(generated_loads, Mapping) else {}

    try:
        target_count = int(merged.get("point_count", 0) or 0)
    except (TypeError, ValueError):
        target_count = 0
    if target_count <= 0:
        weather = merged.get("weather", [])
        target_count = len(weather) if isinstance(weather, list) else 0
    if target_count <= 0:
        for values in existing_loads.values():
            if isinstance(values, list):
                target_count = len(values)
                break

    template_points: list[Any] = []
    for values in existing_loads.values():
        if isinstance(values, list) and values:
            template_points = values
            break
    if not template_points:
        weather = merged.get("weather", [])
        if isinstance(weather, list):
            template_points = weather

    try:
        step_minutes = float(merged.get("time_step_minutes", 1) or 1)
    except (TypeError, ValueError):
        step_minutes = 1.0

    def default_curve(values: Any) -> Any:
        source = copy.deepcopy(values)
        if not isinstance(source, list) or not source or target_count <= 0 or len(source) == target_count:
            return source
        resized: list[Any] = []
        for index in range(target_count):
            source_index = min(len(source) - 1, int(index * len(source) / target_count))
            source_point = source[source_index]
            if not isinstance(source_point, Mapping):
                resized.append(copy.deepcopy(source_point))
                continue
            point = dict(source_point)
            if index < len(template_points) and isinstance(template_points[index], Mapping):
                time_fields = {
                    key: copy.deepcopy(value)
                    for key, value in template_points[index].items()
                    if key not in {"p_kw", "value", "load_kw"}
                }
                if time_fields:
                    point = {**time_fields, "p_kw": point.get("p_kw", 0.0)}
            elif "minute" in point:
                point["minute"] = round(index * step_minutes, 9)
            resized.append(point)
        return resized

    merged["loads"] = {
        str(name): (
            copy.deepcopy(existing_loads[name])
            if name in existing_loads
            else default_curve(values)
        )
        for name, values in generated_loads.items()
    }
    existing_sources = existing_payload.get("sources", [])
    generated_sources = generated_payload.get("sources", [])
    existing_by_identity = {
        source_curve_identity(item): item
        for item in existing_sources
        if isinstance(item, Mapping)
    } if isinstance(existing_sources, Sequence) and not isinstance(existing_sources, (str, bytes)) else {}
    merged["sources"] = [
        copy.deepcopy(existing_by_identity.get(source_curve_identity(item), item))
        for item in generated_sources
        if isinstance(item, Mapping)
    ] if isinstance(generated_sources, Sequence) and not isinstance(generated_sources, (str, bytes)) else []
    return merged


def _write_generated_model_artifacts(
    target_dir: Path,
    artifacts: Mapping[str, Any],
    *,
    diagram_svg_text: Optional[str] = None,
    remove_diagram_when_absent: bool = False,
    preserve_existing_curves: bool = False,
) -> list[str]:
    normalized_diagram = _normalize_diagram_svg_text(diagram_svg_text)
    target_dir.mkdir(parents=True, exist_ok=True)
    model_book = artifacts["model_book"]
    meas_book = artifacts["meas_book"]
    stat_book = artifacts["stat_book"]
    control_book = artifacts["control_book"]
    weather_book = artifacts["weather_book"]
    curves_payload = artifacts["curves_payload"]
    simu_loop.write_ebook_aligned(model_book, target_dir / "model.e")
    simu_loop.clear_model_book_cache(target_dir / "model.e")
    simu_loop.write_ebook_aligned(meas_book, target_dir / "meas.e")
    simu_loop.write_ebook_aligned(stat_book, target_dir / "stat.e")
    simu_loop.write_ebook_aligned(control_book, target_dir / "control.e")
    simu_loop.write_ebook_aligned(weather_book, target_dir / "weather.e")
    curves_path = target_dir / "curves.json"
    curves_to_write = curves_payload
    if preserve_existing_curves and curves_path.exists():
        try:
            existing_curves = json.loads(curves_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_curves = {}
        if isinstance(existing_curves, Mapping):
            curves_to_write = _merge_generated_curves_payload(existing_curves, curves_payload)
    _write_json_file(curves_path, curves_to_write)
    (target_dir / "curves.e").write_text(_curve_definition_text(curves_to_write), encoding="utf-8")
    written = ["model.e", "meas.e", "control.e", "stat.e", "weather.e", "curves.e", "curves.json"]
    if _write_model_diagram(target_dir, normalized_diagram, remove_when_absent=remove_diagram_when_absent):
        written.append(DIAGRAM_FILE_NAME)
    return written


def _recover_incomplete_model_directory(manager: Any, new_model_name: Any) -> Optional[Path]:
    """Move a non-model name collision aside without discarding its files."""
    raw_name = str(new_model_name or "").strip()
    target_id = raw_name if isinstance(manager, SimulatorClusterManager) else _service_model_id(raw_name)
    if not target_id:
        return None
    models_root = Path(manager.models_root).resolve()
    target_dir = (models_root / target_id).resolve()
    try:
        target_dir.relative_to(models_root)
    except ValueError as exc:
        raise ValueError(f"模型名称无效: {new_model_name}") from exc
    if not target_dir.exists() or (target_dir / "model.e").exists():
        return None

    runtime_base = Path(
        getattr(manager, "runtime_root", getattr(manager, "runtime_dir", models_root.parent / "runtime"))
    ).resolve()
    recovery_root = runtime_base / ".incomplete-model-backups"
    recovery_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    recovery_dir = recovery_root / f"{target_id}-{timestamp}"
    target_dir.replace(recovery_dir)
    return recovery_dir


def create_model_from_efile(
    manager: MultiModelSimulator,
    new_model_name: Any,
    model_text: str,
    *,
    diagram_svg_text: Optional[str] = None,
    preflight_result: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Create one simulator source model folder from an uploaded model.e file."""
    artifacts = (
        preflight_result["artifacts"]
        if preflight_result is not None
        else _generated_model_artifacts(model_text)
    )
    with manager.lock:
        recovered_dir = _recover_incomplete_model_directory(manager, new_model_name)
        target_id = manager.validate_new_model_name(new_model_name)
        target_dir = (manager.models_root / target_id).resolve()
        try:
            written = _write_generated_model_artifacts(
                target_dir,
                artifacts,
                diagram_svg_text=diagram_svg_text,
            )
            manager._append_manifest_model(target_id, target_dir)
            model_info = manager.service_for(target_id).model_info()
        except Exception:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            raise
    meas_book = artifacts["meas_book"]
    curves_payload = artifacts["curves_payload"]
    result = {
        **model_info,
        "created": {
            "files": written,
            "measurement_count": len(meas_book.data["Measurement"].data),
            "curve_points": curves_payload["point_count"],
            "recovered_incomplete_directory": str(recovered_dir) if recovered_dir else "",
        },
    }
    if preflight_result is not None:
        result["validation"] = preflight_result["validation"]
    return result


def update_model_from_efile(
    manager: MultiModelSimulator,
    model_id: Any,
    model_text: str,
    *,
    diagram_svg_text: Optional[str] = None,
    replace_diagram: bool = False,
    preflight_result: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Replace an existing stopped model's source definitions from an uploaded model.e file."""
    target = manager.service_for(model_id)
    artifacts = (
        preflight_result["artifacts"]
        if preflight_result is not None
        else _generated_model_artifacts(model_text)
    )
    target_dir = Path(target.sim_dir).resolve()
    try:
        target_dir.relative_to(manager.models_root.resolve())
    except ValueError as exc:
        raise ValueError(f"模型目录无效，无法更新定义: {target.model_id}") from exc

    with target.definition_update_lock:
        with target.lock:
            _require_active_service_instance_locked(target)
            if target.clock.state != "stopped":
                raise ValueError(f"模型运行中或暂停中，无法更新定义: {target.model_id}")
            written = _write_generated_model_artifacts(
                target_dir,
                artifacts,
                diagram_svg_text=diagram_svg_text,
                remove_diagram_when_absent=replace_diagram,
                preserve_existing_curves=True,
            )
            target.reset_runtime_for_model_change()
            model_info = target.model_info()
    result = {
        **model_info,
        "updated": {
            "files": written,
            "measurement_count": len(artifacts["meas_book"].data["Measurement"].data),
            "curve_points": artifacts["curves_payload"]["point_count"],
        },
    }
    if preflight_result is not None:
        result["validation"] = preflight_result["validation"]
    return result


def _parse_definition_archive(data: bytes) -> Mapping[str, Any]:
    try:
        with zipfile.ZipFile(BytesIO(data), mode="r") as archive:
            model_text = _read_zip_text(archive, "model.e")
            meas_text = _read_zip_text(archive, "meas.e")
            control_text = _read_zip_text(archive, "control.e")
            curves_text = _read_zip_text(archive, "curves.e")
            diagram_text = _read_zip_text(archive, DIAGRAM_FILE_NAME)
            definition_defaults_text = _read_zip_text(
                archive,
                DEFINITION_DEFAULTS_FILE,
                required=False,
            )
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid definition archive") from exc

    definition_defaults: Optional[Mapping[str, Any]] = None
    if definition_defaults_text is not None:
        try:
            parsed_defaults = json.loads(definition_defaults_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid {DEFINITION_DEFAULTS_FILE}") from exc
        if not isinstance(parsed_defaults, Mapping):
            raise ValueError(f"Invalid {DEFINITION_DEFAULTS_FILE}")
        raw_statuses = parsed_defaults.get("measurement_statuses", {})
        if not isinstance(raw_statuses, Mapping):
            raise ValueError(f"Invalid {DEFINITION_DEFAULTS_FILE}: measurement_statuses must be an object")
        raw_median_deviations = parsed_defaults.get("measurement_median_deviations", {})
        if not isinstance(raw_median_deviations, Mapping):
            raise ValueError(
                f"Invalid {DEFINITION_DEFAULTS_FILE}: "
                "measurement_median_deviations must be an object"
            )
        median_deviations: dict[str, float] = {}
        for raw_name, raw_value in raw_median_deviations.items():
            name = str(raw_name).strip()
            value = _to_float(raw_value, None)
            if not name or value is None or not math.isfinite(value):
                raise ValueError(
                    f"Invalid {DEFINITION_DEFAULTS_FILE}: "
                    f"measurement_median_deviations[{raw_name!r}] must be finite"
                )
            if value != 0.0:
                median_deviations[name] = float(value)
        definition_defaults = {
            "version": int(_to_float(parsed_defaults.get("version"), 1) or 1),
            "measurement_statuses": {
                str(name): dict(value)
                for name, value in raw_statuses.items()
                if str(name).strip() and isinstance(value, Mapping)
            },
            "measurement_median_deviations": median_deviations,
        }

    assert model_text is not None and meas_text is not None and control_text is not None and curves_text is not None
    model_book = _book_from_text(model_text)
    removed_runtime_fields = _remove_ambiguous_converter_runtime_fields(model_book)
    diagram_inventory = _diagram_svg_inventory(diagram_text)
    schema_repairs = _repair_power_model_schema(
        model_book,
        diagram_inventory.get("devices", []),
    )
    _validate_power_model_schema(model_book)
    _validate_dcac_converter_schema(model_book)
    fixed_boundary_corrections = _repair_fixed_boundaries(model_book)
    if removed_runtime_fields or schema_repairs or fixed_boundary_corrections:
        model_text = render_ebook_aligned(model_book)
    measurement_book = _book_from_text(meas_text)
    measurement_block = measurement_book.data.get("Measurement")
    measurement_rows = (
        []
        if measurement_block is None
        else [
            [str(row.get(header, "")) for header in MEAS_HEADER]
            for row in measurement_block.data
        ]
    )
    measurement_rows, added_measurements = (
        simu_loop.reconcile_hydrogen_inline_flow_measurements(
            model_book,
            measurement_rows,
        )
    )
    if added_measurements:
        meas_text = simu_loop.render_measurement_snapshot_aligned(
            (),
            measurement_rows,
            (),
        )
    control_book = _book_from_text(control_text)
    _ensure_dcac_dcp_control_rows(model_book, control_book)
    _repair_fixed_boundary_control_rows(model_book, control_book)
    return {
        "model_text": model_text,
        "meas_text": meas_text,
        "control_text": render_ebook_aligned(control_book),
        "curves_text": curves_text,
        "diagram_text": _normalize_diagram_svg_text(diagram_text),
        "schema_repairs": schema_repairs,
        "definition_defaults": definition_defaults,
        "curves_payload": _curves_from_definition_text(curves_text),
    }


def _apply_parsed_definition_archive_locked(
    service: PolarMicrogridSimulator,
    parsed: Mapping[str, Any],
) -> Mapping[str, Any]:
    _require_active_service_instance_locked(service)
    if service.clock.state != "stopped":
        raise ValueError(f"模型运行中或暂停中，无法更新定义: {service.model_id}")
    model_text = str(parsed["model_text"])
    meas_text = str(parsed["meas_text"])
    control_text = str(parsed["control_text"])
    curves_text = str(parsed["curves_text"])
    diagram_text = parsed.get("diagram_text")
    curves_payload = parsed["curves_payload"]
    written_files: list[str] = []
    root = Path(service.sim_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "model.e").write_text(model_text, encoding="utf-8", newline="")
    simu_loop.clear_model_book_cache(root / "model.e")
    (root / "meas.e").write_text(meas_text, encoding="utf-8", newline="")
    (root / "control.e").write_text(control_text, encoding="utf-8", newline="")
    (root / "curves.e").write_text(curves_text, encoding="utf-8", newline="")
    definition_defaults = parsed.get("definition_defaults")
    definition_defaults_path = root / DEFINITION_DEFAULTS_FILE
    if isinstance(definition_defaults, Mapping):
        _write_json_file(definition_defaults_path, definition_defaults)
    else:
        definition_defaults_path.unlink(missing_ok=True)
    diagram_written = _write_model_diagram(root, diagram_text, remove_when_absent=True)
    legacy_device = root / "device.e"
    if legacy_device.exists() and legacy_device.is_file():
        legacy_device.unlink()
    _merge_control_definition(root / "stat.e", control_text, model_text)
    _write_json_file(root / "curves.json", curves_payload)
    names = ["model.e", "meas.e", "control.e", "curves.e", "stat.e", "curves.json"]
    if isinstance(definition_defaults, Mapping):
        names.append(DEFINITION_DEFAULTS_FILE)
    if diagram_written:
        names.append(DIAGRAM_FILE_NAME)
    written_files.extend(str(root / name) for name in names)

    service.reset_runtime_for_model_change()
    return {
        "written": len(written_files),
        "files": written_files,
        "curve_mode": curves_payload.get("mode"),
        "curve_points": curves_payload.get("point_count"),
        "load_count": len(curves_payload.get("loads", {})),
        "diagram": diagram_written,
    }


def _apply_parsed_definition_archive(
    service: PolarMicrogridSimulator,
    parsed: Mapping[str, Any],
) -> Mapping[str, Any]:
    with service.definition_update_lock:
        with service.lock:
            return _apply_parsed_definition_archive_locked(service, parsed)


def _preflight_parsed_definition_archive(
    parsed: Mapping[str, Any],
    *,
    source_label: str = "definitions.zip/model.e",
) -> Mapping[str, Any]:
    preflight = _preflight_model_import(
        str(parsed["model_text"]),
        diagram_svg_text=parsed.get("diagram_text"),
        source_label=source_label,
    )
    prior_repairs = list(parsed.get("schema_repairs", []))
    if not prior_repairs:
        return preflight
    validation = copy.deepcopy(preflight["validation"])
    validation["repairs"] = prior_repairs + list(validation.get("repairs", []))
    for check in validation.get("checks", []):
        if check.get("id") != "schema":
            continue
        check["status"] = "repaired"
        check["repairs"] = validation["repairs"]
        check["message"] = (
            f"已自动补齐 {len(validation['repairs'])} 个可确定的必要字段默认值。"
        )
        break
    return {**preflight, "validation": validation}


def import_definition_archive(
    service: PolarMicrogridSimulator,
    data: bytes,
    *,
    source_label: str = "definitions.zip/model.e",
) -> Mapping[str, Any]:
    parsed = _parse_definition_archive(data)
    preflight = _preflight_parsed_definition_archive(parsed, source_label=source_label)
    imported = _apply_parsed_definition_archive(service, parsed)
    return {**imported, "validation": preflight["validation"]}


def import_definition_model(
    manager: MultiModelSimulator,
    source_model_id: Optional[str],
    new_model_name: Any,
    data: bytes,
    *,
    source_label: str = "definitions.zip/model.e",
) -> Mapping[str, Any]:
    manager.validate_new_model_name(new_model_name)
    parsed = _parse_definition_archive(data)
    preflight = _preflight_parsed_definition_archive(parsed, source_label=source_label)

    model_info = manager.clone_model(source_model_id, new_model_name)
    imported_service = manager.service_for(str(model_info["id"]))
    imported = _apply_parsed_definition_archive(imported_service, parsed)
    return {
        **model_info,
        "imported": imported,
        "validation": preflight["validation"],
    }


def make_definition_archive(service: PolarMicrogridSimulator) -> tuple[str, bytes]:
    model_path = _definition_file_path(service, "model", "model.e")
    meas_path = _definition_file_path(service, "meas", "meas.e")
    stat_path = _definition_file_path(service, "stat", "stat.e")
    missing = [str(path) for path in (model_path, meas_path, stat_path) if not path.exists()]
    if missing:
        raise JsonApiError(404, f"Definition file not found: {', '.join(missing)}")

    with service.definition_update_lock:
        _require_active_service_instance_locked(service)
        snapshot = service.definition_snapshot
        manual_changes = tuple(service._manual_definition_changes.values())
        has_device_overrides = any(item.get("kind") == "device" for item in manual_changes)
        has_measurement_overrides = any(item.get("kind") == "measurement" for item in manual_changes)

        model_data = (
            render_ebook_aligned(snapshot.model_book).encode("utf-8")
            if has_device_overrides
            else model_path.read_bytes()
        )
        reconciled_measurement_rows, added_measurements = (
            simu_loop.reconcile_hydrogen_inline_flow_measurements(
                snapshot.model_book,
                snapshot.measurement_rows,
            )
        )
        try:
            _source_before, source_measurement_rows, _source_after = (
                simu_loop.parse_measurement_rows(meas_path)
            )
            _source_rows, source_added_measurements = (
                simu_loop.reconcile_hydrogen_inline_flow_measurements(
                    snapshot.model_book,
                    source_measurement_rows,
                )
            )
        except (OSError, RuntimeError, ValueError):
            source_added_measurements = added_measurements
        meas_data = (
            simu_loop.render_measurement_snapshot_aligned(
                snapshot.measurement_before,
                reconciled_measurement_rows,
                snapshot.measurement_after,
            ).encode("utf-8")
            if has_measurement_overrides or source_added_measurements
            else meas_path.read_bytes()
        )
        export_control_book = _book_from_text(render_ebook_aligned(service.control_book))
        _ensure_dcac_dcp_control_rows(snapshot.model_book, export_control_book)
        _repair_fixed_boundary_control_rows(snapshot.model_book, export_control_book)
        control_text = render_ebook_aligned(export_control_book)
        definition_defaults = {
            "version": 1,
            "measurement_statuses": service.effective_measurement_status_defaults(),
            "measurement_median_deviations": (
                service.effective_measurement_median_deviation_defaults()
            ),
        }
        diagram_path = Path(
            getattr(service, "source_files", {}).get(
                "diagram",
                service.sim_dir / DIAGRAM_FILE_NAME,
            )
        )
        diagram_data = (
            diagram_path.read_bytes()
            if diagram_path.exists() and diagram_path.is_file()
            else _fallback_definition_diagram_svg(service).encode("utf-8")
        )

    with service.curves_lock:
        curves_text = _curve_definition_text(service.curves)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_id = getattr(service, "model_id", "model") or "model"
    archive_name = f"{model_id}_definitions_{timestamp}.zip"

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("model.e", model_data)
        archive.writestr("meas.e", meas_data)
        archive.writestr("control.e", control_text.encode("utf-8"))
        archive.writestr("curves.e", curves_text.encode("utf-8"))
        archive.writestr(
            DEFINITION_DEFAULTS_FILE,
            (json.dumps(definition_defaults, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        archive.writestr(DIAGRAM_FILE_NAME, diagram_data)
    return archive_name, buffer.getvalue()


class JsonApiError(Exception):
    def __init__(self, status: int, message: str, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = dict(details or {})


def _require_active_service_instance_locked(service: PolarMicrogridSimulator) -> None:
    checker = getattr(service, "_service_instance_active_locked", None)
    if callable(checker) and not checker():
        raise JsonApiError(409, "请求所属模型生命周期已失效或已退休，操作已取消。")


def make_http_server(
    server_address: tuple[str, int],
    service: PolarMicrogridSimulator | MultiModelSimulator,
    *,
    role: str = "simulator",
    static_root: Optional[str | Path] = None,
    sim_url: Optional[str] = None,
    trainee_exchange: Optional[TraineeRealtimeExchange] = None,
    renewable_control_manager: Optional[TraineeRenewableControlManager] = None,
    direct_simulator_ui: bool = False,
) -> ThreadingHTTPServer:
    role = role.lower()
    if static_root is None:
        static_root = WEB_DIR / ("trainee" if role == "trainee" else "simulator")
    static_root = Path(static_root).resolve()
    sim_url = sim_url.rstrip("/") if sim_url else None
    exchange = trainee_exchange
    if role == "trainee" and exchange is None:
        exchange = TraineeRealtimeExchange(service)
    renewable_manager = renewable_control_manager
    if role == "trainee" and renewable_manager is None:
        if exchange is None:  # pragma: no cover - guarded by learner construction above.
            raise RuntimeError("学员台实时交换服务未初始化")
        renewable_manager = TraineeRenewableControlManager(
            service,
            snapshot_provider=exchange.control_snapshot,
            receive_status_provider=exchange.receive_status,
            command_sink=exchange.submit_commands,
        )
    renewable_control_path = "/api/trainee/renewable-control"
    trainee_ui_frame_path = "/api/trainee/ui-frame"
    external_realtime_inputs_path = "/api/external/realtime-inputs"
    static_asset_cache: dict[Path, dict[str, Any]] = {}
    static_asset_cache_lock = threading.RLock()

    def load_static_asset(target: Path) -> dict[str, Any]:
        stat = target.stat()
        with static_asset_cache_lock:
            cached = static_asset_cache.get(target)
            if (
                cached
                and cached["mtime_ns"] == stat.st_mtime_ns
                and cached["size"] == stat.st_size
            ):
                return cached

        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        compressible = (
            content_type.startswith("text/")
            or content_type
            in {
                "application/javascript",
                "application/json",
                "application/xml",
                "image/svg+xml",
            }
        )
        gzip_data = b""
        if compressible and len(data) >= 512:
            candidate = gzip.compress(data, compresslevel=1, mtime=0)
            if len(candidate) + 32 < len(data):
                gzip_data = candidate
        loaded = {
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "content_type": content_type,
            "data": data,
            "gzip_data": gzip_data,
            "etag": f'"{hashlib.sha256(data).hexdigest()}"',
        }
        with static_asset_cache_lock:
            static_asset_cache[target] = loaded
        return loaded

    def captured_service_is_current(target: PolarMicrogridSimulator) -> bool:
        if hasattr(service, "service_for"):
            try:
                current = service.service_for(target.model_id)  # type: ignore[union-attr]
            except KeyError:
                return False
            if current is not target:
                return False
        elif service is not target:
            return False
        checker = getattr(target, "service_instance_active", None)
        return bool(checker()) if callable(checker) else True

    class PolarMicrogridHandler(BaseHTTPRequestHandler):
        server_version = "PolarMicrogridHTTP/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            try:
                path = urlparse(self.path).path
                if path == external_realtime_inputs_path and role != "simulator":
                    self._handle_api_get()
                    return
                if (
                    path in LOCAL_DEFINITION_PATHS
                    or path == LOCAL_RUNTIME_SETTINGS_PATH
                    or (role == "trainee" and path in TRAINEE_LOCAL_GET_PATHS)
                ):
                    self._handle_api_get()
                    return
                if path == renewable_control_path and role == "trainee":
                    self._handle_api_get()
                    return
                if (
                    self.path.startswith("/api/")
                    and role == "trainee"
                    and sim_url
                    and not path.startswith("/api/trainee/")
                ):
                    self._proxy_to_simulator("GET", sim_url)
                    return
                if self.path.startswith("/api/"):
                    self._handle_api_get()
                    return
                if direct_simulator_ui and role == "simulator" and path in {"", "/", "/index.html"}:
                    ui_mode = (parse_qs(urlparse(self.path).query).get("ui") or [""])[0]
                    if ui_mode != "direct":
                        self.send_response(302)
                        self._cors(cache_control="no-cache")
                        self.send_header("Location", "/?ui=direct")
                        self.end_headers()
                        return
                self._serve_static(static_root)
            except JsonApiError as exc:
                self._send_json(
                    {"error": exc.message, **self._external_error_metadata(exc.details)},
                    status=exc.status,
                )
            except (
                ServiceInstanceRetiredError,
                TraineeExchangeLifecycleError,
                TraineeRenewableControlLifecycleError,
            ) as exc:
                self._send_json(
                    {"error": str(exc), **self._external_error_metadata({})},
                    status=409,
                )
            except Exception as exc:
                self._send_json(
                    {"error": str(exc), **self._external_error_metadata({})},
                    status=500,
                )

        def do_POST(self) -> None:
            try:
                path = urlparse(self.path).path
                if path == external_realtime_inputs_path and role != "simulator":
                    self._handle_api_post()
                    return
                if (
                    path in LOCAL_DEFINITION_PATHS
                    or path == LOCAL_RUNTIME_SETTINGS_PATH
                    or path == SIMULATOR_COMMAND_DELETE_PATH
                    or (role == "trainee" and path in TRAINEE_LOCAL_POST_PATHS)
                ):
                    self._handle_api_post()
                    return
                if path == renewable_control_path and role == "trainee":
                    self._handle_api_post()
                    return
                if (
                    self.path.startswith("/api/")
                    and role == "trainee"
                    and sim_url
                    and not path.startswith("/api/trainee/")
                ):
                    self._proxy_to_simulator("POST", sim_url)
                    return
                self._handle_api_post()
            except JsonApiError as exc:
                self._send_json(
                    {"error": exc.message, **self._external_error_metadata(exc.details)},
                    status=exc.status,
                )
            except Exception as exc:
                self._send_json(
                    {"error": str(exc), **self._external_error_metadata({})},
                    status=500,
                )

        def do_PUT(self) -> None:
            self.do_POST()

        def _request_model_id(self, payload: Optional[Mapping[str, Any]] = None) -> Optional[str]:
            parsed = urlparse(self.path)
            query_values = parse_qs(parsed.query).get("model_id") or parse_qs(parsed.query).get("model")
            if query_values and query_values[0]:
                return query_values[0]
            if payload:
                value = payload.get("model_id", payload.get("model"))
                return str(value) if value not in (None, "") else None
            return None

        def _target_service(self, payload: Optional[Mapping[str, Any]] = None) -> PolarMicrogridSimulator:
            if hasattr(service, "service_for"):
                try:
                    return service.service_for(self._request_model_id(payload))  # type: ignore[union-attr]
                except KeyError as exc:
                    raise JsonApiError(404, str(exc)) from exc
            return service  # type: ignore[return-value]

        def _external_error_metadata(self, details: Mapping[str, Any]) -> Mapping[str, Any]:
            merged = dict(details)
            if not urlparse(self.path).path.startswith("/api/external/"):
                return merged
            try:
                target = self._target_service()
            except Exception:
                return merged
            return target._external_response_metadata() | merged

        def _reject_active_trainee_receive_model(self, payload: Mapping[str, Any], operation: str) -> None:
            if role != "trainee":
                return
            target = self._target_service(payload)
            if target.trainee_receive_state().get("active"):
                raise JsonApiError(400, f"模型正在接收中，不能{operation}。")

        def _model_catalog(self) -> Mapping[str, Any]:
            if hasattr(service, "models"):
                return {
                    "models": service.models(),  # type: ignore[union-attr]
                    "active_model_id": service.default_model_id,  # type: ignore[union-attr]
                    "models_root": str(service.models_root),  # type: ignore[union-attr]
                }
            return {
                "models": [service.model_info()],  # type: ignore[union-attr]
                "active_model_id": service.model_id,  # type: ignore[union-attr]
                "models_root": str(service.sim_dir),  # type: ignore[union-attr]
            }

        def _request_base_url(self) -> str:
            parsed_sim_url = urlparse(sim_url or "")
            scheme = parsed_sim_url.scheme or "http"
            host = self.headers.get("Host") or parsed_sim_url.netloc
            if not host:
                server_host, server_port = self.server.server_address[:2]
                host = f"{server_host}:{server_port}"
            return f"{scheme}://{host}".rstrip("/")

        def _truthy_query(self, name: str) -> bool:
            value = (parse_qs(urlparse(self.path).query).get(name) or [""])[0]
            return str(value).strip().lower() in {"1", "true", "yes", "on"}

        def _falsey_query(self, name: str) -> bool:
            value = (parse_qs(urlparse(self.path).query).get(name) or [""])[0]
            return str(value).strip().lower() in {"0", "false", "no", "off"}

        def _static_query(self, default_include_static: bool) -> tuple[bool, Optional[Sequence[str]]]:
            values = parse_qs(urlparse(self.path).query).get("static")
            if not values:
                return default_include_static, None
            raw = ",".join(str(value) for value in values).strip()
            normalized = raw.lower()
            if not raw or normalized in {"0", "false", "no", "off", "none"}:
                return False, []
            if normalized in {"1", "true", "yes", "on", "all"}:
                return True, None
            fields = [
                field.strip()
                for value in values
                for field in str(value).split(",")
                if field.strip()
            ]
            return bool(fields), fields

        def _int_query(self, name: str, default: int, minimum: int = 0, maximum: int = 500) -> int:
            raw = (parse_qs(urlparse(self.path).query).get(name) or [default])[0]
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return default
            return max(minimum, min(maximum, value))

        def _optional_int_query(self, name: str) -> Optional[int]:
            values = parse_qs(urlparse(self.path).query).get(name)
            if not values or values[0] in (None, ""):
                return None
            try:
                return int(values[0])
            except (TypeError, ValueError):
                return None

        def _measurement_indices_query(self) -> Optional[List[int]]:
            values = parse_qs(urlparse(self.path).query).get("indices")
            if not values:
                return None
            selected: List[int] = []
            seen: set[int] = set()
            for token in ",".join(str(value) for value in values).split(","):
                try:
                    index = int(token.strip())
                except (TypeError, ValueError):
                    continue
                if index < 0 or index in seen:
                    continue
                selected.append(index)
                seen.add(index)
                if len(selected) >= 256:
                    break
            return selected

        def _trainee_link_payload(self, target: PolarMicrogridSimulator) -> Mapping[str, Any]:
            model = target.model_info()
            model_id = str(model.get("id", target.model_id))
            base_url = self._request_base_url()
            encoded_model_id = quote(model_id, safe="")
            external_api = {
                "devices": f"/api/external/devices?model_id={encoded_model_id}",
                "realtime_inputs": f"{external_realtime_inputs_path}?model_id={encoded_model_id}",
                "telemetry_names": f"/api/external/telemetry/names?model_id={encoded_model_id}",
                "telemetry_values": f"/api/external/telemetry/values?model_id={encoded_model_id}",
                "selected_telemetry_values": f"/api/external/telemetry/values/query?model_id={encoded_model_id}",
                "measurement_history": f"/api/external/telemetry/history/query?model_id={encoded_model_id}",
                "control_names": f"/api/external/controls/names?model_id={encoded_model_id}",
                "control_execute": f"/api/external/controls/execute?model_id={encoded_model_id}",
                "curves_query": f"/api/external/curves/query?model_id={encoded_model_id}",
                "curves_update": f"/api/external/curves/update?model_id={encoded_model_id}",
            }
            return {
                "type": "polar-microgrid-trainee-link",
                "version": 1,
                "role": "simulator",
                "link": base_url,
                "teacher_api_base": base_url,
                "model_id": model_id,
                "model_name": model.get("name", model_id),
                "model_version": target.external_model_version(),
                "snapshot_path": f"/api/snapshot?model_id={encoded_model_id}&trainee_view=1",
                "command_path": f"/api/student/commands?model_id={encoded_model_id}",
                "runtime_logs_path": f"/api/runtime-logs?model_id={encoded_model_id}",
                "measurement_delta_path": f"/api/measurements/delta?model_id={encoded_model_id}&trainee_view=1",
                "definition_archive_path": f"/api/export-definitions?format=json&model_id={encoded_model_id}",
                "telemetry_path": f"/api/external/telemetry?model_id={encoded_model_id}",
                "selected_telemetry_path": f"/api/external/telemetry/query?model_id={encoded_model_id}",
                "control_values_path": f"/api/external/controls?model_id={encoded_model_id}",
                "control_command_path": f"/api/external/controls?model_id={encoded_model_id}",
                "device_information_path": external_api["devices"],
                "realtime_inputs_path": external_api["realtime_inputs"],
                "telemetry_names_path": external_api["telemetry_names"],
                "telemetry_values_path": external_api["telemetry_values"],
                "selected_telemetry_values_path": external_api["selected_telemetry_values"],
                "measurement_history_path": external_api["measurement_history"],
                "control_names_path": external_api["control_names"],
                "control_execute_path": external_api["control_execute"],
                "external_api": external_api,
                "shareable": True,
            }

        def _json_request_to_url(
            self,
            url: str,
            *,
            method: str = "GET",
            payload: Optional[Mapping[str, Any]] = None,
            timeout: float = 10.0,
        ) -> Any:
            body = None
            headers = {"Accept": "application/json"}
            if method in ("POST", "PUT"):
                body = json.dumps(payload or {}, ensure_ascii=False, default=str).encode("utf-8")
                headers["Content-Type"] = "application/json; charset=utf-8"
            request = Request(url, data=body, headers=headers, method=method)
            try:
                with urlopen(request, timeout=timeout) as response:
                    text = response.read().decode("utf-8")
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise JsonApiError(exc.code, detail or exc.reason) from exc
            except URLError as exc:
                raise JsonApiError(502, f"模拟台服务不可达：{exc}") from exc
            try:
                return json.loads(text) if text else {}
            except json.JSONDecodeError as exc:
                raise JsonApiError(502, "模拟台返回内容不是有效 JSON") from exc

        def _resolve_trainee_connection(self, raw_link: str) -> Mapping[str, Any]:
            raw = str(raw_link or "").strip()
            if not raw:
                raise JsonApiError(400, "请输入模拟台服务地址")
            parsed = urlparse(raw)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise JsonApiError(400, "模拟台服务地址必须是完整的 http 或 https 地址")
            if parsed.username or parsed.password:
                raise JsonApiError(400, "模拟台服务地址不能包含用户名或密码")
            base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
            payload = self._json_request_to_url(f"{base_url}/api/trainee-link")
            if not isinstance(payload, Mapping):
                raise JsonApiError(400, "模拟台服务返回的连接信息不是对象")
            if payload.get("type") != "polar-microgrid-trainee-link" or payload.get("role") != "simulator":
                raise JsonApiError(400, "模拟台服务地址无效，请使用模拟台生成的服务地址")
            model_id = str(payload.get("model_id") or "").strip()
            if not model_id:
                raise JsonApiError(400, "模拟台连接信息缺少模型标识")
            encoded_model_id = quote(model_id, safe="")
            snapshot_path = self._with_query_overrides(
                f"/api/snapshot?model_id={encoded_model_id}",
                {"trainee_view": 1},
            )
            measurement_delta_path = self._with_query_overrides(
                f"/api/measurements/delta?model_id={encoded_model_id}",
                {"trainee_view": 1},
            )
            return {
                "link": base_url,
                "teacher_api_base": base_url,
                "model_id": model_id,
                "model_name": str(payload.get("model_name") or model_id),
                "snapshot_path": snapshot_path,
                "command_path": f"/api/student/commands?model_id={encoded_model_id}",
                "measurement_delta_path": measurement_delta_path,
                "definition_archive_path": f"/api/export-definitions?format=json&model_id={encoded_model_id}",
            }

        def _with_query_overrides(self, path: str, overrides: Mapping[str, Any]) -> str:
            parsed = urlparse(path or "")
            query = parse_qs(parsed.query, keep_blank_values=True)
            for key, value in overrides.items():
                if value is None:
                    continue
                query[key] = [str(value)]
            return urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    urlencode(query, doseq=True),
                    parsed.fragment,
                )
            )

        def _trainee_remote_url(
            self,
            target: PolarMicrogridSimulator,
            path_key: str,
            *,
            default_path: str,
            query_overrides: Optional[Mapping[str, Any]] = None,
        ) -> str:
            receive_state = target.trainee_receive_state()
            if not receive_state.get("active"):
                raise JsonApiError(409, "当前模型未启动接收")
            base_url = str(receive_state.get("teacher_api_base") or "").rstrip("/")
            if not base_url:
                raise JsonApiError(409, "当前模型未配置模拟台服务地址")
            remote_path = str(receive_state.get(path_key) or default_path)
            if query_overrides:
                remote_path = self._with_query_overrides(remote_path, query_overrides)
            if remote_path.startswith("http://") or remote_path.startswith("https://"):
                return remote_path
            return urljoin(base_url + "/", remote_path.lstrip("/"))

        def _trainee_snapshot_query_overrides(self) -> Mapping[str, Any]:
            values = parse_qs(urlparse(self.path).query)
            allowed = (
                "lite",
                "logs",
                "runtime_logs",
                "measurements",
                "log_limit",
                "devices",
                "device_states",
                "commands",
                "command_history",
                "static",
                "static_meta",
                "device_runtime_compact",
                "device_runtime_supplement",
                "after_device_runtime_signature",
            )
            return {key: values[key][0] for key in allowed if values.get(key)}

        def _renewable_state_payload(self, target: PolarMicrogridSimulator) -> Mapping[str, Any]:
            if role != "trainee" or renewable_manager is None:
                raise JsonApiError(404, f"Unknown API route: {urlparse(self.path).path}")
            renewable_query = parse_qs(urlparse(self.path).query)
            options = {
                "refresh": self._truthy_query("refresh"),
                "compact": self._truthy_query("compact"),
                "after_log_seq": self._int_query(
                    "after_log_seq",
                    0,
                    0,
                    2_000_000_000,
                ),
                "after_trend_sample_key": str(
                    (renewable_query.get("after_trend_sample_key") or [""])[0]
                ),
                "after_plan_revision": self._optional_int_query("after_plan_revision"),
                "after_performance_revision": self._optional_int_query(
                    "after_performance_revision"
                ),
                "after_controller_instance_id": str(
                    (renewable_query.get("after_controller_instance_id") or [""])[0]
                ),
            }
            state_for_service = getattr(renewable_manager, "state_for_service", None)
            if callable(state_for_service):
                return state_for_service(target, **options)
            if not captured_service_is_current(target):
                raise JsonApiError(
                    409,
                    "新能源控制请求所属模型生命周期已失效或已退休。",
                )
            return renewable_manager.state(target.model_id, **options)

        def _trainee_snapshot_payload(
            self,
            target: PolarMicrogridSimulator,
        ) -> Dict[str, Any]:
            if exchange is None:
                raise JsonApiError(404, f"Unknown API route: {urlparse(self.path).path}")
            snapshot_for_service = getattr(exchange, "snapshot_for_service", None)
            if callable(snapshot_for_service):
                snapshot_payload = snapshot_for_service(
                    target,
                    options=self._trainee_snapshot_query_overrides(),
                    refresh=self._truthy_query("refresh"),
                )
            else:
                if not captured_service_is_current(target):
                    raise JsonApiError(
                        409,
                        "学员台快照请求所属模型生命周期已失效或已退休。",
                    )
                snapshot_payload = exchange.snapshot(
                    target.model_id,
                    options=self._trainee_snapshot_query_overrides(),
                    refresh=self._truthy_query("refresh"),
                )
            measurement_after_seq = self._optional_int_query("measurement_after_seq")
            if measurement_after_seq is not None:
                delta_for_service = getattr(exchange, "measurement_delta_for_service", None)
                if callable(delta_for_service):
                    snapshot_payload["measurement_delta"] = delta_for_service(
                        target,
                        after_seq=max(0, measurement_after_seq),
                        compact=self._truthy_query("measurement_compact"),
                    )
                else:
                    delta_options = {"after_seq": max(0, measurement_after_seq)}
                    if self._truthy_query("measurement_compact"):
                        delta_options["compact"] = True
                    snapshot_payload["measurement_delta"] = exchange.measurement_delta(
                        target.model_id,
                        **delta_options,
                    )
            strip_trainee_remote_details_from_snapshot(snapshot_payload)
            trainee_snapshot_query = parse_qs(urlparse(self.path).query)
            after_command_signature = str(
                (trainee_snapshot_query.get("after_command_signature") or [""])[0]
            ).strip()
            commands_payload = snapshot_payload.get("commands")
            if isinstance(commands_payload, Mapping):
                command_signature = command_payload_signature(commands_payload)
                snapshot_payload["command_signature"] = command_signature
                if after_command_signature == command_signature:
                    snapshot_payload.pop("commands", None)
            if self._truthy_query("device_runtime_compact"):
                if self._truthy_query("device_runtime_supplement"):
                    device_runtime_frame = compact_device_runtime_supplement_frame(
                        snapshot_payload.get("devices", []),
                        snapshot_payload.get("device_states", []),
                        target.measurement_definitions(),
                        definition_revision=target.definition_snapshot.revision,
                    )
                else:
                    device_runtime_frame = compact_device_runtime_frame(
                        snapshot_payload.get("devices", []),
                        snapshot_payload.get("device_states", []),
                        definition_revision=target.definition_snapshot.revision,
                    )
                device_runtime_signature = str(
                    device_runtime_frame.get("runtime_signature", "")
                ).strip()
                after_device_runtime_signature = str(
                    (
                        trainee_snapshot_query.get("after_device_runtime_signature")
                        or [""]
                    )[0]
                ).strip()
                snapshot_payload.pop("devices", None)
                snapshot_payload.pop("device_states", None)
                snapshot_payload["device_runtime_signature"] = device_runtime_signature
                if after_device_runtime_signature != device_runtime_signature:
                    snapshot_payload["device_runtime"] = device_runtime_frame
            return snapshot_payload

        def _handle_trainee_connect(self, payload: Mapping[str, Any]) -> None:
            connection = self._resolve_trainee_connection(str(payload.get("link", payload.get("interaction_link", ""))))
            snapshot_url = urljoin(
                connection["teacher_api_base"].rstrip("/") + "/",
                str(connection["snapshot_path"]).lstrip("/"),
            )
            snapshot = self._json_request_to_url(snapshot_url)
            self._send_json({"connection": connection, "snapshot": snapshot})

        @staticmethod
        def _connection_url(connection: Mapping[str, Any], path_key: str) -> str:
            base_url = str(connection.get("teacher_api_base") or "").rstrip("/")
            remote_path = str(connection.get(path_key) or "")
            if remote_path.startswith("http://") or remote_path.startswith("https://"):
                return remote_path
            return urljoin(base_url + "/", remote_path.lstrip("/"))

        def _handle_trainee_model_initialize(self, payload: Mapping[str, Any]) -> None:
            if role != "trainee":
                raise JsonApiError(404, "Unknown API route: /api/trainee/model-initialize")
            target = self._target_service(payload)
            if target.trainee_receive_state().get("active"):
                raise JsonApiError(409, "当前模型正在接收中，不能执行模型初始化。")

            connection = self._resolve_trainee_connection(
                str(payload.get("link", payload.get("interaction_link", "")))
            )
            archive_url = self._connection_url(connection, "definition_archive_path")
            archive_payload = self._json_request_to_url(archive_url, timeout=30.0)
            if not isinstance(archive_payload, Mapping):
                raise JsonApiError(502, "模拟台定义下载接口返回内容不是对象")
            data_base64 = str(archive_payload.get("data_base64") or "")
            if not data_base64:
                raise JsonApiError(502, "模拟台定义下载接口未返回定义压缩包")
            try:
                archive_data = base64.b64decode(data_base64, validate=True)
            except (ValueError, TypeError) as exc:
                raise JsonApiError(502, "模拟台返回的定义压缩包编码无效") from exc

            exchange_invalidated = False
            try:
                # Download and archive parsing stay outside the mutation locks.
                parsed_archive = _parse_definition_archive(archive_data)
                # Global mutation order: definition -> service -> exchange.
                with target.definition_update_lock:
                    with target.lock:
                        _require_active_service_instance_locked(target)
                        if target.trainee_receive_state().get("active"):
                            raise JsonApiError(409, "当前模型正在接收中，不能执行模型初始化。")
                        imported = _apply_parsed_definition_archive_locked(target, parsed_archive)
                        target._clear_command_history()
                        receive_state = target.set_trainee_receive_state(
                            {
                                "initialized": True,
                                "initialized_at": datetime.now().isoformat(timespec="seconds"),
                                "active": False,
                                "frozen": False,
                                "interaction_link": connection["link"],
                                "teacher_api_base": connection["teacher_api_base"],
                                "teacher_model_id": connection["model_id"],
                                "teacher_model_name": connection["model_name"],
                                "snapshot_path": connection["snapshot_path"],
                                "command_path": connection["command_path"],
                                "measurement_delta_path": connection["measurement_delta_path"],
                                "definition_archive_path": connection["definition_archive_path"],
                                "last_receive_at": "",
                            }
                        )
                        if exchange is not None:
                            invalidate = getattr(exchange, "invalidate_model_for_service", None)
                            if callable(invalidate):
                                invalidate(target)
                                exchange_invalidated = True
            except JsonApiError:
                raise
            except (ValueError, OSError) as exc:
                raise JsonApiError(400, str(exc)) from exc

            if exchange is not None and not exchange_invalidated:
                exchange.invalidate_model(target.model_id)
            self._send_json(
                {
                    "model": target.model_info(),
                    "selected_model_id": target.model_id,
                    "connection": connection,
                    "receive_state": receive_state,
                    "imported": imported,
                    **self._model_catalog(),
                }
            )

        def _handle_trainee_receive(self, payload: Mapping[str, Any]) -> None:
            if role != "trainee":
                raise JsonApiError(404, "Unknown API route: /api/trainee/receive")
            target = self._target_service(payload)
            raw_active = payload.get("active", True)
            active = raw_active if isinstance(raw_active, bool) else str(raw_active).strip().lower() not in {
                "",
                "0",
                "false",
                "no",
                "off",
            }
            exchange_notified = False
            with target.lock:
                _require_active_service_instance_locked(target)
                receive_state = target.trainee_receive_state()
                if active:
                    required = (
                        receive_state.get("initialized"),
                        receive_state.get("interaction_link"),
                        receive_state.get("teacher_api_base"),
                        receive_state.get("snapshot_path"),
                    )
                    if not all(required):
                        raise JsonApiError(409, "请先完成当前本地模型的模型初始化，再启动接收。")
                    if exchange is not None:
                        invalidate = getattr(exchange, "invalidate_model_for_service", None)
                        if callable(invalidate):
                            # A receive start is a new local history lifecycle. Clear
                            # cached snapshots and measurement history before the
                            # active flag can wake the backend polling worker.
                            invalidate(target)
                        elif captured_service_is_current(target):
                            exchange.invalidate_model(target.model_id)
                next_state = target.set_trainee_receive_state(
                    {
                        "active": active,
                        "frozen": not active,
                    }
                )
                if exchange is not None:
                    notify = getattr(exchange, "notify_receive_state_changed_for_service", None)
                    if callable(notify):
                        notify(target)
                        exchange_notified = True
            if exchange is not None and not exchange_notified:
                if captured_service_is_current(target):
                    exchange.receive_state_changed(target.model_id)
            if renewable_manager is not None:
                notify_renewable = getattr(
                    renewable_manager,
                    "receive_state_changed_for_service",
                    None,
                )
                if callable(notify_renewable):
                    try:
                        notify_renewable(target)
                    except RuntimeError:
                        pass
                elif captured_service_is_current(target):
                    renewable_manager.receive_state_changed(target.model_id)
            self._send_json(next_state)

        def _handle_api_get(self) -> None:
            path = urlparse(self.path).path
            target = self._target_service()
            if path == "/api/health":
                health = {
                    "ok": True,
                    "role": role,
                    "model_id": target.model_id,
                    "model_name": target.model_name,
                    "snapshot": {
                        "model": {"id": target.model_id},
                        "clock": target.clock_state(),
                    },
                    "process": _process_health_payload(),
                    "compute": dict(getattr(target, "latest_compute", {}) or {}),
                }
                runner = getattr(target, "kernel_runner", None)
                diagnostics = getattr(runner, "diagnostics", None)
                if callable(diagnostics):
                    health["power_flow_worker"] = diagnostics()
                self._send_json(health)
            elif path == renewable_control_path:
                self._send_json(self._renewable_state_payload(target))
            elif path == trainee_ui_frame_path:
                if role != "trainee":
                    raise JsonApiError(404, f"Unknown API route: {path}")
                receive_state = target.trainee_receive_state()
                receive_state_revision = hashlib.sha256(
                    json.dumps(
                        receive_state,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()[:20]
                query = parse_qs(urlparse(self.path).query)
                after_receive_state_revision = str(
                    (query.get("after_receive_state_revision") or [""])[0]
                ).strip()
                frame: Dict[str, Any] = {
                    "encoding": "trainee-ui-frame-v1",
                    "receive_state_revision": receive_state_revision,
                }
                if after_receive_state_revision != receive_state_revision:
                    frame["receive_state"] = receive_state
                if receive_state.get("active"):
                    frame["snapshot"] = self._trainee_snapshot_payload(target)
                if str((query.get("view") or [""])[0]).strip() == "renewable":
                    frame["renewable_control"] = self._renewable_state_payload(target)
                self._send_json(frame)
            elif path == "/api/models":
                self._send_json(self._model_catalog())
            elif path == MANUAL_DEFINITION_CHANGES_PATH:
                self._send_json(target.manual_definition_changes())
            elif path == "/api/snapshot":
                lite = self._truthy_query("lite")
                trainee_view = self._truthy_query("trainee_view")
                compact_device_runtime = self._truthy_query("device_runtime_compact")
                supplement_device_runtime = self._truthy_query("device_runtime_supplement")
                include_static, static_fields = self._static_query(default_include_static=not lite)
                default_log_limit = 20 if lite else 300
                log_limit = self._int_query("log_limit", default_log_limit)
                include_runtime_logs = not (
                    self._falsey_query("logs") or self._falsey_query("runtime_logs")
                )
                runtime_log_after_seq = self._optional_int_query("runtime_log_after_seq")
                snapshot_query = parse_qs(urlparse(self.path).query)
                after_command_signature = str(
                    (snapshot_query.get("after_command_signature") or [""])[0]
                ).strip()
                after_device_runtime_signature = str(
                    (snapshot_query.get("after_device_runtime_signature") or [""])[0]
                ).strip()
                snapshot_payload = target.snapshot(
                    include_static=include_static,
                    runtime_log_limit=log_limit,
                    include_runtime_logs=(
                        include_runtime_logs and runtime_log_after_seq is None
                    ),
                    include_measurements=not self._falsey_query("measurements"),
                    include_static_meta=not self._falsey_query("static_meta"),
                    static_fields=static_fields,
                    include_devices=(
                        not compact_device_runtime and not self._falsey_query("devices")
                    ),
                    include_device_states=(
                        not compact_device_runtime and not self._falsey_query("device_states")
                    ),
                    include_commands=not self._falsey_query("commands"),
                    include_command_history=not self._falsey_query("command_history"),
                )
                measurement_after_seq = self._optional_int_query("measurement_after_seq")
                periodic_trainee_frame = bool(
                    trainee_view
                    and lite
                    and measurement_after_seq is not None
                    and compact_device_runtime
                )
                if measurement_after_seq is not None:
                    snapshot_payload["measurement_delta"] = target.measurement_delta(
                        after_seq=max(0, measurement_after_seq),
                        compact=self._truthy_query("measurement_compact"),
                    )
                if include_runtime_logs and runtime_log_after_seq is not None:
                    snapshot_payload["runtime_logs_delta"] = target.runtime_logs_delta(
                        after_seq=max(0, runtime_log_after_seq),
                        limit=log_limit,
                    )
                if trainee_view:
                    strip_trainee_remote_details_from_snapshot(snapshot_payload)
                elif role == "trainee":
                    strip_trainee_truth_from_snapshot(snapshot_payload)
                commands_payload = snapshot_payload.get("commands")
                if isinstance(commands_payload, Mapping):
                    command_signature = command_payload_signature(commands_payload)
                    snapshot_payload["command_signature"] = command_signature
                    if after_command_signature == command_signature:
                        snapshot_payload.pop("commands", None)
                if compact_device_runtime:
                    if periodic_trainee_frame or supplement_device_runtime:
                        measurement_definitions = target.measurement_definitions()
                        if periodic_trainee_frame:
                            measurement_definitions = target.measurement_runtime_definitions(
                                measurement_definitions
                            )
                        device_runtime_frame = compact_device_runtime_supplement_frame(
                            target.devices(),
                            target.device_states(),
                            measurement_definitions,
                            definition_revision=target.definition_snapshot.revision,
                        )
                    else:
                        device_runtime_frame = target.device_runtime_frame()
                    device_runtime_signature = str(
                        device_runtime_frame.get("runtime_signature", "")
                    ).strip()
                    snapshot_payload["device_runtime_signature"] = device_runtime_signature
                    if after_device_runtime_signature != device_runtime_signature:
                        snapshot_payload["device_runtime"] = device_runtime_frame
                if periodic_trainee_frame:
                    project_trainee_interstation_snapshot(snapshot_payload)
                self._send_json(snapshot_payload)
            elif path == "/api/runtime-logs":
                self._send_json(
                    target.runtime_logs_delta(
                        after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                        before_seq=self._optional_int_query("before_seq"),
                        limit=self._int_query("limit", 100, 1, 500),
                        log_type=(parse_qs(urlparse(self.path).query).get("type") or [""])[0],
                    )
                )
            elif path == "/api/measurements":
                measurements_payload = target.measurements()
                if role == "trainee" or self._truthy_query("trainee_view"):
                    measurements_payload = strip_trainee_truth_from_measurements(
                        measurements_payload
                    )
                self._send_json(measurements_payload)
            elif path == "/api/measurements/delta":
                delta_payload = target.measurement_delta(
                    after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                    compact=self._truthy_query("compact"),
                )
                if role == "trainee" or self._truthy_query("trainee_view"):
                    delta_payload = strip_trainee_truth_from_measurement_delta(delta_payload)
                self._send_json(delta_payload)
            elif path == "/api/measurement-history":
                history_payload = target.measurement_history(
                    indices=self._measurement_indices_query(),
                    after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                )
                if role == "trainee" or self._truthy_query("trainee_view"):
                    history_payload = strip_trainee_truth_from_measurement_history(
                        history_payload
                    )
                self._send_json(history_payload)
            elif path == "/api/external/telemetry":
                self._send_json(target.latest_telemetry_values())
            elif path == "/api/external/devices":
                self._send_json(target.external_device_information())
            elif path == external_realtime_inputs_path:
                if role != "simulator":
                    raise JsonApiError(404, f"Unknown API route: {path}")
                self._send_json(target.external_realtime_input_schema())
            elif path == "/api/external/telemetry/names":
                self._send_json(target.external_telemetry_names())
            elif path == "/api/external/telemetry/values":
                self._send_json(target.external_telemetry_frame())
            elif path == "/api/external/controls":
                self._send_json(target.latest_control_values())
            elif path == "/api/external/controls/names":
                self._send_json(target.external_control_names())
            elif path == "/api/devices":
                self._send_json({"devices": target.devices()})
            elif path == "/api/device-states":
                self._send_json({"device_states": target.device_states()})
            elif path == "/api/curves":
                self._send_json(target.curves)
            elif path == "/api/curves/summary":
                self._send_json(target.curves_summary())
            elif path == "/api/curves/series":
                values = parse_qs(urlparse(self.path).query)
                keys = [
                    key.strip()
                    for value in values.get("keys", [])
                    for key in str(value).split(",")
                    if key.strip()
                ]
                self._send_json(target.curves_series(keys))
            elif path == "/api/settings":
                self._send_json(target.local_settings)
            elif path == "/api/trainee/receive-state":
                self._send_json(target.trainee_receive_state())
            elif path == "/api/trainee/receive-states":
                if hasattr(service, "trainee_receive_states"):
                    self._send_json({"items": service.trainee_receive_states()})  # type: ignore[union-attr]
                else:
                    self._send_json({"items": {target.model_id: target.trainee_receive_state()}})
            elif path == "/api/trainee/diagnostics":
                if exchange is None:
                    raise JsonApiError(404, f"Unknown API route: {path}")
                receive_status_for_service = getattr(
                    exchange,
                    "receive_status_for_service",
                    None,
                )
                if callable(receive_status_for_service):
                    diagnostics = receive_status_for_service(target)
                else:
                    if not captured_service_is_current(target):
                        raise JsonApiError(
                            409,
                            "学员台诊断请求所属模型生命周期已失效或已退休。",
                        )
                    diagnostics = exchange.receive_status(target.model_id)
                self._send_json(diagnostics)
            elif path == "/api/trainee/snapshot":
                self._send_json(self._trainee_snapshot_payload(target))
            elif path == "/api/trainee/measurements/delta":
                if exchange is None:
                    raise JsonApiError(404, f"Unknown API route: {path}")
                delta_for_service = getattr(exchange, "measurement_delta_for_service", None)
                if callable(delta_for_service):
                    delta_payload = delta_for_service(
                        target,
                        after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                        compact=self._truthy_query("compact"),
                    )
                else:
                    if not captured_service_is_current(target):
                        raise JsonApiError(
                            409,
                            "学员台量测增量请求所属模型生命周期已失效或已退休。",
                        )
                    delta_options = {
                        "after_seq": self._int_query("after_seq", 0, 0, 2_000_000_000)
                    }
                    if self._truthy_query("compact"):
                        delta_options["compact"] = True
                    delta_payload = exchange.measurement_delta(
                        target.model_id,
                        **delta_options,
                    )
                self._send_json(strip_trainee_truth_from_measurement_delta(delta_payload))
            elif path == "/api/trainee/measurement-history":
                if exchange is None:
                    raise JsonApiError(404, f"Unknown API route: {path}")
                history_for_service = getattr(exchange, "measurement_history_for_service", None)
                if callable(history_for_service):
                    history_payload = history_for_service(
                        target,
                        indices=self._measurement_indices_query(),
                        after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                    )
                else:
                    history_payload = exchange.measurement_history(
                        target.model_id,
                        indices=self._measurement_indices_query(),
                        after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                    )
                self._send_json(strip_trainee_truth_from_measurement_history(history_payload))
            elif path in ("/api/trainee-link", "/api/client-link"):
                link_query = parse_qs(urlparse(self.path).query)
                if not hasattr(service, "service_for") and any(
                    key in link_query for key in ("model_id", "model")
                ):
                    raise JsonApiError(
                        400,
                        "单模型模拟服务交互链接不接受 model_id，请直接使用 /api/trainee-link。",
                    )
                self._send_json(self._trainee_link_payload(target))
            elif path == "/api/config":
                runtime_settings = target.web_runtime_settings(role)["settings"]
                self._send_json(
                    {
                        "role": role,
                        "sim_url": sim_url,
                        "poll_ms": int(float(runtime_settings["frontend_refresh_seconds"]) * 1000),
                        "system_parameters": target.system_parameters(),
                        **self._model_catalog(),
                    }
                )
            elif path == LOCAL_RUNTIME_SETTINGS_PATH:
                self._send_json(target.web_runtime_settings(role))
            elif path == "/api/export-definitions":
                parsed = urlparse(self.path)
                response_format = (parse_qs(parsed.query).get("format") or ["zip"])[0]
                if response_format == "json":
                    self._send_definition_archive_json(target)
                else:
                    self._send_definition_archive(target)
            else:
                raise JsonApiError(404, f"Unknown API route: {path}")

        def _handle_api_post(self) -> None:
            path = urlparse(self.path).path
            payload = self._read_json_body()
            if path == renewable_control_path:
                if role != "trainee" or renewable_manager is None:
                    raise JsonApiError(404, f"Unknown API route: {path}")
                try:
                    result = renewable_manager.apply_action(
                        self._request_model_id(payload),
                        payload,
                    )
                except ValueError as exc:
                    raise JsonApiError(400, str(exc)) from exc
                self._send_json(result)
                return
            if path == "/api/trainee/model-initialize":
                self._handle_trainee_model_initialize(payload)
                return
            if path == "/api/trainee/receive":
                self._handle_trainee_receive(payload)
                return
            if path == "/api/trainee/models/create":
                if role != "trainee" or not hasattr(service, "create_model_slot"):
                    raise JsonApiError(404, f"Unknown API route: {path}")
                model_name = str(payload.get("name", payload.get("model_name", ""))).strip()
                if not model_name:
                    raise JsonApiError(400, "请输入新模型名称")
                try:
                    model = service.create_model_slot(model_name)  # type: ignore[union-attr]
                except (ValueError, OSError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                self._send_json(
                    {
                        "model": model,
                        "selected_model_id": model["id"],
                        **self._model_catalog(),
                    }
                )
                return
            if path == "/api/models/create":
                if not hasattr(service, "validate_new_model_name") or not hasattr(service, "models_root"):
                    raise JsonApiError(400, "Current simulator does not support multiple model folders")
                model_name = str(payload.get("name", payload.get("model_name", ""))).strip()
                if not model_name:
                    raise JsonApiError(400, "New model name is required")
                data_base64 = str(payload.get("data_base64", ""))
                if not data_base64:
                    raise JsonApiError(400, "model.e data is required")
                try:
                    model_data = base64.b64decode(data_base64, validate=True)
                    model_text = _decode_uploaded_definition_text(model_data)
                    diagram_svg_text = _decode_optional_svg_payload(payload)
                    preflight = _preflight_model_import(
                        model_text,
                        diagram_svg_text=diagram_svg_text,
                        source_label=str(payload.get("filename") or "model.e"),
                    )
                    model = create_model_from_efile(
                        service,  # type: ignore[arg-type]
                        model_name,
                        model_text,
                        diagram_svg_text=diagram_svg_text,
                        preflight_result=preflight,
                    )
                except ModelPreflightError as exc:
                    raise JsonApiError(400, str(exc), {"validation": exc.validation}) from exc
                except (UnicodeDecodeError, ValueError, OSError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                catalog = dict(self._model_catalog())
                catalog["active_model_id"] = model["id"]
                self._send_json({"model": model, "validation": model.get("validation"), **catalog})
                return
            if path == "/api/models/update-definitions":
                if not hasattr(service, "service_for") or not hasattr(service, "models_root"):
                    raise JsonApiError(400, "Current simulator does not support multiple model folders")
                model_id = self._request_model_id(payload)
                if not str(model_id or "").strip():
                    raise JsonApiError(400, "Model id is required")
                self._reject_active_trainee_receive_model(payload, "修改")
                data_base64 = str(payload.get("data_base64", ""))
                if not data_base64:
                    raise JsonApiError(400, "model.e data is required")
                try:
                    model_data = base64.b64decode(data_base64, validate=True)
                    model_text = _decode_uploaded_definition_text(model_data)
                    diagram_svg_text = _decode_optional_svg_payload(payload)
                    target_service = service.service_for(model_id)  # type: ignore[union-attr]
                    candidate_diagram = diagram_svg_text
                    if candidate_diagram is None:
                        current_diagram_path = Path(target_service.sim_dir) / DIAGRAM_FILE_NAME
                        if current_diagram_path.exists() and current_diagram_path.is_file():
                            candidate_diagram = current_diagram_path.read_text(encoding="utf-8-sig")
                    preflight = _preflight_model_import(
                        model_text,
                        diagram_svg_text=candidate_diagram,
                        source_label=str(payload.get("filename") or "model.e"),
                    )
                    model = update_model_from_efile(
                        service,  # type: ignore[arg-type]
                        model_id,
                        model_text,
                        diagram_svg_text=diagram_svg_text,
                        replace_diagram=bool(payload.get("replace_diagram", False)),
                        preflight_result=preflight,
                    )
                except ModelPreflightError as exc:
                    raise JsonApiError(400, str(exc), {"validation": exc.validation}) from exc
                except (UnicodeDecodeError, ValueError, OSError, KeyError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                catalog = dict(self._model_catalog())
                catalog["active_model_id"] = model["id"]
                self._send_json(
                    {
                        "model": model,
                        "updated": model["updated"],
                        "validation": model.get("validation"),
                        **catalog,
                    }
                )
                return
            if path == "/api/models/clone":
                if not hasattr(service, "clone_model"):
                    raise JsonApiError(400, "Current simulator does not support multiple model folders")
                model_name = payload.get("name", payload.get("model_name", payload.get("new_model_id", "")))
                if not str(model_name or "").strip():
                    raise JsonApiError(400, "New model name is required")
                try:
                    model = service.clone_model(self._request_model_id(payload), model_name)  # type: ignore[union-attr]
                except ValueError as exc:
                    raise JsonApiError(400, str(exc)) from exc
                catalog = dict(self._model_catalog())
                catalog["active_model_id"] = model["id"]
                self._send_json({"model": model, **catalog})
                return
            if path == "/api/models/delete":
                if not hasattr(service, "delete_model"):
                    raise JsonApiError(400, "Current simulator does not support multiple model folders")
                model_id = self._request_model_id(payload)
                if not str(model_id or "").strip():
                    raise JsonApiError(400, "Model id is required")
                try:
                    old_service = service.service_for(model_id)  # type: ignore[union-attr]
                    if old_service.trainee_receive_state().get("active"):
                        raise JsonApiError(400, "模型正在接收中，不能删除。")
                    deleted = service.delete_model(model_id)  # type: ignore[union-attr]
                except JsonApiError:
                    raise
                except KeyError as exc:
                    raise JsonApiError(404, str(exc)) from exc
                except ValueError as exc:
                    raise JsonApiError(400, str(exc)) from exc
                for lifecycle_owner in (exchange, renewable_manager):
                    remove = getattr(lifecycle_owner, "remove_model_for_service", None)
                    if callable(remove):
                        remove(old_service)
                catalog = dict(self._model_catalog())
                catalog["active_model_id"] = deleted.get("active_model_id", catalog.get("active_model_id"))
                self._send_json({"deleted": deleted, **catalog})
                return
            if path == "/api/models/import-definitions":
                data_base64 = str(payload.get("data_base64", ""))
                if not data_base64:
                    raise JsonApiError(400, "Definition archive data is required")
                try:
                    archive_data = base64.b64decode(data_base64, validate=True)
                    if payload.get("create_model"):
                        if not hasattr(service, "clone_model"):
                            raise ValueError("Current simulator does not support multiple model folders")
                        model_name = str(payload.get("name", payload.get("model_name", ""))).strip()
                        if not model_name:
                            raise ValueError("New model name is required")
                        model = import_definition_model(
                            service,  # type: ignore[arg-type]
                            self._request_model_id(payload),
                            model_name,
                            archive_data,
                            source_label=str(payload.get("filename") or "definitions.zip/model.e"),
                        )
                        catalog = dict(self._model_catalog())
                        catalog["active_model_id"] = model["id"]
                        self._send_json(
                            {
                                "model": model,
                                "imported": model["imported"],
                                "validation": model.get("validation"),
                                **catalog,
                            }
                        )
                        return
                    self._reject_active_trainee_receive_model(payload, "修改")
                    imported = import_definition_archive(
                        self._target_service(payload),
                        archive_data,
                        source_label=str(payload.get("filename") or "definitions.zip/model.e"),
                    )
                except ModelPreflightError as exc:
                    raise JsonApiError(400, str(exc), {"validation": exc.validation}) from exc
                except (ValueError, OSError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                self._send_json(
                    {
                        "imported": imported,
                        "validation": imported.get("validation"),
                        **self._model_catalog(),
                    }
                )
                return

            if path == "/api/trainee/connect":
                self._handle_trainee_connect(payload)
                return

            target = self._target_service(payload)
            if path in DEFINITION_EDIT_PATHS:
                try:
                    if path == "/api/definitions/device-parameters":
                        result = target.update_device_parameters(
                            payload,
                            allow_runtime_controls=role != "trainee",
                        )
                    elif path == "/api/definitions/measurement":
                        result = target.update_measurement_definition(payload)
                    elif path == "/api/definitions/manual-changes/retry":
                        result = target.retry_manual_definition_changes(payload)
                    else:
                        result = target.reset_manual_definition_changes(payload)
                except DefinitionRevisionConflict as exc:
                    raise JsonApiError(
                        409,
                        str(exc),
                        {
                            "expected_revision": exc.expected_revision,
                            "current_revision": exc.current_revision,
                        },
                    ) from exc
                except ServiceInstanceRetiredError as exc:
                    raise JsonApiError(409, str(exc)) from exc
                except (KeyError, ValueError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                self._send_json(result)
            elif path == "/api/student/commands":
                try:
                    result = target.apply_student_commands(
                        payload,
                        source=str(payload.get("source", "")),
                    )
                except ValueError as exc:
                    raise JsonApiError(400, str(exc)) from exc
                self._send_json(result)
            elif path == SIMULATOR_COMMAND_DELETE_PATH:
                if role != "simulator":
                    raise JsonApiError(404, f"Unknown API route: {path}")
                self._send_json(target.delete_active_commands(payload, source="simulator-ui"))
            elif path == "/api/trainee/receive-state":
                exchange_notified = False
                with target.lock:
                    _require_active_service_instance_locked(target)
                    receive_state = target.set_trainee_receive_state(payload)
                    if exchange is not None:
                        notify = getattr(exchange, "notify_receive_state_changed_for_service", None)
                        if callable(notify):
                            notify(target)
                            exchange_notified = True
                if exchange is not None and not exchange_notified:
                    if captured_service_is_current(target):
                        exchange.receive_state_changed(target.model_id)
                if renewable_manager is not None:
                    notify_renewable = getattr(
                        renewable_manager,
                        "receive_state_changed_for_service",
                        None,
                    )
                    if callable(notify_renewable):
                        try:
                            notify_renewable(target)
                        except RuntimeError:
                            pass
                    elif captured_service_is_current(target):
                        renewable_manager.receive_state_changed(target.model_id)
                self._send_json(receive_state)
            elif path == "/api/trainee/commands":
                if exchange is None:
                    raise JsonApiError(404, f"Unknown API route: {path}")
                submit_for_service = getattr(exchange, "submit_commands_for_service", None)
                try:
                    if callable(submit_for_service):
                        result = submit_for_service(target, payload)
                    else:
                        if not captured_service_is_current(target):
                            raise JsonApiError(
                                409,
                                "学员台指令请求所属模型生命周期已失效或已退休。",
                            )
                        result = exchange.submit_commands(target.model_id, payload)
                except (ServiceInstanceRetiredError, TraineeExchangeLifecycleError) as exc:
                    raise JsonApiError(409, str(exc)) from exc
                self._send_json(result)
            elif path == "/api/external/telemetry/query":
                self._send_json(target.selected_telemetry_values(payload))
            elif path == "/api/external/telemetry/values/query":
                self._send_json(target.selected_external_telemetry_frame(payload))
            elif path == "/api/external/telemetry/history/query":
                if role != "simulator":
                    raise JsonApiError(404, f"Unknown API route: {path}")
                try:
                    result = target.external_measurement_history(payload)
                except ValueError as exc:
                    raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
                self._send_json(result)
            elif path == "/api/external/curves/query":
                if role != "simulator":
                    raise JsonApiError(404, f"Unknown API route: {path}")
                try:
                    result = target.external_curves_query(payload)
                except ValueError as exc:
                    raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
                self._send_json(result)
            elif path in ("/api/external/curves/update", "/api/external/curves/updat"):
                if role != "simulator":
                    raise JsonApiError(404, f"Unknown API route: {path}")
                try:
                    result = target.external_curves_update(payload)
                except ValueError as exc:
                    raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
                self._send_json(result)
            elif path == external_realtime_inputs_path:
                if role != "simulator":
                    raise JsonApiError(404, f"Unknown API route: {path}")
                try:
                    result = target.apply_external_realtime_inputs(payload)
                except ValueError as exc:
                    raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
                self._send_json(result)
            elif path == "/api/external/controls":
                self._send_json(target.apply_external_control_values(payload))
            elif path == "/api/external/controls/execute":
                try:
                    result = target.apply_external_control_frame(payload)
                except ValueError as exc:
                    raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
                self._send_json(result)
            elif path == "/api/clock":
                self._send_json(target.control_clock(payload))
            elif path == "/api/config":
                self._send_json(target.set_system_parameters(payload))
            elif path == LOCAL_RUNTIME_SETTINGS_PATH:
                try:
                    if role == "trainee" and renewable_manager is not None:
                        renewable_manager.validate_runtime_settings_update_for_service(
                            target,
                            payload,
                        )
                    result = target.set_web_runtime_settings(role, payload)
                except ServiceInstanceRetiredError as exc:
                    raise JsonApiError(409, str(exc)) from exc
                except ValueError as exc:
                    raise JsonApiError(400, str(exc)) from exc
                if exchange is not None:
                    notify_for_service = getattr(
                        exchange,
                        "runtime_settings_changed_for_service",
                        None,
                    )
                    if callable(notify_for_service):
                        notify_for_service(target)
                    elif captured_service_is_current(target):
                        notify = getattr(exchange, "runtime_settings_changed", None)
                        if callable(notify):
                            notify(target.model_id)
                if role == "trainee" and renewable_manager is not None:
                    renewable_manager.runtime_settings_changed_for_service(target)
                self._send_json(result)
            elif path == "/api/runtime-logs/clear":
                self._send_json(target.clear_runtime_logs())
            elif path == "/api/step":
                self._send_json(target.step())
            elif path == "/api/curves":
                self._send_json(target.set_curves(payload))
            elif path == "/api/curves/series":
                self._send_json(target.update_curve_series(payload))
            elif path == "/api/settings":
                self._send_json(target.set_local_settings(payload))
            elif path == "/api/device-faults":
                self._send_json(target.set_local_settings({"device_faults": payload.get("items", payload)}))
            elif path == "/api/measurement-faults":
                self._send_json(target.set_local_settings({"measurement_faults": payload.get("items", payload)}))
            elif path == "/api/modes":
                self._send_json(target.set_local_settings({"modes": payload.get("items", payload)}))
            else:
                raise JsonApiError(404, f"Unknown API route: {path}")

        def _read_json_body(self) -> Mapping[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise JsonApiError(400, f"Invalid JSON payload: {exc}") from exc
            if not isinstance(payload, Mapping):
                raise JsonApiError(400, "JSON payload must be an object")
            return payload

        def _serve_static(self, root: Path) -> None:
            path = urlparse(self.path).path
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (root / rel).resolve()
            if not str(target).startswith(str(root)) or not target.exists() or not target.is_file():
                target = root / "index.html"
            if not target.exists():
                raise JsonApiError(404, f"Static file not found: {rel}")
            asset = load_static_asset(target)
            etag = str(asset["etag"])
            accepted_encodings = self.headers.get("Accept-Encoding", "").lower()
            use_gzip = bool(asset["gzip_data"] and "gzip" in accepted_encodings)
            data = asset["gzip_data"] if use_gzip else asset["data"]
            if self.headers.get("If-None-Match", "").strip() == etag:
                self.send_response(304)
                self._cors(cache_control="no-cache")
                self.send_header("ETag", etag)
                self.send_header("Vary", "Accept-Encoding")
                self.end_headers()
                return
            self.send_response(200)
            self._cors(cache_control="no-cache")
            self.send_header("Content-Type", str(asset["content_type"]))
            self.send_header("ETag", etag)
            self.send_header("Vary", "Accept-Encoding")
            if use_gzip:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _proxy_to_simulator(self, method: str, base_url: str) -> None:
            path = self.path
            body = None
            headers = {"Accept": "application/json"}
            if method in ("POST", "PUT"):
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length else b"{}"
                headers["Content-Type"] = self.headers.get("Content-Type", "application/json")
            request = Request(urljoin(base_url + "/", path.lstrip("/")), data=body, headers=headers, method=method)
            try:
                with urlopen(request, timeout=10) as response:
                    data = response.read()
                    status = response.status
                    content_type = response.headers.get("Content-Type", "application/json")
            except HTTPError as exc:
                data = exc.read()
                status = exc.code
                content_type = exc.headers.get("Content-Type", "application/json")
            except URLError as exc:
                raise JsonApiError(502, f"Simulator is unreachable: {exc}") from exc
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(
                payload,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
            content_encoding = ""
            accepted_encodings = self.headers.get("Accept-Encoding", "").lower()
            if len(data) >= 1024 and "gzip" in accepted_encodings:
                compressed = gzip.compress(data, compresslevel=1, mtime=0)
                if len(compressed) + 32 < len(data):
                    data = compressed
                    content_encoding = "gzip"
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Vary", "Accept-Encoding")
            if content_encoding:
                self.send_header("Content-Encoding", content_encoding)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_definition_archive(self, target: PolarMicrogridSimulator) -> None:
            filename, data = make_definition_archive(target)
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/zip")
            self.send_header(
                "Content-Disposition",
                f"attachment; filename=\"model_definitions.zip\"; filename*=UTF-8''{quote(filename)}",
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_definition_archive_json(self, target: PolarMicrogridSimulator) -> None:
            filename, data = make_definition_archive(target)
            self._send_json(
                {
                    "filename": filename,
                    "content_type": "application/zip",
                    "data_base64": base64.b64encode(data).decode("ascii"),
                }
            )

        def _cors(self, *, cache_control: str = "no-store") -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Cache-Control", cache_control)

    class ManagedThreadingHTTPServer(ThreadingHTTPServer):
        _trainee_exchange_closed = False
        _renewable_manager_closed = False
        _service_closed = False

        def server_close(self) -> None:
            if renewable_manager is not None and not self._renewable_manager_closed:
                self._renewable_manager_closed = True
                renewable_manager.close()
            if exchange is not None and not self._trainee_exchange_closed:
                self._trainee_exchange_closed = True
                exchange.close()
            if not self._service_closed:
                self._service_closed = True
                close_service = getattr(service, "close", None)
                if callable(close_service):
                    close_service()
            super().server_close()

    server = ManagedThreadingHTTPServer(server_address, PolarMicrogridHandler)
    server.service = service  # type: ignore[attr-defined]
    server.trainee_exchange = exchange  # type: ignore[attr-defined]
    server.renewable_control_manager = renewable_manager  # type: ignore[attr-defined]
    return server


def _advance_clock_if_due(service: PolarMicrogridSimulator, last_step: float) -> float:
    clock = service.clock_state()
    now = time.monotonic()
    if clock["state"] != "running":
        return now
    interval_seconds = max(0.1, float(getattr(service, "compute_interval_seconds", CLOCK_BASE_INTERVAL_SECONDS) or CLOCK_BASE_INTERVAL_SECONDS))
    if now - last_step < interval_seconds:
        return last_step
    # Do not catch up by elapsed wall time: one completed solve advances one logical simulation step.
    speed = max(1.0, float(clock.get("speed", 1) or 1))
    advance_seconds = max(1e-9, float(clock.get("effective_step_seconds", speed) or speed))
    try:
        service.step(advance_seconds=advance_seconds, return_snapshot=False)
    except Exception:
        service.control_clock({"action": "pause"})
    return time.monotonic()


def start_clock_worker(service: PolarMicrogridSimulator, stop_event: threading.Event) -> threading.Thread:
    def worker() -> None:
        last_step = time.monotonic()
        while not stop_event.is_set():
            last_step = _advance_clock_if_due(service, last_step)
            stop_event.wait(0.05)

    thread = threading.Thread(target=worker, name=f"polar-microgrid-clock-{service.model_id}", daemon=True)
    thread.start()
    return thread


def start_multi_model_clock_worker(service: MultiModelSimulator, stop_event: threading.Event) -> threading.Thread:
    def worker() -> None:
        last_steps: dict[str, float] = {}
        while not stop_event.is_set():
            current_ids = set()
            for item in service.iter_services():
                current_ids.add(item.model_id)
                last_steps[item.model_id] = _advance_clock_if_due(
                    item,
                    last_steps.get(item.model_id, time.monotonic()),
                )
            for stale_id in set(last_steps) - current_ids:
                last_steps.pop(stale_id, None)
            stop_event.wait(0.05)

    thread = threading.Thread(target=worker, name="polar-microgrid-clock-models", daemon=True)
    thread.start()
    return thread


def start_clock_workers(
    service: PolarMicrogridSimulator | MultiModelSimulator,
    stop_event: threading.Event,
) -> list[threading.Thread]:
    if hasattr(service, "iter_services"):
        return [start_multi_model_clock_worker(service, stop_event)]  # type: ignore[arg-type]
    return [start_clock_worker(service, stop_event)]  # type: ignore[arg-type]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve polar microgrid simulator or trainee console.")
    parser.add_argument(
        "--role",
        choices=("simulator", "simulator-service", "trainee"),
        default="simulator",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--sim-dir", default=str(simu_loop.SIMU_DIR))
    parser.add_argument(
        "--models-dir",
        default=None,
        help="Directory whose direct subfolders are simulation models. Defaults to models/<role>/source.",
    )
    parser.add_argument("--model-id", default=None, help="Single model id for simulator-service mode.")
    parser.add_argument("--model-dir", default=None, help="Single source model directory for simulator-service mode.")
    parser.add_argument("--runtime-dir", default=None)
    parser.add_argument("--sim-url", default=None, help="Simulator API base URL for trainee proxy mode.")
    parser.add_argument("--static-root", default=None)
    parser.add_argument(
        "--service-host",
        default="127.0.0.1",
        help="Host assigned to per-model simulator services managed by the simulator proxy.",
    )
    parser.add_argument(
        "--first-service-port",
        type=int,
        default=8711,
        help="First stable port assigned to a per-model simulator service.",
    )
    parser.add_argument(
        "--service-startup-timeout-seconds",
        type=float,
        default=30.0,
        help="Maximum time for a per-model simulator service to become healthy.",
    )
    parser.add_argument("--no-worker", action="store_true", help="Do not start automatic clock worker.")
    parser.add_argument("--noise-std", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--compute-interval-seconds", type=float, default=1.0)
    parser.add_argument(
        "--power-flow-workers",
        type=int,
        default=0,
        help="Deprecated compatibility option; load flow is always embedded in simu_loop.",
    )
    parser.add_argument(
        "--power-flow-timeout-seconds",
        type=float,
        default=30.0,
        help="Deprecated compatibility option retained for existing launch scripts.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    sim_dir = Path(args.sim_dir).resolve()
    if args.role == "simulator":
        port = args.port if args.port is not None else 8710
        runtime_dir = (
            Path(args.runtime_dir).resolve()
            if args.runtime_dir
            else _default_runtime_dir(sim_dir, "simulator")
        )
        models_dir = (
            Path(args.models_dir).resolve()
            if args.models_dir
            else _default_models_dir(sim_dir, "simulator")
        )
        static_root = Path(args.static_root).resolve() if args.static_root else WEB_DIR / "simulator"
        manager = SimulatorClusterManager(
            sim_dir=sim_dir,
            models_root=models_dir,
            runtime_root=runtime_dir,
            service_host=args.service_host,
            first_service_port=args.first_service_port,
            compute_interval_seconds=args.compute_interval_seconds,
            child_no_worker=args.no_worker,
            noise_std=args.noise_std,
            random_seed=args.seed,
            startup_timeout_seconds=args.service_startup_timeout_seconds,
        )
        server = make_simulator_proxy_server(
            (args.host, port),
            manager,
            static_root=static_root,
        )
        print(f"simulator proxy: http://{args.host}:{port}/")
        print(f"runtime dir: {runtime_dir}")
        print(f"models dir: {manager.models_root}")
        print(f"models: {', '.join(item['id'] for item in manager.models())}")
        print("data plane: browser and trainee services connect directly to per-model simulator services")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
        return 0

    if args.role == "simulator-service":
        if not str(args.model_id or "").strip():
            raise SystemExit("--model-id is required for simulator-service mode")
        if not str(args.model_dir or "").strip():
            raise SystemExit("--model-dir is required for simulator-service mode")
        port = args.port if args.port is not None else 8711
        runtime_dir = (
            Path(args.runtime_dir).resolve()
            if args.runtime_dir
            else _default_runtime_dir(sim_dir, "simulator") / str(args.model_id)
        )
        service = PolarMicrogridSimulator(
            sim_dir=Path(args.model_dir).resolve(),
            runtime_dir=runtime_dir,
            noise_std=args.noise_std,
            random_seed=args.seed,
            compute_interval_seconds=args.compute_interval_seconds,
            model_id=str(args.model_id),
            model_name=str(args.model_id),
            clear_commands_on_start_and_reset=True,
            enforce_runtime_setpoint_bounds=False,
        )
        server = make_http_server(
            (args.host, port),
            service,
            role="simulator",
            static_root=args.static_root,
            direct_simulator_ui=True,
        )
        stop_event = threading.Event()
        workers = [] if args.no_worker else start_clock_workers(service, stop_event)
        print(f"simulator service [{service.model_id}]: http://{args.host}:{port}/?ui=direct")
        print(f"runtime dir: {runtime_dir}")
        print(f"model dir: {service.sim_dir}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            for worker in workers:
                worker.join(timeout=2)
            server.shutdown()
            server.server_close()
        return 0

    port = args.port if args.port is not None else 8720
    runtime_dir = Path(args.runtime_dir).resolve() if args.runtime_dir else _default_runtime_dir(sim_dir, "trainee")
    models_dir = Path(args.models_dir).resolve() if args.models_dir else _default_models_dir(sim_dir, "trainee")
    service = MultiModelSimulator.discover(
        sim_dir=sim_dir,
        runtime_dir=runtime_dir,
        noise_std=args.noise_std,
        random_seed=args.seed,
        compute_interval_seconds=args.compute_interval_seconds,
        models_dir=models_dir,
        kernel_runner=None,
        runtime_role="trainee",
    )
    server = make_http_server(
        (args.host, port),
        service,
        role="trainee",
        static_root=args.static_root,
        sim_url=args.sim_url,
    )
    stop_event = threading.Event()
    workers = [] if args.no_worker else start_clock_workers(service, stop_event)
    print(f"trainee console: http://{args.host}:{port}/")
    print(f"runtime dir: {runtime_dir}")
    print(f"models dir: {service.models_root}")
    print(f"models: {', '.join(item['id'] for item in service.models())}")
    print("power-flow mode: embedded in simu_loop, resident model")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=2)
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
