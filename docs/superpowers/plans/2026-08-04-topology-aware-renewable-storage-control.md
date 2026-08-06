# Topology-Aware Renewable and Storage Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify wind, PV, and storage by their actual path to AC/DC real busbars, split storage into AC/DC grid-following and balance roles, and generate energy-conserving trainee renewable-control commands that respect per-DC-island ACDC transfer limits.

**Architecture:** Add a pure Python topology resolver that builds structural and active graphs from `definitions.model`, contracts switchgear, resolves each resource to the nearest `ACRealBs/DCRealBs`, and creates active DC transfer groups. Feed those results into the existing model-scoped trainee controller, which will normalize resources by technology, topology side, and storage role; preserve the existing ACDC balance loop; and allocate only the residual diesel/renewable request to directly controlled resources. Generalize simulator storage state/SOC handling to both AC and DC generators, then expose the new categories through the existing trainee API and page without reimplementing topology in JavaScript.

**Tech Stack:** Python 3 dataclasses, heap-based graph search, existing E-file parser and `unittest`; vanilla HTML/CSS/JavaScript; existing `/api/snapshot`, `/api/trainee/renewable-control`, `SetValue`, and `StorageSoc` contracts.

**Git note:** The worktree already contains related uncommitted changes in `simu/renewable_control.py`, `simu/server.py`, `simu/web/trainee/app.js`, and renewable-control tests. Preserve those edits exactly. Do not stage, commit, push, or touch `tmp_runtime_probe/` during implementation unless the user explicitly requests Git operations.

---

## File Structure

- Create `simu/resource_topology.py`: pure structural/active graph construction, resource-to-bus resolution, and DC transfer-group discovery.
- Create `tests/test_resource_grid_side_topology.py`: focused topology and transfer-group tests with synthetic model blocks.
- Modify `simu/service.py`: expose all renewable/storage parameter blocks and attach AC/DC storage SOC metadata to device snapshots.
- Modify `simu/server.py`: generate `StorageSoc` and SOC measurements for both AC and DC storage without clipping SOC.
- Modify `simu_loop.py`: apply storage limits and SOC integration to AC and DC storage using actual solved terminal power.
- Modify `simu/renewable_control.py`: build resource specifications, consume topology results, split four storage classes, coordinate direct storage/renewables with ACDC, and emit metrics/logs/commands.
- Modify `simu/web/trainee/index.html`: replace five strategy tabs with ten topology-aware tabs and expose topology columns.
- Modify `simu/web/trainee/app.js`: render backend topology categories and side metrics without local side inference.
- Modify `simu/web/trainee/styles.css`: make ten tabs and the wider strategy table usable at desktop and narrow widths.
- Modify `tests/test_trainee_renewable_backend_control.py`: give the shared fixture a real AC/DC topology and add planner/manager behavior tests.
- Modify `tests/test_storage_soc_constraints.py`: add AC-storage runtime constraint and SOC-integration coverage.
- Modify `tests/test_simulator_model_creation.py`: verify generated AC/DC `StorageSoc` and SOC measurement definitions.
- Modify `tests/test_trainee_renewable_storage_acdc_metrics_ui.py`: update aggregate storage metric expectations.
- Create `tests/test_trainee_renewable_topology_ui.py`: static and Node-backed frontend contracts for tabs, topology columns, and no name-based inference.

---

## Cross-Task Contracts

Keep these names and meanings unchanged throughout the implementation:

```python
# simu/resource_topology.py uses snake_case immutable Python contracts.
ResourceRef(technology, dev_type, dev_name)
ResourceConnection.connection_side
ResourceConnection.actively_connected
ResourceConnection.grid_component_id
ResourceConnection.dc_transfer_group_id
ResourceTopology.resources
ResourceTopology.dc_transfer_groups

# simu/renewable_control.py serializes the same values to camelCase API fields.
connectionSide
activelyConnected
gridComponentId
dcTransferGroupId
```

Use these exact backend category strings, which Task 9 maps directly to tabs:

```python
RESOURCE_CATEGORIES = {
    ("wind", "AC"): "交流风电",
    ("wind", "DC"): "直流风电",
    ("pv", "AC"): "交流光伏",
    ("pv", "DC"): "直流光伏",
    ("storage:grid_following", "AC"): "交流跟网储能",
    ("storage:grid_following", "DC"): "直流跟网储能",
    ("storage:balance", "AC"): "交流平衡储能",
    ("storage:balance", "DC"): "直流平衡储能",
}
```

Add one module-level finite-number helper near the existing `_number()` helper and use it from every later helper. Do not define a local `finite` lambda inside `calculate_renewable_control_plan()`:

```python
def _finite_number(value: Any, default: float = 0.0) -> float:
    number = _number(value)
    return number if number is not None else default
```

The predicted diesel effect is calculated once from AC-side net supply:

```text
AC renewable target delta
+ AC grid-following storage target delta
+ actual change in DC->AC ACDC export
```

DC renewable and DC storage deltas reserve ACDC export but are not added to predicted diesel a second time. AC/DC balance storage never receives a direct `p_set`; its displayed target is a projected balance response, not a command target.

---

### Task 1: Structural Resource-to-Bus Topology Resolver

**Files:**
- Create: `simu/resource_topology.py`
- Create: `tests/test_resource_grid_side_topology.py`

- [ ] **Step 1: Write failing structural-side tests**

Create reusable block/snapshot helpers and tests that intentionally make names and generator domains misleading:

```python
import unittest

from simu.resource_topology import ResourceRef, resolve_resource_topology


def block(rows):
    headers = sorted({key for row in rows for key in row})
    return {"headers": headers, "rows": rows}


def snapshot_with_model(model):
    return {
        "definitions": {"model": {name: block(rows) for name, rows in model.items()}},
        "devices": [],
        "device_states": [],
        "measurements": {"scada": [], "real": []},
    }


class ResourceGridSideTopologyTest(unittest.TestCase):
    def test_name_does_not_override_direct_ac_bus_connection(self):
        snapshot = snapshot_with_model({
            "ACNode": [
                {"idx": 1, "name": "resource-node", "run_stat": 1},
                {"idx": 2, "name": "bus-node", "run_stat": 1},
            ],
            "ACGenerator": [
                {"idx": 1, "name": "直流风机", "node": 1, "run_stat": 1},
            ],
            "ACBranch": [
                {"idx": 1, "name": "line", "i_node": 1, "j_node": 2, "run_stat": 1},
            ],
            "ACRealBs": [
                {"idx": 1, "name": "ac-bus", "node": 2, "run_stat": 1},
            ],
        })

        result = resolve_resource_topology(
            snapshot,
            [ResourceRef("wind", "ACGenerator", "直流风机")],
        )

        item = result.resources[("ACGenerator", "直流风机")]
        self.assertEqual(item.connection_side, "AC")
        self.assertEqual(item.busbar_name, "ac-bus")

    def test_ac_generator_through_dcac_to_dc_bus_is_dc_connected(self):
        snapshot = snapshot_with_model({
            "ACNode": [{"idx": 1, "name": "wind-terminal", "run_stat": 1}],
            "DCNode": [{"idx": 7, "name": "dc-bus-node", "run_stat": 1}],
            "ACGenerator": [{"idx": 1, "name": "交流风机", "node": 1, "run_stat": 1}],
            "DCACConverter": [{
                "idx": 1,
                "name": "rectifier",
                "ac_node": 1,
                "dc_node": 7,
                "run_stat": 1,
            }],
            "DCRealBs": [{"idx": 1, "name": "dc-bus", "node": 7, "run_stat": 1}],
        })

        result = resolve_resource_topology(
            snapshot,
            [ResourceRef("wind", "ACGenerator", "交流风机")],
        )

        item = result.resources[("ACGenerator", "交流风机")]
        self.assertEqual(item.connection_side, "DC")
        self.assertEqual(item.converter_path, (("DCACConverter", "rectifier"),))

    def test_dc_generator_through_dcac_to_ac_bus_is_ac_connected(self):
        snapshot = snapshot_with_model({
            "DCNode": [{"idx": 1, "name": "pv-terminal", "run_stat": 1}],
            "ACNode": [{"idx": 2, "name": "ac-bus-node", "run_stat": 1}],
            "DCGenerator": [{"idx": 1, "name": "直流光伏", "node": 1, "run_stat": 1}],
            "DCACConverter": [{
                "idx": 1,
                "name": "inverter",
                "ac_node": 2,
                "dc_node": 1,
                "run_stat": 1,
            }],
            "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 2, "run_stat": 1}],
        })

        result = resolve_resource_topology(
            snapshot,
            [ResourceRef("pv", "DCGenerator", "直流光伏")],
        )

        self.assertEqual(result.resources[("DCGenerator", "直流光伏")].connection_side, "AC")
```

Add these named tests to the same class, using the `block()` and `snapshot_with_model()` helpers above:

```python
def test_switchlike_edges_have_zero_structural_cost(self):
    for edge_type in ("ACBreak", "ACSwitch", "ACZeroBranch"):
        with self.subTest(edge_type=edge_type):
            item = resolve_single_ac_resource_through(edge_type, status=1)
            self.assertEqual(item.connection_side, "AC")
            self.assertEqual(item.busbar_name, "ac-bus")

    for edge_type in ("DCBreak", "DCSwitch", "DCZeroBranch"):
        with self.subTest(edge_type=edge_type):
            item = resolve_single_dc_resource_through(edge_type, status=1)
            self.assertEqual(item.connection_side, "DC")
            self.assertEqual(item.busbar_name, "dc-bus")

def test_no_converter_path_wins_over_shorter_cross_domain_path(self):
    item = resolve_dual_anchor_resource(
        ac_non_switch_hops=2,
        dc_non_switch_hops=1,
        dc_domain_changes=1,
    )
    self.assertEqual(item.connection_side, "AC")
    self.assertEqual(item.converter_path, ())

def test_equal_best_ac_and_dc_paths_are_ambiguous(self):
    item = resolve_equal_cost_dual_anchor_resource()
    self.assertEqual(item.connection_side, "AMBIGUOUS")
    self.assertFalse(item.actively_connected)

def test_missing_real_bus_is_unresolved(self):
    item = resolve_resource_without_real_bus()
    self.assertEqual(item.connection_side, "UNRESOLVED")
    self.assertFalse(item.actively_connected)

def test_invalid_resource_terminal_is_reported_not_raised(self):
    item = resolve_resource_with_terminal(node="missing-node")
    self.assertEqual(item.connection_side, "INVALID")
    self.assertIn("端子", item.topology_status_label)
```

Implement the small snapshot factories named in this snippet in the test module; each factory must construct explicit rows rather than infer equipment from names.

- [ ] **Step 2: Run the tests and verify the import/function failures are the expected RED state**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_resource_grid_side_topology -v
```

Expected: FAIL because `simu.resource_topology` and its public contracts do not exist.

- [ ] **Step 3: Implement immutable public contracts and explicit terminal maps**

Create these public types exactly:

```python
from dataclasses import dataclass
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
```

Expose `resolve_resource_topology(snapshot: Mapping[str, object], resources: Sequence[ResourceRef]) -> ResourceTopology` with this exact signature.

Use explicit maps, not device-name inference:

```python
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
```

Read rows only from `snapshot["definitions"]["model"][block]["rows"]`. Normalize every node id to `str` before building `NodeKey`, while retaining typed `(dev_type, dev_name)` device identities. Build a structural adjacency list whose edge cost is `(domain_changes, non_switch_hops)`: switchlike edges add `(0, 0)`, ordinary same-domain edges add `(0, 1)`, and `DCACConverter` adds `(1, 1)`. Run Dijkstra from each resource terminal, stop expanding a path after reaching a real-bus anchor, compare costs lexicographically, and return `AMBIGUOUS` only when equal best paths reach different AC/DC domains. Equal-cost anchors on the same domain use deterministic `(busbar_type, busbar_name, busbar_node, path)` ordering.

`structural_path` and `active_path` contain traversed electrical device keys in order. `converter_path` is the ordered subset whose type is `ACACConverter`, `DCDCConverter`, or `DCACConverter`; ordinary branches and switchgear are not included.

Set status fields exactly:

```python
status = {
    "AC": "结构接入交流母线",
    "DC": "结构接入直流母线",
    "AMBIGUOUS": "交流/直流真实母线路径等价，拓扑歧义",
    "UNRESOLVED": "未找到可达真实母线",
    "INVALID": "资源模型引用或端子无效",
}[connection_side]
```

- [ ] **Step 4: Run the focused tests and make them green**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_resource_grid_side_topology.ResourceGridSideTopologyTest -v
```

Expected: all structural-side tests PASS.

- [ ] **Step 5: Refactor graph helpers without changing behavior**

Keep parsing, edge creation, Dijkstra, and result formatting as separate private functions. Run the complete module again after refactoring.

---

### Task 2: Active Connectivity and Per-Island DC Transfer Groups

**Files:**
- Modify: `simu/resource_topology.py`
- Modify: `tests/test_resource_grid_side_topology.py`

- [ ] **Step 1: Write failing active-state and transfer-group tests**

Add tests with two independent DC islands and two ACDC converters. Assert:

```python
def test_open_switch_keeps_structural_side_but_disconnects_runtime_path(self):
    snapshot = switch_connected_dc_resource_snapshot(status=0)
    result = resolve_resource_topology(
        snapshot,
        [ResourceRef("pv", "DCGenerator", "pv-a")],
    )
    item = result.resources[("DCGenerator", "pv-a")]
    self.assertEqual(item.connection_side, "DC")
    self.assertFalse(item.actively_connected)
    self.assertEqual(item.active_path, ())


def test_two_dc_islands_do_not_share_acdc_converters(self):
    snapshot = two_dc_island_snapshot()
    result = resolve_resource_topology(snapshot, [
        ResourceRef("pv", "DCGenerator", "pv-a"),
        ResourceRef("storage", "DCGenerator", "storage-b"),
    ])
    pv = result.resources[("DCGenerator", "pv-a")]
    storage = result.resources[("DCGenerator", "storage-b")]
    self.assertNotEqual(pv.dc_transfer_group_id, storage.dc_transfer_group_id)
    self.assertEqual(
        result.dc_transfer_groups[pv.dc_transfer_group_id].converter_keys,
        (("DCACConverter", "acdc-a"),),
    )
    self.assertEqual(
        result.dc_transfer_groups[storage.dc_transfer_group_id].converter_keys,
        (("DCACConverter", "acdc-b"),),
    )
```

Add these exact assertions:

```python
def test_dead_ac_endpoint_excludes_converter_from_dc_group(self):
    result = resolve_resource_topology(
        dc_group_snapshot(acdc_dead_island=True),
        [ResourceRef("pv", "DCGenerator", "pv-a")],
    )
    item = result.resources[("DCGenerator", "pv-a")]
    self.assertTrue(item.dc_transfer_group_id)
    self.assertEqual(result.dc_transfer_groups[item.dc_transfer_group_id].converter_keys, ())

def test_retired_converter_is_not_transfer_capacity(self):
    result = resolve_resource_topology(
        dc_group_snapshot(acdc_run_stat=0),
        [ResourceRef("pv", "DCGenerator", "pv-a")],
    )
    item = result.resources[("DCGenerator", "pv-a")]
    self.assertEqual(result.dc_transfer_groups[item.dc_transfer_group_id].converter_keys, ())

def test_component_and_group_ids_ignore_model_row_order(self):
    ordered = resolve_resource_topology(
        two_dc_island_snapshot(reverse_rows=False),
        [ResourceRef("pv", "DCGenerator", "pv-a")],
    ).resources[("DCGenerator", "pv-a")]
    reversed_rows = resolve_resource_topology(
        two_dc_island_snapshot(reverse_rows=True),
        [ResourceRef("pv", "DCGenerator", "pv-a")],
    ).resources[("DCGenerator", "pv-a")]
    self.assertEqual(ordered.grid_component_id, reversed_rows.grid_component_id)
    self.assertEqual(ordered.dc_transfer_group_id, reversed_rows.dc_transfer_group_id)
```

- [ ] **Step 2: Run the new tests and verify they fail on missing active-graph behavior**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_resource_grid_side_topology -v
```

- [ ] **Step 3: Implement runtime-state overlays**

Build state maps in this precedence order without applying `abs`, sign reversal, or numeric clipping to realtime values:

```text
model row run_stat/status
  <- snapshot.device_states run_stat/dead_island
  <- snapshot.devices run_stat/status
  <- valid realtime RUN_STAT/STATUS measurements
```

An edge is active only when `run_stat == 1`, `dead_island is False`, and switchlike devices have `status != 0`. A resource start terminal is active only when the resource device itself is online and not dead-island. Real-bus anchors and their nodes must also be active. Structural edges continue to ignore runtime run/open/dead-island state so tab classification remains stable.

After structural resolution, run active Dijkstra from the same terminal and accept only an active real-bus anchor in the already resolved structural domain. An alternate active path to another busbar of the same domain is valid; a runtime path crossing into the other domain never changes `connection_side`. Set `actively_connected=False` and `active_path=()` for `AMBIGUOUS`, `UNRESOLVED`, or `INVALID` resources.

- [ ] **Step 4: Build active same-domain components and DC transfer groups**

Use active AC/DC same-domain edges, including active `ACACConverter/DCDCConverter` but excluding `DCACConverter`, to assign deterministic component ids. Every active DC connected component receives one deterministic internal `dc_transfer_group_id`, serialized later as `dcTransferGroupId`, even when it currently has no usable ACDC. Add an active DCAC to a DC transfer group only when:

```python
dc_endpoint_component == group_dc_component
and ac_endpoint_component_has_active_ac_real_bus
and converter_is_active
```

Do not use a named or presumed main bus. `ac_endpoint_component_has_active_ac_real_bus` means that the active AC component contains any active `ACRealBs` anchor.

Sort node ids and converter keys before creating immutable payloads. Build ids from the sorted domain-prefixed node set, for example `AC:<sha1-prefix>` and `DC:<sha1-prefix>`, rather than row order. Assign `actively_connected`, `active_path`, `grid_component_id`, and `dc_transfer_group_id` to each resource. `grid_component_id` is the active component containing the resolved real-bus anchor, so a bottom-level DC generator that structurally reaches an AC bus through DCAC still reports an AC grid component. A structurally DC resource gets a group id only when its terminal belongs to an active DC component; otherwise the id is empty.

- [ ] **Step 5: Run all topology tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_resource_grid_side_topology -v
```

Expected: structural and runtime topology tests PASS.

---

### Task 3: Snapshot Metadata and Generated AC/DC Storage Definitions

**Files:**
- Modify: `simu/service.py`
- Modify: `simu/server.py`
- Modify: `tests/test_simulator_model_creation.py`
- Create: `tests/test_resource_parameter_snapshot.py`

- [ ] **Step 1: Write failing parameter exposure tests**

Create a temporary `model.e` containing one row in each of `ACWindGen`, `DCWindGen`, `ACPVGen`, `DCPVGen`, `ACStorageGen`, and `DCStorageGen`. Instantiate `PolarMicrogridSimulator` and assert:

```python
parameters = service.device_parameters()
self.assertEqual(
    set(parameters),
    {"ACWindGen", "DCWindGen", "ACPVGen", "DCPVGen", "ACStorageGen", "DCStorageGen"},
)
```

Also assert an `ACStorageGen` row linked to `ACGenerator` receives live `soc_curr` in `service.devices()`, just as a DC storage row does. Give the AC and DC generators the same display name in one test and assert SOC is still attached by `(dev_type, dev_name)`, never by name alone.

- [ ] **Step 2: Write failing generated-artifact tests**

Extend `SimulatorModelCreationTest` with an uploaded model containing AC and DC storage whose initial SOC values are `1.08` and `-0.05`. Use numeric per-unit values for this test; add a separate `%` syntax case proving `108%` parses to `1.08`. Assert generated `control.e/stat.e` contain:

```python
self.assertEqual(
    {(row["dev_type"], row["name"], float(row["soc_curr"])) for row in storage_soc_rows},
    {
        ("ACGenerator", "ac-storage", 1.08),
        ("DCGenerator", "dc-storage", -0.05),
    },
)
```

Assert generated `meas.e` has valid `SOC` rows for both generator types.

- [ ] **Step 3: Run focused tests and confirm current DC-only behavior fails**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_resource_parameter_snapshot tests.test_simulator_model_creation.SimulatorModelCreationTest.test_create_model_from_uploaded_model_e_generates_ac_and_dc_storage_state -v
```

- [ ] **Step 4: Expose all six resource parameter blocks**

In `simu/service.py::device_parameters()`, replace the three-block tuple with:

```python
parameter_blocks = (
    "ACWindGen",
    "DCWindGen",
    "ACPVGen",
    "DCPVGen",
    "ACStorageGen",
    "DCStorageGen",
)
```

Generalize storage SOC attachment in `devices()` by resolving `ACStorageGen.idx_acgenerator -> ACGenerator` and `DCStorageGen.idx_dcgenerator -> DCGenerator`. Change storage parameter and SOC lookup maps to `Dict[Tuple[str, str], ...]`. Preserve `dev_type + name` as the identity; do not match AC/DC devices by name alone. Keep legacy `estorage` support, but resolve its optional `dev_type/source_name` first and use the existing DC fallback only when typed metadata is absent.

- [ ] **Step 5: Generalize generated `StorageSoc` rows**

In `simu/server.py`, introduce explicit specs:

```python
STORAGE_PARAMETER_SPECS = (
    ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
    ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
)
```

Refactor `_storage_source_rows()` to iterate both specs, retain the linked generator type, and store the parsed SOC directly. Use one parser with this exact contract:

```python
def _storage_soc_value(value: Any, default: float = 0.5) -> float:
    text = str(value or "").strip()
    number = _numeric(value, default)
    return number / 100.0 if "%" in text else number
```

Remove `max(0.0, min(1.0, soc))`; generated initial state must preserve out-of-range values. Keep legacy generator-name scanning only for models without either structured storage block. Deduplicate by `(dev_type, name)` and preserve source-model order within each explicit storage block.

- [ ] **Step 6: Run the focused tests and existing simple-model tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_resource_parameter_snapshot tests.test_simulator_model_creation tests.test_simple_model -v
```

Expected: new AC/DC tests pass and the legacy simple model remains compatible.

---

### Task 4: AC/DC Storage Runtime Constraints and SOC Integration

**Files:**
- Modify: `simu_loop.py`
- Modify: `tests/test_storage_soc_constraints.py`

- [ ] **Step 1: Write failing AC-storage constraint and integration tests**

Add an AC storage fixture using `ACGenerator + ACStorageGen + StorageSoc`. Assert a one-hour 40 kW discharge request at SOC 0.21 is limited to 1 kW and integrates to 0.20. Add a snapshot-backed test proving `ACGenerator.P_GEN`, not `p_set`, drives SOC integration:

```python
def test_ac_storage_soc_uses_actual_solved_generator_power(self):
    next_soc = self._integrate_typed_storage_soc(
        dev_type="ACGenerator",
        parameter_block="ACStorageGen",
        reference_field="idx_acgenerator",
        setpoint=0.0,
        actual_power=10.0,
        soc=0.5,
        capacity=100.0,
        efficiency=1.0,
        period_seconds=3600.0,
    )
    self.assertAlmostEqual(next_soc, 0.4)
```

Add regressions proving DC behavior is unchanged, out-of-range SOC continues integrating without clipping, and an offline/dead-island storage device integrates zero power instead of the previous snapshot's stale `P_GEN`.

- [ ] **Step 2: Run the AC-focused tests and confirm they fail because storage targets are DC-only**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_storage_soc_constraints.StorageSocConstraintTest.test_ac_storage_soc_uses_actual_solved_generator_power -v
```

- [ ] **Step 3: Generalize embedded storage definitions**

In `_embedded_device_define_book()`, iterate:

```python
for block_name, generator_type, reference_field in (
    ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
    ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
):
```

Each generated `estorage` row must include `dev_type`, `source_name`, and the existing capacity/SOC/efficiency fields. Legacy `device.e` rows without `dev_type` remain supported.

- [ ] **Step 4: Change storage target identity from DC-only rows to typed targets**

Change the target contract to:

```python
StorageTarget = Tuple[str, dict, str, Optional[dict], int]


def _storage_target_rows(model_book: EBook, dev_define: EBook) -> List[StorageTarget]:
    """Return dev_type, generator row, storage name, definition row, and position."""
```

Update `apply_storage_constraints_book()`, `apply_dc_export_limits()`, `_snapshot_storage_power_by_name()`, and `update_storage_soc_book()` to unpack the typed target. `apply_dc_export_limits()` must count only typed targets whose `dev_type == "DCGenerator"`.

- [ ] **Step 5: Read actual power from the correct solved device type**

In `_snapshot_storage_power_by_name()`, call:

```python
snapshot.value(dev_type, candidate, "P_GEN")
```

In `update_storage_soc_book()`, resolve the source first from the `StorageSoc.dev_type`, then from the typed storage target metadata. Never prefer a same-named DC generator over an AC generator. Before accepting solved power, require the same snapshot's typed device state to have `run_stat == 1` and `dead_island is not True`; otherwise use `0.0`. Do not fall back to an older nonzero solved value.

Retain the existing per-device charge/discharge linear derating and single-period energy checks for both AC and DC typed targets. The constraints may clip candidate power against model limits, but they must not clip the integrated `soc_curr` result itself.

- [ ] **Step 6: Run all storage runtime tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_storage_soc_constraints -v
```

Expected: AC and DC constraints/integration pass; existing unbounded SOC tests remain green.

---

### Task 5: Topology-Aware Backend Resource Normalization

**Files:**
- Modify: `simu/renewable_control.py`
- Modify: `tests/test_trainee_renewable_backend_control.py`

- [ ] **Step 1: Give the shared planner fixture a complete model topology**

Add a `definitions.model` payload to `renewable_snapshot()` containing:

```text
ACGenerator wind-1 at ACNode 1
ACGenerator diesel-1 and ACLoad load-1 at ACNode 2
ACBranch 1 -> 2
ACRealBs at ACNode 2
DCGenerator pv-1 at DCNode 1
DCGenerator storage-1 at DCNode 2
DCBranch/DCBreak paths to DCNode 3
DCRealBs at DCNode 3
DCACConverter grid-converter-1 between ACNode 2 and DCNode 3
```

Keep the existing `definitions.control` block. Add node/terminal fields to device raw rows where present, but make tests rely on `definitions.model` as the source of topology.

- [ ] **Step 2: Write failing resource-category tests**

Add tests that reverse names and bottom-level domains while keeping topology authoritative:

```python
def test_renewables_are_categorized_by_real_bus_topology(self):
    snapshot = renewable_snapshot()
    snapshot = add_ac_generator_wind_through_dcac_to_dc_bus(snapshot, name="交流名称但直流并网")
    snapshot = add_dc_generator_pv_through_dcac_to_ac_bus(snapshot, name="直流名称但交流并网")

    plan = calculate_renewable_control_plan(snapshot)
    by_name = {row["dev_name"]: row for row in plan["commandRows"]}

    self.assertEqual(by_name["交流名称但直流并网"]["category"], "直流风电")
    self.assertEqual(by_name["直流名称但交流并网"]["category"], "交流光伏")
```

Add storage tests for all four combinations and assert unresolved/ambiguous resources have `commandable=False` with a topology status label. Add a phantom-parameter regression: a parameter row whose linked generator idx does not exist must not create a strategy-table device.

Add a renewable recovery regression that supplies valid-looking wind speed and solar irradiance fields but changes neither result when those fields are removed. Recovery must continue to use signed current power, rated capacity, configured renewable step, topology, and verified sinks only.

- [ ] **Step 3: Run the new tests and confirm current block-name categorization fails**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control.RenewableControlPlannerDataQualityTest.test_renewables_are_categorized_by_real_bus_topology -v
```

- [ ] **Step 4: Add resource specification extraction**

Import `ResourceRef` and `resolve_resource_topology`. Add explicit specification tables:

```python
RENEWABLE_PARAMETER_SPECS = (
    ("wind", "ACWindGen", "ACGenerator", "idx_acgenerator"),
    ("wind", "DCWindGen", "DCGenerator", "idx_dcgenerator"),
    ("pv", "ACPVGen", "ACGenerator", "idx_acgenerator"),
    ("pv", "DCPVGen", "DCGenerator", "idx_dcgenerator"),
)

STORAGE_PARAMETER_SPECS = (
    ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
    ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
)

GRID_FOLLOWING_STORAGE_MODES = {"P", "PQ"}
BALANCE_STORAGE_MODES = {"SLACK", "V", "VF", "V/F", "PH"}
```

Normalize modes with `str(mode).strip().upper()` before membership checks. Build one list of actual linked resource devices, call the topology resolver once per plan, and pass the returned map into `_renewable_rows()` and `_storage_rows()`.

Preserve legacy parameter support from `definitions.device` without using legacy block names as side inference:

```python
LEGACY_RESOURCE_SPECS = (
    ("wind", "wind_generator", "ACGenerator"),
    ("pv", "pv_generator", "DCGenerator"),
    ("storage", "estorage", ""),
)
```

For legacy rows, resolve `dev_type/source_name` when present. Only use the existing legacy default device type when typed metadata is absent, then still pass the linked device through `resolve_resource_topology()` to determine AC/DC side. Missing linked devices are diagnostic rows only and never command rows.

- [ ] **Step 5: Emit topology-aware renewable rows**

Set categories only from technology and `connection_side`:

```python
category = {
    ("wind", "AC"): "交流风电",
    ("wind", "DC"): "直流风电",
    ("pv", "AC"): "交流光伏",
    ("pv", "DC"): "直流光伏",
}.get((technology, connection.connection_side), "拓扑未解析新能源")
```

Include `technology`, `resourceDevType`, `resourceDevName`, `connectionSide`, `activelyConnected`, `busbarType`, `busbarName`, `busbarNode`, `structuralPath`, `activePath`, `converterPath`, `gridComponentId`, `dcTransferGroupId`, and `topologyStatusLabel` in every row. `online` for strategy purposes requires both device online and `activelyConnected`. Preserve measured active power exactly as received, including negative values; do not apply `abs`, `max`, `min`, or sign reversal while normalizing realtime values.

- [ ] **Step 6: Emit four storage roles without direct-command leakage**

Use topology side plus mode/control point to set:

```python
role = "grid_following" if mode in GRID_FOLLOWING_STORAGE_MODES and set_type == "p_set" else "balance" if mode in BALANCE_STORAGE_MODES else "uncontrolled"
```

Categories are `交流跟网储能`, `直流跟网储能`, `交流平衡储能`, `直流平衡储能`, or `拓扑未解析储能`. Balance rows always have `commandable=False`, empty `set_type`, and an `indirectControlDevices` list; grid-following rows retain their own `p_set`. `UNRESOLVED`, `AMBIGUOUS`, `INVALID`, missing realtime SOC, invalid power limits, or missing control points disable only that resource and add a diagnostic reason.

- [ ] **Step 7: Restrict the existing ACDC balance state machine to DC balance storage**

Replace the old aggregate `online_storage` input to ACDC/SOC calculations with `online_dc_balance_storage`, grouped by `dcTransferGroupId`. Compute AC balance, DC balance, AC grid-following, and DC grid-following values separately. Preserve the existing renewable-storage-island behavior using only resources in the affected active topology component. Never aggregate AC balance SOC into the ACDC state machine, and never let one DC group's balance storage drive another group's ACDC candidate.

- [ ] **Step 8: Run the complete planner module**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control.RenewableControlPlannerDataQualityTest -v
```

Expected: existing ACDC/DC-balance tests, environment-independence tests, and new topology category tests pass.

---

### Task 6: Direct AC/DC Grid-Following Storage Dispatch

**Files:**
- Modify: `simu/renewable_control.py`
- Modify: `tests/test_trainee_renewable_backend_control.py`

- [ ] **Step 1: Write failing AC-first discharge tests**

Create one AC grid-following and one DC grid-following storage, both SOC 0.60, each with 40 kW discharge capability. Set `converterStepRatio=0.10` so each direct storage has a 4 kW base step. With diesel above its upper deadband, assert AC storage receives `+4 kW` first; only residual demand can reach DC storage.

Add a test where AC storage has only 1 kW margin and assert DC storage receives the remaining step only when its transfer group has ACDC export headroom.

- [ ] **Step 2: Write failing boundary tests**

Assert:

- Diesel in `[minimum, minimum + deadband]` never increases either storage discharge.
- Diesel below minimum reduces existing positive storage power toward zero.
- SOC at/below lower limit prevents increased discharge.
- SOC at/above upper limit prevents increased charging.
- Low SOC alone never creates a negative charging target.
- A DC storage without an active transfer group cannot be used to reduce AC diesel.
- The existing SOC charge/discharge linear derating limits candidate power continuously between configured curve points.
- A one-period energy check clips a candidate that would cross `soc_lower_limit` or `soc_upper_limit`, while leaving the measured/integrated SOC itself unclipped.
- Negative realtime power remains negative in `currentKw`; candidate bounds are computed separately instead of normalizing the measurement.

- [ ] **Step 3: Run focused storage planner tests and verify they fail**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control.RenewableControlPlannerDataQualityTest.test_ac_grid_storage_discharge_precedes_dc_grid_storage -v
```

- [ ] **Step 4: Add direct-storage margin and step helpers**

First move the existing local finite lambda to the module-level `_finite_number()` contract defined above. Do not reintroduce a separate storage-step setting. Reuse `RenewableControlSettings.converter_step_ratio` for ACDC and directly controlled storage:

```python
def _grid_storage_step_kw(row: Mapping[str, Any], settings: RenewableControlSettings) -> float:
    rated = max(
        _finite_number(row.get("maxChargePowerKw")),
        _finite_number(row.get("maxDischargePowerKw")),
    )
    return max(0.0, settings.converter_step_ratio * rated)
```

Add signed target helpers that distinguish current target, charge margin, and discharge margin. Each helper must apply, in order, model power limits, configured SOC linear derating, one-period energy margin, and the step limit. Apply the existing 20% slow-increase rule near the diesel lower boundary and storage SOC lower deadband; decreases that protect diesel/SOC keep the full step.

- [ ] **Step 5: Allocate AC storage before DC storage for diesel reduction**

Compute the residual diesel correction after the existing per-group ACDC/DC-balance candidate. A candidate that improves the diesel lower-limit error is allowed even when one step cannot reach the target. Allocate positive target deltas to AC grid-following storage by available discharge margin. Then allocate only the residual to DC grid-following storage, grouped by `dcTransferGroupId` and capped by that group's available DC->AC ACDC delta.

Within a group, distribute by margin ratio and perform one remainder pass. Never average by device count.

- [ ] **Step 6: Generate independent storage commands**

Grid-following storage command rows use their own target and `p_set`. Balance storage rows remain non-commandable. Add storage commands to `commands` through the existing generic command filter; do not copy ACDC targets into storage rows. A DC grid-storage discharge command and its ACDC reservation remain two independent command objects with matching planned transfer deltas.

- [ ] **Step 7: Run direct-storage tests plus existing command arbitration tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control tests.test_control_command_validity -v
```

---

### Task 7: Side-Aware Renewable Recovery and ACDC Energy Pairing

**Files:**
- Modify: `simu/renewable_control.py`
- Modify: `tests/test_trainee_renewable_backend_control.py`

- [ ] **Step 1: Write failing AC/DC renewable recovery tests**

Add cases proving:

```text
AC renewable increment -> directly reduces AC diesel
DC renewable increment with local DC charging room -> may recover without changing ACDC
DC renewable increment intended for AC -> must pair with additional negative p_ac_set
DC renewable increment with no local sink and no ACDC headroom -> must hold
AC renewable surplus -> may charge AC storage but never DC storage
```

Use two DC transfer groups and assert a renewable in group A cannot use converter or storage capacity from group B.

- [ ] **Step 2: Write failing no-diesel-charging tests**

Assert no grid-following storage receives a negative target unless the same cycle identifies an equal-or-larger renewable source on the same legal power path. Specifically assert `ACDC p_ac_set` never becomes positive and AC renewable surplus never appears in a DC-storage charge budget.

- [ ] **Step 3: Write failing balance-storage response tests**

Add these cases with balance rows kept `commandable=False`:

```text
AC balance storage low-SOC + discharging:
  recover available AC renewable first, then AC grid-storage discharge,
  then usable ACDC export; projected balance discharge must decrease.

AC balance storage high-SOC + charging:
  charge AC grid-storage from verified renewable surplus first;
  if no sink remains, reduce AC renewable or ACDC export until projected
  balance charging is within its SOC-derived allowance.

DC balance storage low-SOC + discharging:
  reduce same-group ACDC export, recover same-group DC renewable, and/or
  increase same-group DC grid-storage discharge; no other group may act.

DC balance storage high-SOC + charging:
  increase same-group ACDC export within headroom; if diesel/ACDC limits block
  export, reduce same-group DC renewable. Never produce positive p_ac_set.
```

For every case assert the balance row has no `p_set` command and its `projectedTargetKw` moves in the protective direction.

- [ ] **Step 4: Run the focused tests and verify current aggregate renewable logic fails**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control.RenewableControlPlannerDataQualityTest.test_dc_renewable_recovery_requires_matching_acdc_export -v
```

- [ ] **Step 5: Build per-side and per-transfer-group budgets**

Add an internal immutable budget structure:

```python
@dataclass(frozen=True)
class _DcGroupBudget:
    group_id: str
    renewable_current_kw: float
    renewable_recovery_kw: float
    local_net_demand_kw: float
    grid_storage_charge_margin_kw: float
    grid_storage_discharge_margin_kw: float
    balance_storage_charge_margin_kw: float
    balance_storage_discharge_margin_kw: float
    balance_storage_current_kw: float
    acdc_current_export_kw: float
    acdc_export_headroom_kw: float
    acdc_step_headroom_kw: float
```

Build budgets only from rows sharing the same `dcTransferGroupId`. Map each active `DCLoad.node` to a group by membership in `DcTransferGroup.dc_nodes`; loads on disconnected/dead DC nodes do not enter a live group. Keep AC resources in a separate AC budget with equivalent renewable, grid-storage, balance-storage, net-demand/diesel, and accepted-ACDC fields. Sum realtime load values with their original sign into `local_net_demand_kw`; do not use `abs`, `max`, or `min` to force a consumption sign.

- [ ] **Step 6: Apply balance-storage protective requests before discretionary recovery**

For each active component/group, derive a protective request from balance-storage SOC region and signed current power. Use capacity-weighted SOC only for group diagnostics; enforce limits per device. Allocate protective actions in the exact order tested in Step 3. Record affected resources in each balance row's `indirectControlDevices`; do not create a balance-storage command.

Compute projected balance targets from island power conservation:

```text
AC balance projected delta
  = -(AC renewable delta + AC grid-storage delta + ACDC export delta)

DC balance projected delta for one group
  = -(DC renewable delta + DC grid-storage delta) + ACDC export delta
```

Apply the projected group delta to multiple balance devices by usable power-margin ratio, then enforce each device's SOC/power/energy boundary. This projected value is display/validation data only.

- [ ] **Step 7: Allocate renewable recovery to verified sinks**

For each DC group, allocate candidate renewable recovery in this order:

```text
local DC load or existing local deficit
DC grid-following storage charging
DC balance storage charging allowance
paired ACDC export to AC
```

Cap the paired ACDC-export sink by the AC side's residual acceptance after earlier AC actions: diesel down-margin, active AC net demand, AC grid-storage charging margin, and AC balance-storage charging allowance. Do not reserve ACDC export merely because converter headroom exists.

For AC renewable recovery, legal sinks are AC diesel down-margin, AC grid-following storage charging, and AC balance-storage charging allowance. ACDC reverse flow is not a legal sink. If no sink exists, target stays at the current value.

Within each side/technology/group allocation, distribute by each device's accepted margin, then perform one remainder pass only among devices that still have legal margin. Never average by device count, and never move remainder across AC/DC sides or DC transfer groups.

- [ ] **Step 8: Pair DC export targets without combining device commands**

When DC renewable or DC grid-storage discharge is intended for AC, reserve the same transfer amount in the group's ACDC export budget. Apply converter efficiency if the existing model exposes one; otherwise use the existing 1.0 planning convention. Emit separate renewable/storage `p_set` and converter `p_ac_set` targets. Clamp every automatic converter target to `p_ac_set <= 0.0`; if a paired action would require positive `p_ac_set`, reject that action and log `禁止ACDC倒送`.

- [ ] **Step 9: Apply the unified final validator and one diesel prediction**

Validate candidates in the design-specified order:

```text
parameter reference
unique structural side
active path/dead-island state
mode and control point
finite realtime P/SOC/bounds
device power, SOC derating, and one-period energy margin
step and direction
DC transfer-group membership
same-group ACDC state/capacity/step/direction
same-path renewable charging budget
combined predicted diesel boundary
```

Discard only the invalid device candidate and continue evaluating independent devices. If receive state changes during calculation, discard the whole plan before command arbitration.

Compute diesel effect once from:

```text
AC renewable delta
+ AC grid-storage delta
+ change in actual DC->AC ACDC export
```

Do not separately add the DC renewable/storage deltas after they have already been represented by ACDC export. Clip later candidates when the combined effect would push diesel below its minimum. Allow partial improving moves; do not require one-step convergence. Re-run same-path charging conservation after clipping so renewable source delta is always greater than or equal to its paired storage charging delta.

- [ ] **Step 10: Run all planner tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control -v
```

Expected: all legacy and topology-aware planner/API tests pass.

---

### Task 8: Metrics, Logs, Trend, and Command Payload

**Files:**
- Modify: `simu/renewable_control.py`
- Modify: `tests/test_trainee_renewable_backend_control.py`
- Modify: `tests/test_trainee_renewable_storage_acdc_metrics_ui.py`

- [ ] **Step 1: Write failing metric and log tests**

Assert `plan["metrics"]` contains finite or `None` values for:

```python
expected_keys = {
    "acWindCurrentKw",
    "acWindTargetKw",
    "dcWindCurrentKw",
    "dcWindTargetKw",
    "acPvCurrentKw",
    "acPvTargetKw",
    "dcPvCurrentKw",
    "dcPvTargetKw",
    "acGridStorageCurrentKw",
    "acGridStorageTargetKw",
    "acGridStorageSoc",
    "dcGridStorageCurrentKw",
    "dcGridStorageTargetKw",
    "dcGridStorageSoc",
    "acBalanceStorageCurrentKw",
    "acBalanceStorageTargetKw",
    "dcBalanceStorageCurrentKw",
    "dcBalanceStorageTargetKw",
    "acBalanceStorageSoc",
    "dcBalanceStorageSoc",
    "dcRenewableToAcKw",
    "dcTransferGroups",
}
self.assertTrue(expected_keys.issubset(plan["metrics"]))
```

Assert balance SOC is weighted by `capacityKwh`, not averaged by device count. Assert `decisionDetail` names topology side, busbar, transfer group, local sink, ACDC reservation, and final clipping reason.

- [ ] **Step 2: Write failing trend and command-payload tests**

Assert `_trend_point()` and `_command_payload()` carry side totals and transfer-group summaries while retaining existing aggregate fields for compatibility. Assert independent AC storage, DC storage, renewable, and ACDC commands all survive serialization unchanged.

- [ ] **Step 3: Run focused tests and confirm missing keys fail**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control.RenewableControlBackendApiTest tests.test_trainee_renewable_storage_acdc_metrics_ui -v
```

- [ ] **Step 4: Add weighted aggregation helpers**

Implement:

```python
def _capacity_weighted_soc(rows: Sequence[Mapping[str, Any]]) -> Optional[float]:
    known = [
        (float(row["soc"]), max(EPSILON, _finite_number(row.get("capacityKwh"))))
        for row in rows
        if row.get("socKnown") and isinstance(row.get("soc"), (int, float))
    ]
    total_capacity = sum(capacity for _soc, capacity in known)
    return (
        sum(soc * capacity for soc, capacity in known) / total_capacity
        if total_capacity > EPSILON
        else None
    )
```

Keep the legacy aggregate `storageCurrentKw/storageSoc` but define them as all online storage signed power and all online storage capacity-weighted SOC. Do not fold ACDC power into storage power. For balance storage, `*BalanceStorageTargetKw` is the summed `projectedTargetKw` from Task 7; it is never serialized as a command target.

- [ ] **Step 5: Extend metrics, trend, and logs**

Serialize each DC group as a JSON-safe mapping with current/target renewable, storage, ACDC export, capacity, actual renewable power delivered through ACDC, and curtailed/blocked power. Define `dcRenewableToAcKw` from the valid groups' actual DC->AC ACDC export attributable to renewable power; never use total DC renewable output as this metric.

Extend decision logs in stable phases: topology, side/role totals, ACDC balance candidate, direct-storage allocation, renewable sink allocation, unified validation, dispatch result. Each phase must include the resource bus/group, current signed power, candidate delta, accepted delta, limiting boundary, and open-loop/closed-loop outcome. Non-finite candidates log a device-level error and are omitted without aborting unrelated resources.

In `_trend_point()` and `_command_payload()`, preserve existing aggregate keys and add the exact metric names from Step 1. Serialize `dcTransferGroups` as copied JSON-safe dictionaries so one page cannot mutate backend controller state shared by other pages.

- [ ] **Step 6: Run API, trend, and metric tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control tests.test_trainee_renewable_storage_acdc_metrics_ui -v
```

---

### Task 9: Trainee Topology-Aware Strategy UI

**Files:**
- Modify: `simu/web/trainee/index.html`
- Modify: `simu/web/trainee/app.js`
- Modify: `simu/web/trainee/styles.css`
- Create: `tests/test_trainee_renewable_topology_ui.py`

- [ ] **Step 1: Write failing static UI contracts**

Assert the HTML contains these exact tab keys and labels:

```python
tabs = {
    "ac-wind": "交流风电",
    "dc-wind": "直流风电",
    "ac-pv": "交流光伏",
    "dc-pv": "直流光伏",
    "ac-grid-storage": "交流跟网储能",
    "dc-grid-storage": "直流跟网储能",
    "ac-balance-storage": "交流平衡储能",
    "dc-balance-storage": "直流平衡储能",
    "diesel": "柴发",
    "converter": "ACDC变流",
}
for key, label in tabs.items():
    self.assertIn(f'data-renewable-strategy-tab="{key}"', self.html)
    self.assertIn(f'>{label}</button>', self.html)
```

Assert the strategy table includes headings for `并网侧`, `接入状态`, `接入母线`, `传输组`, `接入路径`, `拓扑状态`, and `间接调节设备`.

- [ ] **Step 2: Write failing JavaScript source/Node tests**

Assert `RENEWABLE_STRATEGY_TABS` maps exact backend categories and contains no regex/name checks for deciding AC/DC side. Use a Node snippet to call `renewableStrategyRows()` with deliberately misleading device names and verify filtering uses `row.category` only.

- [ ] **Step 3: Run the UI test and confirm current five-tab UI fails**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_topology_ui -v
```

- [ ] **Step 4: Replace the tab model**

Set:

```javascript
const RENEWABLE_STRATEGY_TABS = {
  "ac-wind": { label: "交流风电", categories: new Set(["交流风电"]) },
  "dc-wind": { label: "直流风电", categories: new Set(["直流风电"]) },
  "ac-pv": { label: "交流光伏", categories: new Set(["交流光伏"]) },
  "dc-pv": { label: "直流光伏", categories: new Set(["直流光伏"]) },
  "ac-grid-storage": { label: "交流跟网储能", categories: new Set(["交流跟网储能"]) },
  "dc-grid-storage": { label: "直流跟网储能", categories: new Set(["直流跟网储能"]) },
  "ac-balance-storage": { label: "交流平衡储能", categories: new Set(["交流平衡储能"]) },
  "dc-balance-storage": { label: "直流平衡储能", categories: new Set(["直流平衡储能"]) },
  diesel: { label: "柴发", categories: new Set(["柴油发电"]) },
  converter: { label: "ACDC变流", categories: new Set(["交直流变流器"]) },
};
```

Default to `ac-wind`. Render topology fields directly from backend rows. Show `--` for AC direct devices without transfer groups. Format `converterPath` as device names joined by ` -> `. A known-side but currently disconnected resource remains on its structural-side tab with `当前断开`; it is disabled rather than reclassified.

Keep `UNRESOLVED`, `AMBIGUOUS`, `INVALID`, and missing-model-reference diagnostics visible in the existing strategy/log diagnostic area without creating an eleventh tab. Render their backend `topologyStatusLabel` verbatim and never place them into an AC/DC tab by guessing.

- [ ] **Step 5: Update storage SOC helpers and aggregate display**

Extend `storageSocRatiosByDevice()` to read both `ACStorageGen` and `DCStorageGen` linked devices, keyed by `dev_type|dev_name`. Do not use device names to infer side. Use backend `metrics.storageSoc` on the renewable page and keep homepage SOC semantics consistent. Grid-following rows display executable `targetKw`; balance rows display `projectedTargetKw`, show `indirectControlDevices`, and never render an enabled direct-command action.

- [ ] **Step 6: Make tabs and table responsive**

Use a horizontally scrollable single-row tab strip and preserve fixed button dimensions. Keep the table wrapper horizontally scrollable; do not compress topology text into unreadable cells. Add title text for long bus/path values and retain right alignment for numeric columns.

- [ ] **Step 7: Run topology UI and related renewable UI tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_topology_ui tests.test_trainee_renewable_storage_acdc_metrics_ui tests.test_trainee_renewable_vertical_layout_ui tests.test_trainee_renewable_loop_mode_ui -v
node --check simu\web\trainee\app.js
```

---

### Task 10: End-to-End Regression and Runtime Verification

**Files:**
- Verify all modified files

- [ ] **Step 1: Run syntax and whitespace checks**

```powershell
D:\anaconda3\python.exe -X utf8 -m py_compile simu\resource_topology.py simu\renewable_control.py simu\service.py simu\server.py simu_loop.py
node --check simu\web\trainee\app.js
git diff --check
```

- [ ] **Step 2: Run the complete focused suite**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest `
  tests.test_resource_grid_side_topology `
  tests.test_resource_parameter_snapshot `
  tests.test_storage_soc_constraints `
  tests.test_simulator_model_creation `
  tests.test_trainee_renewable_backend_control `
  tests.test_trainee_renewable_storage_acdc_metrics_ui `
  tests.test_trainee_renewable_topology_ui `
  tests.test_trainee_renewable_receive_independence `
  tests.test_control_command_validity `
  -v
```

Expected: all focused tests PASS, including “启动接收” gating, one automatic dispatch per simulation instant, open-loop logging without dispatch, closed-loop dispatch, and the configurable 120-minute default automatic-command validity.

- [ ] **Step 3: Run the full repository suite**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest discover -s tests
```

Record the exact pass/fail count. Investigate every new failure. If the three previously observed stale baseline UI assertions remain, verify they also fail against commit `804a722` before classifying them as unrelated; do not silently ignore them.

- [ ] **Step 4: Run a topology/energy integration test**

Add `test_topology_aware_ac_dc_resources_conserve_energy_end_to_end()` to `tests/test_trainee_renewable_backend_control.py`. Its in-memory snapshot contains:

```text
one AC wind source
one DC PV source
one AC grid-following storage
one DC grid-following storage
one AC balance storage
one DC balance storage
two isolated DC transfer groups
one active and one disconnected ACDC
```

Calculate a plan and assert programmatically:

```text
resource categories match real bus topology
no disconnected resource has a command
no p_ac_set is positive
DC group A never consumes group B capacity
balance storage has no direct p_set
predicted diesel effect counts ACDC export once
charge targets do not exceed verified same-path renewable surplus
```

Run:

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_trainee_renewable_backend_control.RenewableControlPlannerDataQualityTest.test_topology_aware_ac_dc_resources_conserve_energy_end_to_end -v
```

Expected: PASS.

- [ ] **Step 5: Start simulator and trainee WEB services on available ports**

```powershell
D:\anaconda3\python.exe -X utf8 -u -m simu.server --role simulator --host 127.0.0.1 --port 8710 --sim-dir D:\codex\power_simu_web --compute-interval-seconds 1
D:\anaconda3\python.exe -X utf8 -u -m simu.server --role trainee --host 127.0.0.1 --port 8720 --sim-dir D:\codex\power_simu_web --compute-interval-seconds 1
```

If either port is occupied, inspect the existing process and use the next free port rather than terminating unrelated services.

- [ ] **Step 6: Verify the trainee page in a real browser**

At `http://127.0.0.1:8720/renewable`, verify:

```text
all ten tabs render and remain usable without text overlap
misleading names do not affect category
open switch leaves category stable but shows disconnected state
topology path, busbar, and transfer group match the model
closed-loop AC/DC storage commands use independent p_set points
DC resources reserve only same-group ACDC export
balance storage never shows an executable direct target
refreshing another page reads the same backend plan and logs
```

Also pause/stop trainee receive and verify the controller refuses to run; resume receive and issue two requests at the same simulation timestamp, verifying only one automatic command batch is persisted.

- [ ] **Step 7: Inspect final changes without staging**

```powershell
git status --short
git diff --stat
git diff -- simu/resource_topology.py simu/renewable_control.py simu/service.py simu/server.py simu_loop.py simu/web/trainee/index.html simu/web/trainee/app.js simu/web/trainee/styles.css tests
```

Confirm `tmp_runtime_probe/` remains untouched, no source model is unintentionally rewritten, and all pre-existing worktree edits are preserved.

---

## Self-Review Coverage

| Approved requirement | Implemented/tested by |
| --- | --- |
| Topology, never names/block prefixes/device domain, determines side | Tasks 1, 5, 9 |
| Structural side remains stable while active connectivity follows run/switch/dead-island state | Task 2 |
| Nearest real-bus rule, ambiguity/unresolved/invalid handling | Task 1 |
| One active DC island equals one isolated transfer group | Tasks 2, 7 |
| AC/DC wind and PV plus four storage classes | Tasks 3, 5, 9 |
| Grid-following role requires P/PQ plus valid `p_set`; balance role has no direct command | Tasks 5, 6, 7 |
| AC storage before DC storage; later actions use only residual diesel error | Tasks 6, 7 |
| DC resource action uses same-group ACDC export and never positive `p_ac_set` | Task 7 |
| Charging requires verified same-path renewable surplus; no diesel charging | Task 7 |
| SOC linear derating, energy margin, unbounded SOC integration | Tasks 3, 4, 6, 7 |
| Realtime signs are preserved without `abs/max/min` normalization | Tasks 2, 5, 6 |
| Wind speed/irradiance/environment fields do not affect control | Task 5 |
| Predicted diesel counts ACDC export exactly once | Cross-Task Contracts, Task 7 |
| Renewable/storage/ACDC retain independent command targets | Tasks 6, 7, 8 |
| Metrics/logs/trends expose side, role, group, clipping, and projected balance response | Task 8 |
| Ten-tab frontend consumes backend categories without local topology inference | Task 9 |
| Receive prerequisite, one strategy per instant, open/closed loop, 120-minute validity | Task 10 |
| Existing model-scoped backend controller remains the single shared algorithm instance | Tasks 8, 10 |
| No extra SOC/runtime model files and no simulator pause | Tasks 3, 4, 10 |
