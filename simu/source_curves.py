"""Structured source-curve metadata shared by the service and model generator."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote

from simu.definition_editing import configured_setpoint_bounds


SOURCE_CURVE_SPECS: Mapping[str, Tuple[str, str, str]] = {
    "ACGenerator": ("electric", "p_set", "kW"),
    "DCGenerator": ("electric", "p_set", "kW"),
    "HydroSource": ("hydrogen", "flow_set", "Nm3/h"),
    "HeatSource": ("heat", "flow_set", "kg/s"),
}

LOAD_CURVE_SPECS: Mapping[str, Tuple[str, str, str, Tuple[str, ...]]] = {
    "ACLoad": ("electric", "p_set", "kW", ("p_kw", "value", "load_kw")),
    "DCLoad": ("electric", "p_set", "kW", ("p_kw", "value", "load_kw")),
    "HydroLoad": ("hydrogen", "flow_set", "Nm3/h", ("flow_set", "value")),
    "HeatLoad": ("heat", "heat_power", "kW", ("heat_power", "value")),
}


def _finite_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def source_curve_key(dev_type: Any, dev_name: Any, set_type: Any) -> str:
    parts = (
        quote(str(dev_type or "").strip(), safe=""),
        quote(str(dev_name or "").strip(), safe=""),
        quote(str(set_type or "").strip(), safe=""),
    )
    return f"source:{':'.join(parts)}"


def load_curve_key(dev_type: Any, dev_name: Any, set_type: Any) -> str:
    parts = (
        quote(str(dev_type or "").strip(), safe=""),
        quote(str(dev_name or "").strip(), safe=""),
        quote(str(set_type or "").strip(), safe=""),
    )
    return f"load:{':'.join(parts)}"


def _load_default_value(dev_type: str, row: Mapping[str, Any], set_type: str) -> Optional[float]:
    direct = _finite_number(row.get(set_type))
    if direct is not None:
        return direct
    if dev_type not in {"ACLoad", "DCLoad"} or set_type != "p_set":
        return None
    base = _finite_number(row.get("pbase"))
    constant = _finite_number(row.get("pv0"))
    if constant is None:
        return None
    return constant * (base if base is not None else 1.0)


def load_curve_catalog(model_book: Any) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    data = getattr(model_book, "data", {})
    for dev_type, (family, set_type, unit, aliases) in LOAD_CURVE_SPECS.items():
        block = data.get(dev_type) if isinstance(data, Mapping) else None
        if block is None:
            continue
        stem = set_type.removesuffix("_set")
        for row in getattr(block, "data", ()):
            dev_name = str(row.get("name", "")).strip()
            default_value = _load_default_value(dev_type, row, set_type)
            if not dev_name or default_value is None:
                continue
            bounds = configured_setpoint_bounds(row, set_type)
            lower = bounds[1] if bounds is not None else _finite_number(row.get(f"{stem}_min"))
            upper = bounds[3] if bounds is not None else _finite_number(row.get(f"{stem}_max"))
            item: Dict[str, Any] = {
                "key": load_curve_key(dev_type, dev_name, set_type),
                "dev_type": dev_type,
                "dev_name": dev_name,
                "name": dev_name,
                "set_type": set_type,
                "family": family,
                "unit": unit,
                "value_aliases": aliases,
                "default_value": default_value,
            }
            if lower is not None:
                item["min"] = lower
            if upper is not None:
                item["max"] = upper
            catalog.append(item)
    return catalog


def load_curve_identity(entry: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        str(entry.get("dev_type", "")).strip(),
        str(entry.get("dev_name", entry.get("name", ""))).strip(),
        str(entry.get("set_type", "")).strip(),
    )


def load_curve_catalog_by_identity(model_book: Any) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    return {load_curve_identity(item): item for item in load_curve_catalog(model_book)}


def load_curve_catalog_by_key(model_book: Any) -> Dict[str, Dict[str, Any]]:
    return {str(item["key"]): item for item in load_curve_catalog(model_book)}


def source_curve_identity(entry: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        str(entry.get("dev_type", "")).strip(),
        str(entry.get("dev_name", entry.get("name", ""))).strip(),
        str(entry.get("set_type", "")).strip(),
    )


def source_curve_catalog(model_book: Any) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    data = getattr(model_book, "data", {})
    for dev_type, (family, set_type, unit) in SOURCE_CURVE_SPECS.items():
        block = data.get(dev_type) if isinstance(data, Mapping) else None
        if block is None:
            continue
        stem = set_type.removesuffix("_set")
        for row in getattr(block, "data", ()):
            dev_name = str(row.get("name", "")).strip()
            default_value = _finite_number(row.get(set_type))
            if not dev_name or default_value is None:
                continue
            bounds = configured_setpoint_bounds(row, set_type)
            lower = bounds[1] if bounds is not None else _finite_number(row.get(f"{stem}_min"))
            upper = bounds[3] if bounds is not None else _finite_number(row.get(f"{stem}_max"))
            item: Dict[str, Any] = {
                "key": source_curve_key(dev_type, dev_name, set_type),
                "dev_type": dev_type,
                "dev_name": dev_name,
                "name": dev_name,
                "set_type": set_type,
                "family": family,
                "unit": unit,
                "default_value": default_value,
            }
            if lower is not None:
                item["min"] = lower
            if upper is not None:
                item["max"] = upper
            catalog.append(item)
    return catalog


def source_curve_catalog_by_identity(model_book: Any) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    return {source_curve_identity(item): item for item in source_curve_catalog(model_book)}


def source_curve_catalog_by_key(model_book: Any) -> Dict[str, Dict[str, Any]]:
    return {str(item["key"]): item for item in source_curve_catalog(model_book)}
