"""Model semantics derived from block structure, references, and topology.

Device names and row-level ``dev_type`` values are identifiers or descriptive
metadata only. Runtime technology and converter-boundary decisions must come
from parameter-table references and terminal connectivity.
"""

from __future__ import annotations

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
    if normalized in {"ACGenerator", "DCGenerator"}:
        return "generator"
    if normalized in {"ACLoad", "DCLoad"}:
        return "load"
    if normalized in {"ACDCConverter", "DCACConverter", "ACACConverter", "DCDCConverter"}:
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
    if normalized.startswith("AC"):
        return ("AC",)
    if normalized.startswith("DC"):
        return ("DC",)
    return ()
