# Busbar Runtime Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AC/DC busbar retirement change the electrical topology, keep hybrid load flow solvable when one or both subnetworks are dead, and return zero dynamic results that drive measurements and SVG states correctly.

**Architecture:** Apply `ACRealBs/DCRealBs` states as derived AND constraints on their referenced `ACNode/DCNode` rows in the WEB runtime clone. In the kernel, compute local-reference eligibility before linking ACAC, DCDC, and DCAC islands, then let only eligible endpoints contribute to hybrid component composition. Finally, make `HybridPowerFlowCalc` create sub-solvers only for topology-active nodes and synthesize aligned zero-valued results for skipped subnetworks without changing source operating-state columns.

**Tech Stack:** Python 3.11, NumPy, SciPy sparse graph utilities, existing E-file/PPC models, `unittest`/`pytest`, simulator `run_once()` integration tests.

---

## File Map

### WEB repository: `D:\codex\power_simu_web`

- Create `tests/test_busbar_runtime_status.py`: focused tests for RealBs-to-Node effective state propagation, AND semantics, restoration, and warnings.
- Modify `simu_loop.py`: add the derived busbar/node constraint pass after all explicit runtime states have been applied.
- Modify `tests/test_svg_device_operating_state.py`: Qinling AC/DC busbar retirement end-to-end regressions through `run_once()`.

### Kernel repository: `D:\codex\elec_power_flow\hybrid_power_system_analysis`

- Modify `src/hybrid_power_system_analysis/model/topology.py`: local-reference masks, eligible converter links, and eligible-only component counts.
- Modify `src/hybrid_power_system_analysis/model/ppc_topology.py`: symmetric DCAC reference attachment based on both running endpoints and propagation into hybrid filtering.
- Modify `src/hybrid_power_system_analysis/model/hybrid_model.py`: keep object-model hybrid island grouping consistent with the PPC eligibility rules.
- Modify `src/hybrid_power_system_analysis/lfcore/hybrid_lf.py`: topology-derived `has_ac/has_dc`, skipped-subnet result templates, zero-output clearing, and valid empty-system completion.
- Modify `tests/test_topology_helpers.py`: PPC/object topology regressions for dangling and locally referenced converter terminals.
- Modify `tests/test_hybrid_net_flow_self_contained.py`: dead-AC, dead-DC, both-dead, stale-output, and active-failure solver regressions.

No model source file, SVG file, runtime directory, frontend file, lock, or simulation-thread control is changed.

### Task 1: Propagate Real Busbar State to Effective Node State in WEB Runtime Clones

**Files:**
- Create: `D:\codex\power_simu_web\tests\test_busbar_runtime_status.py`
- Modify: `D:\codex\power_simu_web\simu_loop.py:155-160,986-1068`

- [ ] **Step 1: Write failing unit tests for AC/DC propagation and AND semantics**

Create a compact EBook helper and tests that exercise `apply_dev_stat_book()` directly:

```python
import unittest

import simu_loop


def _book(**blocks):
    return simu_loop.EBook({name: [dict(row) for row in rows] for name, rows in blocks.items()})


class BusbarRuntimeStatusTest(unittest.TestCase):
    def test_retired_real_bus_forces_referenced_ac_and_dc_nodes_off(self):
        model = _book(
            ACNode=[{"idx": 7, "name": "ac-node", "run_stat": 1}],
            ACRealBs=[{"idx": 1, "name": "ac-bus", "node": 7, "run_stat": 1}],
            DCNode=[{"idx": 9, "name": "dc-node", "run_stat": 1}],
            DCRealBs=[{"idx": 1, "name": "dc-bus", "node": 9, "run_stat": 1}],
        )
        stat = _book(
            RunStat=[
                {"dev_type": "ACRealBs", "dev_name": "ac-bus", "run_stat": 0},
                {"dev_type": "DCRealBs", "dev_name": "dc-bus", "run_stat": 0},
            ]
        )

        simu_loop.apply_dev_stat_book(model, stat)

        self.assertEqual("0", str(model.data["ACNode"].data[0]["run_stat"]))
        self.assertEqual("0", str(model.data["DCNode"].data[0]["run_stat"]))

    def test_node_state_is_own_state_and_all_referencing_bus_states(self):
        model = _book(
            ACNode=[
                {"idx": 1, "name": "explicitly-off", "run_stat": 1},
                {"idx": 2, "name": "multi-bus", "run_stat": 1},
            ],
            ACRealBs=[
                {"idx": 1, "name": "bus-a", "node": 1, "run_stat": 1},
                {"idx": 2, "name": "bus-b", "node": 2, "run_stat": 1},
                {"idx": 3, "name": "bus-c", "node": 2, "run_stat": 1},
            ],
        )
        stat = _book(
            RunStat=[
                {"dev_type": "ACNode", "dev_name": "explicitly-off", "run_stat": 0},
                {"dev_type": "ACRealBs", "dev_name": "bus-a", "run_stat": 1},
                {"dev_type": "ACRealBs", "dev_name": "bus-b", "run_stat": 1},
                {"dev_type": "ACRealBs", "dev_name": "bus-c", "run_stat": 0},
            ]
        )

        simu_loop.apply_dev_stat_book(model, stat)

        by_name = {row["name"]: int(row["run_stat"]) for row in model.data["ACNode"].data}
        self.assertEqual(0, by_name["explicitly-off"])
        self.assertEqual(0, by_name["multi-bus"])
```

- [ ] **Step 2: Add failing tests for non-mutation, bad references, and fresh-cycle restoration**

Add these cases to the same class:

```python
    def test_busbar_constraint_does_not_mutate_neighboring_devices(self):
        model = _book(
            DCNode=[{"idx": 5, "name": "bus-node", "run_stat": 1}],
            DCRealBs=[{"idx": 1, "name": "bus", "node": 5, "run_stat": 1}],
            DCBreak=[{"idx": 1, "name": "breaker", "i_node": 5, "j_node": 6, "status": 1, "run_stat": 1}],
            DCBranch=[{"idx": 1, "name": "line", "i_node": 5, "j_node": 6, "run_stat": 1}],
            DCACConverter=[{"idx": 1, "name": "converter", "dc_node": 6, "ac_node": 3, "run_stat": 1}],
        )
        stat = _book(RunStat=[{"dev_type": "DCRealBs", "dev_name": "bus", "run_stat": 0}])

        simu_loop.apply_dev_stat_book(model, stat)

        self.assertEqual(1, int(model.data["DCBreak"].data[0]["run_stat"]))
        self.assertEqual(1, int(model.data["DCBreak"].data[0]["status"]))
        self.assertEqual(1, int(model.data["DCBranch"].data[0]["run_stat"]))
        self.assertEqual(1, int(model.data["DCACConverter"].data[0]["run_stat"]))

    def test_missing_busbar_node_reference_warns_and_leaves_other_nodes_unchanged(self):
        model = _book(
            DCNode=[{"idx": 1, "name": "valid-node", "run_stat": 1}],
            DCRealBs=[{"idx": 1, "name": "bad-bus", "node": 999, "run_stat": 0}],
        )

        with self.assertLogs("SimulationLoop", level="WARNING") as captured:
            simu_loop.apply_dev_stat_book(model, _book())

        self.assertEqual(1, int(model.data["DCNode"].data[0]["run_stat"]))
        self.assertIn("DCRealBs", "\n".join(captured.output))
        self.assertIn("bad-bus", "\n".join(captured.output))
        self.assertIn("999", "\n".join(captured.output))

    def test_fresh_model_clone_restores_node_when_busbar_returns(self):
        source = _book(
            DCNode=[{"idx": 3, "name": "node", "run_stat": 1}],
            DCRealBs=[{"idx": 1, "name": "bus", "node": 3, "run_stat": 1}],
        )
        retired = simu_loop._clone_ebook(source)
        restored = simu_loop._clone_ebook(source)

        simu_loop.apply_dev_stat_book(
            retired,
            _book(RunStat=[{"dev_type": "DCRealBs", "dev_name": "bus", "run_stat": 0}]),
        )
        simu_loop.apply_dev_stat_book(
            restored,
            _book(RunStat=[{"dev_type": "DCRealBs", "dev_name": "bus", "run_stat": 1}]),
        )

        self.assertEqual(0, int(retired.data["DCNode"].data[0]["run_stat"]))
        self.assertEqual(1, int(restored.data["DCNode"].data[0]["run_stat"]))
```

- [ ] **Step 3: Run the new module and verify the intended failures**

Run:

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_busbar_runtime_status -v
```

Expected: the propagation, AND, warning, and restoration assertions fail because `apply_dev_stat_book()` currently never derives node state from RealBs rows.

- [ ] **Step 4: Add the minimal effective-state helper and call it after explicit runtime state application**

Add a module logger beside `setup_logger()` and the helper immediately before `apply_dev_stat_file()`:

```python
LOGGER = logging.getLogger("SimulationLoop")


def _apply_real_bus_node_constraints(model_book: EBook) -> int:
    changed = 0
    for real_bus_type, node_type in (("ACRealBs", "ACNode"), ("DCRealBs", "DCNode")):
        real_bus_block = model_book.data.get(real_bus_type)
        node_block = model_book.data.get(node_type)
        if real_bus_block is None or node_block is None:
            continue

        node_by_idx = {
            _safe_int(row.get("idx"), -1): row
            for row in node_block.data
            if _safe_int(row.get("idx"), -1) >= 0
        }
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
```

At the end of `apply_dev_stat_book()`, after the storage `run_stat` loop and before `return changed`, add:

```python
    changed += _apply_real_bus_node_constraints(model_book)
    return changed
```

This ordering preserves all explicit Node and RealBs updates, then derives only the effective node state. It does not touch adjacent devices.

- [ ] **Step 5: Run the focused tests and the existing runtime-boundary tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_busbar_runtime_status tests.test_model_source_runtime_separation -v
```

Expected: all tests pass, including the existing checks that every simulation step rebuilds its working definition from source files rather than persisting derived runtime state.

- [ ] **Step 6: Commit the WEB state-propagation change**

```powershell
git add simu_loop.py tests/test_busbar_runtime_status.py
git commit -m "fix: apply busbar state to runtime nodes"
```

Run in `D:\codex\power_simu_web`. Do not stage the existing trainee-model files or `tmp_runtime_probe/`.

### Task 2: Enforce Local Reference Eligibility Before Hybrid Island Linking

**Files:**
- Modify: `D:\codex\elec_power_flow\hybrid_power_system_analysis\tests\test_topology_helpers.py`
- Modify: `D:\codex\elec_power_flow\hybrid_power_system_analysis\src\hybrid_power_system_analysis\model\topology.py:825-1019`
- Modify: `D:\codex\elec_power_flow\hybrid_power_system_analysis\src\hybrid_power_system_analysis\model\ppc_topology.py:255-502`
- Modify: `D:\codex\elec_power_flow\hybrid_power_system_analysis\src\hybrid_power_system_analysis\model\hybrid_model.py:134-415`

- [ ] **Step 1: Extend the hybrid fixture so tests can isolate either converter terminal**

Replace `_build_hybrid_island_ppc()` in `tests/test_topology_helpers.py` with this complete fixture so tests can set both converter controls and independently connect or isolate the AC terminal:

```python
def _build_hybrid_island_ppc(
    *,
    dc_breaker_status=1,
    connect_ac_terminal=False,
    ac_control_type="PH",
    dc_control_type="NONE",
):
    from model.ppc_topology import build_hybrid_ppc_with_topology_from_efile_rows

    rows = {
        "Model": _table("path name p_base u_unit p_unit i_unit", [["test", "rooted_hybrid", 100, "V", "kW", "A"]]),
        "ACNode": _table(
            "idx name vbase voltage angle run_stat",
            [
                [1, "ac_main_bus", 380, 380, 0, 1],
                [2, "converter_ac_terminal", 380, 380, 0, 1],
            ],
        ),
        "ACRealBs": _table("idx name node run_stat", [[1, "ac_root", 1, 1]]),
        "ACGenerator": _table(
            "idx name node control_type p_set q_set v_set alpha run_stat",
            [
                [1, "ac_main_slack", 1, "PH", 0, 0, 380, 1, 1],
                [2, "converter_side_source", 2, "PQ", 5, 0, 380, 1, 1],
            ],
        ),
        "ACLoad": _table(
            "idx name node pbase pv0 pv1 pv2 qbase qv0 qv1 qv2 run_stat",
            [[1, "ac_main_load", 1, 10, 1, 0, 0, 2, 1, 0, 0, 1]],
        ),
        "DCNode": _table(
            "idx name vbase voltage run_stat",
            [
                [1, "dc_main_bus", 750, 750, 1],
                [2, "converter_dc_terminal", 750, 750, 1],
            ],
        ),
        "DCRealBs": _table("idx name node run_stat", [[1, "dc_root", 1, 1]]),
        "DCGenerator": _table(
            "idx name node control_type v_set p_set i_set run_stat",
            [[1, "dc_main_voltage_source", 1, "V", 750, 0, 0, 1]],
        ),
        "DCLoad": _table(
            "idx name node pbase pv0 pv1 pv2 run_stat",
            [[1, "dc_main_load", 1, 10, 1, 0, 0, 1]],
        ),
        "DCBreak": _table(
            "idx name i_node j_node status run_stat",
            [[1, "converter_breaker", 1, 2, dc_breaker_status, 1]],
        ),
        "DCACConverter": _table(
            "idx name ac_node dc_node ac_control_type dc_control_type p_ac_set q_ac_set v_ac_set v_dc_set run_stat r1 r2",
            [
                [
                    1,
                    "grid_converter",
                    2,
                    2,
                    ac_control_type,
                    dc_control_type,
                    0,
                    0,
                    380,
                    750,
                    1,
                    0,
                    0,
                ]
            ],
        ),
    }
    if connect_ac_terminal:
        rows["ACBranch"] = _table(
            "idx name i_node j_node r x b run_stat",
            [[1, "converter_ac_tie", 1, 2, 0.01, 0.1, 0.0, 1]],
        )
    return build_hybrid_ppc_with_topology_from_efile_rows(Path("hybrid_island.e"), rows)
```

- [ ] **Step 2: Write failing PPC tests for dangling DC and AC terminals**

Add:

```python
    def test_hybrid_pq_none_converter_cannot_keep_dangling_dc_terminal_alive(self):
        ppc = _build_hybrid_island_ppc(
            dc_breaker_status=0,
            connect_ac_terminal=True,
            ac_control_type="PQ",
            dc_control_type="NONE",
        )

        self.assertEqual([True], ppc["ac"]["_topology_arrays"].island_alive_mask.tolist())
        self.assertEqual([True, False], ppc["dc"]["_topology_arrays"].island_alive_mask.tolist())
        self.assertFalse(ppc["dc"]["_topology_arrays"].node_alive_mask[1])

    def test_hybrid_pq_none_converter_cannot_keep_dangling_ac_terminal_alive(self):
        ppc = _build_hybrid_island_ppc(
            dc_breaker_status=1,
            connect_ac_terminal=False,
            ac_control_type="PQ",
            dc_control_type="NONE",
        )

        self.assertEqual([True, False], ppc["ac"]["_topology_arrays"].island_alive_mask.tolist())
        self.assertEqual([True], ppc["dc"]["_topology_arrays"].island_alive_mask.tolist())

    def test_hybrid_converter_remains_connected_when_both_endpoint_islands_have_local_references(self):
        ppc = _build_hybrid_island_ppc(
            dc_breaker_status=1,
            connect_ac_terminal=False,
            ac_control_type="PH",
            dc_control_type="NONE",
        )

        self.assertEqual([True, True], ppc["ac"]["_topology_arrays"].island_alive_mask.tolist())
        self.assertEqual([True], ppc["dc"]["_topology_arrays"].island_alive_mask.tolist())
```

- [ ] **Step 3: Write failing tests proving ineligible loads/generators cannot change another component's composition**

Add two row builders before `TopologyHelperTest`. Each contains exactly two electrical islands before the converter link. Island A has one running balance generator and no load; island B has one running load and no local reference:

```python
def _build_acac_source_to_unreferenced_load_ppc():
    from model.ac_array_model import build_ac_ppc_from_efile_rows
    from model.ppc_topology import ensure_ac_ppc_topology

    rows = {
        "Model": _table("path name p_base u_unit p_unit i_unit", [["test", "acac_local_ref", 100, "V", "kW", "A"]]),
        "ACNode": _table(
            "idx name vbase voltage angle run_stat",
            [[1, "source-node", 380, 380, 0, 1], [2, "load-node", 380, 380, 0, 1]],
        ),
        "ACGenerator": _table(
            "idx name node control_type p_set q_set v_set alpha run_stat",
            [[1, "source-only-slack", 1, "PH", 0, 0, 380, 1, 1]],
        ),
        "ACLoad": _table(
            "idx name node pbase pv0 pv1 pv2 qbase qv0 qv1 qv2 run_stat",
            [[1, "unreferenced-load", 2, 10, 1, 0, 0, 2, 1, 0, 0, 1]],
        ),
        "ACACConverter": _table(
            "idx name i_node j_node r1 r2 i_control_type j_control_type p_set i_q_set j_q_set i_v_set j_v_set run_stat",
            [[1, "pq-link", 1, 2, 0, 0, "PQ", "PQ", 0, 0, 0, 380, 380, 1]],
        ),
    }
    return ensure_ac_ppc_topology(build_ac_ppc_from_efile_rows(Path("acac_local_ref.e"), rows))


def _build_dcdc_source_to_unreferenced_load_ppc():
    from model.dc_array_model import build_dc_ppc_from_efile_rows
    from model.ppc_topology import ensure_dc_ppc_topology

    rows = {
        "Model": _table("path name p_base u_unit p_unit i_unit", [["test", "dcdc_local_ref", 100, "V", "kW", "A"]]),
        "DCNode": _table(
            "idx name vbase voltage run_stat",
            [[1, "source-node", 750, 750, 1], [2, "load-node", 750, 750, 1]],
        ),
        "DCGenerator": _table(
            "idx name node control_type v_set p_set i_set run_stat",
            [[1, "source-only-voltage", 1, "V", 750, 0, 0, 1]],
        ),
        "DCLoad": _table(
            "idx name node pbase pv0 pv1 pv2 run_stat",
            [[1, "unreferenced-load", 2, 10, 1, 0, 0, 1]],
        ),
        "DCDCConverter": _table(
            "idx name i_node j_node i_control_type j_control_type p_set i_set v_set run_stat r1 r2",
            [[1, "none-link", 1, 2, "NONE", "NONE", 0, 0, 750, 1, 0, 0]],
        ),
    }
    return ensure_dc_ppc_topology(build_dc_ppc_from_efile_rows(Path("dcdc_local_ref.e"), rows))
```

Assert both islands remain dead instead of allowing the unreferenced load to make the source-only component operational:

```python
    def test_acac_does_not_count_load_from_unreferenced_endpoint(self):
        ppc = _build_acac_source_to_unreferenced_load_ppc()
        arrays = ppc["_topology_arrays"]
        self.assertEqual([False, False], arrays.island_alive_mask.tolist())
        self.assertEqual([False], arrays.devices["acac"].alive_mask.tolist())

    def test_dcdc_does_not_count_load_from_unreferenced_endpoint(self):
        ppc = _build_dcdc_source_to_unreferenced_load_ppc()
        arrays = ppc["_topology_arrays"]
        self.assertEqual([False, False], arrays.island_alive_mask.tolist())
        self.assertEqual([False], arrays.devices["dcdc"].alive_mask.tolist())
```

- [ ] **Step 4: Write a failing PPC/object consistency test**

Use the dangling DC fixture for both representations:

```python
    def test_hybrid_object_topology_matches_ppc_local_reference_filter(self):
        from model.ac_array_model import build_ac_network_from_ppc
        from model.dc_array_model import build_dc_network_from_ppc
        from model.hybrid_array_model import build_hybrid_model_from_ppc

        ppc = _build_hybrid_island_ppc(
            dc_breaker_status=0,
            connect_ac_terminal=True,
            ac_control_type="PQ",
            dc_control_type="NONE",
        )
        object_ppc = dict(ppc)
        object_ppc["ac_network"] = build_ac_network_from_ppc(ppc["ac"])
        object_ppc["dc_network"] = build_dc_network_from_ppc(ppc["dc"])
        network = build_hybrid_model_from_ppc(object_ppc)

        network.topo()

        self.assertEqual(
            ppc["ac"]["_topology_arrays"].island_alive_mask.tolist(),
            [island.is_alive for island in network.ac.islands],
        )
        self.assertEqual(
            ppc["dc"]["_topology_arrays"].island_alive_mask.tolist(),
            [island.is_alive for island in network.dc.islands],
        )
        self.assertFalse(network.dcac_converters[0].is_alive)
```

- [ ] **Step 5: Run the focused topology tests and verify failure**

```powershell
D:\anaconda3\python.exe -X utf8 -m pytest tests/test_topology_helpers.py -q
```

Expected: new dangling-terminal/composition tests fail because all running converter links are currently added before local-reference validation.

- [ ] **Step 6: Filter terminal links and device counts by local-reference masks**

In `model/topology.py`, add `_local_reference_island_mask()` and replace `_append_terminal_island_links()` with the complete implementation below:

```python
def _local_reference_island_mask(topology: Optional[GridTopologyArrays]) -> np.ndarray:
    if topology is None:
        return np.zeros(0, dtype=bool)
    return np.asarray(topology.island_reference_bus_pos, dtype=np.int32) >= 0


def _append_terminal_island_links(
    topology: Optional[GridTopologyArrays],
    local_reference_mask: np.ndarray,
    terminals: Sequence[Optional[TerminalDeviceTopologyInput]],
    offset: int,
    left_parts,
    right_parts,
) -> None:
    if topology is None:
        return
    node_count = int(topology.node_ids.size)
    for terminal in terminals:
        if terminal is None:
            continue
        i_node_pos = np.asarray(terminal.i_node_pos, dtype=np.int32).reshape(-1)
        j_node_pos = np.asarray(terminal.j_node_pos, dtype=np.int32).reshape(-1)
        run_mask = np.asarray(terminal.run_mask, dtype=bool).reshape(-1)
        count = min(i_node_pos.size, j_node_pos.size, run_mask.size)
        if count == 0:
            continue
        i_node_pos = i_node_pos[:count]
        j_node_pos = j_node_pos[:count]
        valid = (
            run_mask[:count]
            & (i_node_pos >= 0)
            & (j_node_pos >= 0)
            & (i_node_pos < node_count)
            & (j_node_pos < node_count)
        )
        if np.any(valid):
            rows = np.flatnonzero(valid)
            valid[rows] &= (
                topology.node_run_mask[i_node_pos[rows]]
                & topology.node_run_mask[j_node_pos[rows]]
            )
        if not np.any(valid):
            continue
        i_islands = topology.node_to_island_pos[i_node_pos[valid]]
        j_islands = topology.node_to_island_pos[j_node_pos[valid]]
        valid_islands = (
            (i_islands >= 0)
            & (j_islands >= 0)
            & (i_islands != j_islands)
            & local_reference_mask[i_islands]
            & local_reference_mask[j_islands]
        )
        if np.any(valid_islands):
            left_parts.append(i_islands[valid_islands] + int(offset))
            right_parts.append(j_islands[valid_islands] + int(offset))
```

Replace `hybrid_operational_island_masks()` with this complete local-reference-aware implementation:

```python
def hybrid_operational_island_masks(
    ac_topology: Optional[GridTopologyArrays],
    dc_topology: Optional[GridTopologyArrays],
    *,
    ac_balance_generator_islands=(),
    ac_generator_islands=(),
    ac_load_islands=(),
    dc_balance_generator_islands=(),
    dc_generator_islands=(),
    dc_load_islands=(),
    ac_linked_terminals: Sequence[Optional[TerminalDeviceTopologyInput]] = (),
    dc_linked_terminals: Sequence[Optional[TerminalDeviceTopologyInput]] = (),
    dcac_ac_node_ids=(),
    dcac_dc_node_ids=(),
    dcac_run_mask=(),
) -> Tuple[np.ndarray, np.ndarray]:
    """Judge hybrid components after every endpoint has a local reference."""

    ac_count = 0 if ac_topology is None else int(ac_topology.island_ids.size)
    dc_count = 0 if dc_topology is None else int(dc_topology.island_ids.size)
    total_count = ac_count + dc_count
    if total_count == 0:
        return np.zeros(ac_count, dtype=bool), np.zeros(dc_count, dtype=bool)

    ac_local = _local_reference_island_mask(ac_topology)
    dc_local = _local_reference_island_mask(dc_topology)
    local_eligible = np.concatenate((ac_local, dc_local))

    left_parts = []
    right_parts = []
    _append_terminal_island_links(
        ac_topology,
        ac_local,
        ac_linked_terminals,
        0,
        left_parts,
        right_parts,
    )
    _append_terminal_island_links(
        dc_topology,
        dc_local,
        dc_linked_terminals,
        ac_count,
        left_parts,
        right_parts,
    )

    if ac_topology is not None and dc_topology is not None:
        ac_node_ids = np.asarray(dcac_ac_node_ids, dtype=np.int64).reshape(-1)
        dc_node_ids = np.asarray(dcac_dc_node_ids, dtype=np.int64).reshape(-1)
        run_mask = np.asarray(dcac_run_mask, dtype=bool).reshape(-1)
        count = min(ac_node_ids.size, dc_node_ids.size, run_mask.size)
        if count:
            ac_node_pos = _map_node_positions(
                ac_node_ids[:count],
                _make_node_pos_lookup(ac_topology.node_ids),
            )
            dc_node_pos = _map_node_positions(
                dc_node_ids[:count],
                _make_node_pos_lookup(dc_topology.node_ids),
            )
            valid = (
                run_mask[:count]
                & (ac_node_pos >= 0)
                & (dc_node_pos >= 0)
                & (ac_node_pos < ac_topology.node_ids.size)
                & (dc_node_pos < dc_topology.node_ids.size)
            )
            if np.any(valid):
                rows = np.flatnonzero(valid)
                valid[rows] &= (
                    ac_topology.node_run_mask[ac_node_pos[rows]]
                    & dc_topology.node_run_mask[dc_node_pos[rows]]
                )
            if np.any(valid):
                ac_islands = ac_topology.node_to_island_pos[ac_node_pos[valid]]
                dc_islands = dc_topology.node_to_island_pos[dc_node_pos[valid]]
                valid_islands = (
                    (ac_islands >= 0)
                    & (dc_islands >= 0)
                    & ac_local[ac_islands]
                    & dc_local[dc_islands]
                )
                if np.any(valid_islands):
                    left_parts.append(ac_islands[valid_islands])
                    right_parts.append(dc_islands[valid_islands] + ac_count)

    if left_parts:
        left = np.concatenate(left_parts).astype(np.int32, copy=False)
        right = np.concatenate(right_parts).astype(np.int32, copy=False)
    else:
        left = _EMPTY_INT
        right = _EMPTY_INT
    graph = coo_matrix(
        (np.ones(left.size, dtype=np.int8), (left, right)),
        shape=(total_count, total_count),
    ).tocsr()
    component_count, component_by_island = connected_components(
        graph,
        directed=False,
        return_labels=True,
    )

    def component_counts(island_positions, island_count, offset, local_mask):
        positions = np.asarray(island_positions, dtype=np.int64).reshape(-1)
        valid = (positions >= 0) & (positions < int(island_count))
        if np.any(valid):
            valid_rows = np.flatnonzero(valid)
            valid[valid_rows] &= local_mask[positions[valid_rows]]
        if not np.any(valid):
            return np.zeros(component_count, dtype=np.int64)
        components = component_by_island[positions[valid] + int(offset)]
        return np.bincount(components, minlength=component_count).astype(
            np.int64,
            copy=False,
        )

    reference_count = np.bincount(
        component_by_island,
        weights=local_eligible.astype(np.int8),
        minlength=component_count,
    ).astype(np.int64, copy=False)
    balance_count = component_counts(
        ac_balance_generator_islands,
        ac_count,
        0,
        ac_local,
    )
    balance_count += component_counts(
        dc_balance_generator_islands,
        dc_count,
        ac_count,
        dc_local,
    )
    generator_count = component_counts(ac_generator_islands, ac_count, 0, ac_local)
    generator_count += component_counts(
        dc_generator_islands,
        dc_count,
        ac_count,
        dc_local,
    )
    load_count = component_counts(ac_load_islands, ac_count, 0, ac_local)
    load_count += component_counts(dc_load_islands, dc_count, ac_count, dc_local)

    component_alive = (reference_count > 0) & (balance_count > 0)
    source_only = (balance_count == 1) & (generator_count == 1) & (load_count == 0)
    component_alive &= ~source_only
    island_alive = local_eligible & component_alive[component_by_island]
    return island_alive[:ac_count], island_alive[ac_count:]
```

- [ ] **Step 7: Make DCAC local-reference attachment symmetric and physical-endpoint-aware**

In `model/ppc_topology.py`, extend the hybrid-array import:

```python
from model.hybrid_array_model import (
    DCAC_AC_CONTROL_CODE,
    DCAC_COLS,
    DCAC_DC_CONTROL_CODE,
    build_hybrid_ppc_only_from_efile_rows,
)
```

Add the active-node helper and replace both DCAC reference-attachment functions with these complete implementations:

```python
def _running_node_ids(ppc, cols):
    table = None if ppc is None else np.asarray(ppc.get("bus", ()), dtype=np.float64)
    if table is None or not table.size:
        return np.empty(0, dtype=np.int64)
    running = table[:, cols["run_stat"]].astype(np.int64, copy=False) == 1
    return table[running, cols["idx"]].astype(np.int64, copy=False)


def _attach_hybrid_dc_reference_nodes(ppc: Dict) -> None:
    ac_ppc = ppc.get("ac")
    dc_ppc = ppc.get("dc")
    dcac = ppc.get("dcac")
    if (
        ac_ppc is None
        or dc_ppc is None
        or dcac is None
        or getattr(dcac, "size", 0) == 0
    ):
        return
    dcac = np.asarray(dcac, dtype=np.float64)
    ctrl = dcac[:, DCAC_COLS["dc_control_type"]].astype(np.int64, copy=False)
    run = dcac[:, DCAC_COLS["run_stat"]].astype(np.int64, copy=False) == 1
    active_ac_ids = _running_node_ids(ac_ppc, AC_BUS_COLS)
    active_dc_ids = _running_node_ids(dc_ppc, DC_BUS_COLS)
    dcv_mask = (
        run
        & (ctrl == DCAC_DC_CONTROL_CODE["V"])
        & np.isin(dcac[:, DCAC_COLS["ac_node"]].astype(int), active_ac_ids)
        & np.isin(dcac[:, DCAC_COLS["dc_node"]].astype(int), active_dc_ids)
    )
    if not dcv_mask.any():
        had_external_refs = (
            "_external_voltage_reference_node_ids" in dc_ppc
            or "_external_voltage_reference_pu" in dc_ppc
        )
        dc_ppc.pop("_external_voltage_reference_node_ids", None)
        dc_ppc.pop("_external_voltage_reference_pu", None)
        if had_external_refs:
            dc_ppc.pop("_topology_arrays", None)
        return

    ref_nodes, unique_pos = np.unique(
        dcac[dcv_mask, DCAC_COLS["dc_node"]].astype(np.int64, copy=False),
        return_index=True,
    )
    ref_values = dcac[dcv_mask, DCAC_COLS["v_dc_set"]][unique_pos].astype(
        np.float64,
        copy=False,
    )
    old_nodes = np.asarray(
        dc_ppc.get("_external_voltage_reference_node_ids", []),
        dtype=np.int64,
    )
    old_values = np.asarray(
        dc_ppc.get("_external_voltage_reference_pu", []),
        dtype=np.float64,
    )
    changed = (
        old_nodes.shape != ref_nodes.shape
        or old_values.shape != ref_values.shape
        or not np.array_equal(old_nodes, ref_nodes)
        or not np.allclose(old_values, ref_values)
    )
    dc_ppc["_external_voltage_reference_node_ids"] = ref_nodes
    dc_ppc["_external_voltage_reference_pu"] = ref_values
    if changed:
        dc_ppc.pop("_topology_arrays", None)


def _attach_hybrid_ac_reference_nodes(ppc: Dict) -> None:
    ac_ppc = ppc.get("ac")
    dc_ppc = ppc.get("dc")
    dcac = ppc.get("dcac")
    if (
        ac_ppc is None
        or dc_ppc is None
        or dcac is None
        or getattr(dcac, "size", 0) == 0
    ):
        return
    dcac = np.asarray(dcac, dtype=np.float64)
    ctrl = dcac[:, DCAC_COLS["ac_control_type"]].astype(np.int64, copy=False)
    run = dcac[:, DCAC_COLS["run_stat"]].astype(np.int64, copy=False) == 1
    active_ac_ids = _running_node_ids(ac_ppc, AC_BUS_COLS)
    active_dc_ids = _running_node_ids(dc_ppc, DC_BUS_COLS)
    acv_mask = (
        run
        & (ctrl == DCAC_AC_CONTROL_CODE["PH"])
        & np.isin(dcac[:, DCAC_COLS["ac_node"]].astype(int), active_ac_ids)
        & np.isin(dcac[:, DCAC_COLS["dc_node"]].astype(int), active_dc_ids)
    )
    if not acv_mask.any():
        had_external_refs = (
            "_external_angle_reference_node_ids" in ac_ppc
            or "_external_voltage_reference_pu" in ac_ppc
        )
        ac_ppc.pop("_external_angle_reference_node_ids", None)
        ac_ppc.pop("_external_voltage_reference_pu", None)
        if had_external_refs:
            ac_ppc.pop("_topology_arrays", None)
        return

    ref_nodes, unique_pos = np.unique(
        dcac[acv_mask, DCAC_COLS["ac_node"]].astype(np.int64, copy=False),
        return_index=True,
    )
    ref_values = dcac[acv_mask, DCAC_COLS["v_ac_set"]][unique_pos].astype(
        np.float64,
        copy=False,
    )
    old_nodes = np.asarray(
        ac_ppc.get("_external_angle_reference_node_ids", []),
        dtype=np.int64,
    )
    old_values = np.asarray(
        ac_ppc.get("_external_voltage_reference_pu", []),
        dtype=np.float64,
    )
    changed = (
        old_nodes.shape != ref_nodes.shape
        or old_values.shape != ref_values.shape
        or not np.array_equal(old_nodes, ref_nodes)
        or not np.allclose(old_values, ref_values)
    )
    ac_ppc["_external_angle_reference_node_ids"] = ref_nodes
    ac_ppc["_external_voltage_reference_pu"] = ref_values
    if changed:
        ac_ppc.pop("_topology_arrays", None)
```

These functions only qualify topology references. Do not modify `_install_ac_converter_voltage_control_nodes()` or its existing `PV/PH` solver behavior.

- [ ] **Step 8: Apply the same endpoint eligibility in object-model hybrid topology**

In `model/hybrid_model.py`, add a method that captures local references after the first deferred AC/DC topology pass and augments only the converter-controlled side:

```python
    def _local_reference_island_ids(self):
        ac_ids = {id(island) for island in self.ac.islands if island.is_alive}
        dc_ids = {id(island) for island in self.dc.islands if island.is_alive}
        for conv in self.dcac_converters:
            ac_node = self.ac.node_dict.get(conv.ac_node)
            dc_node = self.dc.node_dict.get(conv.dc_node)
            if (
                conv.run_stat != 1
                or ac_node is None
                or dc_node is None
                or ac_node.run_stat != 1
                or dc_node.run_stat != 1
                or ac_node.isl_obj is None
                or dc_node.isl_obj is None
            ):
                continue
            if str(conv.ac_control_type).upper() == "PH":
                ac_ids.add(id(ac_node.isl_obj))
            if str(conv.dc_control_type).upper() == "V":
                dc_ids.add(id(dc_node.isl_obj))
        for conv in self.acac_converters:
            i_node = self.ac.node_dict.get(conv.i_node)
            j_node = self.ac.node_dict.get(conv.j_node)
            if conv.run_stat != 1 or i_node is None or j_node is None:
                continue
            if i_node.run_stat != 1 or j_node.run_stat != 1:
                continue
            if i_node.isl_obj is not None and str(conv.i_control_type).upper() == "PH":
                ac_ids.add(id(i_node.isl_obj))
            if j_node.isl_obj is not None and str(conv.j_control_type).upper() == "PH":
                ac_ids.add(id(j_node.isl_obj))
        return ac_ids, dc_ids
```

In `_build_hybrid_topo()`, insert the local-reference sets and `eligible_link()` immediately after the nested `union()` helper, then replace the three converter-link loops with the complete block below:

```python
        ac_local_ids, dc_local_ids = self._local_reference_island_ids()

        def eligible_link(
            physical_alive,
            left_island,
            right_island,
            left_ids,
            right_ids,
            left_node,
            right_node,
        ):
            if not physical_alive:
                return False
            if evaluate_operational:
                return id(left_island) in left_ids and id(right_island) in right_ids
            return bool(left_node.is_alive and right_node.is_alive)

        for conv in self.dcac_converters:
            ac_node = self.ac.node_dict.get(conv.ac_node)
            dc_node = self.dc.node_dict.get(conv.dc_node)
            conv.ac_node_obj = ac_node
            conv.dc_node_obj = dc_node
            conv.ac_isl_obj = None if ac_node is None else ac_node.isl_obj
            conv.dc_isl_obj = None if dc_node is None else dc_node.isl_obj
            physical_alive = (
                conv.run_stat == 1
                and ac_node is not None
                and dc_node is not None
                and getattr(ac_node, "run_stat", 0) == 1
                and getattr(dc_node, "run_stat", 0) == 1
                and conv.ac_isl_obj is not None
                and conv.dc_isl_obj is not None
            )
            link_alive = eligible_link(
                physical_alive,
                conv.ac_isl_obj,
                conv.dc_isl_obj,
                ac_local_ids,
                dc_local_ids,
                ac_node,
                dc_node,
            )
            conv.is_alive = link_alive
            if link_alive:
                union(conv.ac_isl_obj, conv.dc_isl_obj)

        for conv in self.acac_converters:
            i_node = self.ac.node_dict.get(conv.i_node)
            j_node = self.ac.node_dict.get(conv.j_node)
            conv.i_node_obj = i_node
            conv.j_node_obj = j_node
            conv.i_isl_obj = None if i_node is None else i_node.isl_obj
            conv.j_isl_obj = None if j_node is None else j_node.isl_obj
            physical_alive = (
                conv.run_stat == 1
                and i_node is not None
                and j_node is not None
                and getattr(i_node, "run_stat", 0) == 1
                and getattr(j_node, "run_stat", 0) == 1
                and conv.i_isl_obj is not None
                and conv.j_isl_obj is not None
            )
            link_alive = eligible_link(
                physical_alive,
                conv.i_isl_obj,
                conv.j_isl_obj,
                ac_local_ids,
                ac_local_ids,
                i_node,
                j_node,
            )
            conv.is_alive = link_alive
            if link_alive:
                union(conv.i_isl_obj, conv.j_isl_obj)

        for conv in self.dc.dcdc_converters:
            i_node = getattr(conv, "i_node_obj", None)
            j_node = getattr(conv, "j_node_obj", None)
            physical_alive = (
                getattr(conv, "run_stat", 0) == 1
                and i_node is not None
                and j_node is not None
                and getattr(i_node, "run_stat", 0) == 1
                and getattr(j_node, "run_stat", 0) == 1
                and i_node.isl_obj is not None
                and j_node.isl_obj is not None
            )
            link_alive = eligible_link(
                physical_alive,
                None if i_node is None else i_node.isl_obj,
                None if j_node is None else j_node.isl_obj,
                dc_local_ids,
                dc_local_ids,
                i_node,
                j_node,
            )
            conv.is_alive = link_alive
            if link_alive:
                union(i_node.isl_obj, j_node.isl_obj)
```

At the end of `_build_hybrid_topo()`, replace the operational evaluation call with:

```python
        if evaluate_operational:
            return self._evaluate_hybrid_operational_islands(ac_local_ids, dc_local_ids)
        return set(), set()
```

Replace `_evaluate_hybrid_operational_islands()` with the complete implementation below so reference qualification is local while generator/load/source-only counting keeps the existing domain rules:

```python
    def _evaluate_hybrid_operational_islands(self, ac_local_ids, dc_local_ids):
        ac_operational = set()
        dc_operational = set()
        ac_auto_balance_ids = {
            id(gen) for gen in getattr(self.ac, "_auto_slack_generators", ())
        }
        for hybrid_island in self.hybrid_islands:
            has_reference = any(
                id(island) in ac_local_ids for island in hybrid_island.ac_islands
            ) or any(
                id(island) in dc_local_ids for island in hybrid_island.dc_islands
            )
            generator_count = 0
            balance_count = 0
            load_count = 0

            for gen in self.ac.generators:
                node = getattr(gen, "node_obj", None)
                if (
                    getattr(gen, "run_stat", 0) != 1
                    or node is None
                    or getattr(node, "run_stat", 0) != 1
                    or node.isl_obj is None
                    or node.isl_obj.hybrid_isl_obj is not hybrid_island
                ):
                    continue
                generator_count += 1
                if (
                    str(getattr(gen, "control_type", "")).upper()
                    in {"V", "SLACK", "PH"}
                    or id(gen) in ac_auto_balance_ids
                ):
                    balance_count += 1

            for gen in self.dc.generators:
                node = getattr(gen, "node_obj", None)
                if (
                    getattr(gen, "run_stat", 0) != 1
                    or node is None
                    or getattr(node, "run_stat", 0) != 1
                    or node.isl_obj is None
                    or node.isl_obj.hybrid_isl_obj is not hybrid_island
                ):
                    continue
                generator_count += 1
                if str(getattr(gen, "control_type", "")).upper() == "V":
                    balance_count += 1

            for loads, node_dict in (
                (self.ac.loads, self.ac.node_dict),
                (self.dc.loads, self.dc.node_dict),
            ):
                for load in loads:
                    node = getattr(load, "node_obj", None) or node_dict.get(int(load.node))
                    if (
                        getattr(load, "run_stat", 0) == 1
                        and node is not None
                        and getattr(node, "run_stat", 0) == 1
                        and node.isl_obj is not None
                        and node.isl_obj.hybrid_isl_obj is hybrid_island
                    ):
                        load_count += 1

            source_only = (
                balance_count == 1 and generator_count == 1 and load_count == 0
            )
            hybrid_island.is_alive = (
                has_reference and balance_count > 0 and not source_only
            )
            if hybrid_island.is_alive:
                ac_operational.update(
                    island.idx for island in hybrid_island.ac_islands
                )
                dc_operational.update(
                    island.idx for island in hybrid_island.dc_islands
                )
            for conv in (
                *hybrid_island.dcac_converters,
                *hybrid_island.dcdc_converters,
                *hybrid_island.acac_converters,
            ):
                conv.is_alive = bool(conv.is_alive and hybrid_island.is_alive)

        return ac_operational, dc_operational
```

- [ ] **Step 9: Run topology tests and relevant existing control tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m pytest tests/test_topology_helpers.py tests/test_hybrid_net_flow_self_contained.py -q
```

Expected: all topology tests pass, including the existing source-only-island, auto-slack, Qinling preparation, and converter-control tests.

- [ ] **Step 10: Commit the kernel topology change**

```powershell
git add src/hybrid_power_system_analysis/model/topology.py src/hybrid_power_system_analysis/model/ppc_topology.py src/hybrid_power_system_analysis/model/hybrid_model.py tests/test_topology_helpers.py
git commit -m "fix: require local references for hybrid links"
```

Run in `D:\codex\elec_power_flow\hybrid_power_system_analysis`. Do not stage `output/doc/IMU模块测量杆头摇晃位移方法.docx`.

### Task 3: Skip Fully Dead AC/DC Subnetworks and Produce Zero Results

**Files:**
- Modify: `D:\codex\elec_power_flow\hybrid_power_system_analysis\tests\test_hybrid_net_flow_self_contained.py`
- Modify: `D:\codex\elec_power_flow\hybrid_power_system_analysis\src\hybrid_power_system_analysis\lfcore\hybrid_lf.py:64-112,741-1047,2469-2588,2714-3206`

- [ ] **Step 1: Add an independent AC/DC fixture with controllable node states**

Add near the test helpers:

```python
def _table(header, rows):
    return {"header_list": header.split(), "rows": rows}


def _independent_hybrid_rows(*, ac_run=1, dc_run=1, stale=0.0, include_converter=False):
    rows = {
        "Model": _table("path name p_base u_unit p_unit i_unit", [["test", "independent", 100, "V", "kW", "A"]]),
        "ACNode": _table("idx name vbase voltage angle run_stat", [[1, "ac-bus", 380, stale, stale, ac_run]]),
        "ACGenerator": _table(
            "idx name node control_type p_set q_set v_set alpha run_stat p q current",
            [[1, "ac-source", 1, "PH", 0, 0, 380, 1, 1, stale, stale, stale]],
        ),
        "ACLoad": _table(
            "idx name node pbase pv0 pv1 pv2 qbase qv0 qv1 qv2 run_stat p q current",
            [[1, "ac-load", 1, 10, 1, 0, 0, 2, 1, 0, 0, 1, stale, stale, stale]],
        ),
        "DCNode": _table("idx name vbase voltage run_stat", [[1, "dc-bus", 750, stale, dc_run]]),
        "DCGenerator": _table(
            "idx name node control_type v_set p_set i_set run_stat p current",
            [[1, "dc-source", 1, "V", 750, 0, 0, 1, stale, stale]],
        ),
        "DCLoad": _table(
            "idx name node pbase pv0 pv1 pv2 run_stat p current",
            [[1, "dc-load", 1, 10, 1, 0, 0, 1, stale, stale]],
        ),
    }
    if include_converter:
        rows["DCACConverter"] = _table(
            "idx name ac_node dc_node r1 r2 ac_control_type dc_control_type p_ac_set q_ac_set v_ac_set v_dc_set run_stat dc_p ac_p ac_q dc_i ac_i",
            [[1, "inactive-converter", 1, 1, 0, 0, "PQ", "NONE", 0, 0, 380, 750, 1, stale, stale, stale, stale, stale]],
        )
    return rows
```

Use `_build_lf_network_from_hybrid_rows(Path("independent.e"), rows)` so tests exercise the same lightweight PPC path as the WEB simulator.

- [ ] **Step 2: Write failing tests for one dead side and aligned zero tables**

```python
    def test_hybrid_solver_skips_dead_dc_and_solves_live_ac(self):
        import numpy as np
        from ac_array_model import BUS_COLS as AC_BUS_COLS
        from dc_array_model import BUS_COLS as DC_BUS_COLS, GEN_COLS as DC_GEN_COLS
        from lfcore.hybrid_lf import HybridPowerFlowCalc, _build_lf_network_from_hybrid_rows

        network = _build_lf_network_from_hybrid_rows(
            Path("dead_dc.e"),
            _independent_hybrid_rows(ac_run=1, dc_run=0, stale=99.0),
        )
        calc = HybridPowerFlowCalc(network, result_mode="array", verbose=False)
        rc = calc.run()

        self.assertEqual(0, rc)
        self.assertTrue(calc.converged)
        self.assertIsNotNone(calc.ac_calc)
        self.assertIsNone(calc.dc_calc)
        self.assertEqual(1, calc.result["dc"]["bus"].shape[0])
        self.assertEqual(1, calc.result["dc"]["gen"].shape[0])
        self.assertTrue(np.all(calc.result["dc"]["bus"][:, DC_BUS_COLS["voltage"]] == 0.0))
        self.assertTrue(np.all(calc.result["dc"]["gen"][:, [DC_GEN_COLS["p"], DC_GEN_COLS["current"]]] == 0.0))
        self.assertEqual(0, int(calc.result["dc"]["bus"][0, DC_BUS_COLS["run_stat"]]))
        self.assertEqual(1, int(calc.result["dc"]["gen"][0, DC_GEN_COLS["run_stat"]]))
        self.assertGreater(float(calc.result["ac"]["bus"][0, AC_BUS_COLS["voltage"]]), 0.0)

    def test_hybrid_solver_skips_dead_ac_and_solves_live_dc(self):
        import numpy as np
        from ac_array_model import BUS_COLS as AC_BUS_COLS, GEN_COLS as AC_GEN_COLS
        from lfcore.hybrid_lf import HybridPowerFlowCalc, _build_lf_network_from_hybrid_rows

        network = _build_lf_network_from_hybrid_rows(
            Path("dead_ac.e"),
            _independent_hybrid_rows(ac_run=0, dc_run=1, stale=99.0),
        )
        calc = HybridPowerFlowCalc(network, result_mode="array", verbose=False)
        rc = calc.run()

        self.assertEqual(0, rc)
        self.assertTrue(calc.converged)
        self.assertIsNone(calc.ac_calc)
        self.assertIsNotNone(calc.dc_calc)
        self.assertTrue(np.all(calc.result["ac"]["bus"][:, [AC_BUS_COLS["voltage"], AC_BUS_COLS["angle"]]] == 0.0))
        self.assertTrue(np.all(calc.result["ac"]["gen"][:, [AC_GEN_COLS["p"], AC_GEN_COLS["q"], AC_GEN_COLS["current"]]] == 0.0))
        self.assertEqual(1, int(calc.result["ac"]["gen"][0, AC_GEN_COLS["run_stat"]]))
```

- [ ] **Step 3: Write failing tests for both-dead success and active failure preservation**

```python
    def test_hybrid_solver_returns_successful_zero_result_when_both_sides_are_dead(self):
        import numpy as np
        from ac_array_model import BUS_COLS as AC_BUS_COLS
        from dc_array_model import BUS_COLS as DC_BUS_COLS
        from lfcore.hybrid_lf import HybridPowerFlowCalc, _build_lf_network_from_hybrid_rows

        network = _build_lf_network_from_hybrid_rows(
            Path("all_dead.e"),
            _independent_hybrid_rows(ac_run=0, dc_run=0, stale=99.0),
        )
        calc = HybridPowerFlowCalc(network, result_mode="array", verbose=False)
        rc = calc.run()

        self.assertEqual(0, rc)
        self.assertTrue(calc.converged)
        self.assertEqual(0, calc.iterations)
        self.assertEqual(0.0, calc.normF)
        self.assertEqual((0, 0), calc.last_jacobian_shape)
        self.assertEqual(0, calc.x.size)
        self.assertTrue(np.all(calc.result["ac"]["bus"][:, [AC_BUS_COLS["voltage"], AC_BUS_COLS["angle"]]] == 0.0))
        self.assertTrue(np.all(calc.result["dc"]["bus"][:, DC_BUS_COLS["voltage"]] == 0.0))

    def test_hybrid_solver_does_not_convert_active_numerical_failure_into_empty_success(self):
        from lfcore.hybrid_lf import HybridPowerFlowCalc, _build_lf_network_from_hybrid_rows

        network = _build_lf_network_from_hybrid_rows(
            Path("live_ac.e"),
            _independent_hybrid_rows(ac_run=1, dc_run=0),
        )
        calc = HybridPowerFlowCalc(network, result_mode="none", verbose=False)
        calc.prepare()

        def fail_active_ac():
            calc.ac_calc.converged = False
            calc.ac_calc.iterations = 1
            calc.ac_calc.normF = 1.0
            return -1

        calc.ac_calc._run_newton_raphson = fail_active_ac
        self.assertEqual(-1, calc.run())
        self.assertFalse(calc.converged)
```

- [ ] **Step 4: Write a failing stale-converter-output regression**

Use the optional DCAC row whose endpoints are both retired and whose result columns start at `99.0`. After `calc.run()`, assert the source-aligned PPC row keeps `run_stat == 1` but all dynamic outputs are zero:

```python
    def test_inactive_dcac_converter_does_not_retain_stale_outputs(self):
        from hybrid_array_model import DCAC_COLS
        from lfcore.hybrid_lf import HybridPowerFlowCalc, _build_lf_network_from_hybrid_rows

        network = _build_lf_network_from_hybrid_rows(
            Path("inactive_converter.e"),
            _independent_hybrid_rows(
                ac_run=0,
                dc_run=0,
                stale=99.0,
                include_converter=True,
            ),
        )
        calc = HybridPowerFlowCalc(network, result_mode="array", verbose=False)

        self.assertEqual(0, calc.run())
        converter = network.ppc["dcac"][0]
        self.assertEqual(1, int(converter[DCAC_COLS["run_stat"]]))
        self.assertEqual(
            [0.0] * 5,
            [float(converter[DCAC_COLS[name]]) for name in ("dc_p", "ac_p", "ac_q", "dc_i", "ac_i")],
        )
```

- [ ] **Step 5: Run the new solver tests and verify failure**

```powershell
D:\anaconda3\python.exe -X utf8 -m pytest tests/test_hybrid_net_flow_self_contained.py -q
```

Expected: dead-side construction currently raises `电网中没有活节点`, and the both-dead case cannot complete as a valid zero solve.

- [ ] **Step 6: Add topology-aware active-node detection and aligned zero-result builders**

In `lfcore/hybrid_lf.py`, import `ensure_hybrid_ppc_topology` and add:

```python
def _ppc_has_operational_nodes(ppc, network_part) -> bool:
    topology = ppc.get("_topology_arrays") if isinstance(ppc, dict) else None
    node_alive = getattr(topology, "node_alive_mask", None)
    if node_alive is not None:
        return bool(np.any(np.asarray(node_alive, dtype=bool)))
    return _node_count(network_part) > 0


def _zero_table_columns(ppc, key, columns):
    source = None if ppc is None else ppc.get(key)
    if source is None:
        width = max(columns) + 1 if columns else 0
        return np.zeros((0, width), dtype=np.float64)
    source = np.asarray(source, dtype=np.float64)
    if source.ndim != 2:
        width = max(columns) + 1 if columns else 0
        source = np.zeros((0, width), dtype=np.float64)
    result = source.copy()
    if result.size and columns:
        result[:, list(columns)] = 0.0
    return result
```

Define exact AC/DC dynamic-column maps using the existing imported column dictionaries:

```python
_AC_ZERO_RESULT_COLUMNS = {
    "bus": (AC_BUS_COLS["voltage"], AC_BUS_COLS["angle"]),
    "gen": (AC_GEN_COLS["p"], AC_GEN_COLS["q"], AC_GEN_COLS["current"]),
    "load": (AC_LOAD_COLS["p"], AC_LOAD_COLS["q"], AC_LOAD_COLS["current"]),
    "shunt": (AC_SHUNT_COLS["p"], AC_SHUNT_COLS["q"], AC_SHUNT_COLS["current"]),
    "branch": tuple(AC_BRANCH_COLS[name] for name in ("i_p", "i_q", "i_c", "j_p", "j_q", "j_c")),
    "transformer": tuple(AC_TRANSFORMER_COLS[name] for name in ("i_p", "i_q", "i_c", "j_p", "j_q", "j_c")),
    "three_winding_transformer": tuple(
        AC_THREE_WINDING_TRANSFORMER_COLS[name]
        for name in ("i_p", "i_q", "i_c", "j_p", "j_q", "j_c", "k_p", "k_q", "k_c")
    ),
    "zero_branch": tuple(AC_ZERO_BRANCH_COLS[name] for name in ("p", "q", "current")),
    "switch": tuple(AC_SWITCH_COLS[name] for name in ("p", "q", "current")),
    "break": tuple(AC_BREAK_COLS[name] for name in ("p", "q", "current")),
    "acac": tuple(ACAC_COLS[name] for name in ("i_p", "i_q", "j_p", "j_q", "i_i", "j_i")),
}

_DC_ZERO_RESULT_COLUMNS = {
    "bus": (DC_BUS_COLS["voltage"],),
    "branch": tuple(DC_BRANCH_COLS[name] for name in ("i_p", "j_p", "current")),
    "load": tuple(DC_LOAD_COLS[name] for name in ("p", "current")),
    "gen": tuple(DC_GEN_COLS[name] for name in ("p", "current")),
    "zero_branch": tuple(DC_ZERO_BRANCH_COLS[name] for name in ("p", "current")),
    "switch": tuple(DC_SWITCH_COLS[name] for name in ("p", "current")),
    "break": tuple(DC_BREAK_COLS[name] for name in ("p", "current")),
    "dcdc": tuple(DC_DCDC_COLS[name] for name in ("i_p", "j_p", "i_c", "j_c")),
}


def _zero_subgrid_result(ppc, column_map):
    if not isinstance(ppc, dict):
        return None
    return {
        key: _zero_table_columns(ppc, key, columns)
        for key, columns in column_map.items()
    }
```

The helper returns every expected table key with source row alignment and only the listed dynamic columns zeroed. It preserves `idx`, `run_stat`, `status`, setpoints, and all static parameters.

- [ ] **Step 7: Derive `has_ac/has_dc` from topology before constructing sub-solvers**

At the beginning of `HybridPowerFlowCalc.__init__`, ensure a hybrid PPC topology when the network owns one:

```python
        hybrid_ppc = getattr(network, "ppc", None)
        if isinstance(hybrid_ppc, dict) and ("ac" in hybrid_ppc or "dc" in hybrid_ppc):
            ensure_hybrid_ppc_topology(hybrid_ppc)
        self._ac_ppc = getattr(network, "_ac_ppc", None) or getattr(network.ac, "ppc", None)
        self._dc_ppc = getattr(network, "_dc_ppc", None) or getattr(network.dc, "ppc", None)
        self.has_ac = _ppc_has_operational_nodes(self._ac_ppc, network.ac)
        self.has_dc = _ppc_has_operational_nodes(self._dc_ppc, network.dc)
        self._skipped_ac_result = _zero_subgrid_result(self._ac_ppc, _AC_ZERO_RESULT_COLUMNS)
        self._skipped_dc_result = _zero_subgrid_result(self._dc_ppc, _DC_ZERO_RESULT_COLUMNS)
```

Replace `_build_ac_subcalc()` and `_build_dc_subcalc()` with the topology-aware versions below. They use the already-prepared PPC when available and do not construct a sub-solver when the corresponding topology mask has no live node:

```python
    def _build_ac_subcalc(self):
        if not self.has_ac:
            return None
        source = self._ac_ppc if self._ac_ppc is not None else self.network.ac
        return ACPowerFlowCalc(
            source,
            parameters=self.params,
            keep_node_objects=False,
            linear_solver=self.linear_solver,
            result_mode="array",
            verbose=self.verbose,
        )

    def _build_dc_subcalc(self):
        if not self.has_dc:
            return None
        source = self._dc_ppc if self._dc_ppc is not None else self.network.dc
        calc = DCPowerFlowCalc(
            source,
            parameters=self.params,
            keep_node_objects=False,
            linear_solver=self.linear_solver,
            result_mode="array",
            verbose=self.verbose,
        )
        if hasattr(self.network, "_dc_ppc"):
            calc._network_writeback = (
                None if getattr(self.network.dc, "_lf_lightweight", False) else self.network.dc
            )
        return calc
```

- [ ] **Step 8: Clear all converter outputs before selecting active converter rows**

Add the helper below:

```python
    def _clear_converter_outputs(self):
        ppc = getattr(self.network, "ppc", {}) or {}
        dcac = ppc.get("dcac")
        if dcac is not None and getattr(dcac, "size", 0):
            dcac[:, [DCAC_COLS[name] for name in ("dc_p", "ac_p", "ac_q", "dc_i", "ac_i")]] = 0.0
        acac = ppc.get("acac")
        if acac is not None and getattr(acac, "size", 0):
            acac[:, [ACAC_COLS[name] for name in ("i_p", "i_q", "j_p", "j_q", "i_i", "j_i")]] = 0.0
        for conv in getattr(self.network, "dcac_converters", ()):
            conv.is_alive = False
            for name in ("dc_p", "ac_p", "ac_q", "dc_i", "ac_i"):
                setattr(conv, name, 0.0)
        for conv in getattr(self.network, "acac_converters", ()):
            conv.is_alive = False
            for name in ("i_p", "i_q", "j_p", "j_q", "i_i", "j_i", "i_c", "j_c"):
                setattr(conv, name, 0.0)
```

In `__init__`, place the call immediately after `_converter_ppc_mode` is computed and before `needs_ac_node_lookup`:

```python
        self._converter_ppc_mode = bool(
            getattr(network, "_lf_lightweight", False)
            and isinstance(getattr(network, "ppc", None), dict)
        )
        self._clear_converter_outputs()
        needs_ac_node_lookup = (
            not self._converter_ppc_mode
            and bool(
                getattr(network, "dcac_converters", [])
                or getattr(network, "acac_converters", [])
            )
        )
```

Active rows are overwritten later by normal writeback; inactive rows cannot retain previous-cycle data.

- [ ] **Step 9: Add a valid no-Newton completion path**

Change `prepare()` so `not parts` creates a stable empty layout instead of raising:

```python
        if not parts:
            self.x = np.empty(0, dtype=np.float64)
            self.total_vars = 0
            self.total_eq = 0
            self.last_jacobian_shape = (0, 0)
            self._residual_work = np.empty(0, dtype=np.float64)
            return self.x
```

Add:

```python
    def _finish_empty_system(self) -> int:
        self.converged = True
        self.iterations = 0
        self.normF = 0.0
        self.failure_reason = ""
        self._write_skipped_results_to_network()
        if self.result_mode == "none":
            self.result = {}
            self.lf_result = None
        elif self.result_mode == "summary":
            self.result = {
                "ac": self._ac_array_summary(self._skipped_ac_result),
                "dc": self._dc_array_summary(self._skipped_dc_result),
                "hybrid": self._hybrid_summary(),
            }
            self.lf_result = None
        else:
            self._set_array_result(self._skipped_ac_result, self._skipped_dc_result)
            self.lf_result = None if self.result_mode == "array" else self._build_lf_result()
        return 0
```

Replace `run()` with the exact guard below so an empty topology completes before `_run_newton_raphson()`:

```python
    def run(self, result_mode=None) -> int:
        """Execute unified Newton iterations over the full hybrid state vector."""
        if result_mode is not None:
            self.result_mode = self._normalize_result_mode(result_mode)
            self._sync_sub_result_modes()
        if self.x.size == 0:
            self.prepare()
        if self.total_vars == 0 and self.total_eq == 0:
            return self._finish_empty_system()
        return self._run_newton_raphson()
```

- [ ] **Step 10: Include skipped-side tables when delegating a single live sub-solver**

Replace `_sync_single_subsolver_result()` so the live side and skipped side are written before full-result facades are constructed:

```python
    def _sync_single_subsolver_result(self, kind):
        ac_result = self.ac_calc.result if kind == "ac" else self._skipped_ac_result
        dc_result = self.dc_calc.result if kind == "dc" else self._skipped_dc_result
        if kind == "ac":
            self._write_ac_ppc_result_to_network()
        elif kind == "dc":
            self._write_dc_ppc_result_to_network()
        self._write_skipped_results_to_network()

        if self.result_mode == "full":
            self._set_array_result(ac_result, dc_result)
            self.lf_result = (
                None if getattr(self, "skip_lf_result", False) else self._build_lf_result()
            )
        elif self.result_mode == "array":
            self._set_array_result(ac_result, dc_result)
            self.lf_result = None
        elif self.result_mode == "summary":
            self.result = {
                "ac": self._ac_array_summary(ac_result),
                "dc": self._dc_array_summary(dc_result),
                "hybrid": self._hybrid_summary(),
            }
            self.lf_result = None
        else:
            self.result = {}
            self.lf_result = None
```

Add exact object-attribute maps and writeback helpers:

```python
_AC_SKIPPED_OBJECT_ATTRS = {
    "nodes": ("voltage", "angle"),
    "generators": ("p", "q", "current"),
    "loads": ("p", "q", "current"),
    "shunt_compensators": ("p", "q", "current"),
    "branches": ("i_p", "i_q", "i_c", "j_p", "j_q", "j_c"),
    "transformers": ("i_p", "i_q", "i_c", "j_p", "j_q", "j_c"),
    "three_winding_transformers": ("i_p", "i_q", "i_c", "j_p", "j_q", "j_c", "k_p", "k_q", "k_c"),
    "zero_branches": ("p", "q", "current"),
    "switches": ("p", "q", "current"),
    "breakers": ("p", "q", "current"),
}

_DC_SKIPPED_OBJECT_ATTRS = {
    "nodes": ("voltage",),
    "generators": ("p", "current"),
    "loads": ("p", "current"),
    "branches": ("i_p", "j_p", "current"),
    "zero_branches": ("p", "current"),
    "switches": ("p", "current"),
    "breakers": ("p", "current"),
    "dcdc_converters": ("i_p", "j_p", "i_c", "j_c"),
}


def _zero_skipped_object_side(network_part, attribute_map):
    for collection_name, attributes in attribute_map.items():
        for device in getattr(network_part, collection_name, ()):
            if hasattr(device, "is_alive"):
                device.is_alive = False
            for attribute in attributes:
                setattr(device, attribute, 0.0)
```

Add to `HybridPowerFlowCalc`:

```python
    def _write_skipped_results_to_network(self):
        if self.ac_calc is None:
            if self._skipped_ac_result is not None:
                self.network.ac.result = self._skipped_ac_result
            _zero_skipped_object_side(self.network.ac, _AC_SKIPPED_OBJECT_ATTRS)
        if self.dc_calc is None:
            if self._skipped_dc_result is not None:
                self.network.dc.result = self._skipped_dc_result
            _zero_skipped_object_side(self.network.dc, _DC_SKIPPED_OBJECT_ATTRS)
```

The two complete methods above already call this helper before result-facade construction, so lightweight and full-object paths are synchronized while every source `run_stat/status` field remains untouched.

- [ ] **Step 11: Run focused and full kernel tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m pytest tests/test_hybrid_net_flow_self_contained.py tests/test_topology_helpers.py -q
D:\anaconda3\python.exe -X utf8 -m pytest -q
```

Expected: both commands pass. Existing active-network convergence failures must remain failures; only topology-empty sides are skipped.

- [ ] **Step 12: Commit the kernel solver change**

```powershell
git add src/hybrid_power_system_analysis/lfcore/hybrid_lf.py tests/test_hybrid_net_flow_self_contained.py
git commit -m "fix: skip inactive hybrid subnetworks"
```

### Task 4: Add Qinling WEB End-to-End Busbar Retirement Regressions

**Files:**
- Modify: `D:\codex\power_simu_web\tests\test_svg_device_operating_state.py:135-320`

- [ ] **Step 1: Extract reusable Qinling and run-once helpers**

Add methods to `SvgDeviceOperatingStateTest`:

```python
    def _qinling_model_dir(self):
        for candidate in (ROOT / "models/simulator/source").glob("*/model.e"):
            book = simu_loop.EBook(candidate)
            model = book.data.get("Model")
            if model is not None and model.data and model.data[0].get("name") == "qinling":
                return candidate.parent
        self.fail("Qinling simulator model was not found")

    @staticmethod
    def _set_runtime_run_stat(stat_book, dev_type, dev_name, run_stat):
        block = stat_book.data.get("RunStat")
        for row in block.data:
            if row.get("dev_type") == dev_type and row.get("dev_name") == dev_name:
                row["run_stat"] = run_stat
                return
        block.data.append({"dev_type": dev_type, "dev_name": dev_name, "run_stat": run_stat})

    def _run_qinling_once(self, model_dir, model_book, stat_book):
        control_book = simu_loop.EBook(model_dir / "control.e")
        weather_book = simu_loop.EBook(model_dir / "weather.e")
        before, measurement_rows, after = simu_loop.parse_measurement_rows(model_dir / "meas.e")
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            return simu_loop.run_once(simu_loop.SimulationConfig(
                model_file=model_dir / "model.e",
                meas_file=model_dir / "meas.e",
                weather_file=model_dir / "weather.e",
                dev_stat_file=model_dir / "stat.e",
                yt_ctrl_file=model_dir / "control.e",
                real_file=runtime / "real.e",
                scada_file=runtime / "scada.e",
                period_seconds=60.0,
                write_output_files=False,
                model_book=model_book,
                meas_before=before,
                meas_rows=measurement_rows,
                meas_after=after,
                weather_book=weather_book,
                dev_stat_book=stat_book,
                yt_ctrl_book=control_book,
                dev_define_book=simu_loop._capability_define_book(model_book, None),
            ))
```

- [ ] **Step 2: Write the failing DC busbar retirement regression**

```python
    def test_qinling_dc_busbar_retirement_changes_topology_without_stopping_ac_flow(self):
        model_dir = self._qinling_model_dir()
        model_book = simu_loop.EBook(model_dir / "model.e")
        stat_book = simu_loop.EBook(model_dir / "stat.e")
        busbar = next(row for row in model_book.data["DCRealBs"].data if int(row["idx"]) == 1)
        node = next(row for row in model_book.data["DCNode"].data if int(row["idx"]) == int(busbar["node"]))
        self._set_runtime_run_stat(stat_book, "DCRealBs", busbar["name"], 0)

        result = self._run_qinling_once(model_dir, model_book, stat_book)

        self.assertRegex(result.solver_info, r"^iter=\d+, normF=\d\.\d{3}e[+-]\d+$|^iter=0, normF=0\.000e\+00$")
        measurements = {(row[2], row[3], row[4]): float(row[7]) for row in result.real_rows or []}
        for key in (
            ("DCNode", node["name"], "V"),
            ("DCBreak", "直流断路器-1", "P_FROM"),
            ("DCBreak", "直流断路器-1", "I"),
            ("DCACConverter", "ACDC变流器-1", "P_DC"),
            ("DCACConverter", "ACDC变流器-1", "P_AC"),
            ("DCACConverter", "ACDC变流器-1", "I_DC"),
            ("DCACConverter", "ACDC变流器-1", "I_AC"),
        ):
            with self.subTest(zero_measurement=key):
                self.assertAlmostEqual(0.0, measurements[key], places=9)

        states = {(row["dev_type"], row["dev_name"]): row for row in result.device_states or []}
        self.assertEqual(0, states[("DCRealBs", busbar["name"])]["run_stat"])
        self.assertEqual(0, states[("DCNode", node["name"])]["run_stat"])
        self.assertEqual(1, states[("DCACConverter", "ACDC变流器-1")]["run_stat"])
        self.assertTrue(states[("DCACConverter", "ACDC变流器-1")]["dead_island"])
        self.assertGreater(abs(measurements[("ACNode", "交流母线（竖向）-1", "V")]), 0.0)
```

This test confirms that DC flow disappears because the topology/result changes, not because the frontend hides values.

- [ ] **Step 3: Write the symmetric AC busbar and restoration regressions**

Add the symmetric AC case. A raised zero-column/empty-subnet error fails the test before any assertion; a successful result must report the RealBs and referenced node as retired and must zero the bus voltage:

```python
    def test_qinling_ac_busbar_retirement_converges_and_zeroes_the_referenced_node(self):
        model_dir = self._qinling_model_dir()
        model_book = simu_loop.EBook(model_dir / "model.e")
        stat_book = simu_loop.EBook(model_dir / "stat.e")
        busbar = next(row for row in model_book.data["ACRealBs"].data if int(row["idx"]) == 1)
        node = next(row for row in model_book.data["ACNode"].data if int(row["idx"]) == int(busbar["node"]))
        self._set_runtime_run_stat(stat_book, "ACRealBs", busbar["name"], 0)

        result = self._run_qinling_once(model_dir, model_book, stat_book)

        self.assertRegex(result.solver_info, r"^iter=\d+, normF=\d\.\d{3}e[+-]\d+$|^iter=0, normF=0\.000e\+00$")
        measurements = {(row[2], row[3], row[4]): float(row[7]) for row in result.real_rows or []}
        states = {(row["dev_type"], row["dev_name"]): row for row in result.device_states or []}
        self.assertEqual(0, states[("ACRealBs", busbar["name"])]["run_stat"])
        self.assertEqual(0, states[("ACNode", node["name"])]["run_stat"])
        self.assertAlmostEqual(0.0, measurements[("ACNode", node["name"], "V")], places=9)

        for state_key, state in states.items():
            if state_key[0] != "DCNode" or state["run_stat"] != 1:
                continue
            voltage_key = ("DCNode", state_key[1], "V")
            if voltage_key not in measurements:
                continue
            if state["dead_island"]:
                self.assertAlmostEqual(0.0, measurements[voltage_key], places=9)

    def test_qinling_busbar_restore_does_not_reenable_explicitly_retired_node(self):
        model_dir = self._qinling_model_dir()
        source = simu_loop.EBook(model_dir / "model.e")
        busbar = next(row for row in source.data["DCRealBs"].data if int(row["idx"]) == 1)
        node = next(row for row in source.data["DCNode"].data if int(row["idx"]) == int(busbar["node"]))
        stat = simu_loop.EBook(model_dir / "stat.e")
        self._set_runtime_run_stat(stat, "DCRealBs", busbar["name"], 1)
        self._set_runtime_run_stat(stat, "DCNode", node["name"], 0)

        result = self._run_qinling_once(model_dir, source, stat)
        states = {(row["dev_type"], row["dev_name"]): row for row in result.device_states or []}

        self.assertEqual(1, states[("DCRealBs", busbar["name"])]["run_stat"])
        self.assertEqual(0, states[("DCNode", node["name"])]["run_stat"])
```

- [ ] **Step 4: Run the focused WEB integration tests**

```powershell
D:\anaconda3\python.exe -X utf8 -m unittest tests.test_busbar_runtime_status tests.test_svg_device_operating_state -v
```

Expected: all pass, including the existing breaker/dead-island and offline-diesel cases.

- [ ] **Step 5: Commit the WEB regression coverage**

```powershell
git add tests/test_svg_device_operating_state.py
git commit -m "test: cover Qinling busbar retirement"
```

Do not stage unrelated model/runtime changes.

### Task 5: Verify Cross-Repository Regressions and Runtime Behavior

**Files:**
- Verify: both repositories' modified files
- Verify: `D:\codex\power_simu_web\models\simulator\source\秦岭站\model.e` without editing it

- [ ] **Step 1: Run kernel static checks**

```powershell
D:\anaconda3\python.exe -X utf8 -m ruff check src/hybrid_power_system_analysis/model/topology.py src/hybrid_power_system_analysis/model/ppc_topology.py src/hybrid_power_system_analysis/model/hybrid_model.py src/hybrid_power_system_analysis/lfcore/hybrid_lf.py
git diff --check
```

Expected: both exit `0` in `D:\codex\elec_power_flow\hybrid_power_system_analysis`.

- [ ] **Step 2: Run the complete kernel test suite**

```powershell
D:\anaconda3\python.exe -X utf8 -m pytest -q
```

Expected: all tests pass. Pay special attention to AC/DC auto-slack, DCAC/ACAC/DCDC, topology-object parity, state estimation, and hybrid array-mode tests.

- [ ] **Step 3: Run WEB static checks**

```powershell
D:\anaconda3\python.exe -X utf8 -m py_compile simu_loop.py tests/test_busbar_runtime_status.py tests/test_svg_device_operating_state.py
git diff --check
```

Expected: both exit `0` in `D:\codex\power_simu_web`.

- [ ] **Step 4: Run the complete WEB suite with the local `simu` package preloaded**

```powershell
D:\anaconda3\python.exe -X utf8 -c "import simu, unittest; suite=unittest.defaultTestLoader.discover('tests', top_level_dir='.'); result=unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(0 if result.wasSuccessful() else 1)"
```

Expected: all WEB tests pass. The command preloads this repository's `simu` package before the kernel adds its own package path.

- [ ] **Step 5: Run a direct Qinling DC-bus probe without writing runtime files**

Run this exact in-memory probe from `D:\codex\power_simu_web`. It reuses the test helper whose `SimulationConfig` has `write_output_files=False`:

```powershell
@'
from tests.test_svg_device_operating_state import SvgDeviceOperatingStateTest
import simu_loop

case = SvgDeviceOperatingStateTest(methodName="runTest")
model_dir = case._qinling_model_dir()
model_book = simu_loop.EBook(model_dir / "model.e")
stat_book = simu_loop.EBook(model_dir / "stat.e")
busbar = next(
    row for row in model_book.data["DCRealBs"].data
    if int(row["idx"]) == 1
)
node = next(
    row for row in model_book.data["DCNode"].data
    if int(row["idx"]) == int(busbar["node"])
)
case._set_runtime_run_stat(stat_book, "DCRealBs", busbar["name"], 0)
result = case._run_qinling_once(model_dir, model_book, stat_book)

measurements = {
    (row[2], row[3], row[4]): float(row[7])
    for row in result.real_rows or []
}
states = {
    (row["dev_type"], row["dev_name"]): row
    for row in result.device_states or []
}
bus_state = states[("DCRealBs", busbar["name"])]
node_state = states[("DCNode", node["name"])]
converter_state = states[("DCACConverter", "ACDC变流器-1")]
converter_values = {
    field: measurements[("DCACConverter", "ACDC变流器-1", field)]
    for field in ("P_DC", "P_AC", "I_DC", "I_AC")
}
dc_voltage = measurements[("DCNode", node["name"], "V")]
ac_voltage = measurements[("ACNode", "交流母线（竖向）-1", "V")]

assert int(bus_state["run_stat"]) == 0
assert int(node_state["run_stat"]) == 0
assert abs(dc_voltage) < 1e-9
assert int(converter_state["run_stat"]) == 1
assert bool(converter_state["dead_island"])
assert all(abs(value) < 1e-9 for value in converter_values.values())
assert abs(ac_voltage) > 0.0

print("solver_info:", result.solver_info)
print("DCRealBs run_stat:", bus_state["run_stat"])
print("DCNode run_stat / V:", node_state["run_stat"], dc_voltage)
print(
    "DCACConverter run_stat / dead_island / values:",
    converter_state["run_stat"],
    converter_state["dead_island"],
    converter_values,
)
print("AC main voltage:", ac_voltage)
'@ | D:\anaconda3\python.exe -X utf8 -
```

Expected:

```text
solver converged
DCRealBs run_stat = 0
DCNode run_stat = 0, V = 0
ACDC converter run_stat = 1, dead_island = true, all dynamic values = 0
AC main network voltage remains nonzero when its island is operational
```

- [ ] **Step 6: Inspect repository state and create no cleanup commit**

In each repository run:

```powershell
git status --short --branch
git log -4 --oneline
```

Expected kernel commits:

```text
fix: require local references for hybrid links
fix: skip inactive hybrid subnetworks
```

Expected WEB commits after the already-approved design commits:

```text
fix: apply busbar state to runtime nodes
test: cover Qinling busbar retirement
```

Do not push or restart WEB services unless the user explicitly requests those operations after implementation.
