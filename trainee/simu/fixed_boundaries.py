"""Repair fixed electrical and multi-energy boundary values in EBook models."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Optional, Sequence


AC_VOLTAGE_CONTROLS = {"PV", "V", "SLACK", "PH", "CTRL_PV", "CTRL_V", "CTRL_SLACK", "CTRL_PH"}
AC_SIDE_VOLTAGE_CONTROLS = {"PV", "V", "PH", "CTRL_PV", "CTRL_V", "CTRL_PH"}
DC_VOLTAGE_CONTROLS = {"V", "SLACK", "CTRL_V", "CTRL_SLACK"}
DC_SIDE_VOLTAGE_CONTROLS = {"V", "CTRL_V"}
PRESSURE_CONTROLS = {"P", "V", "PRESSURE", "SLACK"}
FLUID_PREFIXES = ("Hydro", "Gas", "Heat", "Steam")

ACAC_LEGACY_CONTROLS = {
    "PQQ": ("PQ", "PQ"),
    "PVQ": ("PV", "PQ"),
    "PQV": ("PQ", "PV"),
    "PVV": ("PV", "PV"),
}
DCDC_LEGACY_CONTROLS = {
    "P": ("P", "NONE"),
    "CTRL_P": ("P", "NONE"),
    "V": ("V", "NONE"),
    "CTRL_V": ("V", "NONE"),
    "I": ("I", "NONE"),
    "CTRL_I": ("I", "NONE"),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _control(value: Any) -> str:
    return _text(value).upper()


def _finite(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _positive(value: Any) -> Optional[float]:
    result = _finite(value)
    return result if result is not None and result > 0.0 else None


def _running(row: Mapping[str, Any]) -> bool:
    value = _finite(row.get("run_stat", 1))
    return value is None or int(value) == 1


def _identity(value: Any) -> tuple[str, Any]:
    text = _text(value)
    number = _finite(text)
    if number is not None and number.is_integer():
        return ("index", int(number))
    return ("text", text.casefold())


def _row_name(row: Mapping[str, Any]) -> str:
    return _text(row.get("name")) or _text(row.get("idx")) or "未命名设备"


def _rows(book: Any, block_name: str) -> list[dict]:
    block = getattr(book, "data", {}).get(block_name)
    return [] if block is None else list(getattr(block, "data", []) or [])


def _block(book: Any, block_name: str) -> Any:
    return getattr(book, "data", {}).get(block_name)


def _node_maps(book: Any, block_name: str) -> tuple[dict[tuple[str, Any], dict], dict[int, dict]]:
    by_identity: dict[tuple[str, Any], dict] = {}
    by_object: dict[int, dict] = {}
    for row in _rows(book, block_name):
        if not _running(row):
            continue
        by_object[id(row)] = row
        for field in ("idx", "name"):
            if _text(row.get(field)):
                by_identity[_identity(row.get(field))] = row
    return by_identity, by_object


def _connected_node(node_map: Mapping[tuple[str, Any], dict], value: Any) -> Optional[dict]:
    if not _text(value):
        return None
    return node_map.get(_identity(value))


def _ensure_column(block: Any, field: str) -> None:
    if field not in block.header_list:
        block.header_list.append(field)
    for row in block.data:
        row.setdefault(field, "")


def _number_text(value: float) -> str:
    return format(float(value), ".15g")


def _bound_pair(row: Mapping[str, Any], pairs: Sequence[tuple[str, str]]) -> tuple[Optional[float], Optional[float], str]:
    for minimum_field, maximum_field in pairs:
        minimum = _positive(row.get(minimum_field))
        maximum = _positive(row.get(maximum_field))
        if minimum is not None and maximum is not None and minimum <= maximum:
            return minimum, maximum, f"{minimum_field}/{maximum_field}"
    return None, None, ""


def _midpoint_candidate(
    row: Mapping[str, Any],
    pairs: Sequence[tuple[str, str]],
    reference_prefix: str,
) -> Optional[tuple[float, str]]:
    minimum, maximum, fields = _bound_pair(row, pairs)
    if minimum is None or maximum is None:
        return None
    return (0.5 * (minimum + maximum), f"{reference_prefix}.{fields} 中值")


def _rated_candidates(
    row: Mapping[str, Any],
    fields: Sequence[str],
    reference_prefix: str,
) -> list[tuple[Optional[float], str]]:
    return [
        (_positive(row.get(field)), f"{reference_prefix}.{field}")
        for field in fields
    ]


def _voltage_bound_pair(
    row: Mapping[str, Any],
    pairs: Sequence[tuple[str, str]],
    reference_voltage: Optional[float],
) -> tuple[Optional[float], Optional[float], str]:
    minimum, maximum, fields = _bound_pair(row, pairs)
    if minimum is None or maximum is None:
        return None, None, ""
    if maximum <= 2.0 and reference_voltage is not None and reference_voltage > 2.0:
        return minimum * reference_voltage, maximum * reference_voltage, f"{fields} (pu)"
    return minimum, maximum, fields


def _voltage_midpoint_candidate(
    row: Mapping[str, Any],
    pairs: Sequence[tuple[str, str]],
    reference_prefix: str,
    reference_voltage: Optional[float],
) -> Optional[tuple[float, str]]:
    minimum, maximum, fields = _voltage_bound_pair(row, pairs, reference_voltage)
    if minimum is None or maximum is None:
        return None
    return (0.5 * (minimum + maximum), f"{reference_prefix}.{fields} 中值")


def _within(value: Optional[float], minimum: float, maximum: float) -> bool:
    return value is not None and minimum <= value <= maximum


def _record_correction(
    corrections: list[dict],
    *,
    block_name: str,
    row: Mapping[str, Any],
    field: str,
    original: Any,
    replacement: float,
    reason: str,
    reference: str,
    side: Optional[str] = None,
) -> None:
    item = {
        "device_type": block_name,
        "idx": _text(row.get("idx")),
        "name": _row_name(row),
        "field": field,
        "original": original,
        "replacement": float(replacement),
        "reason": reason,
        "reference": reference,
    }
    if side is not None:
        item["side"] = side
    corrections.append(item)


def _repair_field(
    *,
    block: Any,
    block_name: str,
    row: dict,
    field: str,
    candidates: Iterable[tuple[Optional[float], str]],
    corrections: list[dict],
    minimum: float,
    maximum: float,
    aliases: Sequence[str] = (),
    reason: str,
    side: Optional[str] = None,
) -> float:
    canonical_present = field in row and _text(row.get(field)) != ""
    original = row.get(field, "")
    current = _finite(original) if canonical_present else None
    if canonical_present and _within(current, minimum, maximum):
        return float(current)

    alias_candidates: list[tuple[Optional[float], str]] = []
    if not canonical_present:
        for alias in aliases:
            if alias in row and _text(row.get(alias)):
                alias_candidates.append((_finite(row.get(alias)), f"{block_name}.{_row_name(row)}.{alias}"))

    replacement: Optional[float] = None
    reference = ""
    for candidate, candidate_reference in (*alias_candidates, *tuple(candidates)):
        if _within(candidate, minimum, maximum):
            replacement = float(candidate)
            reference = candidate_reference
            break
    if replacement is None:
        raise ValueError(
            f"{block_name}.{_row_name(row)}.{field} 是投入运行的固定边界，但当前值 {original!r} 无效，"
            "且无法从连接设备、额定值或上下限推导可靠修正值"
        )

    _ensure_column(block, field)
    row[field] = _number_text(replacement)
    _record_correction(
        corrections,
        block_name=block_name,
        row=row,
        field=field,
        original=original,
        replacement=replacement,
        reason=reason,
        reference=reference,
        side=side,
    )
    return replacement


def _device_control_pair(row: Mapping[str, Any], kind: str) -> tuple[str, str]:
    i_control = _control(row.get("i_control_type"))
    j_control = _control(row.get("j_control_type"))
    if i_control or j_control:
        return i_control or "NONE", j_control or "NONE"
    legacy = _control(row.get("control_type"))
    mapping = ACAC_LEGACY_CONTROLS if kind == "ACAC" else DCDC_LEGACY_CONTROLS
    return mapping.get(legacy, (legacy, "NONE"))


def _voltage_device_connections(book: Any, system: str) -> list[tuple[str, dict, str, str, bool, tuple[tuple[str, str], ...]]]:
    result: list[tuple[str, dict, str, str, bool, tuple[tuple[str, str], ...]]] = []
    if system == "AC":
        for row in _rows(book, "ACGenerator"):
            result.append(("ACGenerator", row, "node", "v_set", _control(row.get("control_type")) in AC_VOLTAGE_CONTROLS, (("v_min", "v_max"),)))
        for block_name in ("ACShuntCompensator", "ACShunt"):
            for row in _rows(book, block_name):
                result.append((block_name, row, "node", "v_set", _control(row.get("control_type")) in AC_SIDE_VOLTAGE_CONTROLS, (("v_min", "v_max"),)))
        for row in _rows(book, "ACACConverter"):
            i_control, j_control = _device_control_pair(row, "ACAC")
            result.extend(
                (
                    ("ACACConverter", row, "i_node", "i_v_set", i_control in AC_SIDE_VOLTAGE_CONTROLS, (("i_v_min", "i_v_max"),)),
                    ("ACACConverter", row, "j_node", "j_v_set", j_control in AC_SIDE_VOLTAGE_CONTROLS, (("j_v_min", "j_v_max"),)),
                )
            )
        for row in _rows(book, "DCACConverter"):
            result.append(("DCACConverter", row, "ac_node", "v_ac_set", _control(row.get("ac_control_type")) in AC_SIDE_VOLTAGE_CONTROLS, (("ac_v_min", "ac_v_max"),)))
    else:
        for row in _rows(book, "DCGenerator"):
            result.append(("DCGenerator", row, "node", "v_set", _control(row.get("control_type")) in DC_VOLTAGE_CONTROLS, (("v_min", "v_max"),)))
        for row in _rows(book, "DCDCConverter"):
            i_control, j_control = _device_control_pair(row, "DCDC")
            if (
                _running(row)
                and i_control in DC_SIDE_VOLTAGE_CONTROLS
                and j_control in DC_SIDE_VOLTAGE_CONTROLS
            ):
                raise ValueError(
                    f"DCDCConverter.{_row_name(row)} 的 i/j 两端同时采用 V 控制，"
                    "但两端共享 v_set，无法确定唯一受控端电压参考"
                )
            result.extend(
                (
                    ("DCDCConverter", row, "i_node", "v_set", i_control in DC_SIDE_VOLTAGE_CONTROLS, (("i_v_min", "i_v_max"),)),
                    ("DCDCConverter", row, "j_node", "v_set", j_control in DC_SIDE_VOLTAGE_CONTROLS, (("j_v_min", "j_v_max"),)),
                )
            )
        for row in _rows(book, "DCACConverter"):
            result.append(("DCACConverter", row, "dc_node", "v_dc_set", _control(row.get("dc_control_type")) in DC_SIDE_VOLTAGE_CONTROLS, (("dc_v_min", "dc_v_max"),)))
    return result


def _node_voltage_candidates(
    book: Any,
    system: str,
    node: Mapping[str, Any],
) -> list[tuple[Optional[float], str]]:
    candidates: list[tuple[int, int, Optional[float], str]] = []
    order = 0
    node_name = f"{system}Node.{_row_name(node)}"
    node_reference: Optional[float] = None
    for field, priority in (("voltage", 0), ("rated_voltage", 10)):
        if field in node:
            value = _positive(node.get(field))
            if node_reference is None and value is not None:
                node_reference = value
            candidates.append((priority, order, value, f"{node_name}.{field}"))
            order += 1
    midpoint = _voltage_midpoint_candidate(
        node,
        (("v_min", "v_max"),),
        node_name,
        node_reference,
    )
    if midpoint is not None:
        candidates.append((30, order, midpoint[0], midpoint[1]))
        order += 1

    node_keys = {_identity(node.get("idx")), _identity(node.get("name"))}
    for block_name, row, node_field, setpoint_field, controlled, bound_pairs in _voltage_device_connections(book, system):
        if not _running(row) or _identity(row.get(node_field)) not in node_keys:
            continue
        prefix = f"{block_name}.{_row_name(row)}"
        setpoint = _positive(row.get(setpoint_field)) if controlled else None
        rated: Optional[float] = None
        rated_field_used = ""
        rated_fields = (
            f"{node_field.split('_')[0]}_rated_voltage" if "_node" in node_field else "rated_voltage",
            "rated_voltage",
        )
        for rated_field in rated_fields:
            rated = _positive(row.get(rated_field))
            if rated is not None:
                rated_field_used = rated_field
                break
        bound_reference = rated or setpoint
        minimum, maximum, _ = _voltage_bound_pair(row, bound_pairs, bound_reference)
        if setpoint is not None and (minimum is None or minimum <= setpoint) and (maximum is None or setpoint <= maximum):
            candidates.append((10, order, setpoint, f"{prefix}.{setpoint_field}"))
            order += 1
        if rated is not None and (minimum is None or minimum <= rated) and (maximum is None or rated <= maximum):
            candidates.append((20, order, rated, f"{prefix}.{rated_field_used}"))
            order += 1
        midpoint = _voltage_midpoint_candidate(row, bound_pairs, prefix, bound_reference)
        if midpoint is not None:
            candidates.append((30, order, midpoint[0], midpoint[1]))
            order += 1
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [(value, reference) for _, _, value, reference in candidates]


def _repair_voltage_nodes(book: Any, system: str, corrections: list[dict]) -> dict[tuple[str, Any], dict]:
    block_name = f"{system}Node"
    block = _block(book, block_name)
    if block is None:
        return {}
    node_map, _ = _node_maps(book, block_name)
    for row in block.data:
        if not _running(row):
            continue
        _repair_field(
            block=block,
            block_name=block_name,
            row=row,
            field="vbase",
            candidates=_node_voltage_candidates(book, system, row),
            corrections=corrections,
            minimum=math.nextafter(0.0, 1.0),
            maximum=math.inf,
            reason="投入节点基准电压必须为有限正数",
        )
    return node_map


def _voltage_bounds(row: Mapping[str, Any], pairs: Sequence[tuple[str, str]], node_voltage: float) -> tuple[float, float]:
    minimum, maximum, _ = _voltage_bound_pair(row, pairs, node_voltage)
    if minimum is None or maximum is None:
        return 0.5 * node_voltage, 1.5 * node_voltage
    return minimum, maximum


def _repair_voltage_devices(
    book: Any,
    system: str,
    node_map: Mapping[tuple[str, Any], dict],
    corrections: list[dict],
) -> None:
    for block_name, row, node_field, setpoint_field, controlled, bound_pairs in _voltage_device_connections(book, system):
        if not controlled or not _running(row):
            continue
        block = _block(book, block_name)
        node = _connected_node(node_map, row.get(node_field))
        node_voltage = _positive(None if node is None else node.get("vbase"))
        if node_voltage is None:
            raise ValueError(
                f"{block_name}.{_row_name(row)}.{setpoint_field} 是投入运行的固定电压边界，"
                f"但受控端 {node_field}={row.get(node_field)!r} 没有有效投入节点"
            )
        minimum, maximum = _voltage_bounds(row, bound_pairs, node_voltage)
        prefix = f"{block_name}.{_row_name(row)}"
        candidates: list[tuple[Optional[float], str]] = [(node_voltage, f"{system}Node.{_row_name(node)}.vbase")]
        side = node_field.split("_")[0] if node_field in {"i_node", "j_node", "ac_node", "dc_node"} else None
        rated_fields = ["rated_voltage"]
        if side is not None:
            rated_fields.insert(0, f"{side}_rated_voltage")
        candidates.extend((_positive(row.get(field)), f"{prefix}.{field}") for field in rated_fields)
        midpoint = _voltage_midpoint_candidate(
            row,
            bound_pairs,
            prefix,
            node_voltage,
        )
        if midpoint is not None:
            candidates.append(midpoint)
        _repair_field(
            block=block,
            block_name=block_name,
            row=row,
            field=setpoint_field,
            candidates=candidates,
            corrections=corrections,
            minimum=minimum,
            maximum=maximum,
            reason=f"投入设备的{side + ' 侧' if side else ''}定电压参考必须有效且位于允许范围内",
            side=side,
        )


def _fluid_device_rows(book: Any, prefix: str) -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    for suffix in ("Source", "Storage"):
        block_name = f"{prefix}{suffix}"
        result.extend((block_name, row) for row in _rows(book, block_name))
    return result


def _fluid_pressure_controlled(prefix: str, block_name: str, row: Mapping[str, Any]) -> bool:
    return (prefix == "Hydro" and block_name == "HydroStorage") or _control(row.get("control_type")) in PRESSURE_CONTROLS


def _fluid_reference_node_field(prefix: str, row: Mapping[str, Any], thermal_field: Optional[str] = None) -> str:
    if prefix == "Heat" and thermal_field == "return_temperature":
        return "return_node" if _text(row.get("return_node")) else "node"
    if prefix == "Heat" and _text(row.get("supply_node")):
        return "supply_node"
    return "node"


def _connected_fluid_candidates(
    book: Any,
    prefix: str,
    node: Mapping[str, Any],
    field: str,
) -> list[tuple[Optional[float], str]]:
    candidates: list[tuple[int, int, Optional[float], str]] = []
    node_keys = {_identity(node.get("idx")), _identity(node.get("name"))}
    order = 0
    for block_name, row in _fluid_device_rows(book, prefix):
        if not _running(row):
            continue
        node_field = _fluid_reference_node_field(prefix, row, field)
        if _identity(row.get(node_field)) not in node_keys:
            continue
        name = f"{block_name}.{_row_name(row)}"
        if field == "pressure":
            bound_pairs = (("pressure_min", "pressure_max"),)
            minimum, maximum, _ = _bound_pair(row, bound_pairs)
            if _fluid_pressure_controlled(prefix, block_name, row):
                value = _positive(row.get("pressure_set", row.get("p_set")))
                if value is not None and (minimum is None or minimum <= value) and (maximum is None or value <= maximum):
                    candidates.append((10, order, value, f"{name}.pressure_set"))
                order += 1
            for rated_field in ("rated_pressure", "nominal_pressure"):
                rated_pressure = _positive(row.get(rated_field))
                if (
                    rated_pressure is not None
                    and (minimum is None or minimum <= rated_pressure)
                    and (maximum is None or rated_pressure <= maximum)
                ):
                    candidates.append((20, order, rated_pressure, f"{name}.{rated_field}"))
                order += 1
            midpoint = _midpoint_candidate(row, bound_pairs, name)
        elif field in {"supply_temperature", "return_temperature"}:
            canonical = f"{field}_set"
            bound_pairs = (
                (f"{field}_min", f"{field}_max"),
                ("temperature_min", "temperature_max"),
            )
            value = _positive(row.get(canonical, row.get(field)))
            minimum, maximum, _ = _bound_pair(row, bound_pairs)
            if value is not None and (minimum is None or minimum <= value) and (maximum is None or value <= maximum):
                candidates.append((10, order, value, f"{name}.{canonical}"))
            order += 1
            for rated_value, rated_reference in _rated_candidates(
                row,
                (f"rated_{field}", f"{field}_rated"),
                name,
            ):
                if (
                    rated_value is not None
                    and (minimum is None or minimum <= rated_value)
                    and (maximum is None or rated_value <= maximum)
                ):
                    candidates.append((20, order, rated_value, rated_reference))
                order += 1
            midpoint = _midpoint_candidate(row, bound_pairs, name)
        else:
            bound_pairs = (("enthalpy_min", "enthalpy_max"), ("h_min", "h_max"))
            value = _positive(row.get("enthalpy_set", row.get("h_set")))
            minimum, maximum, _ = _bound_pair(row, bound_pairs)
            if value is not None and (minimum is None or minimum <= value) and (maximum is None or value <= maximum):
                candidates.append((10, order, value, f"{name}.enthalpy_set"))
            order += 1
            for rated_value, rated_reference in _rated_candidates(
                row,
                ("rated_enthalpy", "nominal_enthalpy"),
                name,
            ):
                if (
                    rated_value is not None
                    and (minimum is None or minimum <= rated_value)
                    and (maximum is None or rated_value <= maximum)
                ):
                    candidates.append((20, order, rated_value, rated_reference))
                order += 1
            midpoint = _midpoint_candidate(row, bound_pairs, name)
        if midpoint is not None:
            candidates.append((30, order, midpoint[0], midpoint[1]))
            order += 1
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [(value, reference) for _, _, value, reference in candidates]


def _repair_fluid_nodes(
    book: Any,
    prefix: str,
    corrections: list[dict],
) -> dict[tuple[str, Any], dict]:
    block_name = f"{prefix}Node"
    block = _block(book, block_name)
    if block is None:
        return {}
    node_map, _ = _node_maps(book, block_name)
    for row in block.data:
        if not _running(row):
            continue
        pressure_minimum, pressure_maximum = _fluid_bounds(
            row,
            (("pressure_min", "pressure_max"),),
        )
        pressure_midpoint = _midpoint_candidate(row, (("pressure_min", "pressure_max"),), f"{block_name}.{_row_name(row)}")
        pressure_candidates = _rated_candidates(
            row,
            ("rated_pressure", "nominal_pressure"),
            f"{block_name}.{_row_name(row)}",
        )
        pressure_candidates.extend(
            _connected_fluid_candidates(book, prefix, row, "pressure")
        )
        if pressure_midpoint is not None:
            pressure_candidates.append(pressure_midpoint)
        _repair_field(
            block=block,
            block_name=block_name,
            row=row,
            field="pressure",
            aliases=("p_set",),
            candidates=pressure_candidates,
            corrections=corrections,
            minimum=pressure_minimum,
            maximum=pressure_maximum,
            reason="投入流体节点压力必须为有限正数",
        )
        if prefix == "Heat":
            for field in ("supply_temperature", "return_temperature"):
                temperature_bounds = (
                    (f"{field}_min", f"{field}_max"),
                    ("temperature_min", "temperature_max"),
                )
                temperature_minimum, temperature_maximum = _fluid_bounds(
                    row,
                    temperature_bounds,
                )
                midpoint = _midpoint_candidate(
                    row,
                    temperature_bounds,
                    f"{block_name}.{_row_name(row)}",
                )
                candidates = _rated_candidates(
                    row,
                    (f"rated_{field}", f"{field}_rated"),
                    f"{block_name}.{_row_name(row)}",
                )
                candidates.extend(
                    _connected_fluid_candidates(book, prefix, row, field)
                )
                if midpoint is not None:
                    candidates.append(midpoint)
                _repair_field(
                    block=block,
                    block_name=block_name,
                    row=row,
                    field=field,
                    candidates=candidates,
                    corrections=corrections,
                    minimum=temperature_minimum,
                    maximum=temperature_maximum,
                    reason="投入热网节点温度必须为有限正数",
                )
            _repair_field(
                block=block,
                block_name=block_name,
                row=row,
                field="temperature",
                candidates=((_positive(row.get("supply_temperature")), f"{block_name}.{_row_name(row)}.supply_temperature"),),
                corrections=corrections,
                minimum=math.nextafter(0.0, 1.0),
                maximum=math.inf,
                reason="投入热网节点温度初值必须为有限正数",
            )
        if prefix == "Steam":
            enthalpy_bounds = (("enthalpy_min", "enthalpy_max"), ("h_min", "h_max"))
            enthalpy_minimum, enthalpy_maximum = _fluid_bounds(row, enthalpy_bounds)
            midpoint = _midpoint_candidate(row, enthalpy_bounds, f"{block_name}.{_row_name(row)}")
            candidates = _rated_candidates(
                row,
                ("rated_enthalpy", "nominal_enthalpy"),
                f"{block_name}.{_row_name(row)}",
            )
            candidates.extend(
                _connected_fluid_candidates(book, prefix, row, "enthalpy")
            )
            if midpoint is not None:
                candidates.append(midpoint)
            _repair_field(
                block=block,
                block_name=block_name,
                row=row,
                field="enthalpy",
                aliases=("h",),
                candidates=candidates,
                corrections=corrections,
                minimum=enthalpy_minimum,
                maximum=enthalpy_maximum,
                reason="投入蒸汽节点定焓边界必须为有限正数",
            )
    return node_map


def _fluid_bounds(row: Mapping[str, Any], pairs: Sequence[tuple[str, str]]) -> tuple[float, float]:
    minimum, maximum, _ = _bound_pair(row, pairs)
    if minimum is None or maximum is None:
        return math.nextafter(0.0, 1.0), math.inf
    return minimum, maximum


def _repair_fluid_devices(
    book: Any,
    prefix: str,
    node_map: Mapping[tuple[str, Any], dict],
    corrections: list[dict],
) -> None:
    # Legacy coupling-only definitions may contain HydroSource/HydroStorage
    # metadata without a fluid node table. The kernel does not instantiate a
    # fluid network for those rows, so they are not active fixed boundaries.
    if _block(book, f"{prefix}Node") is None:
        return
    for block_name, row in _fluid_device_rows(book, prefix):
        if not _running(row):
            continue
        block = _block(book, block_name)
        node_field = _fluid_reference_node_field(prefix, row)
        node = _connected_node(node_map, row.get(node_field))
        if _fluid_pressure_controlled(prefix, block_name, row):
            if node is None:
                raise ValueError(
                    f"{block_name}.{_row_name(row)}.pressure_set 是投入运行的定压力边界，"
                    f"但受控端 {node_field}={row.get(node_field)!r} 没有有效投入节点"
                )
            node_pressure = _positive(None if node is None else node.get("pressure"))
            minimum, maximum = _fluid_bounds(row, (("pressure_min", "pressure_max"),))
            midpoint = _midpoint_candidate(row, (("pressure_min", "pressure_max"),), f"{block_name}.{_row_name(row)}")
            candidates: list[tuple[Optional[float], str]] = [
                (node_pressure, f"{prefix}Node.{_row_name(node or {})}.pressure"),
            ]
            candidates.extend(
                (_positive(row.get(field)), f"{block_name}.{_row_name(row)}.{field}")
                for field in ("rated_pressure", "nominal_pressure")
            )
            if midpoint is not None:
                candidates.append(midpoint)
            _repair_field(
                block=block,
                block_name=block_name,
                row=row,
                field="pressure_set",
                aliases=("p_set",),
                candidates=candidates,
                corrections=corrections,
                minimum=minimum,
                maximum=maximum,
                reason="投入设备采用定压力控制时压力参考必须有效且位于允许范围内",
            )

        if prefix == "Heat":
            for field, node_temperature_field in (
                ("supply_temperature_set", "supply_temperature"),
                ("return_temperature_set", "return_temperature"),
            ):
                reference_field = _fluid_reference_node_field(prefix, row, node_temperature_field)
                temperature_node = _connected_node(node_map, row.get(reference_field))
                if temperature_node is None:
                    raise ValueError(
                        f"{block_name}.{_row_name(row)}.{field} 是投入运行的定温边界，"
                        f"但受控端 {reference_field}={row.get(reference_field)!r} 没有有效投入节点"
                    )
                node_temperature = _positive(None if temperature_node is None else temperature_node.get(node_temperature_field))
                bound_pairs = (
                    (f"{node_temperature_field}_min", f"{node_temperature_field}_max"),
                    ("temperature_min", "temperature_max"),
                )
                minimum, maximum = _fluid_bounds(row, bound_pairs)
                midpoint = _midpoint_candidate(row, bound_pairs, f"{block_name}.{_row_name(row)}")
                candidates = [(node_temperature, f"HeatNode.{_row_name(temperature_node or {})}.{node_temperature_field}")]
                candidates.extend(
                    _rated_candidates(
                        row,
                        (
                            f"rated_{node_temperature_field}",
                            f"{node_temperature_field}_rated",
                        ),
                        f"{block_name}.{_row_name(row)}",
                    )
                )
                if midpoint is not None:
                    candidates.append(midpoint)
                _repair_field(
                    block=block,
                    block_name=block_name,
                    row=row,
                    field=field,
                    aliases=(node_temperature_field,),
                    candidates=candidates,
                    corrections=corrections,
                    minimum=minimum,
                    maximum=maximum,
                    reason="投入热源或蓄热设备的定温边界必须为有限正数",
                )

        if prefix == "Steam":
            enthalpy_node = _connected_node(node_map, row.get(node_field))
            if enthalpy_node is None:
                raise ValueError(
                    f"{block_name}.{_row_name(row)}.enthalpy_set 是投入运行的定焓边界，"
                    f"但受控端 {node_field}={row.get(node_field)!r} 没有有效投入节点"
                )
            node_enthalpy = _positive(None if enthalpy_node is None else enthalpy_node.get("enthalpy"))
            bound_pairs = (("enthalpy_min", "enthalpy_max"), ("h_min", "h_max"))
            minimum, maximum = _fluid_bounds(row, bound_pairs)
            midpoint = _midpoint_candidate(row, bound_pairs, f"{block_name}.{_row_name(row)}")
            candidates = [(node_enthalpy, f"SteamNode.{_row_name(enthalpy_node or {})}.enthalpy")]
            candidates.extend(
                _rated_candidates(
                    row,
                    ("rated_enthalpy", "nominal_enthalpy"),
                    f"{block_name}.{_row_name(row)}",
                )
            )
            if midpoint is not None:
                candidates.append(midpoint)
            _repair_field(
                block=block,
                block_name=block_name,
                row=row,
                field="enthalpy_set",
                aliases=("h_set",),
                candidates=candidates,
                corrections=corrections,
                minimum=minimum,
                maximum=maximum,
                reason="投入蒸汽源或储能设备的定焓边界必须为有限正数",
            )


def repair_fixed_boundary_setpoints(model_book: Any) -> list[dict]:
    """Repair active fixed-potential boundaries and return an audit trail.

    Non-controlling placeholders and out-of-service rows are deliberately left
    untouched. Corrections are derived from the controlled terminal, an
    explicit rated value, or valid limits; an unrecoverable boundary is
    rejected with a device-and-field-specific error.
    """

    corrections: list[dict] = []
    ac_nodes = _repair_voltage_nodes(model_book, "AC", corrections)
    dc_nodes = _repair_voltage_nodes(model_book, "DC", corrections)
    _repair_voltage_devices(model_book, "AC", ac_nodes, corrections)
    _repair_voltage_devices(model_book, "DC", dc_nodes, corrections)
    for prefix in FLUID_PREFIXES:
        node_map = _repair_fluid_nodes(model_book, prefix, corrections)
        _repair_fluid_devices(model_book, prefix, node_map, corrections)
    return corrections
