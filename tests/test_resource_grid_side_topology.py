import unittest
from collections.abc import Mapping
from unittest.mock import patch

import simu.resource_topology as topology
from simu.resource_topology import ResourceRef, resolve_resource_topology


def block(rows):
    copied_rows = [dict(row) if isinstance(row, Mapping) else row for row in rows]
    headers = sorted(
        {
            str(key)
            for row in copied_rows
            if isinstance(row, Mapping)
            for key in row
        }
    )
    return {"headers": headers, "rows": copied_rows}


def snapshot_with_model(
    model,
    *,
    devices=None,
    device_states=None,
    scada=None,
    real=None,
):
    return {
        "definitions": {
            "model": {name: block(rows) for name, rows in model.items()}
        },
        "devices": list(devices or []),
        "device_states": list(device_states or []),
        "measurements": {
            "scada": list(scada or []),
            "real": list(real or []),
        },
    }


def resolve_one(model, technology, dev_type, dev_name):
    result = resolve_resource_topology(
        snapshot_with_model(model),
        [ResourceRef(technology, dev_type, dev_name)],
    )
    return result.resources[(dev_type, dev_name)]


def resolve_snapshot(snapshot, *resources):
    refs = [ResourceRef(*resource) for resource in resources]
    return resolve_resource_topology(snapshot, refs)


def reverse_snapshot_rows(snapshot):
    model = snapshot["definitions"]["model"]
    reversed_model = {
        name: {
            **data,
            "rows": list(reversed(data.get("rows", []))),
        }
        for name, data in reversed(list(model.items()))
    }
    return {
        **snapshot,
        "definitions": {**snapshot["definitions"], "model": reversed_model},
        "devices": list(reversed(snapshot.get("devices", []))),
        "device_states": list(reversed(snapshot.get("device_states", []))),
        "measurements": {
            "scada": list(
                reversed(snapshot.get("measurements", {}).get("scada", []))
            ),
            "real": list(
                reversed(snapshot.get("measurements", {}).get("real", []))
            ),
        },
    }


def two_dc_island_snapshot():
    return snapshot_with_model(
        {
            "DCNode": [
                {"idx": 1, "name": "dc-a-resource"},
                {"idx": 2, "name": "dc-a-converter"},
                {"idx": 3, "name": "dc-b-resource"},
                {"idx": 4, "name": "dc-b-converter"},
            ],
            "ACNode": [
                {"idx": 101, "name": "ac-a"},
                {"idx": 102, "name": "ac-b"},
            ],
            "DCGenerator": [
                {"idx": 1, "name": "storage-a", "node": 1, "run_stat": 1},
                {"idx": 2, "name": "storage-b", "node": 3, "run_stat": 1},
            ],
            "DCBranch": [
                {
                    "idx": 1,
                    "name": "dc-line-a",
                    "i_node": 1,
                    "j_node": 2,
                    "run_stat": 1,
                },
                {
                    "idx": 2,
                    "name": "dc-line-b",
                    "i_node": 3,
                    "j_node": 4,
                    "run_stat": 1,
                },
            ],
            "DCRealBs": [
                {"idx": 1, "name": "dc-bus-a", "node": 1, "run_stat": 1},
                {"idx": 2, "name": "dc-bus-b", "node": 3, "run_stat": 1},
            ],
            "ACRealBs": [
                {"idx": 1, "name": "local-ac-a", "node": 101, "run_stat": 1},
                {"idx": 2, "name": "local-ac-b", "node": 102, "run_stat": 1},
            ],
            "DCACConverter": [
                {
                    "idx": 1,
                    "name": "converter-a",
                    "ac_node": 101,
                    "dc_node": 2,
                    "run_stat": 1,
                },
                {
                    "idx": 2,
                    "name": "converter-b",
                    "ac_node": 102,
                    "dc_node": 4,
                    "run_stat": 1,
                },
            ],
        }
    )


def resolve_single_resource_through(edge_type):
    domain = "AC" if edge_type.startswith("AC") else "DC"
    generator_type = f"{domain}Generator"
    node_type = f"{domain}Node"
    busbar_type = f"{domain}RealBs"
    resource_name = f"resource-{edge_type}"
    edge_row = {
        "idx": 1,
        "name": f"edge-{edge_type}",
        "i_node": 1,
        "j_node": 2,
        "run_stat": 1,
        "status": 1,
    }
    return resolve_one(
        {
            node_type: [
                {"idx": 1, "name": "resource-node"},
                {"idx": 2, "name": "switch-bus-node"},
                {"idx": 3, "name": "line-bus-node"},
            ],
            generator_type: [
                {"idx": 1, "name": resource_name, "node": 1, "run_stat": 1}
            ],
            edge_type: [edge_row],
            f"{domain}Branch": [
                {
                    "idx": 2,
                    "name": "ordinary-line",
                    "i_node": 1,
                    "j_node": 3,
                    "run_stat": 1,
                }
            ],
            busbar_type: [
                {"idx": 1, "name": "z-switch-bus", "node": 2},
                {"idx": 2, "name": "a-line-bus", "node": 3},
            ],
        },
        "test",
        generator_type,
        resource_name,
    )


class ResourceGridSideTopologyTest(unittest.TestCase):
    def test_name_does_not_override_direct_ac_bus_connection(self):
        item = resolve_one(
            {
                "ACNode": [
                    {"idx": 1, "name": "resource-node"},
                ],
                "ACGenerator": [
                    {"idx": 1, "name": "直流风机", "node": 1, "run_stat": 1}
                ],
                "ACRealBs": [
                    {"idx": 1, "name": "ac-bus", "node": 1, "run_stat": 1}
                ],
            },
            "wind",
            "ACGenerator",
            "直流风机",
        )

        self.assertEqual("AC", item.connection_side)
        self.assertTrue(item.actively_connected)
        self.assertEqual("ac-bus", item.busbar_name)
        self.assertEqual((), item.structural_path)
        self.assertEqual(item.structural_path, item.active_path)
        self.assertEqual("结构接入交流母线", item.topology_status_label)

    def test_ac_generator_reaching_only_dc_bus_through_dcac_is_dc(self):
        item = resolve_one(
            {
                "ACNode": [{"idx": 1, "name": "wind-terminal"}],
                "DCNode": [{"idx": 7, "name": "dc-bus-node"}],
                "ACGenerator": [
                    {"idx": 1, "name": "交流风机", "node": 1}
                ],
                "DCACConverter": [
                    {
                        "idx": 1,
                        "name": "rectifier",
                        "ac_node": 1,
                        "dc_node": 7,
                    }
                ],
                "DCRealBs": [{"idx": 1, "name": "dc-bus", "node": 7}],
            },
            "wind",
            "ACGenerator",
            "交流风机",
        )

        self.assertEqual("DC", item.connection_side)
        self.assertEqual(("DCACConverter", "rectifier"), item.structural_path[0])
        self.assertEqual(
            (("DCACConverter", "rectifier"),),
            item.converter_path,
        )
        self.assertEqual("结构接入直流母线", item.topology_status_label)

    def test_dc_generator_reaching_only_ac_bus_through_dcac_is_ac(self):
        item = resolve_one(
            {
                "DCNode": [{"idx": 1, "name": "pv-terminal"}],
                "ACNode": [{"idx": 2, "name": "ac-bus-node"}],
                "DCGenerator": [
                    {"idx": 1, "name": "直流光伏", "node": 1}
                ],
                "DCACConverter": [
                    {
                        "idx": 1,
                        "name": "inverter",
                        "ac_node": 2,
                        "dc_node": 1,
                    }
                ],
                "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 2}],
            },
            "pv",
            "DCGenerator",
            "直流光伏",
        )

        self.assertEqual("AC", item.connection_side)
        self.assertEqual("ac-bus", item.busbar_name)
        self.assertEqual(
            (("DCACConverter", "inverter"),),
            item.converter_path,
        )

    def test_misleading_ac_name_directly_connected_to_dc_bus_remains_dc(self):
        item = resolve_one(
            {
                "DCNode": [{"idx": 11, "name": "dc-node"}],
                "DCGenerator": [
                    {"idx": 1, "name": "交流储能", "node": 11}
                ],
                "DCRealBs": [{"idx": 1, "name": "dc-bus", "node": 11}],
            },
            "storage",
            "DCGenerator",
            "交流储能",
        )

        self.assertEqual("DC", item.connection_side)
        self.assertEqual((), item.structural_path)

    def test_switchlike_edges_have_zero_structural_cost(self):
        for edge_type in ("ACBreak", "ACSwitch", "ACZeroBranch"):
            with self.subTest(edge_type=edge_type):
                item = resolve_single_resource_through(edge_type)
                self.assertEqual("AC", item.connection_side)
                self.assertEqual("z-switch-bus", item.busbar_name)
                self.assertEqual(((edge_type, f"edge-{edge_type}"),), item.structural_path)

        for edge_type in ("DCBreak", "DCSwitch", "DCZeroBranch"):
            with self.subTest(edge_type=edge_type):
                item = resolve_single_resource_through(edge_type)
                self.assertEqual("DC", item.connection_side)
                self.assertEqual("z-switch-bus", item.busbar_name)
                self.assertEqual(((edge_type, f"edge-{edge_type}"),), item.structural_path)

    def test_no_domain_change_path_wins_over_shorter_dcac_path(self):
        item = resolve_one(
            {
                "ACNode": [
                    {"idx": 1, "name": "resource-node"},
                    {"idx": 2, "name": "middle-node"},
                    {"idx": 3, "name": "ac-bus-node"},
                ],
                "DCNode": [{"idx": 4, "name": "dc-bus-node"}],
                "ACGenerator": [{"idx": 1, "name": "wind", "node": 1}],
                "ACBranch": [
                    {"idx": 1, "name": "line-1", "i_node": 1, "j_node": 2},
                    {"idx": 2, "name": "line-2", "i_node": 2, "j_node": 3},
                ],
                "DCACConverter": [
                    {
                        "idx": 1,
                        "name": "short-crossing",
                        "ac_node": 1,
                        "dc_node": 4,
                    }
                ],
                "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 3}],
                "DCRealBs": [{"idx": 1, "name": "dc-bus", "node": 4}],
            },
            "wind",
            "ACGenerator",
            "wind",
        )

        self.assertEqual("AC", item.connection_side)
        self.assertEqual((), item.converter_path)
        self.assertEqual(
            (("ACBranch", "line-1"), ("ACBranch", "line-2")),
            item.structural_path,
        )

    def test_equal_best_ac_and_dc_costs_are_ambiguous(self):
        model = {
            "ACNode": [{"idx": 1, "name": "resource-node"}],
            "ACGenerator": [{"idx": 1, "name": "resource", "node": 1}],
        }
        equal_paths = {
            "AC": topology._AnchorPath(
                cost=(1, 1),
                busbar_type="ACRealBs",
                busbar_name="ac-bus",
                busbar_node="2",
                path=(("DCACConverter", "ac-path"),),
            ),
            "DC": topology._AnchorPath(
                cost=(1, 1),
                busbar_type="DCRealBs",
                busbar_name="dc-bus",
                busbar_node="3",
                path=(("DCACConverter", "dc-path"),),
            ),
        }

        with patch.object(topology, "_anchor_paths_for_node", return_value=equal_paths):
            item = resolve_one(model, "wind", "ACGenerator", "resource")

        self.assertEqual("AMBIGUOUS", item.connection_side)
        self.assertFalse(item.actively_connected)
        self.assertEqual((), item.active_path)
        self.assertEqual(
            "交流/直流真实母线路径等价，拓扑歧义",
            item.topology_status_label,
        )

    def test_no_real_bus_is_unresolved(self):
        item = resolve_one(
            {
                "DCNode": [{"idx": 1, "name": "resource-node"}],
                "DCGenerator": [{"idx": 1, "name": "pv", "node": 1}],
                "DCBranch": [
                    {"idx": 1, "name": "line", "i_node": 1, "j_node": 2}
                ],
            },
            "pv",
            "DCGenerator",
            "pv",
        )

        self.assertEqual("UNRESOLVED", item.connection_side)
        self.assertFalse(item.actively_connected)
        self.assertEqual((), item.active_path)
        self.assertEqual("未找到可达真实母线", item.topology_status_label)

    def test_direct_real_bus_anchor_wins_over_incomplete_converter(self):
        item = resolve_one(
            {
                "ACNode": [{"idx": 1, "name": "resource-and-bus-node"}],
                "ACGenerator": [
                    {"idx": 1, "name": "anchored-resource", "node": 1}
                ],
                "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 1}],
                "DCACConverter": [
                    {"idx": 1, "name": "incomplete", "ac_node": 1}
                ],
            },
            "wind",
            "ACGenerator",
            "anchored-resource",
        )

        self.assertEqual("AC", item.connection_side)
        self.assertTrue(item.actively_connected)
        self.assertEqual("ac-bus", item.busbar_name)
        self.assertEqual((), item.structural_path)
        self.assertEqual((), item.active_path)

    def test_selected_real_bus_path_wins_over_incomplete_unselected_branch(self):
        item = resolve_one(
            {
                "ACNode": [
                    {"idx": 1, "name": "resource-node"},
                    {"idx": 2, "name": "bus-node"},
                    {"idx": 3, "name": "unselected-node"},
                ],
                "ACGenerator": [
                    {"idx": 1, "name": "branched-resource", "node": 1}
                ],
                "ACBranch": [
                    {"idx": 1, "name": "selected-line", "i_node": 1, "j_node": 2},
                    {"idx": 2, "name": "side-branch", "i_node": 1, "j_node": 3},
                ],
                "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 2}],
                "DCACConverter": [
                    {"idx": 1, "name": "incomplete", "ac_node": 3}
                ],
            },
            "wind",
            "ACGenerator",
            "branched-resource",
        )

        self.assertEqual("AC", item.connection_side)
        self.assertTrue(item.actively_connected)
        self.assertEqual("ac-bus", item.busbar_name)
        self.assertEqual(
            (("ACBranch", "selected-line"),),
            item.structural_path,
        )
        self.assertEqual(item.structural_path, item.active_path)

    def test_incomplete_converter_without_valid_bus_route_is_invalid(self):
        item = resolve_one(
            {
                "ACNode": [{"idx": 1, "name": "resource-node"}],
                "ACGenerator": [
                    {"idx": 1, "name": "bad-converter-path", "node": 1}
                ],
                "DCACConverter": [
                    {"idx": 1, "name": "incomplete", "ac_node": 1}
                ],
            },
            "wind",
            "ACGenerator",
            "bad-converter-path",
        )

        self.assertEqual("INVALID", item.connection_side)
        self.assertFalse(item.actively_connected)
        self.assertEqual((), item.active_path)
        self.assertEqual("资源模型引用或端子无效", item.topology_status_label)

    def test_invalid_inputs_return_invalid_without_raising(self):
        cases = {
            "missing resource": (
                {
                    "ACNode": [{"idx": 1, "name": "node"}],
                    "ACGenerator": [],
                },
                "ACGenerator",
                "missing",
            ),
            "invalid terminal node": (
                {
                    "DCNode": [{"idx": 1, "name": "declared-node"}],
                    "DCGenerator": [
                        {"idx": 1, "name": "bad-terminal", "node": "missing-node"}
                    ],
                },
                "DCGenerator",
                "bad-terminal",
            ),
        }

        for label, (model, dev_type, dev_name) in cases.items():
            with self.subTest(case=label):
                item = resolve_one(model, "test", dev_type, dev_name)
                self.assertEqual("INVALID", item.connection_side)
                self.assertFalse(item.actively_connected)
                self.assertEqual((), item.active_path)
                self.assertEqual(
                    "资源模型引用或端子无效",
                    item.topology_status_label,
                )

    def test_equal_cost_same_domain_anchors_are_deterministic(self):
        item = resolve_one(
            {
                "ACNode": [
                    {"idx": 1, "name": "resource-node"},
                    {"idx": 2, "name": "bus-node-b"},
                    {"idx": 3, "name": "bus-node-a"},
                ],
                "ACGenerator": [{"idx": 1, "name": "resource", "node": 1}],
                "ACBranch": [
                    {"idx": 1, "name": "line-b", "i_node": 1, "j_node": 2},
                    {"idx": 2, "name": "line-a", "i_node": 1, "j_node": 3},
                ],
                "ACRealBs": [
                    {"idx": 1, "name": "bus-b", "node": 2},
                    {"idx": 2, "name": "bus-a", "node": 3},
                ],
            },
            "wind",
            "ACGenerator",
            "resource",
        )

        self.assertEqual("AC", item.connection_side)
        self.assertEqual("bus-a", item.busbar_name)
        self.assertEqual((("ACBranch", "line-a"),), item.structural_path)

    def test_model_row_order_does_not_change_result(self):
        model = {
            "ACNode": [
                {"idx": 1, "name": "resource-node"},
                {"idx": 2, "name": "bus-node-b"},
                {"idx": 3, "name": "bus-node-a"},
            ],
            "ACGenerator": [{"idx": 1, "name": "resource", "node": 1}],
            "ACSwitch": [
                {
                    "idx": 1,
                    "name": "switch-b",
                    "i_node": 1,
                    "j_node": 2,
                    "status": 1,
                },
                {
                    "idx": 2,
                    "name": "switch-a",
                    "i_node": 1,
                    "j_node": 3,
                    "status": 1,
                },
            ],
            "ACRealBs": [
                {"idx": 1, "name": "bus-b", "node": 2},
                {"idx": 2, "name": "bus-a", "node": 3},
            ],
        }
        reversed_model = {
            name: list(reversed(rows)) for name, rows in reversed(list(model.items()))
        }

        ordered = resolve_one(model, "wind", "ACGenerator", "resource")
        reversed_result = resolve_one(
            reversed_model,
            "wind",
            "ACGenerator",
            "resource",
        )

        self.assertEqual(ordered, reversed_result)
        self.assertEqual("bus-a", ordered.busbar_name)

    def test_open_switch_changes_active_path_without_changing_structural_side(self):
        model = {
            "DCNode": [
                {"idx": 1, "name": "resource-node", "run_stat": 1},
                {"idx": 2, "name": "middle-node", "run_stat": 1},
                {"idx": 3, "name": "bus-node", "run_stat": 1},
            ],
            "DCGenerator": [
                {"idx": 1, "name": "storage", "node": 1, "run_stat": 1}
            ],
            "DCBreak": [
                {
                    "idx": 1,
                    "name": "breaker",
                    "i_node": 1,
                    "j_node": 2,
                    "run_stat": 1,
                    "status": 1,
                }
            ],
            "DCSwitch": [
                {
                    "idx": 1,
                    "name": "isolator",
                    "i_node": 2,
                    "j_node": 3,
                    "run_stat": 1,
                    "status": 1,
                }
            ],
            "DCRealBs": [
                {"idx": 1, "name": "dc-bus", "node": 3, "run_stat": 1}
            ],
        }
        open_snapshot = snapshot_with_model(
            model,
            scada=[
                {
                    "dev_type": "DCSwitch",
                    "dev_name": "isolator",
                    "meas_type": "STATUS",
                    "value": 0,
                    "valid": 1,
                }
            ],
        )
        closed_snapshot = snapshot_with_model(
            model,
            scada=[
                {
                    "dev_type": "DCSwitch",
                    "dev_name": "isolator",
                    "meas_type": "STATUS",
                    "value": 1,
                    "valid": 1,
                }
            ],
        )

        opened = resolve_snapshot(
            open_snapshot, ("storage", "DCGenerator", "storage")
        ).resources[("DCGenerator", "storage")]
        closed = resolve_snapshot(
            closed_snapshot, ("storage", "DCGenerator", "storage")
        ).resources[("DCGenerator", "storage")]

        self.assertEqual("DC", opened.connection_side)
        self.assertFalse(opened.actively_connected)
        self.assertEqual((), opened.active_path)
        self.assertTrue(closed.actively_connected)
        self.assertEqual(
            (("DCBreak", "breaker"), ("DCSwitch", "isolator")),
            closed.active_path,
        )
        self.assertEqual(opened.connection_side, closed.connection_side)
        self.assertEqual(opened.structural_path, closed.structural_path)
        self.assertEqual(opened.busbar_name, closed.busbar_name)

    def test_resource_and_required_path_device_state_control_connectivity(self):
        model = {
            "ACNode": [
                {"idx": 1, "name": "resource-node", "run_stat": 1},
                {"idx": 2, "name": "bus-node", "run_stat": 1},
            ],
            "ACGenerator": [
                {"idx": 1, "name": "wind", "node": 1, "run_stat": 1}
            ],
            "ACBranch": [
                {
                    "idx": 1,
                    "name": "line",
                    "i_node": 1,
                    "j_node": 2,
                    "run_stat": 1,
                }
            ],
            "ACRealBs": [
                {"idx": 1, "name": "ac-bus", "node": 2, "run_stat": 1}
            ],
        }
        offline_cases = {
            "resource run stat": snapshot_with_model(
                {
                    **model,
                    "ACGenerator": [
                        {"idx": 1, "name": "wind", "node": 1, "run_stat": 0}
                    ],
                }
            ),
            "resource dead island": snapshot_with_model(
                model,
                device_states=[
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "wind",
                        "run_stat": 1,
                        "dead_island": True,
                    }
                ],
            ),
            "path device dead island": snapshot_with_model(
                model,
                device_states=[
                    {
                        "dev_type": "ACBranch",
                        "dev_name": "line",
                        "run_stat": 1,
                        "dead_island": True,
                    }
                ],
            ),
            "path device run stat": snapshot_with_model(
                {
                    **model,
                    "ACBranch": [
                        {
                            "idx": 1,
                            "name": "line",
                            "i_node": 1,
                            "j_node": 2,
                            "run_stat": 0,
                        }
                    ],
                }
            ),
        }

        for label, snapshot in offline_cases.items():
            with self.subTest(case=label):
                item = resolve_snapshot(
                    snapshot, ("wind", "ACGenerator", "wind")
                ).resources[("ACGenerator", "wind")]
                self.assertEqual("AC", item.connection_side)
                self.assertFalse(item.actively_connected)
                self.assertEqual((), item.active_path)

    def test_model_dead_island_switch_disconnects_active_path(self):
        snapshot = snapshot_with_model(
            {
                "DCNode": [
                    {"idx": 1, "name": "resource-node"},
                    {"idx": 2, "name": "bus-node"},
                ],
                "DCGenerator": [
                    {"idx": 1, "name": "storage", "node": 1, "run_stat": 1}
                ],
                "DCSwitch": [
                    {
                        "idx": 1,
                        "name": "island-switch",
                        "i_node": 1,
                        "j_node": 2,
                        "run_stat": 1,
                        "status": 1,
                        "dead_island": True,
                    }
                ],
                "DCRealBs": [{"idx": 1, "name": "dc-bus", "node": 2}],
            }
        )

        item = resolve_snapshot(
            snapshot,
            ("storage", "DCGenerator", "storage"),
        ).resources[("DCGenerator", "storage")]

        self.assertEqual("DC", item.connection_side)
        self.assertEqual((("DCSwitch", "island-switch"),), item.structural_path)
        self.assertFalse(item.actively_connected)
        self.assertEqual((), item.active_path)

    def test_device_state_status_opens_switch_before_device_overlay(self):
        snapshot = snapshot_with_model(
            {
                "ACNode": [
                    {"idx": 1, "name": "resource-node"},
                    {"idx": 2, "name": "bus-node"},
                ],
                "ACGenerator": [
                    {"idx": 1, "name": "wind", "node": 1, "run_stat": 1}
                ],
                "ACSwitch": [
                    {
                        "idx": 1,
                        "name": "collector-switch",
                        "i_node": 1,
                        "j_node": 2,
                        "run_stat": 1,
                        "status": 1,
                    }
                ],
                "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 2}],
            },
            device_states=[
                {
                    "dev_type": "ACSwitch",
                    "dev_name": "collector-switch",
                    "run_stat": 1,
                    "status": 0,
                    "dead_island": False,
                }
            ],
        )

        item = resolve_snapshot(
            snapshot,
            ("wind", "ACGenerator", "wind"),
        ).resources[("ACGenerator", "wind")]

        self.assertEqual("AC", item.connection_side)
        self.assertEqual(
            (("ACSwitch", "collector-switch"),),
            item.structural_path,
        )
        self.assertFalse(item.actively_connected)
        self.assertEqual((), item.active_path)

    def test_inactive_nodes_and_real_bus_anchor_prevent_active_path(self):
        base_model = {
            "DCNode": [
                {"idx": 1, "name": "resource-node", "run_stat": 1},
                {"idx": 2, "name": "bus-node", "run_stat": 1},
            ],
            "DCGenerator": [
                {"idx": 1, "name": "pv", "node": 1, "run_stat": 1}
            ],
            "DCBranch": [
                {
                    "idx": 1,
                    "name": "line",
                    "i_node": 1,
                    "j_node": 2,
                    "run_stat": 1,
                }
            ],
            "DCRealBs": [
                {"idx": 1, "name": "dc-bus", "node": 2, "run_stat": 1}
            ],
        }
        cases = {
            "endpoint node run stat": snapshot_with_model(
                {
                    **base_model,
                    "DCNode": [
                        {"idx": 1, "name": "resource-node", "run_stat": 0},
                        {"idx": 2, "name": "bus-node", "run_stat": 1},
                    ],
                }
            ),
            "bus node dead island": snapshot_with_model(
                base_model,
                device_states=[
                    {
                        "dev_type": "DCNode",
                        "dev_name": "bus-node",
                        "run_stat": 1,
                        "dead_island": True,
                    }
                ],
            ),
            "real bus run stat": snapshot_with_model(
                {
                    **base_model,
                    "DCRealBs": [
                        {
                            "idx": 1,
                            "name": "dc-bus",
                            "node": 2,
                            "run_stat": 0,
                        }
                    ],
                }
            ),
            "real bus dead island": snapshot_with_model(
                base_model,
                devices=[
                    {
                        "dev_type": "DCRealBs",
                        "dev_name": "dc-bus",
                        "run_stat": 1,
                        "dead_island": True,
                    }
                ],
            ),
        }

        for label, snapshot in cases.items():
            with self.subTest(case=label):
                item = resolve_snapshot(
                    snapshot, ("pv", "DCGenerator", "pv")
                ).resources[("DCGenerator", "pv")]
                self.assertEqual("DC", item.connection_side)
                self.assertFalse(item.actively_connected)
                self.assertEqual((), item.active_path)

    def test_runtime_overlay_precedence_and_measurement_validation(self):
        model = {
            "ACNode": [
                {"idx": 1, "name": "resource-node"},
                {"idx": 2, "name": "bus-node"},
            ],
            "ACGenerator": [
                {"idx": 1, "name": "wind", "node": 1, "run_stat": 0}
            ],
            "ACSwitch": [
                {
                    "idx": 1,
                    "name": "switch",
                    "i_node": 1,
                    "j_node": 2,
                    "run_stat": 1,
                    "status": 0,
                }
            ],
            "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 2}],
        }
        snapshot = snapshot_with_model(
            model,
            device_states=[
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "wind",
                    "run_stat": 1,
                    "dead_island": False,
                },
                {
                    "dev_type": "ACSwitch",
                    "dev_name": "switch",
                    "run_stat": 1,
                    "dead_island": False,
                },
            ],
            devices=[
                {
                    "dev_type": "ACGenerator",
                    "name": "wind",
                    "run_stat": 0,
                    "dead_island": False,
                },
                {
                    "dev_type": "ACSwitch",
                    "dev_name": "switch",
                    "run_stat": 1,
                    "status": 0,
                    "dead_island": False,
                },
            ],
            scada=[
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "wind",
                    "meas_type": "RUN_STAT",
                    "value": 1,
                    "valid": 1,
                },
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "wind",
                    "meas_type": "RUN_STAT",
                    "value": 0,
                    "valid": 1,
                },
                {
                    "dev_type": "ACSwitch",
                    "dev_name": "switch",
                    "meas_type": "STATUS",
                    "value": 1,
                    "valid": 0,
                },
                {
                    "dev_type": "ACSwitch",
                    "dev_name": "wrong-name",
                    "meas_type": "STATUS",
                    "value": 1,
                    "valid": 1,
                },
            ],
            real=[
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "wind",
                    "meas_type": "RUN_STAT",
                    "value": 0,
                    "valid": 1,
                },
                {
                    "dev_type": "ACSwitch",
                    "dev_name": "switch",
                    "meas_type": "STATUS",
                    "value": 1,
                    "valid": 1,
                },
            ],
        )

        item = resolve_snapshot(
            snapshot, ("wind", "ACGenerator", "wind")
        ).resources[("ACGenerator", "wind")]

        self.assertTrue(item.actively_connected)
        self.assertEqual((("ACSwitch", "switch"),), item.active_path)
        self.assertTrue(item.grid_component_id.startswith("AC:"))

        invalid_measurements = snapshot_with_model(
            {
                **model,
                "ACGenerator": [
                    {"idx": 1, "name": "wind", "node": 1, "run_stat": 1}
                ],
                "ACSwitch": [
                    {
                        "idx": 1,
                        "name": "switch",
                        "i_node": 1,
                        "j_node": 2,
                        "run_stat": 1,
                        "status": 1,
                    }
                ],
            },
            scada=[
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "wind",
                    "meas_type": "RUN_STAT",
                    "value": float("nan"),
                    "valid": 1,
                },
                {
                    "dev_type": "ACSwitch",
                    "dev_name": "switch",
                    "meas_type": "STATUS",
                    "value": float("inf"),
                    "valid": 1,
                },
                {
                    "dev_type": "ACSwitch",
                    "dev_name": "switch",
                    "meas_type": "STATUS",
                    "value": 0,
                    "valid": 0,
                },
            ],
        )
        valid_item = resolve_snapshot(
            invalid_measurements, ("wind", "ACGenerator", "wind")
        ).resources[("ACGenerator", "wind")]
        self.assertTrue(valid_item.actively_connected)

    def test_two_independent_dc_islands_get_isolated_transfer_groups(self):
        result = resolve_snapshot(
            two_dc_island_snapshot(),
            ("storage", "DCGenerator", "storage-a"),
            ("storage", "DCGenerator", "storage-b"),
        )
        resource_a = result.resources[("DCGenerator", "storage-a")]
        resource_b = result.resources[("DCGenerator", "storage-b")]

        self.assertTrue(resource_a.dc_transfer_group_id)
        self.assertTrue(resource_b.dc_transfer_group_id)
        self.assertNotEqual(
            resource_a.dc_transfer_group_id,
            resource_b.dc_transfer_group_id,
        )
        group_a = result.dc_transfer_groups[resource_a.dc_transfer_group_id]
        group_b = result.dc_transfer_groups[resource_b.dc_transfer_group_id]
        self.assertEqual(("1", "2"), group_a.dc_nodes)
        self.assertEqual(("3", "4"), group_b.dc_nodes)
        self.assertEqual(
            (("DCACConverter", "converter-a"),),
            group_a.converter_keys,
        )
        self.assertEqual(
            (("DCACConverter", "converter-b"),),
            group_b.converter_keys,
        )
        self.assertNotIn(("DCACConverter", "converter-b"), group_a.converter_keys)
        self.assertNotIn(("DCACConverter", "converter-a"), group_b.converter_keys)
        self.assertEqual(1, len(group_a.ac_component_ids))
        self.assertEqual(1, len(group_b.ac_component_ids))
        self.assertEqual(
            (group_a.ac_component_ids[0], group_a.group_id),
            result.converter_component_ids[("DCACConverter", "converter-a")],
        )
        self.assertEqual(
            (group_b.ac_component_ids[0], group_b.group_id),
            result.converter_component_ids[("DCACConverter", "converter-b")],
        )

    def test_ac_terminal_resource_uses_resolved_dc_island_transfer_group(self):
        snapshot = snapshot_with_model(
            {
                "ACNode": [
                    {"idx": 1, "name": "wind-terminal-node", "run_stat": 1},
                    {"idx": 100, "name": "grid-ac-node", "run_stat": 1},
                ],
                "DCNode": [
                    {"idx": 10, "name": "dc-entry-node", "run_stat": 1},
                    {"idx": 11, "name": "dc-bus-node", "run_stat": 1},
                ],
                "ACGenerator": [
                    {
                        "idx": 1,
                        "name": "wind-ac-terminal",
                        "node": 1,
                        "run_stat": 1,
                    }
                ],
                "DCACConverter": [
                    {
                        "idx": 1,
                        "name": "rectifier",
                        "ac_node": 1,
                        "dc_node": 10,
                        "run_stat": 1,
                    },
                    {
                        "idx": 2,
                        "name": "grid-acdc",
                        "ac_node": 100,
                        "dc_node": 10,
                        "run_stat": 1,
                    },
                ],
                "DCBranch": [
                    {
                        "idx": 1,
                        "name": "dc-collector",
                        "i_node": 10,
                        "j_node": 11,
                        "run_stat": 1,
                    }
                ],
                "DCRealBs": [
                    {"idx": 1, "name": "dc-collector-bus", "node": 11}
                ],
                "ACRealBs": [
                    {"idx": 1, "name": "grid-ac-bus", "node": 100}
                ],
            }
        )

        result = resolve_snapshot(
            snapshot,
            ("wind", "ACGenerator", "wind-ac-terminal"),
        )
        item = result.resources[("ACGenerator", "wind-ac-terminal")]

        self.assertEqual("DC", item.connection_side)
        self.assertTrue(item.actively_connected)
        self.assertTrue(item.grid_component_id.startswith("DC:"))
        self.assertEqual(item.grid_component_id, item.dc_transfer_group_id)
        group = result.dc_transfer_groups[item.dc_transfer_group_id]
        self.assertIn(("DCACConverter", "grid-acdc"), group.converter_keys)
        self.assertNotIn(("DCACConverter", "rectifier"), group.converter_keys)

    def test_dc_terminal_group_stays_on_origin_island_after_ac_detour(self):
        snapshot = snapshot_with_model(
            {
                "DCNode": [
                    {"idx": 1, "name": "origin-dc-node"},
                    {"idx": 10, "name": "resolved-dc-node"},
                ],
                "ACNode": [{"idx": 100, "name": "detour-ac-node"}],
                "DCGenerator": [
                    {"idx": 1, "name": "storage-a", "node": 1, "run_stat": 1}
                ],
                "DCACConverter": [
                    {
                        "idx": 1,
                        "name": "from-island-a",
                        "dc_node": 1,
                        "ac_node": 100,
                        "run_stat": 1,
                    },
                    {
                        "idx": 2,
                        "name": "to-island-b",
                        "dc_node": 10,
                        "ac_node": 100,
                        "run_stat": 1,
                    },
                ],
                "DCRealBs": [
                    {"idx": 1, "name": "island-b-bus", "node": 10}
                ],
            }
        )

        result = resolve_snapshot(
            snapshot,
            ("storage", "DCGenerator", "storage-a"),
        )
        item = result.resources[("DCGenerator", "storage-a")]
        groups_by_nodes = {
            group.dc_nodes: group
            for group in result.dc_transfer_groups.values()
        }
        group_a = groups_by_nodes[("1",)]
        group_b = groups_by_nodes[("10",)]

        self.assertEqual("DC", item.connection_side)
        self.assertTrue(item.actively_connected)
        self.assertEqual(group_b.group_id, item.grid_component_id)
        self.assertEqual(group_a.group_id, item.dc_transfer_group_id)
        self.assertNotEqual(group_a.group_id, group_b.group_id)
        self.assertEqual((), group_a.converter_keys)
        self.assertEqual((), group_b.converter_keys)

    def test_component_ids_distinguish_nul_joining_node_sequences(self):
        snapshot = snapshot_with_model(
            {
                "DCNode": [
                    {"idx": "a", "name": "node-a"},
                    {"idx": "b", "name": "node-b"},
                    {"idx": "a\0b", "name": "node-a-nul-b"},
                ],
                "DCGenerator": [
                    {"idx": 1, "name": "resource-ab", "node": "a"},
                    {"idx": 2, "name": "resource-a-nul-b", "node": "a\0b"},
                ],
                "DCBranch": [
                    {
                        "idx": 1,
                        "name": "line-a-b",
                        "i_node": "a",
                        "j_node": "b",
                    }
                ],
                "DCRealBs": [
                    {"idx": 1, "name": "bus-ab", "node": "a"},
                    {"idx": 2, "name": "bus-a-nul-b", "node": "a\0b"},
                ],
            }
        )

        result = resolve_snapshot(
            snapshot,
            ("storage", "DCGenerator", "resource-ab"),
            ("storage", "DCGenerator", "resource-a-nul-b"),
        )
        resource_ab = result.resources[("DCGenerator", "resource-ab")]
        resource_nul = result.resources[("DCGenerator", "resource-a-nul-b")]

        self.assertNotEqual(
            resource_ab.dc_transfer_group_id,
            resource_nul.dc_transfer_group_id,
        )
        self.assertEqual(
            ("a", "b"),
            result.dc_transfer_groups[
                resource_ab.dc_transfer_group_id
            ].dc_nodes,
        )
        self.assertEqual(
            ("a\0b",),
            result.dc_transfer_groups[
                resource_nul.dc_transfer_group_id
            ].dc_nodes,
        )

    def test_many_resources_use_graph_level_anchor_indexes(self):
        resource_count = 40
        snapshot = snapshot_with_model(
            {
                "ACNode": [
                    {"idx": 1, "name": "resource-node"},
                    {"idx": 2, "name": "bus-node"},
                ],
                "ACGenerator": [
                    {"idx": index, "name": f"wind-{index}", "node": 1}
                    for index in range(resource_count)
                ],
                "ACBranch": [
                    {
                        "idx": 1,
                        "name": "collector-line",
                        "i_node": 1,
                        "j_node": 2,
                    }
                ],
                "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 2}],
            }
        )
        resources = tuple(
            ("wind", "ACGenerator", f"wind-{index}")
            for index in range(resource_count)
        )

        with patch.object(
            topology,
            "_build_reverse_anchor_indexes",
            wraps=topology._build_reverse_anchor_indexes,
        ) as build_indexes:
            result = resolve_snapshot(snapshot, *resources)

        self.assertEqual(resource_count, len(result.resources))
        self.assertTrue(
            all(item.actively_connected for item in result.resources.values())
        )
        self.assertEqual(2, build_indexes.call_count)

    def test_repeated_switch_diamonds_keep_index_work_polynomial(self):
        layer_count = 8
        nodes = [{"idx": "n0", "name": "node-n0"}]
        switches = []
        terminal_nodes = ["n0"]
        entry = "n0"
        for layer in range(layer_count):
            upper = f"u{layer}"
            lower = f"l{layer}"
            exit_node = f"n{layer + 1}"
            nodes.extend(
                [
                    {"idx": upper, "name": f"node-{upper}"},
                    {"idx": lower, "name": f"node-{lower}"},
                    {"idx": exit_node, "name": f"node-{exit_node}"},
                ]
            )
            for suffix, left, right in (
                ("a", entry, upper),
                ("b", entry, lower),
                ("c", upper, exit_node),
                ("d", lower, exit_node),
            ):
                switches.append(
                    {
                        "idx": len(switches),
                        "name": f"switch-{layer}-{suffix}",
                        "i_node": left,
                        "j_node": right,
                        "status": 1,
                    }
                )
            entry = exit_node
            terminal_nodes.append(entry)

        snapshot = snapshot_with_model(
            {
                "ACNode": nodes,
                "ACGenerator": [
                    {
                        "idx": index,
                        "name": f"wind-{index}",
                        "node": node_id,
                    }
                    for index, node_id in enumerate(terminal_nodes)
                ],
                "ACSwitch": switches,
                "ACRealBs": [{"idx": 1, "name": "mesh-bus", "node": entry}],
            }
        )
        resources = tuple(
            ("wind", "ACGenerator", f"wind-{index}")
            for index in range(len(terminal_nodes))
        )
        real_heappush = topology.heapq.heappush

        with patch.object(
            topology.heapq,
            "heappush",
            side_effect=real_heappush,
        ) as heap_push:
            result = resolve_snapshot(snapshot, *resources)

        self.assertTrue(
            all(item.actively_connected for item in result.resources.values())
        )
        graph_size = len(nodes) + len(switches)
        self.assertLessEqual(heap_push.call_count, 20 * graph_size)

    def test_dc_converter_eligibility_requires_active_converter_and_ac_grid(self):
        base = two_dc_island_snapshot()
        cases = {
            "converter run stat": snapshot_with_model(
                {
                    name: [
                        {
                            **row,
                            **(
                                {"run_stat": 0}
                                if name == "DCACConverter"
                                and row["name"] == "converter-a"
                                else {}
                            ),
                        }
                        for row in data["rows"]
                    ]
                    for name, data in base["definitions"]["model"].items()
                }
            ),
            "converter dead island": {
                **base,
                "device_states": [
                    {
                        "dev_type": "DCACConverter",
                        "dev_name": "converter-a",
                        "run_stat": 1,
                        "dead_island": True,
                    }
                ],
            },
            "ac bus dead island": {
                **base,
                "device_states": [
                    {
                        "dev_type": "ACRealBs",
                        "dev_name": "local-ac-a",
                        "run_stat": 1,
                        "dead_island": True,
                    }
                ],
            },
            "ac node dead island": {
                **base,
                "device_states": [
                    {
                        "dev_type": "ACNode",
                        "dev_name": "ac-a",
                        "run_stat": 1,
                        "dead_island": True,
                    }
                ],
            },
        }

        for label, snapshot in cases.items():
            with self.subTest(case=label):
                result = resolve_snapshot(
                    snapshot, ("storage", "DCGenerator", "storage-a")
                )
                item = result.resources[("DCGenerator", "storage-a")]
                self.assertTrue(item.dc_transfer_group_id)
                group = result.dc_transfer_groups[item.dc_transfer_group_id]
                self.assertEqual((), group.converter_keys)
                self.assertEqual((), group.ac_component_ids)

    def test_converter_with_no_active_ac_real_bus_is_excluded(self):
        snapshot = two_dc_island_snapshot()
        snapshot["definitions"]["model"]["ACRealBs"]["rows"] = [
            row
            for row in snapshot["definitions"]["model"]["ACRealBs"]["rows"]
            if row["name"] != "local-ac-a"
        ]

        result = resolve_snapshot(
            snapshot, ("storage", "DCGenerator", "storage-a")
        )
        item = result.resources[("DCGenerator", "storage-a")]
        self.assertTrue(item.dc_transfer_group_id)
        group = result.dc_transfer_groups[item.dc_transfer_group_id]

        self.assertEqual((), group.converter_keys)
        self.assertEqual((), group.ac_component_ids)

    def test_converter_cannot_be_borrowed_from_another_dc_component(self):
        snapshot = two_dc_island_snapshot()
        result = resolve_snapshot(
            snapshot,
            ("storage", "DCGenerator", "storage-a"),
            ("storage", "DCGenerator", "storage-b"),
        )
        resource_a = result.resources[("DCGenerator", "storage-a")]
        resource_b = result.resources[("DCGenerator", "storage-b")]
        self.assertTrue(resource_a.dc_transfer_group_id)
        self.assertTrue(resource_b.dc_transfer_group_id)
        group_a = result.dc_transfer_groups[resource_a.dc_transfer_group_id]
        group_b = result.dc_transfer_groups[resource_b.dc_transfer_group_id]

        self.assertNotIn(("DCACConverter", "converter-b"), group_a.converter_keys)
        self.assertIn(("DCACConverter", "converter-b"), group_b.converter_keys)

    def test_same_domain_converters_join_active_components(self):
        snapshot = snapshot_with_model(
            {
                "ACNode": [
                    {"idx": 1, "name": "ac-resource-node"},
                    {"idx": 2, "name": "ac-bus-node"},
                ],
                "DCNode": [
                    {"idx": 3, "name": "dc-resource-node"},
                    {"idx": 4, "name": "dc-bus-node"},
                ],
                "ACGenerator": [{"idx": 1, "name": "wind", "node": 1}],
                "DCGenerator": [{"idx": 2, "name": "storage", "node": 3}],
                "ACACConverter": [
                    {
                        "idx": 1,
                        "name": "ac-link",
                        "i_node": 1,
                        "j_node": 2,
                        "run_stat": 1,
                    }
                ],
                "DCDCConverter": [
                    {
                        "idx": 2,
                        "name": "dc-link",
                        "i_node": 3,
                        "j_node": 4,
                        "run_stat": 1,
                    }
                ],
                "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 2}],
                "DCRealBs": [{"idx": 2, "name": "dc-bus", "node": 4}],
            }
        )

        result = resolve_snapshot(
            snapshot,
            ("wind", "ACGenerator", "wind"),
            ("storage", "DCGenerator", "storage"),
        )
        wind = result.resources[("ACGenerator", "wind")]
        storage = result.resources[("DCGenerator", "storage")]

        self.assertTrue(wind.actively_connected)
        self.assertEqual((("ACACConverter", "ac-link"),), wind.active_path)
        self.assertTrue(wind.grid_component_id.startswith("AC:"))
        self.assertTrue(storage.actively_connected)
        self.assertEqual((("DCDCConverter", "dc-link"),), storage.active_path)
        group = result.dc_transfer_groups[storage.dc_transfer_group_id]
        self.assertEqual(("3", "4"), group.dc_nodes)

    def test_open_dc_switch_splits_group_and_keeps_active_isolated_resource_group(self):
        model = {
            "DCNode": [
                {"idx": 1, "name": "resource-node"},
                {"idx": 2, "name": "converter-node"},
                {"idx": 3, "name": "bus-node"},
            ],
            "ACNode": [{"idx": 10, "name": "ac-node"}],
            "DCGenerator": [
                {"idx": 1, "name": "storage", "node": 1, "run_stat": 1}
            ],
            "DCSwitch": [
                {
                    "idx": 1,
                    "name": "section-switch",
                    "i_node": 1,
                    "j_node": 2,
                    "run_stat": 1,
                    "status": 1,
                }
            ],
            "DCBranch": [
                {
                    "idx": 1,
                    "name": "bus-line",
                    "i_node": 2,
                    "j_node": 3,
                    "run_stat": 1,
                }
            ],
            "DCRealBs": [{"idx": 1, "name": "dc-bus", "node": 3}],
            "ACRealBs": [{"idx": 1, "name": "ordinary-ac-bus", "node": 10}],
            "DCACConverter": [
                {
                    "idx": 1,
                    "name": "converter",
                    "dc_node": 2,
                    "ac_node": 10,
                    "run_stat": 1,
                }
            ],
        }
        closed = resolve_snapshot(
            snapshot_with_model(model),
            ("storage", "DCGenerator", "storage"),
        )
        opened = resolve_snapshot(
            snapshot_with_model(
                model,
                scada=[
                    {
                        "dev_type": "DCSwitch",
                        "dev_name": "section-switch",
                        "meas_type": "STATUS",
                        "value": 0,
                        "valid": 1,
                    }
                ],
            ),
            ("storage", "DCGenerator", "storage"),
        )
        closed_item = closed.resources[("DCGenerator", "storage")]
        opened_item = opened.resources[("DCGenerator", "storage")]

        self.assertTrue(closed_item.actively_connected)
        self.assertFalse(opened_item.actively_connected)
        self.assertEqual("DC", opened_item.connection_side)
        self.assertEqual(closed_item.structural_path, opened_item.structural_path)
        self.assertTrue(opened_item.dc_transfer_group_id)
        self.assertNotEqual(
            closed_item.dc_transfer_group_id,
            opened_item.dc_transfer_group_id,
        )
        isolated_group = opened.dc_transfer_groups[
            opened_item.dc_transfer_group_id
        ]
        self.assertEqual(("1",), isolated_group.dc_nodes)
        self.assertEqual((), isolated_group.converter_keys)

    def test_inactive_dc_resource_terminal_has_no_transfer_group(self):
        snapshot = snapshot_with_model(
            {
                "DCNode": [
                    {"idx": 1, "name": "resource-node", "run_stat": 0}
                ],
                "DCGenerator": [
                    {"idx": 1, "name": "storage", "node": 1, "run_stat": 1}
                ],
                "DCRealBs": [{"idx": 1, "name": "dc-bus", "node": 1}],
            }
        )

        item = resolve_snapshot(
            snapshot, ("storage", "DCGenerator", "storage")
        ).resources[("DCGenerator", "storage")]

        self.assertEqual("DC", item.connection_side)
        self.assertFalse(item.actively_connected)
        self.assertEqual("", item.dc_transfer_group_id)

    def test_alternate_active_path_stays_in_structural_domain(self):
        model = {
            "ACNode": [
                {"idx": 1, "name": "resource-node"},
                {"idx": 2, "name": "bus-node-a"},
                {"idx": 3, "name": "bus-node-b"},
            ],
            "ACGenerator": [{"idx": 1, "name": "wind", "node": 1}],
            "ACSwitch": [
                {
                    "idx": 1,
                    "name": "switch-a",
                    "i_node": 1,
                    "j_node": 2,
                    "status": 1,
                },
                {
                    "idx": 2,
                    "name": "switch-b",
                    "i_node": 1,
                    "j_node": 3,
                    "status": 1,
                },
            ],
            "ACRealBs": [
                {"idx": 1, "name": "bus-a", "node": 2},
                {"idx": 2, "name": "bus-b", "node": 3},
            ],
        }
        result = resolve_snapshot(
            snapshot_with_model(
                model,
                scada=[
                    {
                        "dev_type": "ACSwitch",
                        "dev_name": "switch-a",
                        "meas_type": "STATUS",
                        "value": 0,
                        "valid": 1,
                    }
                ],
            ),
            ("wind", "ACGenerator", "wind"),
        )
        item = result.resources[("ACGenerator", "wind")]

        self.assertEqual("AC", item.connection_side)
        self.assertEqual("bus-a", item.busbar_name)
        self.assertEqual((("ACSwitch", "switch-a"),), item.structural_path)
        self.assertTrue(item.actively_connected)
        self.assertEqual((("ACSwitch", "switch-b"),), item.active_path)
        self.assertTrue(item.grid_component_id.startswith("AC:"))

    def test_active_topology_outputs_are_deterministic_when_rows_reverse(self):
        snapshot = two_dc_island_snapshot()
        snapshot["devices"] = [
            {
                "dev_type": "DCGenerator",
                "dev_name": "storage-a",
                "run_stat": 1,
            },
            {
                "dev_type": "DCACConverter",
                "dev_name": "converter-b",
                "run_stat": 1,
            },
        ]
        snapshot["device_states"] = [
            {
                "dev_type": "DCBranch",
                "dev_name": "dc-line-a",
                "run_stat": 1,
                "dead_island": False,
            },
            {
                "dev_type": "ACNode",
                "dev_name": "ac-b",
                "run_stat": 1,
                "dead_island": False,
            },
        ]
        snapshot["measurements"]["scada"] = [
            {
                "dev_type": "DCGenerator",
                "dev_name": "storage-a",
                "meas_type": "RUN_STAT",
                "value": 1,
                "valid": 1,
            },
            {
                "dev_type": "DCACConverter",
                "dev_name": "converter-b",
                "meas_type": "RUN_STAT",
                "value": 1,
                "valid": 1,
            },
        ]
        resources = (
            ("storage", "DCGenerator", "storage-a"),
            ("storage", "DCGenerator", "storage-b"),
        )

        ordered = resolve_snapshot(snapshot, *resources)
        reversed_result = resolve_snapshot(
            reverse_snapshot_rows(snapshot), *resources
        )

        self.assertEqual(2, len(ordered.dc_transfer_groups))
        self.assertTrue(
            all(
                item.grid_component_id and item.dc_transfer_group_id
                for item in ordered.resources.values()
            )
        )

        ordered_fields = {
            key: (
                item.grid_component_id,
                item.dc_transfer_group_id,
            )
            for key, item in ordered.resources.items()
        }
        reversed_fields = {
            key: (
                item.grid_component_id,
                item.dc_transfer_group_id,
            )
            for key, item in reversed_result.resources.items()
        }
        self.assertEqual(ordered_fields, reversed_fields)
        self.assertEqual(
            dict(ordered.dc_transfer_groups),
            dict(reversed_result.dc_transfer_groups),
        )

    def test_zero_cost_active_cycle_terminates_and_is_deterministic(self):
        model = {
            "ACNode": [
                {"idx": 1, "name": "resource-node"},
                {"idx": 2, "name": "cycle-node-a"},
                {"idx": 3, "name": "cycle-node-b"},
                {"idx": 4, "name": "bus-node"},
            ],
            "ACGenerator": [{"idx": 1, "name": "wind", "node": 1}],
            "ACSwitch": [
                {"idx": 1, "name": "cycle-a", "i_node": 1, "j_node": 2},
                {"idx": 2, "name": "cycle-b", "i_node": 2, "j_node": 3},
                {"idx": 3, "name": "cycle-c", "i_node": 3, "j_node": 1},
                {"idx": 4, "name": "to-bus", "i_node": 3, "j_node": 4},
            ],
            "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 4}],
        }
        ordered = resolve_snapshot(
            snapshot_with_model(model),
            ("wind", "ACGenerator", "wind"),
        ).resources[("ACGenerator", "wind")]
        reversed_result = resolve_snapshot(
            reverse_snapshot_rows(snapshot_with_model(model)),
            ("wind", "ACGenerator", "wind"),
        ).resources[("ACGenerator", "wind")]

        self.assertTrue(ordered.actively_connected)
        self.assertTrue(ordered.grid_component_id.startswith("AC:"))
        self.assertEqual(ordered.active_path, reversed_result.active_path)
        self.assertEqual(
            ordered.grid_component_id,
            reversed_result.grid_component_id,
        )

    def test_zero_cost_triangle_uses_canonical_full_device_path(self):
        model = {
            "ACNode": [
                {"idx": 0, "name": "resource-node"},
                {"idx": 1, "name": "middle-node"},
                {"idx": 2, "name": "anchor-node"},
            ],
            "ACGenerator": [{"idx": 1, "name": "wind", "node": 0}],
            "ACSwitch": [
                {"idx": 1, "name": "e00", "i_node": 0, "j_node": 1},
                {"idx": 2, "name": "e01", "i_node": 0, "j_node": 2},
                {"idx": 3, "name": "e02", "i_node": 1, "j_node": 2},
            ],
            "ACRealBs": [{"idx": 1, "name": "ac-bus", "node": 2}],
        }

        item = resolve_snapshot(
            snapshot_with_model(model),
            ("wind", "ACGenerator", "wind"),
        ).resources[("ACGenerator", "wind")]

        expected_path = (
            ("ACSwitch", "e00"),
            ("ACSwitch", "e02"),
        )
        self.assertEqual("AC", item.connection_side)
        self.assertTrue(item.actively_connected)
        self.assertEqual(expected_path, item.structural_path)
        self.assertEqual(expected_path, item.active_path)


if __name__ == "__main__":
    unittest.main()
