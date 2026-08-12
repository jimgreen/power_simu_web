"""Model semantics derived from block structure, references, and topology.

Device names and row-level ``dev_type`` values are identifiers or descriptive
metadata only. Runtime technology and converter-boundary decisions must come
from parameter-table references and terminal connectivity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple


DeviceKey = Tuple[str, str]


@dataclass(frozen=True)
class ResourceRelationSpec:
    technology: str
    parameter_block: str
    source_block: str
    source_index_field: str


@dataclass(frozen=True)
class StructuredResource:
    technology: str
    parameter_block: str
    parameter_index: str
    source_block: str
    source_index: str
    source_name: str
    parameter: Mapping[str, Any]
    source: Mapping[str, Any]

    @property
    def device_key(self) -> DeviceKey:
        return self.source_block, self.source_name


RESOURCE_RELATION_SPECS: Tuple[ResourceRelationSpec, ...] = (
    ResourceRelationSpec("wind", "ACWindGen", "ACGenerator", "idx_acgenerator"),
    ResourceRelationSpec("wind", "DCWindGen", "DCGenerator", "idx_dcgenerator"),
    ResourceRelationSpec("pv", "ACPVGen", "ACGenerator", "idx_acgenerator"),
    ResourceRelationSpec("pv", "DCPVGen", "DCGenerator", "idx_dcgenerator"),
    ResourceRelationSpec("storage", "ACStorageGen", "ACGenerator", "idx_acgenerator"),
    ResourceRelationSpec("storage", "DCStorageGen", "DCGenerator", "idx_dcgenerator"),
    ResourceRelationSpec("diesel", "ACDieselGen", "ACGenerator", "idx_acgenerator"),
    ResourceRelationSpec("diesel", "DCDieselGen", "DCGenerator", "idx_dcgenerator"),
)

SAME_DOMAIN_EDGE_SPECS = (
    ("ACBranch", "AC"),
    ("ACLine", "AC"),
    ("ACTransformer", "AC"),
    ("ACZeroBranch", "AC"),
    ("ACSwitch", "AC"),
    ("ACBreak", "AC"),
    ("ACACConverter", "AC"),
    ("DCBranch", "DC"),
    ("DCLine", "DC"),
    ("DCZeroBranch", "DC"),
    ("DCSwitch", "DC"),
    ("DCBreak", "DC"),
    ("DCDCConverter", "DC"),
)

CROSS_DOMAIN_CONVERTER_BLOCKS = ("ACDCConverter", "DCACConverter")
HYDROGEN_CONVERSION_BLOCKS = (
    "AcE2Hydro",
    "DcE2Hydro",
    "Hydro2AcE",
    "Hydro2DcE",
)
HYDROGEN_CONVERSION_CONTROL_MODES = frozenset({"P", "FLOW"})


def normalize_hydrogen_conversion_control_mode(value: Any) -> str:
    mode = str(value or "").strip().upper()
    if mode not in HYDROGEN_CONVERSION_CONTROL_MODES:
        raise ValueError("hydrogen conversion control_type must be P or FLOW")
    return mode


def hydrogen_conversion_active_set_type(value: Any) -> str:
    mode = str(value or "").strip().upper()
    return {"P": "p_set", "PQ": "p_set", "FLOW": "flow_set"}.get(mode, "")


def _model_blocks(model: Any) -> Mapping[str, Any]:
    if hasattr(model, "data") and isinstance(model.data, Mapping):
        return model.data
    if not isinstance(model, Mapping):
        return {}
    definitions = model.get("definitions")
    if isinstance(definitions, Mapping):
        nested = definitions.get("model")
        if isinstance(nested, Mapping):
            return nested
    nested = model.get("model")
    if isinstance(nested, Mapping):
        return nested
    return model


def model_rows(model: Any, block_name: str) -> Tuple[Mapping[str, Any], ...]:
    block = _model_blocks(model).get(block_name)
    if block is None:
        return ()
    if hasattr(block, "data"):
        rows = block.data
    elif isinstance(block, Mapping):
        rows = block.get("rows", ())
    else:
        rows = block
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()
    return tuple(row for row in rows if isinstance(row, Mapping))


def _coupling_endpoint_block(reference_field: Any) -> str:
    token = "".join(char for char in str(reference_field or "").casefold() if char.isalnum())
    token = token.removeprefix("idx").removesuffix("t1").removesuffix("t2")
    if token.startswith(("ace", "ac")):
        return "ACLoad" if "load" in token else "ACGenerator"
    if token.startswith(("dce", "dc")):
        return "DCLoad" if "load" in token else "DCGenerator"
    if token.startswith(("hydrogen", "hydro", "h2")):
        if "load" in token:
            return "HydroLoad"
        if "storage" in token or "tank" in token:
            return "HydroStorage"
        return "HydroSource"
    return ""


def energy_coupling_control_bindings(model: Any) -> Dict[DeviceKey, Tuple[Dict[str, Any], ...]]:
    """Map each electric/H2 converter to endpoint-owned P and FLOW controls."""

    endpoint_rows: Dict[str, Dict[str, Mapping[str, Any]]] = {}
    for block_name in (
        "ACGenerator",
        "DCGenerator",
        "ACLoad",
        "DCLoad",
        "HydroSource",
        "HydroLoad",
        "HydroStorage",
    ):
        endpoint_rows[block_name] = {
            str(row.get("idx", "")).strip(): row
            for row in model_rows(model, block_name)
            if str(row.get("idx", "")).strip()
        }

    result: Dict[DeviceKey, Tuple[Dict[str, Any], ...]] = {}
    for block_name in HYDROGEN_CONVERSION_BLOCKS:
        for row in model_rows(model, block_name):
            coupling_name = str(row.get("name", "")).strip()
            if not coupling_name:
                continue
            active_set_type = hydrogen_conversion_active_set_type(row.get("control_type"))
            bindings = []
            for field, endpoint_idx in row.items():
                field_name = str(field)
                if not field_name.startswith("idx_") or field_name in {"idx", "index"}:
                    continue
                endpoint_block = _coupling_endpoint_block(field_name)
                endpoint = endpoint_rows.get(endpoint_block, {}).get(
                    str(endpoint_idx).strip()
                )
                endpoint_name = str((endpoint or {}).get("name", "")).strip()
                if not endpoint_block or not endpoint_name:
                    continue
                if endpoint_block in {"ACGenerator", "DCGenerator", "ACLoad", "DCLoad"}:
                    set_type = "p_set"
                elif endpoint_block in {"HydroSource", "HydroLoad"}:
                    set_type = "flow_set"
                else:
                    continue
                bindings.append(
                    {
                        "set_type": set_type,
                        "target_dev_type": endpoint_block,
                        "target_dev_name": endpoint_name,
                        "target_set_type": set_type,
                        "active": set_type == active_set_type,
                    }
                )
            by_set_type = {binding["set_type"]: binding for binding in bindings}
            if set(by_set_type) == {"p_set", "flow_set"}:
                result[(block_name, coupling_name)] = tuple(
                    by_set_type[set_type] for set_type in ("p_set", "flow_set")
                )
    return result


def _finite_semantic_number(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _semantic_number_text(value: float) -> str:
    text = format(float(value), ".15g")
    return "0" if text in {"-0", "-0.0"} else text


def validate_hydrogen_power_setpoint_safety(
    model: Any,
    dev_type: Any,
    dev_name: Any,
    set_type: Any,
    value: Any,
) -> Dict[str, Any] | None:
    """Validate the hydrogen-side flow implied by an active electric P control.

    Electric and hydrogen endpoints own separate configured limits. A power
    setpoint can therefore be legal for its electric endpoint while its
    converted hydrogen flow is unsafe. This check resolves converter endpoints
    structurally and never relies on device-name conventions.
    """

    target_type = str(dev_type or "").strip()
    target_name = str(dev_name or "").strip()
    target_set_type = str(set_type or "").strip()
    if target_set_type != "p_set" or not target_type or not target_name:
        return None

    number = _finite_semantic_number(value)
    if number is None:
        raise ValueError(f"p_set={value!s} 不是有限数值")

    coupling_rows = {
        (block_name, str(row.get("name", "")).strip()): row
        for block_name in HYDROGEN_CONVERSION_BLOCKS
        for row in model_rows(model, block_name)
        if str(row.get("name", "")).strip()
    }
    endpoint_rows = {
        (block_name, str(row.get("name", "")).strip()): row
        for block_name in ("HydroSource", "HydroLoad")
        for row in model_rows(model, block_name)
        if str(row.get("name", "")).strip()
    }
    matches: list[tuple[DeviceKey, Mapping[str, Any], Mapping[str, Any]]] = []
    for coupling_key, bindings in energy_coupling_control_bindings(model).items():
        power_binding = next(
            (
                binding
                for binding in bindings
                if binding.get("active")
                and str(binding.get("target_set_type", binding.get("set_type", "")))
                == "p_set"
                and str(binding.get("target_dev_type", "")) == target_type
                and str(binding.get("target_dev_name", "")) == target_name
            ),
            None,
        )
        flow_binding = next(
            (
                binding
                for binding in bindings
                if str(binding.get("target_set_type", binding.get("set_type", "")))
                == "flow_set"
            ),
            None,
        )
        if power_binding is not None and flow_binding is not None:
            matches.append((coupling_key, power_binding, flow_binding))

    if not matches:
        return None
    if len(matches) != 1:
        names = ", ".join(f"{key[0]}/{key[1]}" for key, _power, _flow in matches)
        raise ValueError(
            f"{target_type}/{target_name}.p_set 同时关联多个氢能转换设备：{names}"
        )

    coupling_key, _power_binding, flow_binding = matches[0]
    coupling_type, coupling_name = coupling_key
    coupling_row = coupling_rows.get(coupling_key, {})
    if coupling_type in {"AcE2Hydro", "DcE2Hydro"}:
        coefficient_name = "e2h_coeff"
        coefficient = _finite_semantic_number(coupling_row.get(coefficient_name))
        if coefficient is None or coefficient <= 0.0:
            raise ValueError(
                f"{coupling_type}/{coupling_name} 的 {coefficient_name}="
                f"{coupling_row.get(coefficient_name, '')} 必须是大于 0 的有限数值"
            )
        flow = abs(number) * coefficient
    else:
        coefficient_name = "h2e_coeff"
        coefficient = _finite_semantic_number(coupling_row.get(coefficient_name))
        if coefficient is None or coefficient <= 0.0:
            raise ValueError(
                f"{coupling_type}/{coupling_name} 的 {coefficient_name}="
                f"{coupling_row.get(coefficient_name, '')} 必须是大于 0 的有限数值"
            )
        flow = abs(number) / coefficient

    hydrogen_type = str(flow_binding.get("target_dev_type", ""))
    hydrogen_name = str(flow_binding.get("target_dev_name", ""))
    hydrogen_row = endpoint_rows.get((hydrogen_type, hydrogen_name), {})
    flow_min = _finite_semantic_number(hydrogen_row.get("flow_min"))
    flow_max = _finite_semantic_number(hydrogen_row.get("flow_max"))
    result = {
        "coupling_type": coupling_type,
        "coupling_name": coupling_name,
        "electric_dev_type": target_type,
        "electric_dev_name": target_name,
        "p_set": number,
        "coefficient_name": coefficient_name,
        "coefficient": coefficient,
        "hydrogen_dev_type": hydrogen_type,
        "hydrogen_dev_name": hydrogen_name,
        "flow": flow,
        "flow_min": flow_min,
        "flow_max": flow_max,
    }
    if flow_min is None and flow_max is None:
        return result

    tolerance = 1e-9 * max(
        1.0,
        abs(flow),
        abs(flow_min) if flow_min is not None else 0.0,
        abs(flow_max) if flow_max is not None else 0.0,
    )
    outside_lower = flow_min is not None and flow < flow_min - tolerance
    outside_upper = flow_max is not None and flow > flow_max + tolerance
    if outside_lower or outside_upper:
        bounds = []
        if flow_min is not None:
            bounds.append(f"flow_min={_semantic_number_text(flow_min)}")
        if flow_max is not None:
            bounds.append(f"flow_max={_semantic_number_text(flow_max)}")
        raise ValueError(
            f"{coupling_type}/{coupling_name} 将 {target_type}/{target_name} 的 "
            f"p_set={_semantic_number_text(number)} 按 {coefficient_name}="
            f"{_semantic_number_text(coefficient)} 换算为氢流量 "
            f"{_semantic_number_text(flow)} Nm3/h，超出 "
            f"{hydrogen_type}/{hydrogen_name} 的 {', '.join(bounds)}"
        )
    return result


def structured_resources(model: Any) -> Tuple[StructuredResource, ...]:
    sources_by_index: Dict[str, Dict[str, Mapping[str, Any]]] = {}
    for source_block in {spec.source_block for spec in RESOURCE_RELATION_SPECS}:
        sources_by_index[source_block] = {
            str(row.get("idx", "")).strip(): row
            for row in model_rows(model, source_block)
            if str(row.get("idx", "")).strip()
        }

    candidates: Dict[Tuple[str, str], list[StructuredResource]] = {}
    for spec in RESOURCE_RELATION_SPECS:
        for parameter in model_rows(model, spec.parameter_block):
            source_index = str(parameter.get(spec.source_index_field, "")).strip()
            source = sources_by_index[spec.source_block].get(source_index)
            if source is None:
                continue
            source_name = str(source.get("name", "")).strip()
            source_key = (spec.source_block, source_index)
            if not source_name:
                continue
            candidates.setdefault(source_key, []).append(
                StructuredResource(
                    technology=spec.technology,
                    parameter_block=spec.parameter_block,
                    parameter_index=str(parameter.get("idx", "")).strip(),
                    source_block=spec.source_block,
                    source_index=source_index,
                    source_name=source_name,
                    parameter=parameter,
                    source=source,
                )
            )
    return tuple(
        rows[0]
        for rows in candidates.values()
        if len(rows) == 1
    )


def resource_aliases(resource: StructuredResource) -> Tuple[str, ...]:
    """Return explicit identifiers declared by the resource relation."""
    aliases = []
    for value in (
        resource.source_name,
        resource.parameter.get("name"),
        resource.parameter.get("source_name"),
        resource.parameter.get("dev_name"),
    ):
        normalized = str(value or "").strip()
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    return tuple(aliases)


def resource_keys_by_alias(
    model: Any,
    technologies: Iterable[str] = (),
) -> Dict[str, set[DeviceKey]]:
    selected = {str(value) for value in technologies}
    aliases: Dict[str, set[DeviceKey]] = {}
    for resource in structured_resources(model):
        if selected and resource.technology not in selected:
            continue
        for alias in resource_aliases(resource):
            aliases.setdefault(alias, set()).add(resource.device_key)
    return aliases


def resources_by_device_key(model: Any) -> Dict[DeviceKey, StructuredResource]:
    return {resource.device_key: resource for resource in structured_resources(model)}


def resource_device_keys(model: Any, technologies: Iterable[str] = ()) -> set[DeviceKey]:
    selected = {str(value) for value in technologies}
    return {
        resource.device_key
        for resource in structured_resources(model)
        if not selected or resource.technology in selected
    }


def resolve_resource_reference(
    resources: Sequence[StructuredResource],
    row: Mapping[str, Any],
) -> DeviceKey | None:
    """Resolve a runtime/control row to one structured resource.

    ``dev_type`` and ``name`` remain protocol identifiers.  They are accepted
    only as exact source identities or explicit aliases; index matching uses
    the source and parameter-table references and fails closed on ambiguity.
    """
    dev_type = str(row.get("dev_type", "")).strip()
    name = str(row.get("name", row.get("dev_name", ""))).strip()
    index = str(row.get("idx", "")).strip()

    exact = {
        resource.device_key
        for resource in resources
        if dev_type == resource.source_block and name == resource.source_name
    }
    if len(exact) == 1:
        return next(iter(exact))

    typed_index = {
        resource.device_key
        for resource in resources
        if index
        and (
            (dev_type == resource.source_block and index == resource.source_index)
            or (dev_type == resource.parameter_block and index == resource.parameter_index)
        )
    }
    if len(typed_index) == 1:
        return next(iter(typed_index))

    indexed = {
        resource.device_key
        for resource in resources
        if index and index in {resource.source_index, resource.parameter_index}
    }
    if len(indexed) == 1:
        return next(iter(indexed))

    aliased = {
        resource.device_key
        for resource in resources
        if name and name in resource_aliases(resource)
    }
    return next(iter(aliased)) if len(aliased) == 1 else None


class _UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[Tuple[str, str], Tuple[str, str]] = {}

    def add(self, item: Tuple[str, str]) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: Tuple[str, str]) -> Tuple[str, str]:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: Tuple[str, str], right: Tuple[str, str]) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _node_key(domain: str, value: Any) -> Tuple[str, str] | None:
    node = str(value if value is not None else "").strip()
    return (domain, node) if node else None


def grid_converter_keys(model: Any) -> set[DeviceKey]:
    """Return converters whose AC and DC terminals both reach real busbars."""
    graph = _UnionFind()
    for block_name, domain in SAME_DOMAIN_EDGE_SPECS:
        for row in model_rows(model, block_name):
            left = _node_key(domain, row.get("i_node"))
            right = _node_key(domain, row.get("j_node"))
            if left is not None and right is not None:
                graph.union(left, right)

    anchored_roots: Dict[str, set[Tuple[str, str]]] = {"AC": set(), "DC": set()}
    for block_name, domain in (("ACRealBs", "AC"), ("DCRealBs", "DC")):
        for row in model_rows(model, block_name):
            node = _node_key(domain, row.get("node"))
            if node is not None:
                anchored_roots[domain].add(graph.find(node))

    keys: set[DeviceKey] = set()
    for block_name in CROSS_DOMAIN_CONVERTER_BLOCKS:
        for row in model_rows(model, block_name):
            name = str(row.get("name", "")).strip()
            ac_node = _node_key("AC", row.get("ac_node"))
            dc_node = _node_key("DC", row.get("dc_node"))
            if not name or ac_node is None or dc_node is None:
                continue
            if (
                graph.find(ac_node) in anchored_roots["AC"]
                and graph.find(dc_node) in anchored_roots["DC"]
            ):
                keys.add((block_name, name))
    return keys


def device_family_from_block(block_name: Any) -> str:
    normalized = str(block_name or "").strip()
    if normalized in {"ACGenerator", "DCGenerator", "HydroSource"}:
        return "generator"
    if normalized in {"ACLoad", "DCLoad", "HydroLoad"}:
        return "load"
    if normalized in {
        "ACDCConverter",
        "DCACConverter",
        "ACACConverter",
        "DCDCConverter",
        *HYDROGEN_CONVERSION_BLOCKS,
    }:
        return "converter"
    if normalized in {"ACBreak", "DCBreak", "ACSwitch", "DCSwitch"}:
        return "switch"
    if normalized == "Environment":
        return "environment"
    return "device"


def terminal_domains_from_block(block_name: Any) -> Tuple[str, ...]:
    normalized = str(block_name or "").strip()
    if normalized in {"ACDCConverter", "DCACConverter"}:
        return "AC", "DC"
    if normalized == "AcE2Hydro":
        return "AC", "HYDRO"
    if normalized == "DcE2Hydro":
        return "DC", "HYDRO"
    if normalized == "Hydro2AcE":
        return "HYDRO", "AC"
    if normalized == "Hydro2DcE":
        return "HYDRO", "DC"
    if normalized.startswith("Hydro"):
        return ("HYDRO",)
    if normalized.startswith("AC"):
        return ("AC",)
    if normalized.startswith("DC"):
        return ("DC",)
    return ()
