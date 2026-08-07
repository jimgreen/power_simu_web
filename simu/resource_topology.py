from __future__ import annotations

import hashlib
import heapq
import json
import math
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Dict, Mapping, Sequence, Tuple


NodeKey = Tuple[str, str]
DeviceKey = Tuple[str, str]


@dataclass(frozen=True)
class ResourceRef:
    technology: str
    dev_type: str
    dev_name: str


@dataclass(frozen=True)
class ResourceConnection:
    technology: str
    dev_type: str
    dev_name: str
    connection_side: str
    actively_connected: bool
    busbar_type: str = ""
    busbar_name: str = ""
    busbar_node: str = ""
    structural_path: Tuple[DeviceKey, ...] = ()
    active_path: Tuple[DeviceKey, ...] = ()
    converter_path: Tuple[DeviceKey, ...] = ()
    grid_component_id: str = ""
    dc_transfer_group_id: str = ""
    topology_status_label: str = ""


@dataclass(frozen=True)
class DcTransferGroup:
    group_id: str
    dc_nodes: Tuple[str, ...]
    converter_keys: Tuple[DeviceKey, ...]
    ac_component_ids: Tuple[str, ...]


@dataclass(frozen=True)
class ResourceTopology:
    resources: Mapping[DeviceKey, ResourceConnection]
    dc_transfer_groups: Mapping[str, DcTransferGroup]
    # Component ids are derived for all terminal devices in the single graph
    # pass.  This lets callers inspect non-dispatchable balance devices (such
    # as diesel generators) without resolving the topology a second time.
    device_component_ids: Mapping[DeviceKey, str] = field(
        default_factory=lambda: MappingProxyType({})
    )


RESOURCE_TERMINALS = {
    "ACGenerator": ("AC", "node"),
    "DCGenerator": ("DC", "node"),
}

SAME_DOMAIN_EDGES = {
    "ACBranch": ("AC", "i_node", "j_node", False),
    "ACTransformer": ("AC", "i_node", "j_node", False),
    "ACZeroBranch": ("AC", "i_node", "j_node", True),
    "ACSwitch": ("AC", "i_node", "j_node", True),
    "ACBreak": ("AC", "i_node", "j_node", True),
    "DCBranch": ("DC", "i_node", "j_node", False),
    "DCZeroBranch": ("DC", "i_node", "j_node", True),
    "DCSwitch": ("DC", "i_node", "j_node", True),
    "DCBreak": ("DC", "i_node", "j_node", True),
    "ACACConverter": ("AC", "i_node", "j_node", False),
    "DCDCConverter": ("DC", "i_node", "j_node", False),
}

CROSS_DOMAIN_EDGES = {
    "DCACConverter": (("AC", "ac_node"), ("DC", "dc_node")),
}

REAL_BUSBARS = {
    "ACRealBs": ("AC", "node"),
    "DCRealBs": ("DC", "node"),
}


_NODE_BLOCKS = {
    "ACNode": "AC",
    "DCNode": "DC",
}
_CONVERTER_TYPES = frozenset(
    {"ACACConverter", "DCDCConverter", "DCACConverter"}
)
_SWITCHLIKE_TYPES = frozenset(
    dev_type
    for dev_type, (*_, switchlike) in SAME_DOMAIN_EDGES.items()
    if switchlike
)
_STATUS_LABELS = {
    "AC": "结构接入交流母线",
    "DC": "结构接入直流母线",
    "AMBIGUOUS": "交流/直流真实母线路径等价，拓扑歧义",
    "UNRESOLVED": "未找到可达真实母线",
    "INVALID": "资源模型引用或端子无效",
}
_Cost = Tuple[int, int]


@dataclass(frozen=True)
class _Edge:
    neighbor: NodeKey
    device_key: DeviceKey
    cost: _Cost


@dataclass(frozen=True)
class _Anchor:
    domain: str
    busbar_type: str
    busbar_name: str
    busbar_node: str


@dataclass(frozen=True)
class _AnchorPath:
    cost: _Cost
    busbar_type: str
    busbar_name: str
    busbar_node: str
    path: Tuple[DeviceKey, ...]

    def rank(self) -> Tuple[object, ...]:
        return (
            self.cost,
            self.busbar_type,
            self.busbar_name,
            self.busbar_node,
            self.path,
        )


@dataclass(frozen=True)
class _ParsedModel:
    model: Mapping[str, object]
    declared_nodes: frozenset[NodeKey]
    model_rows: Mapping[DeviceKey, Mapping[str, object]]
    node_rows: Mapping[NodeKey, Mapping[str, object]]
    resource_rows: Mapping[DeviceKey, Mapping[str, object]]
    anchors: Mapping[NodeKey, Tuple[_Anchor, ...]]


@dataclass(frozen=True)
class _StructuralGraph:
    adjacency: Mapping[NodeKey, Tuple[_Edge, ...]]
    invalid_converter_nodes: frozenset[NodeKey]


@dataclass(frozen=True)
class _OperatingState:
    run_stat: float
    status: float
    dead_island: bool


@dataclass(frozen=True)
class _ActiveGraph:
    adjacency: Mapping[NodeKey, Tuple[_Edge, ...]]
    active_nodes: frozenset[NodeKey]
    active_anchors: Mapping[NodeKey, Tuple[_Anchor, ...]]


@dataclass(frozen=True)
class _ActiveComponents:
    node_component_ids: Mapping[NodeKey, str]
    nodes_by_component_id: Mapping[str, Tuple[NodeKey, ...]]


@dataclass(frozen=True)
class _AnchorObjective:
    cost: _Cost
    busbar_type: str
    busbar_name: str
    busbar_node: str

    def rank(self) -> Tuple[object, ...]:
        return (
            self.cost,
            self.busbar_type,
            self.busbar_name,
            self.busbar_node,
        )


def _model_blocks(snapshot: Mapping[str, object]) -> Mapping[str, object]:
    definitions = snapshot.get("definitions")
    if not isinstance(definitions, Mapping):
        return {}
    model = definitions.get("model")
    return model if isinstance(model, Mapping) else {}


def _block_rows(
    model: Mapping[str, object], block_name: str
) -> Tuple[Mapping[str, object], ...]:
    block = model.get(block_name)
    if not isinstance(block, Mapping):
        return ()
    rows = block.get("rows")
    if not isinstance(rows, (list, tuple)):
        return ()
    return tuple(row for row in rows if isinstance(row, Mapping))


def _node_id(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    return normalized if normalized.strip() else None


def _device_name(row: Mapping[str, object]) -> str | None:
    name = row.get("name")
    return name if isinstance(name, str) and name else None


def _runtime_device_name(row: Mapping[str, object]) -> str | None:
    for field in ("dev_name", "name"):
        name = row.get(field)
        if isinstance(name, str) and name:
            return name
    return None


def _row_rank(row: Mapping[str, object]) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((str(key), repr(value)) for key, value in row.items()))


def _parse_model(snapshot: Mapping[str, object]) -> _ParsedModel:
    model = _model_blocks(snapshot)
    declared_nodes = set()
    node_candidates: Dict[NodeKey, list[Mapping[str, object]]] = {}
    for block_name, domain in _NODE_BLOCKS.items():
        for row in _block_rows(model, block_name):
            node_id = _node_id(row.get("idx"))
            if node_id is not None:
                node_key = (domain, node_id)
                declared_nodes.add(node_key)
                node_candidates.setdefault(node_key, []).append(row)

    node_rows = {
        node_key: min(rows, key=_row_rank)
        for node_key, rows in node_candidates.items()
    }

    model_candidates: Dict[DeviceKey, list[Mapping[str, object]]] = {}
    for block_name in sorted(model):
        for row in _block_rows(model, block_name):
            dev_name = _device_name(row)
            if dev_name is not None:
                model_candidates.setdefault((block_name, dev_name), []).append(row)
    model_rows = {
        device_key: min(rows, key=_row_rank)
        for device_key, rows in model_candidates.items()
    }

    resource_candidates: Dict[DeviceKey, list[Mapping[str, object]]] = {}
    for dev_type in RESOURCE_TERMINALS:
        for row in _block_rows(model, dev_type):
            dev_name = _device_name(row)
            if dev_name is not None:
                resource_candidates.setdefault((dev_type, dev_name), []).append(row)

    resource_rows: Dict[DeviceKey, Mapping[str, object]] = {}
    for device_key, rows in resource_candidates.items():
        terminal_field = RESOURCE_TERMINALS[device_key[0]][1]
        resource_rows[device_key] = min(
            rows,
            key=lambda row: _node_id(row.get(terminal_field)) or "",
        )

    anchors: Dict[NodeKey, list[_Anchor]] = {}
    for busbar_type, (domain, terminal_field) in REAL_BUSBARS.items():
        for row in _block_rows(model, busbar_type):
            busbar_name = _device_name(row)
            busbar_node = _node_id(row.get(terminal_field))
            node_key = (domain, busbar_node) if busbar_node is not None else None
            if (
                busbar_name is None
                or node_key is None
                or node_key not in declared_nodes
            ):
                continue
            anchors.setdefault(node_key, []).append(
                _Anchor(
                    domain=domain,
                    busbar_type=busbar_type,
                    busbar_name=busbar_name,
                    busbar_node=busbar_node,
                )
            )

    sorted_anchors = {
        node_key: tuple(
            sorted(
                node_anchors,
                key=lambda anchor: (
                    anchor.busbar_type,
                    anchor.busbar_name,
                    anchor.busbar_node,
                ),
            )
        )
        for node_key, node_anchors in anchors.items()
    }
    return _ParsedModel(
        model=model,
        declared_nodes=frozenset(declared_nodes),
        model_rows=MappingProxyType(model_rows),
        node_rows=MappingProxyType(node_rows),
        resource_rows=MappingProxyType(resource_rows),
        anchors=MappingProxyType(sorted_anchors),
    )


def _finite_number(value: object, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _boolean(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    number = _finite_number(value)
    if number is not None:
        return number != 0.0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on"}:
            return True
        if normalized in {"false", "no", "off", ""}:
            return False
    return default


def _state_from_model_row(row: Mapping[str, object]) -> _OperatingState:
    return _OperatingState(
        run_stat=_finite_number(row.get("run_stat"), 1.0) or 0.0,
        status=_finite_number(row.get("status"), 1.0) or 0.0,
        dead_island=_boolean(row.get("dead_island"), False),
    )


def _runtime_rows(
    snapshot: Mapping[str, object], field: str
) -> Tuple[Mapping[str, object], ...]:
    rows = snapshot.get(field)
    if not isinstance(rows, (list, tuple)):
        return ()
    return tuple(row for row in rows if isinstance(row, Mapping))


def _runtime_row_key(row: Mapping[str, object]) -> DeviceKey | None:
    dev_type = row.get("dev_type")
    dev_name = _runtime_device_name(row)
    if not isinstance(dev_type, str) or not dev_type or dev_name is None:
        return None
    return (dev_type, dev_name)


def _overlay_runtime_rows(
    states: Dict[DeviceKey, _OperatingState],
    rows: Sequence[Mapping[str, object]],
    *,
    include_status: bool,
) -> None:
    for row in sorted(rows, key=lambda item: (_runtime_row_key(item) or ("", ""), _row_rank(item))):
        device_key = _runtime_row_key(row)
        if device_key is None or device_key not in states:
            continue
        current = states[device_key]
        run_stat = current.run_stat
        status = current.status
        dead_island = current.dead_island
        if "run_stat" in row:
            run_stat = _finite_number(row.get("run_stat"), run_stat) or 0.0
        if include_status and "status" in row:
            status = _finite_number(row.get("status"), status) or 0.0
        if "dead_island" in row:
            dead_island = _boolean(row.get("dead_island"), dead_island)
        states[device_key] = _OperatingState(
            run_stat=run_stat,
            status=status,
            dead_island=dead_island,
        )


def _measurement_values(
    snapshot: Mapping[str, object],
) -> Mapping[Tuple[str, str, str], float]:
    measurements = snapshot.get("measurements")
    if not isinstance(measurements, Mapping):
        return {}
    values: Dict[Tuple[str, str, str], float] = {}
    for source in ("scada", "real"):
        rows = measurements.get(source)
        if not isinstance(rows, (list, tuple)):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            valid = _finite_number(row.get("valid"))
            value = _finite_number(row.get("value"))
            dev_type = row.get("dev_type")
            dev_name = row.get("dev_name")
            meas_type = str(row.get("meas_type", "")).upper()
            if (
                valid != 1.0
                or value is None
                or not isinstance(dev_type, str)
                or not dev_type
                or not isinstance(dev_name, str)
                or not dev_name
                or meas_type not in {"RUN_STAT", "STATUS"}
            ):
                continue
            values.setdefault((dev_type, dev_name, meas_type), value)
    return MappingProxyType(values)


def _operating_states(
    snapshot: Mapping[str, object], parsed: _ParsedModel
) -> Mapping[DeviceKey, _OperatingState]:
    states = {
        device_key: _state_from_model_row(row)
        for device_key, row in parsed.model_rows.items()
    }
    _overlay_runtime_rows(
        states,
        _runtime_rows(snapshot, "device_states"),
        include_status=True,
    )
    _overlay_runtime_rows(
        states,
        _runtime_rows(snapshot, "devices"),
        include_status=True,
    )
    for (dev_type, dev_name, meas_type), value in _measurement_values(
        snapshot
    ).items():
        device_key = (dev_type, dev_name)
        current = states.get(device_key)
        if current is None:
            continue
        states[device_key] = replace(
            current,
            **(
                {"run_stat": value}
                if meas_type == "RUN_STAT"
                else {"status": value}
            ),
        )
    return MappingProxyType(states)


def _row_state(
    dev_type: str,
    row: Mapping[str, object],
    states: Mapping[DeviceKey, _OperatingState],
) -> _OperatingState:
    dev_name = _device_name(row)
    if dev_name is not None:
        state = states.get((dev_type, dev_name))
        if state is not None:
            return state
    return _state_from_model_row(row)


def _is_active_state(state: _OperatingState, *, switchlike: bool = False) -> bool:
    return (
        state.run_stat == 1.0
        and not state.dead_island
        and (not switchlike or state.status != 0.0)
    )


def _device_is_active(
    device_key: DeviceKey,
    parsed: _ParsedModel,
    states: Mapping[DeviceKey, _OperatingState],
) -> bool:
    row = parsed.model_rows.get(device_key)
    if row is None:
        return False
    return _is_active_state(
        _row_state(device_key[0], row, states),
        switchlike=device_key[0] in _SWITCHLIKE_TYPES,
    )


def _add_undirected_edge(
    adjacency: Dict[NodeKey, list[_Edge]],
    left: NodeKey,
    right: NodeKey,
    device_key: DeviceKey,
    cost: _Cost,
) -> None:
    adjacency.setdefault(left, []).append(_Edge(right, device_key, cost))
    adjacency.setdefault(right, []).append(_Edge(left, device_key, cost))


def _build_structural_graph(parsed: _ParsedModel) -> _StructuralGraph:
    adjacency: Dict[NodeKey, list[_Edge]] = {}
    invalid_converter_nodes = set()

    for dev_type, (domain, left_field, right_field, switchlike) in (
        SAME_DOMAIN_EDGES.items()
    ):
        cost = (0, 0) if switchlike else (0, 1)
        for row in _block_rows(parsed.model, dev_type):
            dev_name = _device_name(row)
            left_id = _node_id(row.get(left_field))
            right_id = _node_id(row.get(right_field))
            if dev_name is None or left_id is None or right_id is None:
                continue
            left = (domain, left_id)
            right = (domain, right_id)
            if left not in parsed.declared_nodes or right not in parsed.declared_nodes:
                continue
            _add_undirected_edge(
                adjacency,
                left,
                right,
                (dev_type, dev_name),
                cost,
            )

    for dev_type, (left_terminal, right_terminal) in CROSS_DOMAIN_EDGES.items():
        left_domain, left_field = left_terminal
        right_domain, right_field = right_terminal
        for row in _block_rows(parsed.model, dev_type):
            dev_name = _device_name(row)
            if dev_name is None:
                continue
            left_id = _node_id(row.get(left_field))
            right_id = _node_id(row.get(right_field))
            left = (left_domain, left_id) if left_id is not None else None
            right = (right_domain, right_id) if right_id is not None else None
            left_valid = left is not None and left in parsed.declared_nodes
            right_valid = right is not None and right in parsed.declared_nodes
            if not left_valid or not right_valid:
                if left_valid:
                    invalid_converter_nodes.add(left)
                if right_valid:
                    invalid_converter_nodes.add(right)
                continue
            _add_undirected_edge(
                adjacency,
                left,
                right,
                (dev_type, dev_name),
                (1, 1),
            )

    sorted_adjacency = {
        node_key: tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.device_key,
                    edge.neighbor,
                    edge.cost,
                ),
            )
        )
        for node_key, edges in adjacency.items()
    }
    return _StructuralGraph(
        adjacency=MappingProxyType(sorted_adjacency),
        invalid_converter_nodes=frozenset(invalid_converter_nodes),
    )


def _active_node_keys(
    parsed: _ParsedModel,
    states: Mapping[DeviceKey, _OperatingState],
) -> frozenset[NodeKey]:
    active_nodes = set()
    for node_key, row in parsed.node_rows.items():
        dev_type = f"{node_key[0]}Node"
        if _is_active_state(_row_state(dev_type, row, states)):
            active_nodes.add(node_key)
    return frozenset(active_nodes)


def _build_active_graph(
    parsed: _ParsedModel,
    structural_graph: _StructuralGraph,
    states: Mapping[DeviceKey, _OperatingState],
) -> _ActiveGraph:
    active_nodes = _active_node_keys(parsed, states)
    adjacency: Dict[NodeKey, list[_Edge]] = {}
    for node_key in sorted(active_nodes):
        for edge in structural_graph.adjacency.get(node_key, ()):
            if edge.neighbor not in active_nodes:
                continue
            if not _device_is_active(edge.device_key, parsed, states):
                continue
            adjacency.setdefault(node_key, []).append(edge)

    active_anchors: Dict[NodeKey, Tuple[_Anchor, ...]] = {}
    for node_key, anchors in parsed.anchors.items():
        if node_key not in active_nodes:
            continue
        available = tuple(
            anchor
            for anchor in anchors
            if _device_is_active(
                (anchor.busbar_type, anchor.busbar_name),
                parsed,
                states,
            )
        )
        if available:
            active_anchors[node_key] = available

    sorted_adjacency = {
        node_key: tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.device_key,
                    edge.neighbor,
                    edge.cost,
                ),
            )
        )
        for node_key, edges in adjacency.items()
    }
    return _ActiveGraph(
        adjacency=MappingProxyType(sorted_adjacency),
        active_nodes=active_nodes,
        active_anchors=MappingProxyType(active_anchors),
    )


def _component_payload(domain: str, node_ids: Sequence[str]) -> bytes:
    return json.dumps(
        {"domain": domain, "nodes": list(node_ids)},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _component_id(domain: str, payload: bytes) -> str:
    return f"{domain}:{hashlib.sha256(payload).hexdigest()}"


def _build_active_components(active_graph: _ActiveGraph) -> _ActiveComponents:
    same_domain_neighbors: Dict[NodeKey, set[NodeKey]] = {
        node_key: set() for node_key in active_graph.active_nodes
    }
    for node_key, edges in active_graph.adjacency.items():
        for edge in edges:
            if edge.neighbor[0] == node_key[0]:
                same_domain_neighbors[node_key].add(edge.neighbor)

    node_component_ids: Dict[NodeKey, str] = {}
    nodes_by_component_id: Dict[str, Tuple[NodeKey, ...]] = {}
    payloads_by_component_id: Dict[str, bytes] = {}
    unseen = set(active_graph.active_nodes)
    while unseen:
        start = min(unseen)
        pending = [start]
        component_nodes = set()
        while pending:
            node_key = pending.pop()
            if node_key in component_nodes:
                continue
            component_nodes.add(node_key)
            unseen.discard(node_key)
            pending.extend(
                sorted(
                    same_domain_neighbors.get(node_key, ()),
                    reverse=True,
                )
            )
        ordered_nodes = tuple(sorted(component_nodes))
        domain = ordered_nodes[0][0]
        component_payload = _component_payload(
            domain,
            tuple(node_id for _, node_id in ordered_nodes),
        )
        component_id = _component_id(domain, component_payload)
        existing_payload = payloads_by_component_id.get(component_id)
        if existing_payload is not None and existing_payload != component_payload:
            raise ValueError(f"active component id collision: {component_id}")
        payloads_by_component_id[component_id] = component_payload
        nodes_by_component_id[component_id] = ordered_nodes
        for node_key in ordered_nodes:
            node_component_ids[node_key] = component_id

    return _ActiveComponents(
        node_component_ids=MappingProxyType(node_component_ids),
        nodes_by_component_id=MappingProxyType(
            dict(sorted(nodes_by_component_id.items()))
        ),
    )


def _build_domain_anchor_index(
    adjacency: Mapping[NodeKey, Tuple[_Edge, ...]],
    anchors: Mapping[NodeKey, Tuple[_Anchor, ...]],
    barrier_nodes: frozenset[NodeKey],
    target_domain: str,
) -> Mapping[NodeKey, _AnchorPath]:
    graph_nodes = set(adjacency)
    graph_nodes.update(
        edge.neighbor
        for edges in adjacency.values()
        for edge in edges
    )
    graph_nodes.difference_update(barrier_nodes)

    zero_neighbors: Dict[NodeKey, list[NodeKey]] = {
        node_key: [] for node_key in graph_nodes
    }
    for node_key in sorted(graph_nodes):
        for edge in adjacency.get(node_key, ()):
            if edge.neighbor in graph_nodes and edge.cost == (0, 0):
                zero_neighbors[node_key].append(edge.neighbor)

    component_by_node: Dict[NodeKey, int] = {}
    nodes_by_component: Dict[int, Tuple[NodeKey, ...]] = {}
    unseen = set(graph_nodes)
    while unseen:
        start = min(unseen)
        pending = [start]
        component_nodes = set()
        while pending:
            node_key = pending.pop()
            if node_key in component_nodes:
                continue
            component_nodes.add(node_key)
            unseen.discard(node_key)
            pending.extend(
                sorted(zero_neighbors.get(node_key, ()), reverse=True)
            )
        component_id = len(nodes_by_component)
        ordered_nodes = tuple(sorted(component_nodes))
        nodes_by_component[component_id] = ordered_nodes
        for node_key in ordered_nodes:
            component_by_node[node_key] = component_id

    portals_by_component: Dict[int, Tuple[Tuple[NodeKey, _Edge], ...]] = {}
    internal_edges: Dict[NodeKey, Tuple[_Edge, ...]] = {}
    for component_id, component_nodes in nodes_by_component.items():
        portals = []
        for node_key in component_nodes:
            internal = []
            for edge in adjacency.get(node_key, ()):
                if component_by_node.get(edge.neighbor) == component_id:
                    if edge.cost == (0, 0):
                        internal.append(edge)
                    continue
                portals.append((node_key, edge))
            internal_edges[node_key] = tuple(
                sorted(
                    internal,
                    key=lambda edge: (edge.device_key, edge.neighbor),
                )
            )
        portals_by_component[component_id] = tuple(
            sorted(
                portals,
                key=lambda item: (
                    item[0],
                    item[1].device_key,
                    item[1].neighbor,
                    item[1].cost,
                ),
            )
        )

    def extend_objective(
        objective: _AnchorObjective,
        edge_cost: _Cost,
    ) -> _AnchorObjective:
        return _AnchorObjective(
            cost=(
                objective.cost[0] + edge_cost[0],
                objective.cost[1] + edge_cost[1],
            ),
            busbar_type=objective.busbar_type,
            busbar_name=objective.busbar_name,
            busbar_node=objective.busbar_node,
        )

    component_objectives: Dict[int, _AnchorObjective] = {}
    queue: list[Tuple[Tuple[object, ...], int]] = []

    def update_objective(
        component_id: int,
        candidate: _AnchorObjective,
    ) -> None:
        current = component_objectives.get(component_id)
        if current is not None and current.rank() <= candidate.rank():
            return
        component_objectives[component_id] = candidate
        heapq.heappush(queue, (candidate.rank(), component_id))

    for component_id, portals in portals_by_component.items():
        for _, edge in portals:
            if edge.neighbor not in barrier_nodes:
                continue
            for anchor in anchors.get(edge.neighbor, ()):
                if anchor.domain != target_domain:
                    continue
                update_objective(
                    component_id,
                    _AnchorObjective(
                        cost=edge.cost,
                        busbar_type=anchor.busbar_type,
                        busbar_name=anchor.busbar_name,
                        busbar_node=anchor.busbar_node,
                    ),
                )

    while queue:
        objective_rank, component_id = heapq.heappop(queue)
        objective = component_objectives.get(component_id)
        if objective is None or objective.rank() != objective_rank:
            continue
        for _, edge in portals_by_component.get(component_id, ()):
            if edge.neighbor in barrier_nodes:
                continue
            neighbor_component = component_by_node.get(edge.neighbor)
            if neighbor_component is None or neighbor_component == component_id:
                continue
            update_objective(
                neighbor_component,
                extend_objective(objective, edge.cost),
            )

    indexed_paths: Dict[NodeKey, _AnchorPath] = {}
    for node_key in sorted(barrier_nodes):
        matching = tuple(
            anchor
            for anchor in anchors.get(node_key, ())
            if anchor.domain == target_domain
        )
        if not matching:
            continue
        anchor = min(
            matching,
            key=lambda item: (
                item.busbar_type,
                item.busbar_name,
                item.busbar_node,
            ),
        )
        indexed_paths[node_key] = _AnchorPath(
            cost=(0, 0),
            busbar_type=anchor.busbar_type,
            busbar_name=anchor.busbar_name,
            busbar_node=anchor.busbar_node,
            path=(),
        )

    def can_reach_exit(
        start: NodeKey,
        blocked: frozenset[NodeKey],
        exit_nodes: frozenset[NodeKey],
    ) -> bool:
        pending = [start]
        seen = set(blocked)
        while pending:
            node_key = pending.pop()
            if node_key in seen:
                continue
            if node_key in exit_nodes:
                return True
            seen.add(node_key)
            pending.extend(
                edge.neighbor
                for edge in reversed(internal_edges.get(node_key, ()))
                if edge.neighbor not in seen
            )
        return False

    def canonical_path(
        source: NodeKey,
        objective: _AnchorObjective,
        exits: Mapping[NodeKey, Tuple[_AnchorPath, ...]],
    ) -> _AnchorPath | None:
        exit_nodes = frozenset(exits)
        current = source
        visited = {source}
        prefix: list[DeviceKey] = []
        while True:
            actions = []
            for option in exits.get(current, ()):
                if option.path:
                    actions.append(
                        (
                            (option.path[0], 0, option.path),
                            "exit",
                            option,
                        )
                    )
            blocked = frozenset(visited)
            for edge in internal_edges.get(current, ()):
                if edge.neighbor in visited:
                    continue
                if not can_reach_exit(edge.neighbor, blocked, exit_nodes):
                    continue
                actions.append(
                    (
                        (edge.device_key, 1, edge.neighbor),
                        "edge",
                        edge,
                    )
                )
            if not actions:
                return None
            _, action_type, payload = min(actions, key=lambda item: item[0])
            if action_type == "exit":
                option = payload
                return _AnchorPath(
                    cost=objective.cost,
                    busbar_type=option.busbar_type,
                    busbar_name=option.busbar_name,
                    busbar_node=option.busbar_node,
                    path=tuple(prefix) + option.path,
                )
            edge = payload
            prefix.append(edge.device_key)
            current = edge.neighbor
            visited.add(current)

    ordered_components = sorted(
        component_objectives,
        key=lambda component_id: (
            component_objectives[component_id].rank(),
            component_id,
        ),
    )
    for component_id in ordered_components:
        objective = component_objectives[component_id]
        exit_candidates: Dict[NodeKey, list[_AnchorPath]] = {}
        for inside_node, edge in portals_by_component.get(component_id, ()):
            if edge.neighbor in barrier_nodes:
                for anchor in anchors.get(edge.neighbor, ()):
                    if anchor.domain != target_domain:
                        continue
                    candidate_objective = _AnchorObjective(
                        cost=edge.cost,
                        busbar_type=anchor.busbar_type,
                        busbar_name=anchor.busbar_name,
                        busbar_node=anchor.busbar_node,
                    )
                    if candidate_objective != objective:
                        continue
                    exit_candidates.setdefault(inside_node, []).append(
                        _AnchorPath(
                            cost=objective.cost,
                            busbar_type=anchor.busbar_type,
                            busbar_name=anchor.busbar_name,
                            busbar_node=anchor.busbar_node,
                            path=(edge.device_key,),
                        )
                    )
                continue

            neighbor_component = component_by_node.get(edge.neighbor)
            neighbor_objective = component_objectives.get(neighbor_component)
            neighbor_path = indexed_paths.get(edge.neighbor)
            if neighbor_objective is None or neighbor_path is None:
                continue
            if extend_objective(neighbor_objective, edge.cost) != objective:
                continue
            exit_candidates.setdefault(inside_node, []).append(
                _AnchorPath(
                    cost=objective.cost,
                    busbar_type=neighbor_path.busbar_type,
                    busbar_name=neighbor_path.busbar_name,
                    busbar_node=neighbor_path.busbar_node,
                    path=(edge.device_key,) + neighbor_path.path,
                )
            )

        exits = {
            node_key: tuple(sorted(set(options), key=lambda item: item.rank()))
            for node_key, options in exit_candidates.items()
        }
        for node_key in nodes_by_component[component_id]:
            path = canonical_path(node_key, objective, exits)
            if path is not None:
                indexed_paths[node_key] = path

    return MappingProxyType(dict(sorted(indexed_paths.items())))


def _build_reverse_anchor_indexes(
    adjacency: Mapping[NodeKey, Tuple[_Edge, ...]],
    anchors: Mapping[NodeKey, Tuple[_Anchor, ...]],
    barrier_nodes: Sequence[NodeKey],
) -> Mapping[str, Mapping[NodeKey, _AnchorPath]]:
    locked_nodes = frozenset(barrier_nodes)
    return MappingProxyType(
        {
            domain: _build_domain_anchor_index(
                adjacency,
                anchors,
                locked_nodes,
                domain,
            )
            for domain in ("AC", "DC")
        }
    )


def _anchor_paths_for_node(
    indexes: Mapping[str, Mapping[NodeKey, _AnchorPath]],
    node_key: NodeKey,
) -> Mapping[str, _AnchorPath]:
    return MappingProxyType(
        {
            domain: anchor_path
            for domain in ("AC", "DC")
            if (anchor_path := indexes.get(domain, {}).get(node_key)) is not None
        }
    )


def _invalid_converter_reachable_nodes(
    graph: _StructuralGraph,
    anchors: Mapping[NodeKey, Tuple[_Anchor, ...]],
) -> frozenset[NodeKey]:
    barrier_nodes = frozenset(anchors)
    pending = sorted(
        graph.invalid_converter_nodes - barrier_nodes,
        reverse=True,
    )
    reachable = set()
    while pending:
        node_key = pending.pop()
        if node_key in reachable or node_key in barrier_nodes:
            continue
        reachable.add(node_key)
        pending.extend(
            edge.neighbor
            for edge in reversed(graph.adjacency.get(node_key, ()))
            if edge.neighbor not in reachable
            and edge.neighbor not in barrier_nodes
        )
    return frozenset(reachable)


def _active_ac_grid_component_ids(
    active_graph: _ActiveGraph,
    components: _ActiveComponents,
) -> frozenset[str]:
    component_ids = set()
    for node_key, anchors in active_graph.active_anchors.items():
        if not any(anchor.domain == "AC" for anchor in anchors):
            continue
        component_id = components.node_component_ids.get(node_key)
        if component_id is not None:
            component_ids.add(component_id)
    return frozenset(component_ids)


def _dc_transfer_groups(
    parsed: _ParsedModel,
    states: Mapping[DeviceKey, _OperatingState],
    active_graph: _ActiveGraph,
    components: _ActiveComponents,
) -> Mapping[str, DcTransferGroup]:
    converter_keys: Dict[str, set[DeviceKey]] = {}
    ac_component_ids: Dict[str, set[str]] = {}
    ac_grid_components = _active_ac_grid_component_ids(
        active_graph,
        components,
    )

    for row in sorted(
        _block_rows(parsed.model, "DCACConverter"),
        key=lambda item: (_device_name(item) or "", _row_rank(item)),
    ):
        dev_name = _device_name(row)
        dc_node_id = _node_id(row.get("dc_node"))
        ac_node_id = _node_id(row.get("ac_node"))
        if dev_name is None or dc_node_id is None or ac_node_id is None:
            continue
        device_key = ("DCACConverter", dev_name)
        dc_node = ("DC", dc_node_id)
        ac_node = ("AC", ac_node_id)
        if (
            dc_node not in active_graph.active_nodes
            or ac_node not in active_graph.active_nodes
            or not _device_is_active(device_key, parsed, states)
        ):
            continue
        dc_component_id = components.node_component_ids.get(dc_node)
        ac_component_id = components.node_component_ids.get(ac_node)
        if (
            dc_component_id is None
            or ac_component_id is None
            or ac_component_id not in ac_grid_components
        ):
            continue
        converter_keys.setdefault(dc_component_id, set()).add(device_key)
        ac_component_ids.setdefault(dc_component_id, set()).add(ac_component_id)

    groups: Dict[str, DcTransferGroup] = {}
    for component_id, nodes in components.nodes_by_component_id.items():
        if not component_id.startswith("DC:"):
            continue
        groups[component_id] = DcTransferGroup(
            group_id=component_id,
            dc_nodes=tuple(sorted(node_id for _, node_id in nodes)),
            converter_keys=tuple(sorted(converter_keys.get(component_id, ()))),
            ac_component_ids=tuple(
                sorted(ac_component_ids.get(component_id, ()))
            ),
        )
    return MappingProxyType(dict(sorted(groups.items())))


def _empty_connection(resource: ResourceRef, connection_side: str) -> ResourceConnection:
    return ResourceConnection(
        technology=resource.technology,
        dev_type=resource.dev_type,
        dev_name=resource.dev_name,
        connection_side=connection_side,
        actively_connected=False,
        topology_status_label=_STATUS_LABELS[connection_side],
    )


def _format_connection(
    resource: ResourceRef,
    anchor_paths: Mapping[str, _AnchorPath],
) -> ResourceConnection:
    ac_path = anchor_paths.get("AC")
    dc_path = anchor_paths.get("DC")
    if ac_path is None and dc_path is None:
        return _empty_connection(resource, "UNRESOLVED")
    if ac_path is not None and dc_path is not None and ac_path.cost == dc_path.cost:
        return _empty_connection(resource, "AMBIGUOUS")

    if ac_path is None:
        connection_side = "DC"
        chosen = dc_path
    elif dc_path is None or ac_path.cost < dc_path.cost:
        connection_side = "AC"
        chosen = ac_path
    else:
        connection_side = "DC"
        chosen = dc_path

    if chosen is None:
        return _empty_connection(resource, "UNRESOLVED")
    converter_path = tuple(
        device_key
        for device_key in chosen.path
        if device_key[0] in _CONVERTER_TYPES
    )
    return ResourceConnection(
        technology=resource.technology,
        dev_type=resource.dev_type,
        dev_name=resource.dev_name,
        connection_side=connection_side,
        actively_connected=True,
        busbar_type=chosen.busbar_type,
        busbar_name=chosen.busbar_name,
        busbar_node=chosen.busbar_node,
        structural_path=chosen.path,
        active_path=chosen.path,
        converter_path=converter_path,
        topology_status_label=_STATUS_LABELS[connection_side],
    )


def _resolve_resource(
    resource: ResourceRef,
    parsed: _ParsedModel,
    anchor_indexes: Mapping[str, Mapping[NodeKey, _AnchorPath]],
    invalid_converter_nodes: frozenset[NodeKey],
) -> ResourceConnection:
    terminal_spec = RESOURCE_TERMINALS.get(resource.dev_type)
    resource_row = parsed.resource_rows.get((resource.dev_type, resource.dev_name))
    if terminal_spec is None or resource_row is None:
        return _empty_connection(resource, "INVALID")

    domain, terminal_field = terminal_spec
    terminal_id = _node_id(resource_row.get(terminal_field))
    terminal = (domain, terminal_id) if terminal_id is not None else None
    if terminal is None or terminal not in parsed.declared_nodes:
        return _empty_connection(resource, "INVALID")

    anchor_paths = _anchor_paths_for_node(anchor_indexes, terminal)
    if anchor_paths:
        return _format_connection(resource, anchor_paths)
    if terminal in invalid_converter_nodes:
        return _empty_connection(resource, "INVALID")
    return _format_connection(resource, anchor_paths)


def _resource_terminal(
    resource: ResourceRef,
    parsed: _ParsedModel,
) -> NodeKey | None:
    terminal_spec = RESOURCE_TERMINALS.get(resource.dev_type)
    resource_row = parsed.resource_rows.get((resource.dev_type, resource.dev_name))
    if terminal_spec is None or resource_row is None:
        return None
    domain, terminal_field = terminal_spec
    terminal_id = _node_id(resource_row.get(terminal_field))
    terminal = (domain, terminal_id) if terminal_id is not None else None
    if terminal not in parsed.declared_nodes:
        return None
    return terminal


def _apply_active_topology(
    resource: ResourceRef,
    connection: ResourceConnection,
    parsed: _ParsedModel,
    states: Mapping[DeviceKey, _OperatingState],
    active_graph: _ActiveGraph,
    active_anchor_indexes: Mapping[str, Mapping[NodeKey, _AnchorPath]],
    components: _ActiveComponents,
) -> ResourceConnection:
    if connection.connection_side not in {"AC", "DC"}:
        return replace(
            connection,
            actively_connected=False,
            active_path=(),
            grid_component_id="",
            dc_transfer_group_id="",
        )

    device_key = (resource.dev_type, resource.dev_name)
    terminal = _resource_terminal(resource, parsed)
    resource_active = _device_is_active(device_key, parsed, states)
    terminal_active = terminal in active_graph.active_nodes if terminal else False
    dc_transfer_group_id = ""
    if (
        connection.connection_side == "DC"
        and resource_active
        and terminal_active
        and terminal is not None
        and terminal[0] == "DC"
    ):
        dc_transfer_group_id = components.node_component_ids.get(terminal, "")

    if not resource_active or not terminal_active or terminal is None:
        return replace(
            connection,
            actively_connected=False,
            active_path=(),
            grid_component_id="",
            dc_transfer_group_id=dc_transfer_group_id,
        )

    active_anchor = active_anchor_indexes.get(
        connection.connection_side,
        {},
    ).get(terminal)
    if active_anchor is None:
        return replace(
            connection,
            actively_connected=False,
            active_path=(),
            grid_component_id="",
            dc_transfer_group_id=dc_transfer_group_id,
        )

    anchor_node = (connection.connection_side, active_anchor.busbar_node)
    grid_component_id = components.node_component_ids.get(anchor_node, "")
    if connection.connection_side == "DC" and terminal[0] != "DC":
        dc_transfer_group_id = grid_component_id
    return replace(
        connection,
        actively_connected=True,
        active_path=active_anchor.path,
        grid_component_id=grid_component_id,
        dc_transfer_group_id=dc_transfer_group_id,
    )


def resolve_resource_topology(
    snapshot: Mapping[str, object], resources: Sequence[ResourceRef]
) -> ResourceTopology:
    parsed = _parse_model(snapshot)
    graph = _build_structural_graph(parsed)
    structural_anchor_indexes = _build_reverse_anchor_indexes(
        graph.adjacency,
        parsed.anchors,
        parsed.anchors,
    )
    invalid_converter_nodes = _invalid_converter_reachable_nodes(
        graph,
        parsed.anchors,
    )
    states = _operating_states(snapshot, parsed)
    active_graph = _build_active_graph(parsed, graph, states)
    active_anchor_indexes = _build_reverse_anchor_indexes(
        active_graph.adjacency,
        active_graph.active_anchors,
        parsed.anchors,
    )
    components = _build_active_components(active_graph)
    dc_transfer_groups = _dc_transfer_groups(
        parsed,
        states,
        active_graph,
        components,
    )
    device_component_ids: Dict[DeviceKey, str] = {}
    for device_key in parsed.resource_rows:
        resource = ResourceRef(
            technology="",
            dev_type=device_key[0],
            dev_name=device_key[1],
        )
        terminal = _resource_terminal(resource, parsed)
        if terminal is None:
            continue
        component_id = components.node_component_ids.get(terminal, "")
        if component_id:
            device_component_ids[device_key] = component_id
    resolved: Dict[DeviceKey, ResourceConnection] = {}
    for resource in resources:
        device_key = (resource.dev_type, resource.dev_name)
        structural_connection = _resolve_resource(
            resource,
            parsed,
            structural_anchor_indexes,
            invalid_converter_nodes,
        )
        resolved[device_key] = _apply_active_topology(
            resource,
            structural_connection,
            parsed,
            states,
            active_graph,
            active_anchor_indexes,
            components,
        )
    return ResourceTopology(
        resources=MappingProxyType(resolved),
        dc_transfer_groups=dc_transfer_groups,
        device_component_ids=MappingProxyType(device_component_ids),
    )
