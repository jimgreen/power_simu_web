"""HTTP server for the polar microgrid simulator and trainee consoles."""

from __future__ import annotations

import argparse
import base64
import html
import json
import math
import mimetypes
import re
import threading
import time
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
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
    from .service import (
        DEFAULT_WEATHER,
        DIAGRAM_FILE_NAME,
        MEAS_HEADER,
        SIGNAL_MEASUREMENTS,
        STAT_HEADERS,
        WEATHER_HEADER,
        WEATHER_MEASUREMENTS,
        MultiModelSimulator,
        PolarMicrogridSimulator,
        _to_float,
    )
except ImportError:  # pragma: no cover - legacy package compatibility.
    from hybrid_power_system_analysis.polar_microgrid_sim.service import (
        DEFAULT_WEATHER,
        DIAGRAM_FILE_NAME,
        MEAS_HEADER,
        SIGNAL_MEASUREMENTS,
        STAT_HEADERS,
        WEATHER_HEADER,
        WEATHER_MEASUREMENTS,
        MultiModelSimulator,
        PolarMicrogridSimulator,
        _to_float,
    )

try:
    import simu_loop  # type: ignore
except ImportError:  # pragma: no cover - legacy package compatibility.
    from hybrid_power_system_analysis.simu import simu_loop


PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
CLOCK_BASE_INTERVAL_SECONDS = 1.0
ROLE_MODEL_DIRS = {
    "simulator": ("models", "simulator"),
    "trainee": ("models", "trainee"),
}
CONTROL_DEFINITION_BLOCKS = {"RunStat", "CbOpenStat", "SetValue", "StorageSoc"}


def _clock_int_value(value: Any, default: int = 1) -> int:
    try:
        return max(1, int(round(float(value))))
    except (TypeError, ValueError):
        return default


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


def _merge_control_definition(stat_path: Path, control_text: str, meas_text: str = "") -> None:
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
        if meas_text:
            meas_book = _book_from_text(meas_text)
            measurement_block = meas_book.data.get("Measurement")
            storage_rows = []
            for row in getattr(measurement_block, "data", []):
                if str(row.get("dev_type", "")) != "ESS" or str(row.get("meas_type", "")).upper() != "SOC":
                    continue
                storage_rows.append((str(row.get("dev_name", "")), row.get("value", "0.5")))
            if storage_rows:
                storage_block = EBlock("StorageSoc")
                storage_block.header_list = ["dev_type", "idx", "name", "soc_curr"]
                for idx, (name, value) in enumerate(storage_rows, start=1):
                    storage_block.AddRow(["ESS", str(idx), name, str(value)])
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
    if not payload["point_count"]:
        payload["point_count"] = len(payload["weather"])
    return payload


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_zip_text(archive: zipfile.ZipFile, entry_name: str, required: bool = True) -> Optional[str]:
    try:
        data = archive.read(entry_name)
    except KeyError:
        if required:
            raise ValueError(f"Definition archive is missing {entry_name}") from None
        return None
    return data.decode("utf-8-sig")


def _normalize_diagram_svg_text(svg_text: Optional[str]) -> Optional[str]:
    if svg_text is None:
        return None
    text = str(svg_text).lstrip("\ufeff")
    if not text.strip():
        return None
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
        return base64.b64decode(data_base64, validate=True).decode("utf-8-sig")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("SVG图形文件解析失败") from exc


def _write_model_diagram(target_dir: Path, diagram_svg_text: Optional[str], *, remove_when_absent: bool = False) -> bool:
    path = target_dir / DIAGRAM_FILE_NAME
    normalized = _normalize_diagram_svg_text(diagram_svg_text)
    if normalized is None:
        if remove_when_absent and path.exists() and path.is_file():
            path.unlink()
        return False
    path.write_text(normalized, encoding="utf-8")
    return True


def _fallback_definition_diagram_svg(service: PolarMicrogridSimulator) -> str:
    model_id = html.escape(str(getattr(service, "model_id", "model") or "model"))
    model_name = html.escape(str(getattr(service, "model_name", model_id) or model_id))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">'
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
    "ACLoad": (("p_set", "pv0"), ("q_set", "qv0")),
    "DCLoad": (("p_set", "p_set"), ("v_set", "v_set"), ("i_set", "i_set")),
}
MEASUREMENT_TYPE_MAP = {
    "ACNode": ("V", "ANGLE"),
    "DCNode": ("V",),
    "ACGenerator": ("P_GEN", "Q_GEN", "V_GEN", "I_GEN"),
    "DCGenerator": ("P_GEN", "V_GEN", "I_GEN"),
    "ACLoad": ("P_LOAD", "Q_LOAD", "V_LOAD", "I_LOAD"),
    "DCLoad": ("P_LOAD", "V_LOAD", "I_LOAD"),
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
}


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


def _first_present(row: Mapping[str, Any], columns: Sequence[str], default: Any = "") -> Any:
    for column in columns:
        if column in row and row.get(column, "") != "":
            return row.get(column)
    return default


def _model_book_has_power_model(book: EBook) -> bool:
    return any(name in MODEL_DEVICE_BLOCKS and getattr(block, "data", []) for name, block in book.data.items())


def _storage_source_rows(model_book: EBook) -> list[dict]:
    dc_generators = {str(row.get("idx", "")): row for row in _rows(model_book, "DCGenerator")}
    storage_rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for pos, row in enumerate(_rows(model_book, "DCStorageGen"), start=1):
        source = dc_generators.get(str(row.get("idx_dcgenerator", "")), {})
        name = str(source.get("name", row.get("name", f"storage_{pos}")))
        if not name:
            continue
        soc = _numeric(row.get("state_of_charge", row.get("soc_curr", row.get("soc_cur", 0.5))), 0.5)
        if soc > 1.0:
            soc /= 100.0
        storage_rows.append(
            {
                "dev_type": "DCGenerator" if source else "ESS",
                "idx": source.get("idx", row.get("idx", pos)),
                "name": name,
                "soc_curr": max(0.0, min(1.0, soc)),
            }
        )
        seen.add((str(storage_rows[-1]["dev_type"]), name))
    for pos, row in enumerate(_rows(model_book, "DCGenerator"), start=1):
        name = _row_name(row)
        if not name or ("storage" not in str(row.get("dev_type", "")).casefold() and "储能" not in name):
            continue
        key = ("DCGenerator", name)
        if key in seen:
            continue
        storage_rows.append(
            {
                "dev_type": "DCGenerator",
                "idx": row.get("idx", pos),
                "name": name,
                "soc_curr": row.get("soc_curr", row.get("soc", row.get("state_of_charge", 0.5))),
            }
        )
        seen.add(key)
    return storage_rows


def _generated_control_blocks(model_book: EBook) -> Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]]:
    run_rows: list[dict[str, Any]] = []
    cb_rows: list[dict[str, Any]] = []
    set_rows: list[dict[str, Any]] = []

    for block_name, block in model_book.data.items():
        headers = set(getattr(block, "header_list", []))
        for row in getattr(block, "data", []):
            name = _row_name(row)
            if not name:
                continue
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
                if source_column not in row:
                    continue
                set_rows.append(
                    {
                        "dev_type": block_name,
                        "dev_name": name,
                        "set_type": set_type,
                        "set_value": row.get(source_column, 0),
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
    return blocks


def _generated_measurement_book(
    model_book: EBook,
    control_blocks: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]],
) -> EBook:
    rows: list[dict[str, Any]] = []
    name_counts: dict[str, int] = {}
    storage_names = {
        (str(row.get("dev_type", "")), str(row.get("name", "")))
        for row in control_blocks.get("StorageSoc", ((), ()))[1]
    }

    def add(dev_type: str, dev_name: str, meas_type: str, *, weight: float = 10000.0, value: Any = 0.0) -> None:
        if not dev_name:
            return
        base_name = f"{dev_type}.{dev_name}.{str(meas_type).lower() if meas_type in {'RUN_STAT', 'STATUS'} else meas_type}"
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
                "valid": 1,
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
            if (block_name, name) in storage_names:
                add(block_name, name, "SOC", value=row.get("soc_curr", row.get("soc", 0.5)))

    for weather_key, _name_suffix, meas_type in WEATHER_MEASUREMENTS:
        add("Environment", "weather", meas_type, weight=1.0, value=DEFAULT_WEATHER.get(weather_key, 0.0))

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
    row = {**DEFAULT_WEATHER, "time": "00:00:00"}
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
    for block_name in ("ACLoad", "DCLoad"):
        for row in _rows(model_book, block_name):
            name = _row_name(row)
            if name:
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
    }


def _generated_model_artifacts(model_text: str) -> Mapping[str, Any]:
    if not str(model_text or "").strip():
        raise ValueError("model.e 不能为空")
    model_book = _book_from_text(model_text)
    if not _model_book_has_power_model(model_book):
        raise ValueError("model.e 中未找到可识别的电网模型设备块")

    control_blocks = _generated_control_blocks(model_book)
    return {
        "model_book": model_book,
        "stat_book": _ebook_from_blocks(control_blocks),
        "control_book": _ebook_from_blocks(control_blocks),
        "meas_book": _generated_measurement_book(model_book, control_blocks),
        "weather_book": _generated_weather_book(),
        "curves_payload": _generated_curves_payload(model_book),
    }


def _write_generated_model_artifacts(
    target_dir: Path,
    artifacts: Mapping[str, Any],
    *,
    diagram_svg_text: Optional[str] = None,
    remove_diagram_when_absent: bool = False,
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
    _write_json_file(target_dir / "curves.json", curves_payload)
    (target_dir / "curves.e").write_text(_curve_definition_text(curves_payload), encoding="utf-8")
    written = ["model.e", "meas.e", "control.e", "stat.e", "weather.e", "curves.e", "curves.json"]
    if _write_model_diagram(target_dir, normalized_diagram, remove_when_absent=remove_diagram_when_absent):
        written.append(DIAGRAM_FILE_NAME)
    return written


def create_model_from_efile(
    manager: MultiModelSimulator,
    new_model_name: Any,
    model_text: str,
    *,
    diagram_svg_text: Optional[str] = None,
) -> Mapping[str, Any]:
    """Create one simulator source model folder from an uploaded model.e file."""
    target_id = manager.validate_new_model_name(new_model_name)
    artifacts = _generated_model_artifacts(model_text)

    target_dir = (manager.models_root / target_id).resolve()
    try:
        target_dir.relative_to(manager.models_root.resolve())
    except ValueError as exc:
        raise ValueError(f"模型名称无效: {new_model_name}") from exc
    if target_dir.exists():
        raise ValueError(f"模型文件夹已存在: {target_id}")

    written = _write_generated_model_artifacts(target_dir, artifacts, diagram_svg_text=diagram_svg_text)
    meas_book = artifacts["meas_book"]
    curves_payload = artifacts["curves_payload"]

    manager._append_manifest_model(target_id, target_dir)
    model_info = manager.service_for(target_id).model_info()
    return {
        **model_info,
        "created": {
            "files": written,
            "measurement_count": len(meas_book.data["Measurement"].data),
            "curve_points": curves_payload["point_count"],
        },
    }


def update_model_from_efile(
    manager: MultiModelSimulator,
    model_id: Any,
    model_text: str,
    *,
    diagram_svg_text: Optional[str] = None,
    replace_diagram: bool = False,
) -> Mapping[str, Any]:
    """Replace an existing stopped model's source definitions from an uploaded model.e file."""
    target = manager.service_for(model_id)
    if target.clock.state != "stopped":
        raise ValueError(f"模型运行中或暂停中，无法更新定义: {target.model_id}")
    artifacts = _generated_model_artifacts(model_text)
    target_dir = Path(target.sim_dir).resolve()
    try:
        target_dir.relative_to(manager.models_root.resolve())
    except ValueError as exc:
        raise ValueError(f"模型目录无效，无法更新定义: {target.model_id}") from exc

    written = _write_generated_model_artifacts(
        target_dir,
        artifacts,
        diagram_svg_text=diagram_svg_text,
        remove_diagram_when_absent=replace_diagram,
    )
    for path in (target.work_files.get("stat"), target.work_files.get("weather")):
        if path and Path(path).exists() and Path(path).is_file():
            Path(path).unlink()
    target._copy_runtime_inputs()
    target.reload_definition_state()
    target.ensure_weather_measurements_in_definition_files()
    target.curves = dict(artifacts["curves_payload"])
    _write_json_file(target.curves_file, target.curves)
    target.clock.step_minutes = max(1, int(_to_float(target.curves.get("time_step_minutes"), 1) or 1))
    target.reload_definition_state()
    target._materialize_active_control_commands(target.clock.absolute_minute, persist=True)
    target.latest_result = {}
    model_info = target.model_info()
    return {
        **model_info,
        "updated": {
            "files": written,
            "measurement_count": len(artifacts["meas_book"].data["Measurement"].data),
            "curve_points": artifacts["curves_payload"]["point_count"],
        },
    }


def import_definition_archive(service: PolarMicrogridSimulator, data: bytes) -> Mapping[str, Any]:
    try:
        archive = zipfile.ZipFile(BytesIO(data), mode="r")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid definition archive") from exc

    with archive:
        model_text = _read_zip_text(archive, "model.e")
        meas_text = _read_zip_text(archive, "meas.e")
        control_text = _read_zip_text(archive, "control.e")
        curves_text = _read_zip_text(archive, "curves.e")
        diagram_text = _read_zip_text(archive, DIAGRAM_FILE_NAME)

    assert model_text is not None and meas_text is not None and control_text is not None and curves_text is not None
    diagram_text = _normalize_diagram_svg_text(diagram_text)
    curves_payload = _curves_from_definition_text(curves_text)
    written_files: list[str] = []
    root = Path(service.sim_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "model.e").write_text(model_text, encoding="utf-8")
    simu_loop.clear_model_book_cache(root / "model.e")
    (root / "meas.e").write_text(meas_text, encoding="utf-8")
    (root / "control.e").write_text(control_text, encoding="utf-8")
    (root / "curves.e").write_text(curves_text, encoding="utf-8")
    diagram_written = _write_model_diagram(root, diagram_text, remove_when_absent=True)
    legacy_device = root / "device.e"
    if legacy_device.exists() and legacy_device.is_file():
        legacy_device.unlink()
    _merge_control_definition(root / "stat.e", control_text, meas_text)
    _write_json_file(root / "curves.json", curves_payload)
    names = ["model.e", "meas.e", "control.e", "curves.e", "stat.e", "curves.json"]
    if diagram_written:
        names.append(DIAGRAM_FILE_NAME)
    written_files.extend(str(root / name) for name in names)

    service.reload_definition_state()
    service.ensure_weather_measurements_in_definition_files()
    service.curves = dict(curves_payload)
    _write_json_file(service.curves_file, curves_payload)
    service.reload_definition_state()
    service._materialize_active_control_commands(service.clock.absolute_minute, persist=True)
    service.latest_result = {}
    return {
        "written": len(written_files),
        "files": written_files,
        "curve_mode": curves_payload.get("mode"),
        "curve_points": curves_payload.get("point_count"),
        "load_count": len(curves_payload.get("loads", {})),
        "diagram": diagram_written,
    }


def import_definition_model(
    manager: MultiModelSimulator,
    source_model_id: Optional[str],
    new_model_name: Any,
    data: bytes,
) -> Mapping[str, Any]:
    manager.validate_new_model_name(new_model_name)
    try:
        with zipfile.ZipFile(BytesIO(data), mode="r") as archive:
            curves_text = _read_zip_text(archive, "curves.e")
            _read_zip_text(archive, "model.e")
            _read_zip_text(archive, "meas.e")
            _read_zip_text(archive, "control.e")
            diagram_text = _read_zip_text(archive, DIAGRAM_FILE_NAME)
        assert curves_text is not None
        _curves_from_definition_text(curves_text)
        _normalize_diagram_svg_text(diagram_text)
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid definition archive") from exc

    model_info = manager.clone_model(source_model_id, new_model_name)
    imported_service = manager.service_for(str(model_info["id"]))
    imported = import_definition_archive(imported_service, data)
    return {**model_info, "imported": imported}


def make_definition_archive(service: PolarMicrogridSimulator) -> tuple[str, bytes]:
    model_path = _definition_file_path(service, "model", "model.e")
    meas_path = _definition_file_path(service, "meas", "meas.e")
    stat_path = _definition_file_path(service, "stat", "stat.e")
    missing = [str(path) for path in (model_path, meas_path, stat_path) if not path.exists()]
    if missing:
        raise JsonApiError(404, f"Definition file not found: {', '.join(missing)}")

    control_text = stat_path.read_text(encoding="utf-8")
    control_text = _extract_efile_blocks(control_text, CONTROL_DEFINITION_BLOCKS) or control_text
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_id = getattr(service, "model_id", "model") or "model"
    archive_name = f"{model_id}_definitions_{timestamp}.zip"

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(model_path, "model.e")
        archive.write(meas_path, "meas.e")
        archive.writestr("control.e", control_text.encode("utf-8"))
        archive.writestr("curves.e", _curve_definition_text(service.curves).encode("utf-8"))
        diagram_path = Path(getattr(service, "source_files", {}).get("diagram", service.sim_dir / DIAGRAM_FILE_NAME))
        if diagram_path.exists() and diagram_path.is_file():
            archive.write(diagram_path, DIAGRAM_FILE_NAME)
        else:
            archive.writestr(DIAGRAM_FILE_NAME, _fallback_definition_diagram_svg(service).encode("utf-8"))
    return archive_name, buffer.getvalue()


class JsonApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def make_http_server(
    server_address: tuple[str, int],
    service: PolarMicrogridSimulator | MultiModelSimulator,
    *,
    role: str = "simulator",
    static_root: Optional[str | Path] = None,
    sim_url: Optional[str] = None,
) -> ThreadingHTTPServer:
    role = role.lower()
    if static_root is None:
        static_root = WEB_DIR / ("trainee" if role == "trainee" else "simulator")
    static_root = Path(static_root).resolve()
    sim_url = sim_url.rstrip("/") if sim_url else None

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
                if self.path.startswith("/api/") and role == "trainee" and sim_url:
                    self._proxy_to_simulator("GET", sim_url)
                    return
                if self.path.startswith("/api/"):
                    self._handle_api_get()
                    return
                self._serve_static(static_root)
            except JsonApiError as exc:
                self._send_json({"error": exc.message}, status=exc.status)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)

        def do_POST(self) -> None:
            try:
                if self.path.startswith("/api/") and role == "trainee" and sim_url:
                    self._proxy_to_simulator("POST", sim_url)
                    return
                self._handle_api_post()
            except JsonApiError as exc:
                self._send_json({"error": exc.message}, status=exc.status)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)

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

        def _trainee_link_payload(self, target: PolarMicrogridSimulator) -> Mapping[str, Any]:
            model = target.model_info()
            model_id = str(model.get("id", target.model_id))
            base_url = self._request_base_url()
            encoded_model_id = quote(model_id, safe="")
            link = f"{base_url}/api/trainee-link?model_id={encoded_model_id}"
            return {
                "type": "polar-microgrid-trainee-link",
                "version": 1,
                "role": "simulator",
                "link": link,
                "teacher_api_base": base_url,
                "model_id": model_id,
                "model_name": model.get("name", model_id),
                "snapshot_path": f"/api/snapshot?model_id={encoded_model_id}",
                "command_path": f"/api/student/commands?model_id={encoded_model_id}",
                "runtime_logs_path": f"/api/runtime-logs?model_id={encoded_model_id}",
                "measurement_delta_path": f"/api/measurements/delta?model_id={encoded_model_id}",
                "telemetry_path": f"/api/external/telemetry?model_id={encoded_model_id}",
                "selected_telemetry_path": f"/api/external/telemetry/query?model_id={encoded_model_id}",
                "control_values_path": f"/api/external/controls?model_id={encoded_model_id}",
                "control_command_path": f"/api/external/controls?model_id={encoded_model_id}",
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

        def _legacy_trainee_connection_from_link(self, raw_link: str, parsed: Any) -> Optional[Mapping[str, Any]]:
            path = parsed.path.replace("//", "/").rstrip("/")
            if path not in {"/api/trainee-link", "/api/client-link"}:
                return None
            values = parse_qs(parsed.query)
            model_id = (values.get("model_id") or values.get("model") or [""])[0]
            if not model_id:
                return None
            encoded_model_id = quote(model_id, safe="")
            base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
            return {
                "type": "polar-microgrid-trainee-link",
                "role": "simulator",
                "link": raw_link,
                "teacher_api_base": base_url,
                "model_id": model_id,
                "model_name": model_id,
                "snapshot_path": f"/api/snapshot?model_id={encoded_model_id}",
                "command_path": f"/api/student/commands?model_id={encoded_model_id}",
                "measurement_delta_path": f"/api/measurements/delta?model_id={encoded_model_id}",
            }

        def _resolve_trainee_connection(self, raw_link: str) -> Mapping[str, Any]:
            raw = str(raw_link or "").strip()
            if not raw:
                raise JsonApiError(400, "请输入模拟台生成的交互链接")
            parsed = urlparse(raw)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise JsonApiError(400, "交互链接必须是完整的 http 或 https 地址")
            try:
                payload = self._json_request_to_url(raw)
            except JsonApiError as exc:
                legacy = self._legacy_trainee_connection_from_link(raw, parsed)
                if legacy and exc.status == 404:
                    payload = legacy
                else:
                    raise
            if not isinstance(payload, Mapping):
                raise JsonApiError(400, "交互链接返回内容不是对象")
            if payload.get("type") != "polar-microgrid-trainee-link" or payload.get("role") != "simulator":
                raise JsonApiError(400, "交互链接无效，请使用模拟台生成的链接")
            model_id = str(payload.get("model_id") or (parse_qs(parsed.query).get("model_id") or [""])[0]).strip()
            if not model_id:
                raise JsonApiError(400, "交互链接缺少模型标识")
            encoded_model_id = quote(model_id, safe="")
            base_url = str(payload.get("teacher_api_base") or f"{parsed.scheme}://{parsed.netloc}").rstrip("/")
            snapshot_path = str(payload.get("snapshot_path") or f"/api/snapshot?model_id={encoded_model_id}")
            return {
                "link": str(payload.get("link") or raw),
                "teacher_api_base": base_url,
                "model_id": model_id,
                "model_name": str(payload.get("model_name") or model_id),
                "snapshot_path": snapshot_path,
                "command_path": str(payload.get("command_path") or f"/api/student/commands?model_id={encoded_model_id}"),
                "measurement_delta_path": str(
                    payload.get("measurement_delta_path") or self._measurement_delta_path_from_snapshot_path(snapshot_path)
                ),
            }

        def _measurement_delta_path_from_snapshot_path(self, snapshot_path: str) -> str:
            parsed = urlparse(snapshot_path or "/api/snapshot")
            return urlunparse(("", "", "/api/measurements/delta", "", parsed.query, ""))

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
            allowed = ("lite", "logs", "runtime_logs", "measurements", "log_limit")
            return {key: values[key][0] for key in allowed if values.get(key)}

        def _handle_trainee_connect(self, payload: Mapping[str, Any]) -> None:
            connection = self._resolve_trainee_connection(str(payload.get("link", payload.get("interaction_link", ""))))
            snapshot_url = urljoin(
                connection["teacher_api_base"].rstrip("/") + "/",
                str(connection["snapshot_path"]).lstrip("/"),
            )
            snapshot = self._json_request_to_url(snapshot_url)
            self._send_json({"connection": connection, "snapshot": snapshot})

        def _handle_api_get(self) -> None:
            path = urlparse(self.path).path
            target = self._target_service()
            if path == "/api/health":
                self._send_json({"ok": True, "role": role})
            elif path == "/api/models":
                self._send_json(self._model_catalog())
            elif path == "/api/snapshot":
                lite = self._truthy_query("lite")
                default_log_limit = 20 if lite else 300
                self._send_json(
                    target.snapshot(
                        include_static=not lite,
                        runtime_log_limit=self._int_query("log_limit", default_log_limit),
                        include_runtime_logs=not (
                            self._falsey_query("logs") or self._falsey_query("runtime_logs")
                        ),
                        include_measurements=not self._falsey_query("measurements"),
                    )
                )
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
                self._send_json(target.measurements())
            elif path == "/api/measurements/delta":
                self._send_json(
                    target.measurement_delta(
                        after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                    )
                )
            elif path == "/api/external/telemetry":
                self._send_json(target.latest_telemetry_values())
            elif path == "/api/external/controls":
                self._send_json(target.latest_control_values())
            elif path == "/api/devices":
                self._send_json({"devices": target.devices()})
            elif path == "/api/curves":
                self._send_json(target.curves)
            elif path == "/api/settings":
                self._send_json(target.local_settings)
            elif path == "/api/trainee/receive-state":
                self._send_json(target.trainee_receive_state())
            elif path == "/api/trainee/receive-states":
                if hasattr(service, "trainee_receive_states"):
                    self._send_json({"items": service.trainee_receive_states()})  # type: ignore[union-attr]
                else:
                    self._send_json({"items": {target.model_id: target.trainee_receive_state()}})
            elif path == "/api/trainee/snapshot":
                remote_url = self._trainee_remote_url(
                    target,
                    "snapshot_path",
                    default_path="/api/snapshot",
                    query_overrides=self._trainee_snapshot_query_overrides(),
                )
                self._send_json(self._json_request_to_url(remote_url))
            elif path == "/api/trainee/measurements/delta":
                remote_url = self._trainee_remote_url(
                    target,
                    "measurement_delta_path",
                    default_path=self._measurement_delta_path_from_snapshot_path(target.trainee_receive_state().get("snapshot_path", "")),
                    query_overrides={"after_seq": self._int_query("after_seq", 0, 0, 2_000_000_000)},
                )
                self._send_json(self._json_request_to_url(remote_url))
            elif path in ("/api/trainee-link", "/api/client-link"):
                self._send_json(self._trainee_link_payload(target))
            elif path == "/api/config":
                self._send_json(
                    {
                        "role": role,
                        "sim_url": sim_url,
                        "poll_ms": 2000,
                        "system_parameters": target.system_parameters(),
                        **self._model_catalog(),
                    }
                )
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
                    model_text = model_data.decode("utf-8-sig")
                    diagram_svg_text = _decode_optional_svg_payload(payload)
                    model = create_model_from_efile(
                        service,  # type: ignore[arg-type]
                        model_name,
                        model_text,
                        diagram_svg_text=diagram_svg_text,
                    )
                except (UnicodeDecodeError, ValueError, OSError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                catalog = dict(self._model_catalog())
                catalog["active_model_id"] = model["id"]
                self._send_json({"model": model, **catalog})
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
                    model_text = model_data.decode("utf-8-sig")
                    diagram_svg_text = _decode_optional_svg_payload(payload)
                    model = update_model_from_efile(
                        service,  # type: ignore[arg-type]
                        model_id,
                        model_text,
                        diagram_svg_text=diagram_svg_text,
                        replace_diagram=bool(payload.get("replace_diagram", False)),
                    )
                except (UnicodeDecodeError, ValueError, OSError, KeyError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                catalog = dict(self._model_catalog())
                catalog["active_model_id"] = model["id"]
                self._send_json({"model": model, "updated": model["updated"], **catalog})
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
                    deleted = service.delete_model(model_id)  # type: ignore[union-attr]
                except KeyError as exc:
                    raise JsonApiError(404, str(exc)) from exc
                except ValueError as exc:
                    raise JsonApiError(400, str(exc)) from exc
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
                        )
                        catalog = dict(self._model_catalog())
                        catalog["active_model_id"] = model["id"]
                        self._send_json({"model": model, "imported": model["imported"], **catalog})
                        return
                    self._reject_active_trainee_receive_model(payload, "修改")
                    imported = import_definition_archive(self._target_service(payload), archive_data)
                except (ValueError, OSError) as exc:
                    raise JsonApiError(400, str(exc)) from exc
                self._send_json({"imported": imported, **self._model_catalog()})
                return

            if path == "/api/trainee/connect":
                self._handle_trainee_connect(payload)
                return

            target = self._target_service(payload)
            if path == "/api/student/commands":
                self._send_json(target.apply_student_commands(payload, source=str(payload.get("source", ""))))
            elif path == "/api/trainee/receive-state":
                self._send_json(target.set_trainee_receive_state(payload))
            elif path == "/api/trainee/commands":
                remote_url = self._trainee_remote_url(
                    target,
                    "command_path",
                    default_path="/api/student/commands",
                )
                command_payload = dict(payload)
                command_payload.pop("model_id", None)
                command_payload.pop("model", None)
                self._send_json(self._json_request_to_url(remote_url, method="POST", payload=command_payload))
            elif path == "/api/external/telemetry/query":
                self._send_json(target.selected_telemetry_values(payload))
            elif path == "/api/external/controls":
                self._send_json(target.apply_external_control_values(payload))
            elif path == "/api/clock":
                self._send_json(target.control_clock(payload))
            elif path == "/api/config":
                self._send_json(target.set_system_parameters(payload))
            elif path == "/api/runtime-logs/clear":
                self._send_json(target.clear_runtime_logs())
            elif path == "/api/step":
                self._send_json(target.step())
            elif path == "/api/curves":
                self._send_json(target.set_curves(payload))
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
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", content_type)
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
            data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
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

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Cache-Control", "no-store")

    server = ThreadingHTTPServer(server_address, PolarMicrogridHandler)
    server.service = service  # type: ignore[attr-defined]
    return server


def _advance_clock_if_due(service: PolarMicrogridSimulator, last_step: float) -> float:
    clock = service.snapshot()["clock"]
    now = time.monotonic()
    if clock["state"] != "running":
        return now
    interval_seconds = max(0.1, float(getattr(service, "compute_interval_seconds", CLOCK_BASE_INTERVAL_SECONDS) or CLOCK_BASE_INTERVAL_SECONDS))
    if now - last_step < interval_seconds:
        return last_step
    speed_minutes = _clock_int_value(clock.get("speed"), 1)
    step_minutes = _clock_int_value(clock.get("step_minutes"), 1)
    # Do not catch up by elapsed wall time: one completed solve advances one logical simulation step.
    advance_minutes = speed_minutes * step_minutes
    try:
        service.step(advance_minutes=advance_minutes)
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
    parser.add_argument("--role", choices=("simulator", "trainee"), default="simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--sim-dir", default=str(simu_loop.SIMU_DIR))
    parser.add_argument(
        "--models-dir",
        default=None,
        help="Directory whose direct subfolders are simulation models. Defaults to models/<role>/source.",
    )
    parser.add_argument("--runtime-dir", default=None)
    parser.add_argument("--sim-url", default=None, help="Simulator API base URL for trainee proxy mode.")
    parser.add_argument("--static-root", default=None)
    parser.add_argument("--no-worker", action="store_true", help="Do not start automatic clock worker.")
    parser.add_argument("--noise-std", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--compute-interval-seconds", type=float, default=1.0)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    port = args.port if args.port is not None else (8720 if args.role == "trainee" else 8710)
    sim_dir = Path(args.sim_dir).resolve()
    runtime_dir = Path(args.runtime_dir).resolve() if args.runtime_dir else _default_runtime_dir(sim_dir, args.role)
    models_dir = Path(args.models_dir).resolve() if args.models_dir else _default_models_dir(sim_dir, args.role)
    service = MultiModelSimulator.discover(
        sim_dir=sim_dir,
        runtime_dir=runtime_dir,
        noise_std=args.noise_std,
        random_seed=args.seed,
        compute_interval_seconds=args.compute_interval_seconds,
        models_dir=models_dir,
    )
    server = make_http_server(
        (args.host, port),
        service,
        role=args.role,
        static_root=args.static_root,
        sim_url=args.sim_url,
    )
    stop_event = threading.Event()
    workers = [] if args.no_worker else start_clock_workers(service, stop_event)
    print(f"{args.role} console: http://{args.host}:{port}/")
    print(f"runtime dir: {runtime_dir}")
    print(f"models dir: {service.models_root}")
    print(f"models: {', '.join(item['id'] for item in service.models())}")
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
